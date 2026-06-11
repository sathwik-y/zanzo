"""Bot account pool: admin CRUD, least-loaded assignment, verification binding."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from recall.ai.gemini import FakeGemini
from recall.api.deps import get_ai, get_storage
from recall.api.main import create_app
from recall.db import get_db
from recall.instagram.bots import pick_least_loaded_bot
from recall.instagram.types import DmText
from recall.models import BotAccount, BotStatus, User
from recall.services.poller import process_verification_texts
from recall.storage import LocalDirStorage


@pytest.fixture()
def client(db, tmp_path):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_storage] = lambda: LocalDirStorage(tmp_path)
    app.dependency_overrides[get_ai] = lambda: FakeGemini()
    return TestClient(app)


def _admin(client) -> dict:
    resp = client.post(
        "/auth/signup", json={"email": "admin@example.com", "password": "hunter2hunter2"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _user(client, email) -> dict:
    resp = client.post("/auth/signup", json={"email": email, "password": "hunter2hunter2"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_bot_crud_and_gating(client, db):
    admin = _admin(client)
    user = _user(client, "pleb@example.com")

    assert client.get("/admin/bots", headers=user).status_code == 403

    rows = client.post(
        "/admin/bots",
        json={"username": "@Bot.One", "sessionid": "session-one", "note": "first"},
        headers=admin,
    )
    assert rows.status_code == 201
    assert rows.json()[0]["username"] == "bot.one"
    assert rows.json()[0]["status"] == "ACTIVE"

    # duplicate username
    assert client.post(
        "/admin/bots", json={"username": "bot.one", "sessionid": "x" * 12}, headers=admin
    ).status_code == 409

    bot_id = rows.json()[0]["id"]
    updated = client.patch(
        f"/admin/bots/{bot_id}", json={"status": "DISABLED"}, headers=admin
    ).json()
    assert updated[0]["status"] == "DISABLED"
    assert client.patch(
        f"/admin/bots/{bot_id}", json={"status": "CHALLENGE"}, headers=admin
    ).status_code == 422

    deleted = client.delete(f"/admin/bots/{bot_id}", headers=admin)
    assert deleted.status_code == 200 and deleted.json() == []


def test_link_assigns_least_loaded_bot(client, db):
    admin = _admin(client)
    for name in ("bot.a", "bot.b"):
        client.post(
            "/admin/bots", json={"username": name, "sessionid": "s" * 12}, headers=admin
        )

    bots = {b.username: b for b in db.scalars(select(BotAccount)).all()}

    # three users link; they spread across the two bots
    assigned = []
    for i in range(3):
        headers = _user(client, f"u{i}@example.com")
        body = client.post(
            "/auth/instagram/link", json={"ig_username": f"insta{i}"}, headers=headers
        ).json()
        assigned.append(body["bot_username"])
    assert set(assigned) == {"bot.a", "bot.b"}
    counts = sorted(assigned.count(n) for n in ("bot.a", "bot.b"))
    assert counts == [1, 2]

    # a disabled bot never gets new users
    bots["bot.a"].status = BotStatus.DISABLED
    db.commit()
    headers = _user(client, "u9@example.com")
    body = client.post(
        "/auth/instagram/link", json={"ig_username": "insta9"}, headers=headers
    ).json()
    assert body["bot_username"] == "bot.b"

    assert pick_least_loaded_bot(db).username == "bot.b"


def test_verification_rebinds_to_receiving_bot(client, db):
    admin = _admin(client)
    client.post("/admin/bots", json={"username": "bot.a", "sessionid": "s" * 12}, headers=admin)
    client.post("/admin/bots", json={"username": "bot.b", "sessionid": "s" * 12}, headers=admin)
    bot_b = db.scalar(select(BotAccount).where(BotAccount.username == "bot.b"))

    headers = _user(client, "alice@example.com")
    code = client.post(
        "/auth/instagram/link", json={"ig_username": "alice"}, headers=headers
    ).json()["pending_code"]

    # the code lands in bot.b's inbox -> alice is bound to bot.b
    assert process_verification_texts(
        db,
        [DmText(sender_pk="777", sender_username="alice", text=f"ZANZO {code}")],
        bot=bot_b,
    ) == 1
    alice = db.scalar(select(User).where(User.email == "alice@example.com"))
    assert alice.bot_account_id == bot_b.id
    assert alice.ig_verified is True

    status = client.get("/auth/instagram/link", headers=headers).json()
    assert status["bot_username"] == "bot.b"


def test_delete_bot_reassigns_users(client, db):
    admin = _admin(client)
    client.post("/admin/bots", json={"username": "bot.a", "sessionid": "s" * 12}, headers=admin)
    client.post("/admin/bots", json={"username": "bot.b", "sessionid": "s" * 12}, headers=admin)
    bots = {b.username: b for b in db.scalars(select(BotAccount)).all()}

    headers = _user(client, "alice@example.com")
    client.post("/auth/instagram/link", json={"ig_username": "alice"}, headers=headers)
    alice = db.scalar(select(User).where(User.email == "alice@example.com"))
    original = alice.bot_account_id
    other = bots["bot.b"].id if original == bots["bot.a"].id else bots["bot.a"].id

    client.delete(f"/admin/bots/{original}", headers=admin)
    db.expire_all()
    alice = db.scalar(select(User).where(User.email == "alice@example.com"))
    assert alice.bot_account_id == other


def test_admin_users_includes_bot(client, db):
    admin = _admin(client)
    client.post("/admin/bots", json={"username": "bot.a", "sessionid": "s" * 12}, headers=admin)
    headers = _user(client, "alice@example.com")
    client.post("/auth/instagram/link", json={"ig_username": "alice"}, headers=headers)

    rows = client.get("/admin/users", headers=admin).json()
    alice_row = next(r for r in rows if r["email"] == "alice@example.com")
    assert alice_row["bot_username"] == "bot.a"
