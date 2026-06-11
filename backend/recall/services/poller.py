"""Poller service: discovers new saved/DMed media and enqueues processing jobs.

Run with: python -m recall.services.poller
"""
import logging
import random
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from recall.config import get_settings
from recall.db import get_session_factory
from recall.instagram.client import InstagramChallengeError, build_client
from recall.instagram.dms import fetch_dm_inbox
from recall.instagram.saved import fetch_saved
from recall.instagram.types import DiscoveredMedia, DmText
from recall.models import ItemStatus, SavedItem, User
from recall.queueing import JobQueue, RedisQueue
from recall.state import POLLER_KEY, get_state, set_state

logger = logging.getLogger(__name__)


def _resolve_owner(db: Session, d: DiscoveredMedia) -> uuid.UUID | None:
    """DM shares belong to the verified user whose ig_user_pk matches the sender.

    Saved-collection items and DMs from unlinked accounts stay unassigned
    (user_id NULL) — visible to admins only.
    """
    if d.source != "DM" or not d.dm_sender_pk:
        return None
    user = db.scalar(
        select(User).where(User.ig_user_pk == d.dm_sender_pk, User.ig_verified.is_(True))
    )
    return user.id if user else None


def ingest_discovered(db: Session, queue: JobQueue, discovered: list[DiscoveredMedia]) -> int:
    """Insert PENDING rows for unseen media and enqueue jobs. Returns new-item count."""
    if not discovered:
        return 0
    # Dedup within the batch per (owner, media_pk): the same reel DMed by two
    # different users is two items; an item both saved and DMed (same owner)
    # keeps the first occurrence.
    by_key: dict[tuple[uuid.UUID | None, str], DiscoveredMedia] = {}
    owners: dict[tuple[uuid.UUID | None, str], uuid.UUID | None] = {}
    for d in discovered:
        owner = _resolve_owner(db, d)
        key = (owner, d.media_pk)
        by_key.setdefault(key, d)
        owners.setdefault(key, owner)

    existing = {
        (uid, pk)
        for uid, pk in db.execute(
            select(SavedItem.user_id, SavedItem.media_pk).where(
                SavedItem.media_pk.in_({pk for _, pk in by_key})
            )
        )
    }
    new_items = [(key, d) for key, d in by_key.items() if key not in existing]
    for key, d in new_items:
        item = SavedItem(
            user_id=owners[key],
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
        logger.info(
            "new item %s (%s, %s, owner=%s)", d.media_pk, d.source, d.media_type, owners[key]
        )
    db.commit()
    return len(new_items)


def process_verification_texts(db: Session, texts: list[DmText]) -> int:
    """Match DMed verification codes to pending account links. Returns matches."""
    if not texts:
        return 0
    now = datetime.now(UTC)
    pending = db.scalars(
        select(User).where(
            User.ig_verification_code.is_not(None),
            User.ig_verified.is_(False),
            User.ig_verification_expires_at > now,
        )
    ).all()
    if not pending:
        return 0

    verified = 0
    for text in texts:
        normalized = text.text.upper()
        for user in pending:
            if user.ig_verification_code and user.ig_verification_code in normalized:
                # The DM proves control of the sending account; bind its stable
                # pk (handles later username changes) and the actual handle.
                user.ig_user_pk = text.sender_pk
                if text.sender_username:
                    user.ig_username = text.sender_username.lower()
                user.ig_verified = True
                user.ig_verification_code = None
                user.ig_verification_expires_at = None
                verified += 1
                logger.info(
                    "instagram link verified for %s (ig=%s pk=%s)",
                    user.email,
                    user.ig_username,
                    user.ig_user_pk,
                )
    if verified:
        db.commit()
    return verified


def poll_once(db: Session, queue: JobQueue, cl) -> int:
    settings = get_settings()
    discovered: list[DiscoveredMedia] = []
    discovered.extend(fetch_saved(cl, amount=settings.max_items_per_poll))
    dm_shares, dm_texts = fetch_dm_inbox(cl)
    process_verification_texts(db, dm_texts)
    discovered.extend(dm_shares)
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
