from sqlalchemy import select

from recall.ai.gemini import FakeGemini
from recall.models import Engagement
from recall.pipeline.cta import detect_cta, make_cta_stage


def test_detect_cta_positive(db, make_item):
    item = make_item(
        caption='Comment "GMB" and follow me to get the exact workflow',
        author_username="builders.central",
    )
    spec = detect_cta(FakeGemini(), db, item)
    assert spec.is_cta is True
    assert spec.keyword == "GMB"
    assert spec.needs_follow is True
    assert spec.channel == "comment"


def test_detect_cta_dm_channel(db, make_item):
    item = make_item(caption="DM me the word START to receive the template", author_username="x")
    spec = detect_cta(FakeGemini(), db, item)
    assert spec.is_cta is True
    assert spec.channel == "dm"


def test_detect_cta_negative(db, make_item):
    item = make_item(caption="Just a normal travel vlog from Bali", author_username="x")
    spec = detect_cta(FakeGemini(), db, item)
    assert spec.is_cta is False


def test_cta_stage_queues_engagement(db, make_item):
    item = make_item(
        caption='comment "LINK" and follow me for the guide', author_username="creator1"
    )
    make_cta_stage(FakeGemini())(db, item)
    eng = db.scalar(select(Engagement).where(Engagement.item_id == item.id))
    assert eng is not None
    assert eng.keyword == "LINK"
    assert eng.needs_follow is True
    assert eng.creator_username == "creator1"
    assert eng.status == "PENDING"


def test_cta_stage_no_engagement_when_not_cta(db, make_item):
    item = make_item(caption="nice sunset", author_username="creator1")
    make_cta_stage(FakeGemini())(db, item)
    assert db.scalar(select(Engagement).where(Engagement.item_id == item.id)) is None


def test_cta_stage_idempotent(db, make_item):
    item = make_item(caption='comment "GUIDE"', author_username="creator1")
    stage = make_cta_stage(FakeGemini())
    stage(db, item)
    stage(db, item)
    rows = db.scalars(select(Engagement).where(Engagement.item_id == item.id)).all()
    assert len(rows) == 1
