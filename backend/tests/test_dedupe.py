"""Re-linking the same Instagram must not re-ingest or re-engage anything."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from recall.ai.gemini import FakeGemini
from recall.api.deps import get_ai, get_storage
from recall.api.main import create_app
from recall.db import get_db
from recall.instagram.types import DiscoveredMedia, DmText
from recall.models import Engagement, EngagementStatus, SavedItem, User
from recall.pipeline.cta import CtaSpec, queue_engagement
from recall.queueing import InMemoryQueue
from recall.services.poller import ingest_discovered, process_verification_texts
from recall.storage import LocalDirStorage


@pytest.fixture()
def client(db, tmp_path):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_storage] = lambda: LocalDirStorage(tmp_path)
    app.dependency_overrides[get_ai] = lambda: FakeGemini()
    return TestClient(app)


def _signup_and_link(client, db, email: str) -> tuple[dict, str]:
    resp = client.post("/auth/signup", json={"email": email, "password": "hunter2hunter2"})
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    code = client.post(
        "/auth/instagram/link", json={"ig_username": "alice"}, headers=headers
    ).json()["pending_code"]
    return headers, code


def test_verified_user_claims_prior_items(client, db):
    # Reels arrive from pk 555 before anyone links that Instagram.
    queue = InMemoryQueue()
    pk1, pk2 = f"t-{uuid.uuid4().hex[:10]}", f"t-{uuid.uuid4().hex[:10]}"
    ingest_discovered(
        db,
        queue,
        [
            DiscoveredMedia(media_pk=pk1, source="DM", dm_sender_pk="555"),
            DiscoveredMedia(media_pk=pk2, source="DM", dm_sender_pk="555"),
        ],
    )
    assert queue.depth() == 2

    # Alice signs up and verifies that Instagram → history transfers, no re-ingest.
    headers, code = _signup_and_link(client, db, "alice@example.com")
    process_verification_texts(
        db, [DmText(sender_pk="555", sender_username="alice", text=f"ZANZO {code}")]
    )
    alice_id = uuid.UUID(client.get("/auth/me", headers=headers).json()["id"])
    owned = db.scalars(select(SavedItem).where(SavedItem.user_id == alice_id)).all()
    assert {i.media_pk for i in owned} == {pk1, pk2}

    # The next sweep sees the same reels: nothing new is inserted.
    assert ingest_discovered(
        db,
        queue,
        [DiscoveredMedia(media_pk=pk1, source="DM", dm_sender_pk="555")],
    ) == 0


def test_relink_moves_identity_and_keeps_single_copy(client, db):
    queue = InMemoryQueue()
    pk = f"t-{uuid.uuid4().hex[:10]}"

    # Account one owns the item via verification.
    h1, code1 = _signup_and_link(client, db, "one@example.com")
    process_verification_texts(
        db, [DmText(sender_pk="777", sender_username="alice", text=f"ZANZO {code1}")]
    )
    ingest_discovered(db, queue, [DiscoveredMedia(media_pk=pk, source="DM", dm_sender_pk="777")])

    # Same Instagram verifies on a fresh account.
    h2, code2 = _signup_and_link(client, db, "two@example.com")
    process_verification_texts(
        db, [DmText(sender_pk="777", sender_username="alice", text=f"ZANZO {code2}")]
    )

    one = db.scalar(select(User).where(User.email == "one@example.com"))
    two = db.scalar(select(User).where(User.email == "two@example.com"))
    assert one.ig_user_pk is None and one.ig_verified is False
    assert two.ig_user_pk == "777" and two.ig_verified is True

    # Future DMs of that reel land for account two as its own row; account
    # one's history is untouched.
    assert ingest_discovered(
        db, queue, [DiscoveredMedia(media_pk=pk, source="DM", dm_sender_pk="777")]
    ) == 1
    assert db.scalar(select(SavedItem).where(SavedItem.user_id == one.id)) is not None


def test_same_post_never_engaged_twice(db, make_item):
    owner = User(email="owner@example.com", password_hash="x", role="USER")
    db.add(owner)
    db.commit()

    spec = CtaSpec(is_cta=True, keyword="GUIDE", needs_follow=True, channel="both")
    first = make_item(user_id=owner.id, author_username="creator", status="COMPLETED")
    eng = queue_engagement(db, first, spec)
    assert eng is not None
    first.resources = [{"url": "https://example.com/guide", "source": "dm"}]
    eng.status = EngagementStatus.RESOURCE_RECEIVED
    db.commit()

    # The same post re-ingested as another item (other user / re-link):
    dup = make_item(media_pk=first.media_pk, user_id=None, author_username="creator", status="COMPLETED")
    assert queue_engagement(db, dup, spec) is None  # no second comment/follow
    assert db.scalar(select(Engagement).where(Engagement.item_id == dup.id)) is None
    # ...but it inherits the already-harvested resources.
    assert dup.resources and dup.resources[0]["url"] == "https://example.com/guide"
