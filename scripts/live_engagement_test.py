"""Live engagement test: queue the GMB reel's CTA, then do a REAL follow+comment.

Uses FakeGemini for CTA detection (no Gemini quota needed) and the real
Instagram client for the follow/comment. Low caps + short delays so it runs now.
Run it again after a minute to harvest the creator's DM reply into resources.
"""
import sys
from datetime import UTC, datetime

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import select  # noqa: E402

from recall.ai.gemini import FakeGemini  # noqa: E402
from recall.db import get_session_factory  # noqa: E402
from recall.instagram.client import build_client  # noqa: E402
from recall.models import Engagement, SavedItem  # noqa: E402
from recall.pipeline.cta import detect_cta, queue_engagement  # noqa: E402
from recall.services.engagement import IgEngagementClient, reconcile_once  # noqa: E402

GMB_PK = "3907785651718712082"

CONFIG = {
    "enabled": True,
    "daily_follow_cap": 1,
    "daily_comment_cap": 1,
    "daily_dm_cap": 1,
    "min_delay_s": 2,
    "max_delay_s": 5,
    "dm_fallback_after_s": 7200,
    "exhaust_after_s": 172800,
}

db = get_session_factory()()
item = db.scalar(select(SavedItem).where(SavedItem.media_pk == GMB_PK))

# 1. Ensure the engagement row exists (FakeGemini CTA detection, no quota burn)
existing = db.scalar(select(Engagement).where(Engagement.item_id == item.id))
if existing is None:
    spec = detect_cta(FakeGemini(), db, item)
    print(f"CTA detected: keyword={spec.keyword} needs_follow={spec.needs_follow} channel={spec.channel}")
    queue_engagement(db, item, spec)
else:
    print(f"engagement already exists: status={existing.status}")

# 2. Real reconcile against Instagram
client = IgEngagementClient(build_client())
summary = reconcile_once(db, client, CONFIG, datetime.now(UTC))
print("reconcile summary:", summary)

eng = db.scalar(select(Engagement).where(Engagement.item_id == item.id))
print(f"engagement status now: {eng.status}")
if eng.last_error:
    print("last_error:", eng.last_error)
db.refresh(item)
print("resources:", item.resources)
sys.exit(0)
