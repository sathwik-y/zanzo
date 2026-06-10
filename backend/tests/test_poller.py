import uuid

from sqlalchemy import select

from recall.instagram.types import DiscoveredMedia
from recall.models import SavedItem
from recall.queueing import InMemoryQueue
from recall.services.poller import ingest_discovered


def _media(pk: str, source: str = "SAVED", **kw) -> DiscoveredMedia:
    return DiscoveredMedia(media_pk=pk, source=source, **kw)


def test_ingest_inserts_new_and_enqueues(db):
    queue = InMemoryQueue()
    pk = f"test-{uuid.uuid4().hex[:12]}"
    new = ingest_discovered(db, queue, [_media(pk, caption="hello")])
    assert new == 1
    assert queue.depth() == 1

    item = db.scalar(select(SavedItem).where(SavedItem.media_pk == pk))
    assert item.status == "PENDING"
    assert item.source == "SAVED"
    assert item.saved_at is not None
    assert queue.dequeue() == str(item.id)


def test_ingest_skips_existing_and_batch_dupes(db, make_item):
    queue = InMemoryQueue()
    existing = make_item()
    pk_new = f"test-{uuid.uuid4().hex[:12]}"
    discovered = [
        _media(existing.media_pk),          # already in DB
        _media(pk_new, source="SAVED"),     # new
        _media(pk_new, source="DM"),        # duplicate within batch
    ]
    new = ingest_discovered(db, queue, discovered)
    assert new == 1
    assert queue.depth() == 1
    item = db.scalar(select(SavedItem).where(SavedItem.media_pk == pk_new))
    assert item.source == "SAVED"  # first discovery wins
