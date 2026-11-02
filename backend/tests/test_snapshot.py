import json

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import AppState, Item, Source, User
from app.snapshot import SNAPSHOT, load_snapshot


def test_bundled_snapshot_roundtrip_and_existing_data_guard(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "snapshot.sqlite3"))
    Base.metadata.create_all(engine)
    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    with Session(engine) as db:
        result = load_snapshot(db)
        assert result["items"] == len(payload["items"]) > 0
        assert db.scalar(select(func.count()).select_from(Item)) == result["items"]
        assert db.scalar(select(func.count()).select_from(User)) == 0
        assert db.scalar(select(func.count()).select_from(AppState)) == 0
        assert all(not s.enabled and s.config == {} for s in db.scalars(select(Source)))
        assert all(not it.is_direct and it.reply_ref is None and it.text == it.text_masked
                   for it in db.scalars(select(Item)))
        with pytest.raises(ValueError, match="без сообщений"):
            load_snapshot(db)
        assert db.scalar(select(func.count()).select_from(Item)) == result["items"]
    engine.dispose()
