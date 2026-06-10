"""Poller service: discovers new saved/DMed media and enqueues processing jobs.

Run with: python -m recall.services.poller
"""
import logging
import random
import time
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from recall.config import get_settings
from recall.db import get_session_factory
from recall.instagram.client import InstagramChallengeError, build_client
from recall.instagram.dms import fetch_dm_shares
from recall.instagram.saved import fetch_saved
from recall.instagram.types import DiscoveredMedia
from recall.models import ItemStatus, SavedItem
from recall.queueing import JobQueue, RedisQueue
from recall.state import POLLER_KEY, get_state, set_state

logger = logging.getLogger(__name__)


def ingest_discovered(db: Session, queue: JobQueue, discovered: list[DiscoveredMedia]) -> int:
    """Insert PENDING rows for unseen media and enqueue jobs. Returns new-item count."""
    if not discovered:
        return 0
    # Dedup within the batch (an item can be both saved and DMed; first wins)
    by_pk: dict[str, DiscoveredMedia] = {}
    for d in discovered:
        by_pk.setdefault(d.media_pk, d)

    existing = set(
        db.scalars(
            select(SavedItem.media_pk).where(SavedItem.media_pk.in_(by_pk.keys()))
        ).all()
    )
    new_items = [d for pk, d in by_pk.items() if pk not in existing]
    for d in new_items:
        item = SavedItem(
            media_pk=d.media_pk,
            media_type=d.media_type,
            source=d.source,
            instagram_url=d.instagram_url,
            author_username=d.author_username,
            author_full_name=d.author_full_name,
            caption=d.caption,
            post_created_at=d.post_created_at,
            saved_at=d.saved_at or datetime.now(UTC),
            status=ItemStatus.PENDING,
        )
        db.add(item)
        db.flush()
        queue.enqueue(str(item.id))
        logger.info("new item %s (%s, %s)", d.media_pk, d.source, d.media_type)
    db.commit()
    return len(new_items)


def poll_once(db: Session, queue: JobQueue, cl) -> int:
    settings = get_settings()
    discovered: list[DiscoveredMedia] = []
    discovered.extend(fetch_saved(cl, amount=settings.max_items_per_poll))
    discovered.extend(fetch_dm_shares(cl))
    return ingest_discovered(db, queue, discovered[: settings.max_items_per_poll])


def run_forever() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = get_settings()
    factory = get_session_factory()
    queue = RedisQueue()
    cl = None

    while True:
        with factory() as db:
            status = get_state(db, POLLER_KEY).get("status", "running")
            if status != "running":
                logger.info("poller %s; waiting for resume", status)
                time.sleep(15)
                continue
            try:
                if cl is None:
                    cl = build_client()
                new = poll_once(db, queue, cl)
                set_state(
                    db,
                    POLLER_KEY,
                    {
                        "status": "running",
                        "last_run_at": datetime.now(UTC).isoformat(),
                        "last_new_items": new,
                        "last_error": None,
                    },
                )
            except InstagramChallengeError as exc:
                logger.error("instagram challenge required: %s", exc)
                cl = None
                set_state(
                    db,
                    POLLER_KEY,
                    {
                        "status": "challenge_required",
                        "last_error": str(exc),
                        "last_run_at": datetime.now(UTC).isoformat(),
                    },
                )
                continue
            except Exception as exc:
                logger.exception("poll failed")
                set_state(
                    db,
                    POLLER_KEY,
                    {
                        "status": "running",
                        "last_error": f"{type(exc).__name__}: {exc}",
                        "last_run_at": datetime.now(UTC).isoformat(),
                    },
                )

        jitter = random.uniform(-settings.poll_jitter_seconds, settings.poll_jitter_seconds)
        time.sleep(max(30.0, settings.poll_interval_seconds + jitter))


if __name__ == "__main__":
    run_forever()
