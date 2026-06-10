"""Re-run the reconciler a few times to harvest the creator's DM reply."""
import time
from datetime import UTC, datetime

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import select  # noqa: E402

from recall.db import get_session_factory  # noqa: E402
from recall.instagram.client import build_client  # noqa: E402
from recall.models import Engagement, SavedItem  # noqa: E402
from recall.services.engagement import IgEngagementClient, reconcile_once  # noqa: E402

GMB_PK = "3907785651718712082"
CONFIG = {
    "enabled": True, "daily_follow_cap": 1, "daily_comment_cap": 1, "daily_dm_cap": 1,
    "min_delay_s": 2, "max_delay_s": 5, "dm_fallback_after_s": 7200, "exhaust_after_s": 172800,
}

client = IgEngagementClient(build_client())
factory = get_session_factory()

for attempt in range(8):
    with factory() as db:
        summary = reconcile_once(db, client, CONFIG, datetime.now(UTC))
        item = db.scalar(select(SavedItem).where(SavedItem.media_pk == GMB_PK))
        eng = db.scalar(select(Engagement).where(Engagement.item_id == item.id))
        print(f"attempt {attempt+1}: status={eng.status} summary={summary}", flush=True)
        if item.resources:
            print("RESOURCES HARVESTED:", item.resources, flush=True)
            break
    time.sleep(30)
else:
    print("no resource yet after polling; creator bot may be slow or require a follow/DM", flush=True)
