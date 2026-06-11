"""Merge duplicate items created before claim-on-verify existed.

A media_pk that exists both as an unowned legacy row (user_id NULL) and as a
user-owned row is a duplicate: the owned row is kept, resources are merged
into it, and the legacy row is deleted. If the kept item's engagement is
still mid-flight while the merged resources already contain the goods, the
engagement is closed so the bot doesn't keep acting on a solved post.

Usage:
    python -m scripts.dedupe_items [--dry-run]
"""
import sys
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import select

from recall.db import get_session_factory
from recall.models import Engagement, EngagementStatus, SavedItem

ACTIVE_ENGAGEMENT = {
    EngagementStatus.PENDING,
    EngagementStatus.FOLLOWING,
    EngagementStatus.COMMENTED,
    EngagementStatus.AWAITING_REPLY,
    EngagementStatus.DM_SENT,
}


def main() -> int:
    dry = "--dry-run" in sys.argv
    deleted = merged = closed = 0

    with get_session_factory()() as db:
        groups: dict[str, list[SavedItem]] = defaultdict(list)
        for item in db.scalars(select(SavedItem)):
            groups[item.media_pk].append(item)

        for media_pk, items in groups.items():
            owned = [i for i in items if i.user_id is not None]
            legacy = [i for i in items if i.user_id is None]
            if not owned or not legacy:
                continue

            legacy_resources = [r for i in legacy for r in (i.resources or [])]
            for keeper in owned:
                urls = {r.get("url") for r in (keeper.resources or [])}
                extra = [r for r in legacy_resources if r.get("url") not in urls]
                if extra:
                    keeper.resources = (keeper.resources or []) + extra
                    merged += len(extra)
                    eng = db.scalar(select(Engagement).where(Engagement.item_id == keeper.id))
                    if eng is not None and eng.status in ACTIVE_ENGAGEMENT:
                        eng.status = EngagementStatus.RESOURCE_RECEIVED
                        eng.resource_received_at = datetime.now(UTC)
                        closed += 1

            for dup in legacy:
                print(f"delete legacy duplicate {dup.id} ({media_pk})")
                db.delete(dup)
                deleted += 1

        if dry:
            db.rollback()
            print(f"[dry-run] would delete {deleted}, merge {merged} resources, close {closed} engagements")
        else:
            db.commit()
            print(f"deleted {deleted} legacy duplicates, merged {merged} resources, closed {closed} engagements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
