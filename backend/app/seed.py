"""Idempotent seed: departments from the spec, three users, default sources."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Department, Source, User
from app.reference import DEPARTMENTS
from app.security import hash_password


def seed(db: Session) -> None:
    s = get_settings()
    for i, d in enumerate(DEPARTMENTS):
        if not db.scalar(select(Department).where(Department.code == d["code"])):
            db.add(Department(code=d["code"], name=d["name"], name_kk=d["name_kk"], description=d["description"],
                              keywords=d["keywords"], sort=i))
    users = [("admin", "Администратор системы", "admin", s.seed_admin_password),
             ("operator", "Оператор ситуационного центра", "operator", s.seed_operator_password),
             ("viewer", "Наблюдатель (пресс-служба)", "viewer", s.seed_viewer_password)]
    for login, name, role, pwd in users:
        if not db.scalar(select(User).where(User.login == login)):
            db.add(User(login=login, full_name=name, role=role, password_hash=hash_password(pwd)))
    defaults = [
        ("telegram_bot", "Direct: Telegram-бот приёма обращений", {"auto_ack": True}, 1, "city",
         "Личные обращения жителей в бот акимата"),
        ("telegram_web", "Telegram: публичные каналы", {"channels": [], "pages": 3}, 60, "region",
         "Посты публичных каналов (несколько каналов в одном источнике)"),
        ("telethon", "Telegram: комментарии и чаты", {"channels": [], "chats": [], "days": 7}, 60, "region",
         "Комментарии под постами и сообщения публичных чатов"),
        ("news", "Новостной портал", {"feeds": [], "max_articles": 30}, 60, "region", "RSS местного СМИ"),
        ("instagram", "Instagram: подключённый аккаунт", {"own_media": True, "business_accounts": [], "hashtags": [],
                                                          "direct": False, "days": 14}, 60, "city",
         "Комментарии под постами подключённого профессионального аккаунта"),
        ("threads", "Threads: поиск и ответы", {"keywords": ["Павлодар", "Pavlodar"], "own_posts": True,
                                                "fetch_replies": True, "days": 7}, 60, "national",
         "Поиск публичных постов по ключевым словам и ответы на них"),
    ]
    from app.collectors.registry import PLATFORM_OF

    for type_, name, cfg, minutes, scope, desc in defaults:
        if not db.scalar(select(Source).where(Source.type == type_)):
            db.add(Source(type=type_, name=name, config=cfg, enabled=type_ == "telegram_bot", schedule_minutes=minutes,
                          platform=PLATFORM_OF[type_], geo_scope=scope, description=desc))
    db.commit()
