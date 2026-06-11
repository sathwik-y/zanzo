"""Resources endpoint: search, status filter, pagination, scoping."""
import pytest
from fastapi.testclient import TestClient

from recall.ai.gemini import FakeGemini
from recall.api.deps import get_ai, get_storage
from recall.api.main import create_app
from recall.config import get_settings
from recall.db import get_db
from recall.models import Engagement
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


def _engaged_item(db, make_item, *, creator, keyword, status, resources=None, caption=None):
    item = make_item(status="COMPLETED", caption=caption, author_username=creator)
    if resources:
        item.resources = resources
    db.add(
        Engagement(
            item_id=item.id, creator_username=creator, media_pk=item.media_pk,
            keyword=keyword, needs_follow=False, channel="both", status=status,
        )
    )
    db.commit()
    return item


def test_resources_search_filter_pagination(client, auth, db, make_item):
    _engaged_item(
        db, make_item, creator="chef.anna", keyword="RECIPE",
        status="RESOURCE_RECEIVED",
        resources=[{"url": "https://notion.site/broth-guide", "source": "dm"}],
        caption="tonkotsu broth",
    )
    _engaged_item(db, make_item, creator="dev.bob", keyword="AGENTS", status="AWAITING_REPLY")
    for i in range(20):
        _engaged_item(db, make_item, creator=f"bulk{i}", keyword="X", status="PENDING")

    body = client.get("/resources", headers=auth).json()
    assert body["total"] == 22
    assert len(body["rows"]) == 20  # default page size

    # pagination
    page2 = client.get("/resources?limit=20&offset=20", headers=auth).json()
    assert page2["total"] == 22 and len(page2["rows"]) == 2

    # status group filter
    harvested = client.get("/resources?status=harvested", headers=auth).json()
    assert harvested["total"] == 1
    assert harvested["rows"][0]["creator_username"] == "chef.anna"
    progress = client.get("/resources?status=progress", headers=auth).json()
    assert progress["total"] == 21

    # search hits creator, keyword, caption and harvested link text
    for q in ("chef.anna", "tonkotsu", "notion.site"):
        found = client.get(f"/resources?search={q}", headers=auth).json()
        assert found["total"] == 1, q
    assert client.get("/resources?search=AGENTS", headers=auth).json()["total"] == 1
    assert client.get("/resources?search=zzz-nope", headers=auth).json()["total"] == 0


def test_home_search_finds_resource_links(client, auth, db, make_item):
    from recall.models import Embedding

    fake = FakeGemini()
    item = make_item(status="COMPLETED", caption="some reel")
    item.resources = [{"url": "https://example.com/ultimate-gmb-guide", "source": "dm"}]
    db.add(Embedding(item_id=item.id, vector=fake.embed(db, item.id, "some reel"), model="fake"))
    db.commit()

    body = client.get("/items?search=gmb-guide", headers=auth).json()
    assert any(i["id"] == str(item.id) for i in body["items"])
