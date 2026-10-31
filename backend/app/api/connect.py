"""Connecting Instagram and Threads accounts via Meta OAuth (documented flows only).

Instagram (Business Login for Instagram):
  authorize  https://www.instagram.com/oauth/authorize
  code→token POST https://api.instagram.com/oauth/access_token
  long-lived GET  https://graph.instagram.com/access_token?grant_type=ig_exchange_token
  refresh    GET  https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token
Threads:
  authorize  https://threads.com/oauth/authorize
  code→token POST https://graph.threads.com/oauth/access_token
  long-lived GET  https://graph.threads.com/access_token?grant_type=th_exchange_token
  refresh    GET  https://graph.threads.com/refresh_access_token?grant_type=th_refresh_token
"""
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.audit import audit
from app.config import get_settings
from app.db import get_db
from app.integrations import meta_http, tokens
from app.integrations.meta_http import MetaError
from app.models import User
from app.security import get_current_user, require_role

router = APIRouter(prefix="/api/connect", tags=["connect"])
PLATFORMS = ("instagram", "threads")

CAPABILITIES = {
    "instagram": [
        {"name": "Комментарии и ответы под постами подключённого аккаунта", "status": "available",
         "needs": "instagram_business_basic, instagram_business_manage_comments"},
        {"name": "Публичные посты других бизнес-аккаунтов (без комментариев)", "status": "limited",
         "needs": "Business Discovery; документирован для Facebook Login (INSTAGRAM_API_HOST=graph.facebook.com)"},
        {"name": "Публичные посты по хэштегу", "status": "app_review",
         "needs": "App Review: Instagram Public Content Access, токен Facebook Login, 30 хэштегов за 7 дней"},
        {"name": "Direct подключённого аккаунта", "status": "app_review",
         "needs": "instagram_business_manage_messages; без Advanced Access — только люди с ролью в приложении"},
        {"name": "Комментарии под чужими постами, личные аккаунты", "status": "not_possible",
         "needs": "Официальный API не предоставляет"},
    ],
    "threads": [
        {"name": "Посты подключённого аккаунта и ответы на них", "status": "available",
         "needs": "threads_basic, threads_read_replies"},
        {"name": "Поиск публичных постов по ключевым словам", "status": "app_review",
         "needs": "threads_keyword_search; до одобрения ищет только по своим постам; 2 200 запросов в сутки"},
        {"name": "Ответы на чужие публичные посты", "status": "app_review",
         "needs": "Advanced Access; без него Meta отдаёт только посты тестировщиков приложения"},
        {"name": "Посты публичных профилей", "status": "app_review",
         "needs": "threads_profile_discovery; при стандартном доступе — только аккаунты Meta"},
        {"name": "Лайки и просмотры", "status": "not_collected", "needs": "threads_manage_insights — не используется"},
    ],
}


def redirect_uri(platform: str) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/api/connect/{platform}/callback"


def _app_creds(platform: str) -> tuple[str, str]:
    s = get_settings()
    app_id, secret = (s.instagram_app_id, s.instagram_app_secret) if platform == "instagram" else (s.threads_app_id, s.threads_app_secret)
    return app_id, secret


def _status(db: Session, platform: str) -> dict:
    app_id, secret = _app_creds(platform)
    cred = tokens.load(db, platform)
    expires = cred.expires_at if cred else None
    return {
        "platform": platform, "app_configured": bool(app_id and secret), "connected": cred is not None,
        "origin": cred.origin if cred else None, "username": cred.username if cred else None,
        "user_id": cred.user_id if cred else None, "scopes": cred.scopes if cred else [],
        "expires_at": expires.isoformat() if expires else None,
        "expires_soon": bool(expires and expires - datetime.now(timezone.utc) < timedelta(days=10)),
        "redirect_uri": redirect_uri(platform), "capabilities": CAPABILITIES[platform],
    }


@router.get("/status")
def status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [_status(db, p) for p in PLATFORMS]


def _check(platform: str):
    if platform not in PLATFORMS:
        raise HTTPException(404, "Неизвестная платформа")


@router.get("/{platform}/start")
def start(platform: str, user: User = Depends(require_role("admin"))):
    _check(platform)
    s = get_settings()
    app_id, secret = _app_creds(platform)
    if not app_id or not secret:
        env = platform.upper()
        raise HTTPException(400, f"Задайте {env}_APP_ID и {env}_APP_SECRET в .env и перезапустите приложение")
    state = jwt.encode({"sub": str(user.id), "platform": platform, "nonce": secrets.token_hex(8),
                        "exp": datetime.now(timezone.utc) + timedelta(minutes=15)}, s.secret_key, algorithm="HS256")
    if platform == "instagram":
        url = "https://www.instagram.com/oauth/authorize?" + urlencode({
            "client_id": app_id, "redirect_uri": redirect_uri(platform), "response_type": "code",
            "scope": s.instagram_scopes, "state": state})
    else:
        url = "https://threads.com/oauth/authorize?" + urlencode({
            "client_id": app_id, "redirect_uri": redirect_uri(platform), "response_type": "code",
            "scope": s.threads_scopes, "state": state})
    return {"url": url}


def exchange(platform: str, code: str) -> dict:
    """Code → short-lived → long-lived token → profile. Returns fields for tokens.save()."""
    s = get_settings()
    app_id, secret = _app_creds(platform)
    code = code.split("#")[0]
    with meta_http.client() as c:
        if platform == "instagram":
            short = meta_http.post(c, "https://api.instagram.com/oauth/access_token", {
                "client_id": app_id, "client_secret": secret, "grant_type": "authorization_code",
                "redirect_uri": redirect_uri(platform), "code": code})
            row = (short.get("data") or [short])[0]
            long = meta_http.get(c, "https://graph.instagram.com/access_token", {
                "grant_type": "ig_exchange_token", "client_secret": secret, "access_token": row["access_token"]})
            me = meta_http.get(c, f"https://graph.instagram.com/{s.meta_graph_version}/me",
                               {"fields": "user_id,username", "access_token": long["access_token"]})
            perms = row.get("permissions") or s.instagram_scopes.split(",")
            return {"access_token": long["access_token"], "user_id": me.get("user_id") or row.get("user_id"),
                    "username": me.get("username"), "expires_in": long.get("expires_in"),
                    "scopes": perms if isinstance(perms, list) else str(perms).split(",")}
        host = f"https://{s.threads_api_host}"
        short = meta_http.post(c, f"{host}/oauth/access_token", {
            "client_id": app_id, "client_secret": secret, "grant_type": "authorization_code",
            "redirect_uri": redirect_uri(platform), "code": code})
        long = meta_http.get(c, f"{host}/access_token", {
            "grant_type": "th_exchange_token", "client_secret": secret, "access_token": short["access_token"]})
        me = meta_http.get(c, f"{host}/v1.0/me", {"fields": "id,username", "access_token": long["access_token"]})
        return {"access_token": long["access_token"], "user_id": me.get("id") or short.get("user_id"),
                "username": me.get("username"), "expires_in": long.get("expires_in"),
                "scopes": s.threads_scopes.split(",")}


@router.get("/{platform}/callback", include_in_schema=False)
def callback(platform: str, code: str | None = None, state: str | None = None, error: str | None = None,
             error_description: str | None = None, db: Session = Depends(get_db)):
    """Browser redirect from Meta. Authenticated by the signed `state` created in /start."""
    _check(platform)
    back = "/sources?tab=" + platform
    if error or not code:
        return RedirectResponse(f"{back}&connect_error={error_description or error or 'отменено'}")
    try:
        data = jwt.decode(state or "", get_settings().secret_key, algorithms=["HS256"])
        if data.get("platform") != platform:
            raise jwt.InvalidTokenError
    except jwt.PyJWTError:
        return RedirectResponse(f"{back}&connect_error=Недействительный или просроченный запрос подключения")
    user = db.get(User, int(data["sub"]))
    if user is None or user.role != "admin":
        return RedirectResponse(f"{back}&connect_error=Подключать аккаунты может только администратор")
    try:
        res = exchange(platform, code)
    except MetaError as e:
        return RedirectResponse(f"{back}&connect_error={str(e)[:200]}")
    tokens.save(db, platform, res["access_token"], res["user_id"], res["username"], res["expires_in"], res["scopes"])
    audit(db, user, f"connect.{platform}", username=res["username"])
    db.commit()
    return RedirectResponse(f"{back}&connected={platform}")


def refresh_token(db: Session, platform: str) -> dict:
    cred = tokens.load(db, platform)
    if cred is None or cred.origin != "oauth":
        raise MetaError("Нет подключённого через OAuth аккаунта")
    s = get_settings()
    with meta_http.client() as c:
        if platform == "instagram":
            r = meta_http.get(c, "https://graph.instagram.com/refresh_access_token",
                              {"grant_type": "ig_refresh_token", "access_token": cred.access_token})
        else:
            r = meta_http.get(c, f"https://{s.threads_api_host}/refresh_access_token",
                              {"grant_type": "th_refresh_token", "access_token": cred.access_token})
    tokens.save(db, platform, r["access_token"], cred.user_id, cred.username, r.get("expires_in"), cred.scopes)
    return _status(db, platform)


@router.post("/{platform}/refresh")
def refresh(platform: str, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    _check(platform)
    try:
        out = refresh_token(db, platform)
    except MetaError as e:
        raise HTTPException(400, str(e))
    audit(db, user, f"connect.{platform}.refresh")
    db.commit()
    return out


@router.post("/{platform}/test")
def test(platform: str, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    """Calls /me with the stored token: proves the connection works."""
    _check(platform)
    cred = tokens.load(db, platform)
    if cred is None:
        raise HTTPException(400, "Аккаунт не подключён")
    s = get_settings()
    url = (f"https://{s.instagram_api_host}/{s.meta_graph_version}/me" if platform == "instagram"
           else f"https://{s.threads_api_host}/v1.0/me")
    fields = "user_id,username" if platform == "instagram" and "instagram.com" in s.instagram_api_host else "id,username"
    try:
        with meta_http.client() as c:
            me = meta_http.get(c, url, {"fields": fields, "access_token": cred.access_token})
    except MetaError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "username": me.get("username"), "id": me.get("user_id") or me.get("id")}


@router.delete("/{platform}")
def disconnect(platform: str, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    _check(platform)
    tokens.delete(db, platform)
    audit(db, user, f"connect.{platform}.disconnect")
    db.commit()
    return _status(db, platform)
