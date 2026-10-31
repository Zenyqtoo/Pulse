from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.ai import embeddings
from app.audit import audit
from app.collectors.registry import PLATFORM_NAMES
from app.config import get_settings
from app.db import get_db
from app.models import AuditLog, Department, Enrichment, Source, User
from app.reference import PRIORITY_NAMES, SENTIMENT_NAMES, STATUS_NAMES, TYPE_NAMES, URGENCY_MARKERS
from app.security import create_token, get_current_user, hash_password, require_role, verify_password

router = APIRouter(prefix="/api", tags=["auth & admin"])

_attempts: dict[str, list[float]] = {}


class LoginIn(BaseModel):
    login: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


def user_dict(u: User) -> dict:
    return {"id": u.id, "login": u.login, "full_name": u.full_name, "role": u.role,
            "department_code": u.department_code, "active": u.active}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    import time

    key = f"{request.client.host if request.client else '-'}:{body.login.lower()}"
    now = time.time()
    recent = [t for t in _attempts.get(key, []) if now - t < 300]
    if len(recent) >= 10:
        raise HTTPException(429, "Слишком много попыток входа. Подождите 5 минут.")
    u = db.scalar(select(User).where(func.lower(User.login) == body.login.lower()))
    if u is None or not u.active or not verify_password(body.password, u.password_hash):
        _attempts[key] = recent + [now]
        audit(db, None, "auth.failed", login=body.login[:80])
        db.commit()
        raise HTTPException(401, "Неверный логин или пароль")
    _attempts.pop(key, None)
    audit(db, u, "auth.login")
    db.commit()
    return {"token": create_token(u), "user": user_dict(u)}


@router.get("/auth/me")
def me(user: User = Depends(get_current_user)):
    return user_dict(user)


@router.get("/meta")
def meta(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = get_settings()
    depts = db.scalars(select(Department).order_by(Department.sort)).all()
    districts = [d for (d,) in db.execute(select(distinct(Enrichment.district)).where(Enrichment.district.is_not(None))
                                          .limit(300)).all()]
    sources = db.scalars(select(Source).order_by(Source.id)).all()
    return {
        "app_name": s.app_name, "city_name": s.city_name,
        "departments": [{"code": d.code, "name": d.name, "name_kk": d.name_kk} for d in depts],
        "statuses": STATUS_NAMES, "sentiments": SENTIMENT_NAMES, "types": TYPE_NAMES, "priorities": PRIORITY_NAMES,
        "urgency_markers": URGENCY_MARKERS, "districts": sorted(districts),
        "sources": [{"id": x.id, "name": x.name, "type": x.type, "is_synthetic": x.is_synthetic, "platform": x.platform}
                    for x in sources],
        "platforms": PLATFORM_NAMES,
        "llm_enabled": s.llm_enabled, "llm_model": s.llm_model_enrich, "embedding_backend": embeddings.backend_name(),
        "user": user_dict(user),
    }


# --- users -----------------------------------------------------------------
class UserIn(BaseModel):
    login: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9_.\-]+$")
    full_name: str = Field(min_length=2, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    role: Literal["admin", "operator", "viewer"]
    department_code: str | None = None


class UserPatch(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=200)
    password: str | None = Field(None, min_length=8, max_length=200)
    role: Literal["admin", "operator", "viewer"] | None = None
    department_code: str | None = None
    active: bool | None = None


@router.get("/users")
def users(db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    return [user_dict(u) for u in db.scalars(select(User).order_by(User.id)).all()]


@router.post("/users")
def create_user(body: UserIn, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    if db.scalar(select(User).where(func.lower(User.login) == body.login.lower())):
        raise HTTPException(400, "Такой логин уже есть")
    u = User(login=body.login, full_name=body.full_name, password_hash=hash_password(body.password),
             role=body.role, department_code=body.department_code or None)
    db.add(u)
    db.flush()
    audit(db, user, "user.create", "user", u.id, role=body.role)
    db.commit()
    return user_dict(u)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserPatch, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Пользователь не найден")
    if u.id == user.id and (body.active is False or (body.role and body.role != "admin")):
        raise HTTPException(400, "Нельзя отключить себя или снять с себя роль администратора")
    data = body.model_dump(exclude_unset=True)
    if "password" in data:
        u.password_hash = hash_password(data.pop("password"))
    for k, v in data.items():
        setattr(u, k, v or None if k == "department_code" else v)
    audit(db, user, "user.update", "user", u.id, fields=list(body.model_dump(exclude_unset=True).keys()))
    db.commit()
    return user_dict(u)


# --- departments -----------------------------------------------------------
class DeptIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    name_kk: str | None = None
    description: str = Field("", max_length=1000)
    keywords: list[str] = []


@router.get("/departments")
def departments(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [{"code": d.code, "name": d.name, "name_kk": d.name_kk, "description": d.description,
             "keywords": d.keywords} for d in db.scalars(select(Department).order_by(Department.sort)).all()]


@router.put("/departments/{code}")
def upsert_department(code: str, body: DeptIn, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    if not code.replace("_", "").isalnum() or len(code) > 40:
        raise HTTPException(400, "Код: латиница, цифры и _")
    d = db.scalar(select(Department).where(Department.code == code))
    if d is None:
        d = Department(code=code, sort=(db.scalar(select(func.max(Department.sort))) or 0) + 1)
        db.add(d)
    d.name, d.name_kk, d.description = body.name, body.name_kk, body.description
    d.keywords = [k.strip().lower() for k in body.keywords if k.strip()]
    audit(db, user, "department.save", "department", code)
    db.commit()
    return {"ok": True}


@router.get("/audit")
def audit_log(limit: int = 200, action: str | None = None, db: Session = Depends(get_db),
              user: User = Depends(require_role("admin"))):
    stmt = select(AuditLog, User.full_name).outerjoin(User, User.id == AuditLog.user_id)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    rows = db.execute(stmt.order_by(AuditLog.created_at.desc()).limit(min(limit, 1000))).all()
    return [{"id": a.id, "at": a.created_at.isoformat(), "user": name or "—", "action": a.action,
             "entity": a.entity, "entity_id": a.entity_id, "details": a.details} for a, name in rows]
