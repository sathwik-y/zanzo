"""Reset every non-completed item to PENDING and re-enqueue it.

Also re-enqueues COMPLETED items if --all is passed (stages are idempotent).
"""
import sys

from sqlalchemy import select

from recall.db import get_session_factory
from recall.models import ItemStatus, SavedItem
from recall.queueing import RedisQueue

include_completed = "--all" in sys.argv

queue = RedisQueue()
with get_session_factory()() as db:
    items = db.scalars(select(SavedItem)).all()
    n = 0
    for item in items:
        if item.status == ItemStatus.COMPLETED and not include_completed:
            continue
        item.status = ItemStatus.PENDING
        item.error_log = None
        queue.enqueue(str(item.id))
        n += 1
    db.commit()
print(f"re-enqueued {n} item(s)")
