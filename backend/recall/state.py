"""Tiny key/value app-state helpers (poller status, cursors)."""
from sqlalchemy.orm import Session

from recall.models import AppState

POLLER_KEY = "poller"
ENGAGEMENT_KEY = "engagement"

# Enabled by default (burner account); conservative caps + delays keep it ban-safe.
# One write action per reconcile pass, spaced >= min_action_gap_s apart, capped
# per rolling hour and per day, and suppressed during the poller's quiet hours.
DEFAULT_ENGAGEMENT_CONFIG = {
    "enabled": True,
    "daily_follow_cap": 4,
    "daily_comment_cap": 4,
    "daily_dm_cap": 3,
    "hourly_action_cap": 2,        # max write actions in any rolling hour
    "min_action_gap_s": 900,       # >= 15 min between consecutive write actions
    "min_delay_s": 120,
    "max_delay_s": 600,
    "dm_fallback_after_s": 7200,   # DM the keyword if no reply 2h after commenting
    "exhaust_after_s": 172800,     # give up watching for a reply after 2 days
}


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


def get_engagement_config(db: Session) -> dict:
    return {**DEFAULT_ENGAGEMENT_CONFIG, **get_state(db, ENGAGEMENT_KEY)}
