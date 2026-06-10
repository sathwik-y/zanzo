"""Reprocess every non-completed item synchronously through the full pipeline.

Bypasses the Redis queue (which is flaky on Docker-for-Windows) so we get
deterministic, per-item output. Uses the real stages incl. multi-key Gemini.
"""
import sys

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import select  # noqa: E402

from recall.db import get_session_factory  # noqa: E402
from recall.models import Engagement, ItemStatus, SavedItem  # noqa: E402
from recall.pipeline.runner import process_item  # noqa: E402
from recall.services.worker import build_stages  # noqa: E402

stages = build_stages()
factory = get_session_factory()

with factory() as db:
    items = db.scalars(select(SavedItem).order_by(SavedItem.ingested_at)).all()
    ids = [(str(i.id), i.media_pk, i.author_username) for i in items]

for item_id, pk, author in ids:
    with factory() as db:
        item = db.get(SavedItem, item_id)
        item.status = ItemStatus.PENDING
        item.error_log = None
        db.commit()
    with factory() as db:
        ok = process_item(db, item_id, stages)
        item = db.get(SavedItem, item_id)
        eng = db.scalar(select(Engagement).where(Engagement.item_id == item.id))
        print(
            f"@{author:16} -> {item.status:12} cat={item.category} "
            f"eng={eng.status if eng else '-'}",
            flush=True,
        )

print("done", flush=True)
sys.exit(0)
