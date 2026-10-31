"""Encrypted storage of platform access tokens (Instagram, Threads).

Tokens are encrypted with a key derived from SECRET_KEY and kept in the app_state table.
They never leave the server: the API only reports whether a platform is connected.
A token in .env (INSTAGRAM_ACCESS_TOKEN / THREADS_ACCESS_TOKEN) takes effect when nothing is stored.
"""
import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AppState


def _fernet() -> Fernet:
    key = hashlib.sha256(("pulse-tokens:" + get_settings().secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


@dataclass
class Credential:
    platform: str
    access_token: str
    user_id: str | None
    username: str | None
    expires_at: datetime | None
    scopes: list[str]
    origin: str        # "oauth" | "env"
    obtained_at: datetime | None = None


def save(db: Session, platform: str, access_token: str, user_id: str | None, username: str | None,
         expires_in: int | None, scopes: list[str]) -> None:
    now = datetime.now(timezone.utc)
    value = {
        "token": _fernet().encrypt(access_token.encode()).decode(),
        "user_id": str(user_id) if user_id else None, "username": username, "scopes": scopes,
        "expires_at": (now + timedelta(seconds=int(expires_in))).isoformat() if expires_in else None,
        "obtained_at": now.isoformat(),
    }
    row = db.get(AppState, f"oauth:{platform}")
    if row:
        row.value = value
    else:
        db.add(AppState(key=f"oauth:{platform}", value=value))
    db.commit()


def delete(db: Session, platform: str) -> None:
    row = db.get(AppState, f"oauth:{platform}")
    if row:
        db.delete(row)
        db.commit()


def load(db: Session, platform: str) -> Credential | None:
    row = db.get(AppState, f"oauth:{platform}")
    if row and row.value.get("token"):
        try:
            token = _fernet().decrypt(row.value["token"].encode()).decode()
        except InvalidToken:  # SECRET_KEY changed: the stored token is unusable
            return None
        v = row.value
        return Credential(platform, token, v.get("user_id"), v.get("username"),
                          datetime.fromisoformat(v["expires_at"]) if v.get("expires_at") else None,
                          v.get("scopes") or [], "oauth",
                          datetime.fromisoformat(v["obtained_at"]) if v.get("obtained_at") else None)
    s = get_settings()
    if platform == "instagram" and s.instagram_access_token:
        return Credential("instagram", s.instagram_access_token, s.instagram_user_id or None, None, None, [], "env")
    if platform == "threads" and s.threads_access_token:
        return Credential("threads", s.threads_access_token, None, None, None, [], "env")
    return None
