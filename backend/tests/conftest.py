import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from recall.config import get_settings

# All DB tests run against the dockerized postgres from docker-compose.yml.
# They use the migrated schema and clean up after themselves.


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(get_settings().database_url)
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("postgres not running (docker compose up -d postgres)")
    return eng


@pytest.fixture()
def db(engine):
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    yield session
    session.rollback()
    # Clean rows created by tests (test media_pks are prefixed)
    session.execute(text("DELETE FROM saved_items WHERE media_pk LIKE 'test-%'"))
    session.execute(text("DELETE FROM app_state WHERE key LIKE 'test.%'"))
    session.commit()
    session.close()


@pytest.fixture()
def make_item(db):
    from recall.models import SavedItem

    def _make(**kw):
        defaults = dict(
            media_pk=f"test-{uuid.uuid4().hex[:12]}",
            media_type="REEL",
            source="SAVED",
            caption="test caption",
            status="PENDING",
        )
        defaults.update(kw)
        item = SavedItem(**defaults)
        db.add(item)
        db.commit()
        return item

    return _make
