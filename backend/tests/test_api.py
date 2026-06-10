import uuid

import pytest
from fastapi.testclient import TestClient

from recall.ai.gemini import FakeGemini
from recall.api.deps import get_ai, get_storage
from recall.api.main import create_app
from recall.config import get_settings
from recall.db import get_db
from recall.models import Embedding, Extraction
from recall.storage import LocalDirStorage


@pytest.fixture()
def client(db, tmp_path):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_storage] = lambda: LocalDirStorage(tmp_path)
    app.dependency_overrides[get_ai] = lambda: FakeGemini()
    return TestClient(app)


@pytest.fixture()
def auth():
    return {"X-API-Key": get_settings().api_key}


def test_health_needs_no_auth(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_items_requires_api_key(client):
    assert client.get("/items").status_code == 401
    assert client.get("/items", headers={"X-API-Key": "wrong"}).status_code == 401


def test_list_and_detail(client, auth, db, make_item):
    item = make_item(caption="ramen tour of tokyo", category="TRAVEL", status="COMPLETED")
    db.add(Extraction(item_id=item.id, payload={"destination": "Tokyo", "summary": "ramen"}))
    db.commit()

    resp = client.get("/items", headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    listed = [i for i in body["items"] if i["id"] == str(item.id)]
    assert listed and listed[0]["extraction"]["destination"] == "Tokyo"

    detail = client.get(f"/items/{item.id}", headers=auth).json()
    assert detail["caption"] == "ramen tour of tokyo"
    assert detail["extraction"]["summary"] == "ramen"

    assert client.get(f"/items/{uuid.uuid4()}", headers=auth).status_code == 404


def test_category_filter(client, auth, make_item):
    a = make_item(category="RECIPE", status="COMPLETED")
    make_item(category="EVENT", status="COMPLETED")
    body = client.get("/items?category=recipe", headers=auth).json()
    ids = [i["id"] for i in body["items"]]
    assert str(a.id) in ids
    assert all(i["category"] == "RECIPE" for i in body["items"])


def test_search_semantic_and_text(client, auth, db, make_item):
    fake = FakeGemini()
    a = make_item(caption="incredible tonkotsu ramen broth recipe", status="COMPLETED")
    b = make_item(caption="postgres replication deep dive", status="COMPLETED")
    for it in (a, b):
        db.add(Embedding(item_id=it.id, vector=fake.embed(db, it.id, it.caption), model="fake"))
    db.commit()

    body = client.get("/items?search=ramen", headers=auth).json()
    assert body["items"], "search returned nothing"
    top = body["items"][0]
    assert top["id"] == str(a.id)
    assert "text" in top["match_reason"]


def test_recategorize_reruns_extraction(client, auth, db, make_item):
    item = make_item(caption="actually a recipe", category="OTHER", status="COMPLETED")
    resp = client.post(
        f"/items/{item.id}/recategorize", json={"category": "RECIPE"}, headers=auth
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["category"] == "RECIPE"
    assert body["category_confidence"] == 1.0
    assert "ingredients" in body["extraction"]


def test_archive_and_delete(client, auth, db, make_item):
    item = make_item(status="COMPLETED")
    assert client.patch(f"/items/{item.id}", json={"archived": True}, headers=auth).json()["archived"] is True
    # archived items vanish from the default list
    ids = [i["id"] for i in client.get("/items", headers=auth).json()["items"]]
    assert str(item.id) not in ids
    assert client.delete(f"/items/{item.id}", headers=auth).status_code == 204
    assert client.get(f"/items/{item.id}", headers=auth).status_code == 404


def test_stats(client, auth, make_item):
    make_item(category="RECIPE", status="COMPLETED")
    make_item(status="FAILED_TRANSCRIBE")
    body = client.get("/stats", headers=auth).json()
    assert body["total_items"] >= 2
    assert body["failed_count"] >= 1
    assert "RECIPE" in body["by_category"]


def test_poller_status_and_resume(client, auth):
    body = client.post("/poller/resume", headers=auth).json()
    assert body["status"] == "running"
    assert client.get("/poller/status", headers=auth).json()["status"] == "running"


def test_event_ics(client, auth, db, make_item):
    item = make_item(category="EVENT", status="COMPLETED")
    db.add(
        Extraction(
            item_id=item.id,
            payload={
                "title": "Winter Beats Festival",
                "event_type": "festival",
                "starts_at": "2026-11-21T18:00:00+05:30",
                "venue_name": "Palace Grounds",
                "city": "Bengaluru",
                "ticket_url": "https://example.com/tix",
                "summary": "Two stages, eight artists.",
            },
        )
    )
    db.commit()

    resp = client.post(f"/actions/event/{item.id}/add-to-calendar", headers=auth)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/calendar")
    assert "Winter Beats Festival" in resp.text
    assert "BEGIN:VEVENT" in resp.text

    no_date = make_item(category="EVENT", status="COMPLETED")
    db.add(Extraction(item_id=no_date.id, payload={"title": "x", "event_type": "other", "summary": "y"}))
    db.commit()
    assert client.post(f"/actions/event/{no_date.id}/add-to-calendar", headers=auth).status_code == 422
