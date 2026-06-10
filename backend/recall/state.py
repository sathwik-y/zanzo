"""Tiny key/value app-state helpers (poller status, cursors)."""
from sqlalchemy.orm import Session

from recall.models import AppState

POLLER_KEY = "poller"


def get_state(db: Session, key: str) -> dict:
    row = db.get(AppState, key)
    return row.value if row else {}


def set_state(db: Session, key: str, value: dict) -> None:
    row = db.get(AppState, key)
    if row:
        row.value = {**row.value, **value}
    else:
        db.add(AppState(key=key, value=value))
    db.commit()
