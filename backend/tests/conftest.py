import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from recall.config import get_settings
from recall.db import Base

# DB tests run against a SEPARATE database (the dev DB name + "_test") so they
# never read or mutate real data. reconcile_once() in particular queries the
# whole engagements table, so sharing the dev DB would let tests act on real
# rows. The test DB is created and schema-built on first use.


def _test_database_url() -> str:
    url = get_settings().database_url
    base, _, name = url.rpartition("/")
    return f"{base}/{name}_test"


@pytest.fixture(scope="session")
def engine():
    import recall.models  # noqa: F401  (register tables on Base.metadata)

    admin_url = get_settings().database_url
    test_url = _test_database_url()
    test_db_name = test_url.rpartition("/")[2]

    try:
        admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": test_db_name}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{test_db_name}"'))
    except Exception:
        pytest.skip("postgres not running (docker compose up -d postgres)")

    eng = create_engine(test_url)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def db(engine):
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    yield session
    session.rollback()
    # Isolated test DB: wipe everything between tests for full isolation.
    session.execute(
        text(
            "TRUNCATE saved_items, app_state, llm_usage, users, bot_accounts "
            "RESTART IDENTITY CASCADE"
        )
    )
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
