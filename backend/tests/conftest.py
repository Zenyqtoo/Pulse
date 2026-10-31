import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://pulse:pulse@localhost:5432/pulse_test")
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["SECRET_KEY"] = "test-secret-key-0123456789abcdef0123456789abcdef"
os.environ["CITY_NAME"] = "Павлодар"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_ALERT_CHAT_ID"] = ""

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app import pipeline  # noqa: E402
from app.ai import llm  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import Base, SessionLocal, get_engine, reset_engine  # noqa: E402
from app.models import Source  # noqa: E402
from app.seed import seed  # noqa: E402

get_settings.cache_clear()


@pytest.fixture(scope="session")
def engine():
    reset_engine()
    eng = get_engine()
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    db = SessionLocal()
    seed(db)
    src = Source(type="demo", name="Демо-набор (синтетический)", is_synthetic=True, config={}, platform="demo",
                 geo_scope="city")
    db.add(src)
    db.commit()
    pipeline.run_source(db, src, "manual")
    pipeline.process_pending(db, limit=5000)
    pipeline.after_processing(db)
    db.close()
    yield eng


@pytest.fixture
def db(engine):
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture(scope="session")
def client(engine):
    from app.main import app

    with TestClient(app) as c:
        yield c


def token(client, login, password):
    r = client.post("/api/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def admin(client):
    return token(client, "admin", "admin123")


@pytest.fixture(scope="session")
def operator(client):
    return token(client, "operator", "operator123")


@pytest.fixture(scope="session")
def viewer(client):
    return token(client, "viewer", "viewer123")


@pytest.fixture(autouse=True)
def no_llm():
    llm.set_client(None)
    yield
    llm.set_client(None)
