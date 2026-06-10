"""Pipeline orchestration: walks an item through its stages with status tracking.

Each stage is a callable (db, item) -> None. Stages must be idempotent so a
retry re-runs the whole pipeline safely (fetch skips existing media, etc.).
On failure the item is parked at FAILED_<STAGE> with the error captured in
error_log; other items are unaffected.
"""
import logging
import traceback
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from recall.models import ItemStatus, SavedItem

logger = logging.getLogger(__name__)

Stage = Callable[[Session, SavedItem], None]

# (running status, failed status) per stage name
STAGE_STATUSES: dict[str, tuple[ItemStatus, ItemStatus]] = {
    "fetch": (ItemStatus.FETCHING, ItemStatus.FAILED_FETCH),
    "transcribe": (ItemStatus.TRANSCRIBING, ItemStatus.FAILED_TRANSCRIBE),
    "classify": (ItemStatus.CLASSIFYING, ItemStatus.FAILED_CLASSIFY),
    "extract": (ItemStatus.EXTRACTING, ItemStatus.FAILED_EXTRACT),
    "embed": (ItemStatus.EMBEDDING, ItemStatus.FAILED_EMBED),
}

STAGE_ORDER = ["fetch", "transcribe", "classify", "extract", "embed"]


def process_item(db: Session, item_id: str, stages: dict[str, Stage]) -> bool:
    """Run all stages for one item. Returns True if it reached COMPLETED."""
    item = db.get(SavedItem, item_id)
    if item is None:
        logger.warning("item %s vanished before processing", item_id)
        return False

    for name in STAGE_ORDER:
        stage = stages.get(name)
        if stage is None:
            continue
        running, failed = STAGE_STATUSES[name]
        item.status = running
        db.commit()
        try:
            stage(db, item)
        except Exception as exc:
            tb = traceback.format_exc(limit=8)
            logger.exception("stage %s failed for item %s", name, item.media_pk)
            item.status = failed
            item.error_log = {
                "stage": name,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback_tail": tb[-2000:],
                "at": datetime.now(UTC).isoformat(),
            }
            db.commit()
            return False

    item.status = ItemStatus.COMPLETED
    item.error_log = None
    db.commit()
    logger.info("item %s completed", item.media_pk)
    return True
