"""Run the engagement reconciler against real Instagram for a few passes.

Follows + comments on PENDING engagements (within caps), then watches for
creator replies to harvest into resources. Short delays so it runs now.
"""
import time
from datetime import UTC, datetime

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import select  # noqa: E402

from recall.db import get_session_factory  # noqa: E402
from recall.instagram.client import build_client  # noqa: E402
from recall.models import Engagement  # noqa: E402
from recall.services.engagement import IgEngagementClient, reconcile_once  # noqa: E402

CONFIG = {
    "enabled": True,
    "daily_follow_cap": 10,
    "daily_comment_cap": 10,
    "daily_dm_cap": 10,
    "min_delay_s": 3,
    "max_delay_s": 8,
    "dm_fallback_after_s": 7200,
    "exhaust_after_s": 172800,
}

client = IgEngagementClient(build_client())
factory = get_session_factory()

for n in range(4):
    with factory() as db:
        summary = reconcile_once(db, client, CONFIG, datetime.now(UTC))
        rows = db.scalars(select(Engagement)).all()
        states = ", ".join(f"@{e.creator_username}:{e.status}" for e in rows)
        print(f"pass {n + 1}: {summary}", flush=True)
        print(f"   {states}", flush=True)
    time.sleep(20)
print("done", flush=True)
