import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from recall.models import Engagement, EngagementStatus, SavedItem
from recall.services.engagement import (
    harvest_links_from_messages,
    parse_thread_item,
    pending_interaction,
    reconcile_once,
)
from recall.state import DEFAULT_ENGAGEMENT_CONFIG

FIXTURES = Path(__file__).parent.parent / "fixtures"


class FakeClient:
    def __init__(self, messages=None):
        self.followed = []
        self.comments = []
        self.dms = []
        self._messages = messages or []

    def user_id(self, username):
        return f"uid-{username}"

    def follow(self, user_id):
        self.followed.append(user_id)

    def comment(self, media_pk, text):
        self.comments.append((media_pk, text))

    def dm(self, user_id, text):
        self.dms.append((user_id, text))

    def creator_messages(self, user_id):
        return self._messages


def _noop_sleep(_):
    pass


def _config(**over):
    cfg = dict(DEFAULT_ENGAGEMENT_CONFIG)
    cfg.update(over)
    return cfg


def _engagement(db, item, **kw):
    defaults = dict(
        item_id=item.id,
        creator_username="creator1",
        media_pk=item.media_pk,
        keyword="GMB",
        needs_follow=True,
        channel="both",
        status=EngagementStatus.PENDING,
    )
    defaults.update(kw)
    eng = Engagement(**defaults)
    db.add(eng)
    db.commit()
    return eng


def test_follow_then_comment(db, make_item):
    item = make_item()
    eng = _engagement(db, item)
    client = FakeClient()
    now = datetime.now(UTC)

    summary = reconcile_once(db, client, _config(), now, sleeper=_noop_sleep)
    db.refresh(eng)
    assert client.followed == ["uid-creator1"]
    assert client.comments == [(item.media_pk, "GMB")]
    assert eng.status == EngagementStatus.AWAITING_REPLY
    assert summary["followed"] == 1 and summary["commented"] == 1


def test_comment_cap_defers(db, make_item):
    # cap of 0 comments -> nothing should be commented, row stays PENDING
    item = make_item()
    eng = _engagement(db, item, needs_follow=False)
    client = FakeClient()
    summary = reconcile_once(
        db, client, _config(daily_comment_cap=0), datetime.now(UTC), sleeper=_noop_sleep
    )
    db.refresh(eng)
    assert client.comments == []
    assert eng.status == EngagementStatus.PENDING
    assert summary["deferred"] == 1


def test_resource_harvested_from_reply(db, make_item):
    item = make_item()
    commented = datetime.now(UTC) - timedelta(minutes=5)
    eng = _engagement(
        db, item, status=EngagementStatus.AWAITING_REPLY, commented_at=commented,
        creator_user_id="uid-creator1", needs_follow=False,
    )
    msgs = [
        {"timestamp": datetime.now(UTC), "text": "Here you go https://example.com/guide", "urls": []}
    ]
    client = FakeClient(messages=msgs)
    summary = reconcile_once(db, client, _config(), datetime.now(UTC), sleeper=_noop_sleep)
    db.refresh(eng)
    item = db.get(SavedItem, item.id)
    assert eng.status == EngagementStatus.RESOURCE_RECEIVED
    assert item.resources[0]["url"] == "https://example.com/guide"
    assert summary["resources"] == 1


def test_dm_fallback_after_threshold(db, make_item):
    item = make_item()
    # commented 3h ago, no reply, dm_fallback at 2h -> should DM now
    commented = datetime.now(UTC) - timedelta(hours=3)
    eng = _engagement(
        db, item, status=EngagementStatus.AWAITING_REPLY, commented_at=commented,
        creator_user_id="uid-creator1", needs_follow=False, channel="both",
    )
    client = FakeClient(messages=[])
    summary = reconcile_once(db, client, _config(), datetime.now(UTC), sleeper=_noop_sleep)
    db.refresh(eng)
    assert client.dms == [("uid-creator1", "GMB")]
    assert eng.status == EngagementStatus.DM_SENT
    assert summary["dm_sent"] == 1


def test_disabled_does_nothing(db, make_item):
    item = make_item()
    eng = _engagement(db, item)
    client = FakeClient()
    reconcile_once(db, client, _config(enabled=False), datetime.now(UTC), sleeper=_noop_sleep)
    db.refresh(eng)
    assert eng.status == EngagementStatus.PENDING
    assert client.followed == []


def test_parse_generic_xma_with_direct_link():
    item = json.loads((FIXTURES / "generic_xma_link.json").read_text())
    parsed = parse_thread_item(item)
    assert "https://helloveeru.com/gmb-workflow?ref=ig" in parsed["urls"]
    assert parsed["needs_interaction"] is False
    assert "GMB workflow" in parsed["text"]


def test_parse_generic_xma_postback_needs_interaction():
    item = json.loads((FIXTURES / "generic_xma_postback.json").read_text())
    parsed = parse_thread_item(item)
    assert parsed["urls"] == []
    assert parsed["needs_interaction"] is True
    assert "Click below" in parsed["text"]


def test_pending_interaction_detected():
    item = json.loads((FIXTURES / "generic_xma_postback.json").read_text())
    parsed = parse_thread_item(item)
    # message is newer than `since`
    text = pending_interaction([parsed], since=datetime(2026, 1, 1, tzinfo=UTC))
    assert text and "Click below" in text


def test_reconcile_marks_interaction_required(db, make_item):
    item = make_item()
    commented = datetime.now(UTC) - timedelta(minutes=2)
    eng = _engagement(
        db, item, status=EngagementStatus.AWAITING_REPLY, commented_at=commented,
        creator_user_id="uid-creator1", needs_follow=False, channel="comment",
    )
    postback = parse_thread_item(json.loads((FIXTURES / "generic_xma_postback.json").read_text()))
    postback["timestamp"] = datetime.now(UTC)  # newer than commented_at
    client = FakeClient(messages=[postback])
    reconcile_once(db, client, _config(), datetime.now(UTC), sleeper=_noop_sleep)
    db.refresh(eng)
    item = db.get(SavedItem, item.id)
    assert eng.status == EngagementStatus.INTERACTION_REQUIRED
    assert item.resources[0]["source"] == "interaction_required"


def test_reconcile_harvests_generic_xma_link(db, make_item):
    item = make_item()
    commented = datetime.now(UTC) - timedelta(minutes=2)
    eng = _engagement(
        db, item, status=EngagementStatus.AWAITING_REPLY, commented_at=commented,
        creator_user_id="uid-creator1", needs_follow=False,
    )
    linkmsg = parse_thread_item(json.loads((FIXTURES / "generic_xma_link.json").read_text()))
    linkmsg["timestamp"] = datetime.now(UTC)
    client = FakeClient(messages=[linkmsg])
    reconcile_once(db, client, _config(), datetime.now(UTC), sleeper=_noop_sleep)
    db.refresh(eng)
    item = db.get(SavedItem, item.id)
    assert eng.status == EngagementStatus.RESOURCE_RECEIVED
    assert "helloveeru.com/gmb-workflow" in item.resources[0]["url"]


def test_harvest_handles_naive_message_timestamps():
    # instagrapi returns naive datetimes; commented_at (since) is tz-aware.
    # Comparing them must not raise.
    aware_since = datetime.now(UTC) - timedelta(minutes=10)
    naive_after = (datetime.now(UTC) + timedelta(minutes=1)).replace(tzinfo=None)
    msgs = [{"timestamp": naive_after, "text": "link: https://res.com/x", "urls": []}]
    out = harvest_links_from_messages(msgs, since=aware_since)
    assert [r["url"] for r in out] == ["https://res.com/x"]


def test_harvest_links_dedup_and_since():
    base = datetime.now(UTC)
    msgs = [
        {"timestamp": base - timedelta(hours=1), "text": "old https://old.com", "urls": []},
        {"timestamp": base + timedelta(minutes=1), "text": "new https://a.com and https://a.com", "urls": []},
        {"timestamp": base + timedelta(minutes=2), "text": None, "urls": ["https://b.com"]},
    ]
    out = harvest_links_from_messages(msgs, since=base)
    urls = [r["url"] for r in out]
    assert urls == ["https://a.com", "https://b.com"]  # old excluded, dupes collapsed
