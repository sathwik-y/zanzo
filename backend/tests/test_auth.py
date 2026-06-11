"""Auth: signup/login/refresh, role assignment, per-user scoping, IG linking."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from recall.ai.gemini import FakeGemini
from recall.api.deps import get_ai, get_storage
from recall.api.main import create_app
from recall.config import get_settings
from recall.db import get_db
from recall.instagram.types import DiscoveredMedia, DmText
from recall.models import SavedItem, User
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


@pytest.fixture()
def service_auth():
    return {"X-API-Key": get_settings().api_key}


def _signup(client, email, password="hunter2hunter2") -> dict:
    resp = client.post("/auth/signup", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _bearer(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_signup_login_me_refresh(client):
    tokens = _signup(client, "alice@example.com")
    assert tokens["user"]["email"] == "alice@example.com"

    assert client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "wrong-password"}
    ).status_code == 401
    login = client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "hunter2hunter2"}
    )
    assert login.status_code == 200

    me = client.get("/auth/me", headers=_bearer(login.json()))
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"

    refreshed = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    assert client.get("/auth/me", headers=_bearer(refreshed.json())).status_code == 200

    # a refresh token is not an access token
    assert client.get(
        "/auth/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}
    ).status_code == 401

    # duplicate email
    assert client.post(
        "/auth/signup", json={"email": "alice@example.com", "password": "hunter2hunter2"}
    ).status_code == 409


def test_first_user_and_admin_emails_become_admin(client):
    settings = get_settings()
    old = settings.admin_emails
    settings.admin_emails = "boss@example.com"
    try:
        first = _signup(client, "first@example.com")
        assert first["user"]["role"] == "ADMIN"  # bootstrap: first account
        normal = _signup(client, "pleb@example.com")
        assert normal["user"]["role"] == "USER"
        boss = _signup(client, "boss@example.com")
        assert boss["user"]["role"] == "ADMIN"  # on the admin list
    finally:
        settings.admin_emails = old


def test_items_scoped_per_user(client, db, make_item, service_auth):
    admin = _signup(client, "admin@example.com")  # first → ADMIN
    alice = _signup(client, "alice@example.com")
    bob = _signup(client, "bob@example.com")

    alice_id = uuid.UUID(alice["user"]["id"])
    bob_id = uuid.UUID(bob["user"]["id"])
    a_item = make_item(user_id=alice_id, status="COMPLETED", caption="alice reel")
    b_item = make_item(user_id=bob_id, status="COMPLETED", caption="bob reel")
    legacy = make_item(status="COMPLETED", caption="unassigned legacy")

    def ids(tokens):
        return {i["id"] for i in client.get("/items", headers=_bearer(tokens)).json()["items"]}

    assert ids(alice) == {str(a_item.id)}
    assert ids(bob) == {str(b_item.id)}
    # admin sees own (none) + unassigned, but NOT other users' items
    assert ids(admin) == {str(legacy.id)}
    # service key sees everything
    everything = {
        i["id"] for i in client.get("/items", headers=service_auth).json()["items"]
    }
    assert everything == {str(a_item.id), str(b_item.id), str(legacy.id)}

    # cross-user detail access is a 404, as are mutations
    assert client.get(f"/items/{b_item.id}", headers=_bearer(alice)).status_code == 404
    assert client.delete(f"/items/{b_item.id}", headers=_bearer(alice)).status_code == 404
    assert client.get(f"/items/{a_item.id}", headers=_bearer(alice)).status_code == 200

    # stats are scoped too
    assert client.get("/stats", headers=_bearer(alice)).json()["total_items"] == 1


def test_admin_endpoints_gated(client, service_auth):
    _signup(client, "admin@example.com")  # first → ADMIN
    user = _signup(client, "user@example.com")
    admin_login = client.post(
        "/auth/login", json={"email": "admin@example.com", "password": "hunter2hunter2"}
    ).json()

    assert client.get("/admin/users", headers=_bearer(user)).status_code == 403
    assert client.get("/poller/status", headers=_bearer(user)).status_code == 403
    assert client.get("/engagement/config", headers=_bearer(user)).status_code == 403

    rows = client.get("/admin/users", headers=_bearer(admin_login))
    assert rows.status_code == 200
    assert {r["email"] for r in rows.json()} == {"admin@example.com", "user@example.com"}
    assert client.get("/admin/stats", headers=_bearer(admin_login)).status_code == 200
    # service key is admin-equivalent
    assert client.get("/admin/users", headers=service_auth).status_code == 200


def test_ig_link_and_dm_verification(client, db):
    tokens = _signup(client, "alice@example.com")
    resp = client.post(
        "/auth/instagram/link", json={"ig_username": "@Alice.Reels"}, headers=_bearer(tokens)
    )
    assert resp.status_code == 200
    body = resp.json()
    code = body["pending_code"]
    assert code and len(code) == 6
    assert body["ig_username"] == "alice.reels"
    assert body["ig_verified"] is False

    # wrong code does nothing
    assert process_verification_texts(
        db, [DmText(sender_pk="111", sender_username="alice_actual", text="ZANZO NOPE")]
    ) == 0
    # right code (case-insensitive, embedded in a sentence) verifies and binds
    # the *actual* sender identity
    assert process_verification_texts(
        db,
        [DmText(sender_pk="111", sender_username="Alice_Actual", text=f"zanzo {code.lower()}")],
    ) == 1

    status = client.get("/auth/instagram/link", headers=_bearer(tokens)).json()
    assert status["ig_verified"] is True
    assert status["ig_username"] == "alice_actual"
    assert status["pending_code"] is None

    user = db.scalar(select(User).where(User.email == "alice@example.com"))
    assert user.ig_user_pk == "111"

    # expired codes never match
    tokens2 = _signup(client, "bob@example.com")
    client.post("/auth/instagram/link", json={"ig_username": "bob"}, headers=_bearer(tokens2))
    bob = db.scalar(select(User).where(User.email == "bob@example.com"))
    bob_code = bob.ig_verification_code
    bob.ig_verification_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    assert process_verification_texts(
        db, [DmText(sender_pk="222", sender_username="bob", text=f"ZANZO {bob_code}")]
    ) == 0


def test_dm_items_route_to_verified_owner(client, db):
    tokens = _signup(client, "alice@example.com")
    code = client.post(
        "/auth/instagram/link", json={"ig_username": "alice"}, headers=_bearer(tokens)
    ).json()["pending_code"]
    process_verification_texts(
        db, [DmText(sender_pk="9001", sender_username="alice", text=f"ZANZO {code}")]
    )

    queue = InMemoryQueue()
    pk = f"test-{uuid.uuid4().hex[:12]}"
    discovered = [
        DiscoveredMedia(media_pk=pk, source="DM", dm_sender_pk="9001", dm_sender_username="alice"),
        DiscoveredMedia(media_pk=pk, source="DM", dm_sender_pk="404404"),  # unlinked sender
        DiscoveredMedia(media_pk=f"test-{uuid.uuid4().hex[:12]}", source="SAVED"),
    ]
    assert ingest_discovered(db, queue, discovered) == 3

    alice_id = uuid.UUID(tokens["user"]["id"])
    owned = db.scalars(select(SavedItem).where(SavedItem.user_id == alice_id)).all()
    assert len(owned) == 1 and owned[0].media_pk == pk
    unassigned = db.scalars(select(SavedItem).where(SavedItem.user_id.is_(None))).all()
    assert len(unassigned) == 2

    # same reel DMed again by the same user → deduplicated
    assert ingest_discovered(
        db,
        queue,
        [DiscoveredMedia(media_pk=pk, source="DM", dm_sender_pk="9001")],
    ) == 0
