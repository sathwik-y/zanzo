"""Engagement reconciler: acts on queued CTAs to fetch creator resources.

State machine per engagement row:
  PENDING -> (follow if needed) -> FOLLOWING -> (comment keyword) -> COMMENTED/AWAITING_REPLY
  AWAITING_REPLY -> harvest creator DM links -> RESOURCE_RECEIVED
                 -> (after dm_fallback_after_s, DM the keyword) -> DM_SENT -> AWAITING_REPLY
                 -> (after exhaust_after_s) -> EXHAUSTED
Any write error increments attempts and records last_error; too many -> FAILED.

Daily caps are counted from the row timestamps, so rows deferred when a cap is
hit are simply retried on the next run once the 24h window rolls forward.

Run with: python -m recall.services.engagement
"""
import logging
import random
import re
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from recall.db import get_session_factory
from recall.instagram.bots import BotClientPool
from recall.models import Engagement, EngagementChannel, EngagementStatus, SavedItem
from recall.state import get_engagement_config

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
_URL_RE = re.compile(r"https?://[^\s\"'<>)]+")


def _as_utc(dt: datetime | None) -> datetime | None:
    """Coerce a datetime to timezone-aware UTC.

    instagrapi returns naive datetimes; our DB timestamps are aware. Comparing
    the two raises, so normalize everything before comparing.
    """
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _ts_from_micros(raw) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(raw) / 1_000_000, tz=UTC)
    except (TypeError, ValueError):
        return None


def parse_thread_item(item: dict) -> dict:
    """Normalize a raw direct_v2 thread item into {timestamp, text, urls, needs_interaction}.

    Handles plain text, link attachments, shared media (xma_clip / media_share),
    and rich cards (generic_xma) including ManyChat-style postback buttons that
    gate the real link behind an in-app click.
    """
    text_parts: list[str] = []
    urls: list[str] = []
    needs_interaction = False
    itype = item.get("item_type")

    if item.get("text"):
        text_parts.append(item["text"])

    link = item.get("link") or {}
    if isinstance(link, dict):
        url = (link.get("link_context") or {}).get("link_url") or link.get("link_url")
        if url:
            urls.append(url)
        if link.get("text"):
            text_parts.append(link["text"])

    for key in ("generic_xma", "xma_clip", "xma_media_share"):
        for card in item.get(key) or []:
            if not isinstance(card, dict):
                continue
            for field in ("title_text", "subtitle_text", "caption_body_text"):
                if card.get(field):
                    text_parts.append(card[field])
            if card.get("target_url"):
                urls.append(card["target_url"])
            buttons = card.get("cta_buttons") or []
            has_postback = False
            for btn in buttons:
                action = (btn or {}).get("action_url")
                if action:
                    urls.append(action)
                elif (btn or {}).get("cta_type") == "postback":
                    has_postback = True
            # a card with only postback buttons and no real link needs a manual click
            if has_postback and not urls:
                needs_interaction = True

    clean_urls = []
    seen = set()
    for u in urls:
        u = u.strip()
        if u and u.startswith("http") and u not in seen:
            seen.add(u)
            clean_urls.append(u)

    return {
        "timestamp": _ts_from_micros(item.get("timestamp")),
        "text": " ".join(t.strip() for t in text_parts if t).strip() or None,
        "urls": clean_urls,
        "needs_interaction": needs_interaction,
        "item_type": itype,
    }


def harvest_links_from_messages(messages: list[dict], since: datetime | None) -> list[dict]:
    """Pull resource links from a creator's DM messages newer than `since`.

    Each message dict: {timestamp: datetime|None, text: str|None, urls: [str]}.
    Returns resource dicts {url, text, source, received_at}.
    """
    resources: list[dict] = []
    seen: set[str] = set()
    since = _as_utc(since)
    for msg in messages:
        ts = _as_utc(msg.get("timestamp"))
        if since is not None and ts is not None and ts <= since:
            continue
        urls = list(msg.get("urls") or [])
        urls += _URL_RE.findall(msg.get("text") or "")
        for url in urls:
            url = url.rstrip(".,)")
            if url in seen:
                continue
            seen.add(url)
            resources.append(
                {
                    "url": url,
                    "text": (msg.get("text") or "")[:200],
                    "source": "dm",
                    "received_at": (ts or datetime.now(UTC)).isoformat(),
                }
            )
    return resources


def pending_interaction(messages: list[dict], since: datetime | None) -> str | None:
    """Return the opening message text if the creator replied with a postback-gated
    card (link behind an in-app click) newer than `since` and no link was sent."""
    since = _as_utc(since)
    for msg in messages:
        ts = _as_utc(msg.get("timestamp"))
        if since is not None and ts is not None and ts <= since:
            continue
        if msg.get("needs_interaction") and not msg.get("urls"):
            return msg.get("text") or "Creator replied; open the chat to claim the resource."
    return None


class IgEngagementClient:
    """Thin wrapper over instagrapi for the actions the reconciler needs."""

    def __init__(self, cl):
        self.cl = cl

    def user_id(self, username: str) -> str:
        return str(self.cl.user_id_from_username(username))

    def follow(self, user_id: str) -> None:
        self.cl.user_follow(user_id)

    def comment(self, media_pk: str, text: str) -> None:
        self.cl.media_comment(self.cl.media_id(media_pk), text)

    def dm(self, user_id: str, text: str) -> None:
        self.cl.direct_send(text, user_ids=[int(user_id)])

    def creator_messages(self, user_id: str) -> list[dict]:
        """Recent DM messages from a creator's thread, normalized via the raw
        thread endpoint so rich generic_xma cards (and their links) are parsed."""
        try:
            thread = self.cl.direct_thread_by_participants([int(user_id)])
            thread_id = thread["thread"]["thread_id"] if isinstance(thread, dict) else thread.id
        except Exception:
            return []
        try:
            res = self.cl.private_request(
                f"direct_v2/threads/{thread_id}/", params={"limit": 20}
            )
            items = res["thread"]["items"]
        except Exception:
            return []
        return [parse_thread_item(it) for it in items]


class EngagementClientPool:
    """Resolves the IgEngagementClient for an item owner's assigned bot."""

    def __init__(self):
        self._bots = BotClientPool()
        self._wrapped: dict[int, IgEngagementClient] = {}

    def for_user(self, db: Session, user_id) -> IgEngagementClient:
        raw = self._bots.for_user(db, user_id)
        key = id(raw)
        if key not in self._wrapped:
            self._wrapped[key] = IgEngagementClient(raw)
        return self._wrapped[key]


def _today_count(db: Session, column, now: datetime) -> int:
    day_ago = now - timedelta(days=1)
    return (
        db.query(Engagement).filter(column.is_not(None), column >= day_ago).count()  # noqa: E711
    )


def _jitter_sleep(config: dict, sleeper=time.sleep) -> None:
    sleeper(random.uniform(config["min_delay_s"], config["max_delay_s"]))


def reconcile_once(db: Session, client, config: dict, now: datetime, sleeper=time.sleep) -> dict:
    """Advance every actionable engagement by at most one step. Returns a summary.

    `client` is an IgEngagementClient (or compatible fake). `sleeper` is
    injectable so tests run instantly.
    """
    summary = {"followed": 0, "commented": 0, "dm_sent": 0, "resources": 0, "deferred": 0}
    if not config.get("enabled"):
        return summary

    follows_today = _today_count(db, Engagement.commented_at, now)  # follow precedes comment
    comments_today = _today_count(db, Engagement.commented_at, now)
    dms_today = _today_count(db, Engagement.dm_sent_at, now)

    rows = db.scalars(
        select(Engagement).where(
            Engagement.status.in_(
                [
                    EngagementStatus.PENDING,
                    EngagementStatus.FOLLOWING,
                    EngagementStatus.COMMENTED,
                    EngagementStatus.AWAITING_REPLY,
                    EngagementStatus.DM_SENT,
                ]
            )
        )
    ).all()

    for eng in rows:
        try:
            # Pool mode: act through the bot assigned to the item's owner, so
            # the account that received the reel is the one that engages.
            if isinstance(client, EngagementClientPool):
                item = db.get(SavedItem, eng.item_id)
                cl = client.for_user(db, item.user_id if item else None)
            else:
                cl = client
            if eng.status in (EngagementStatus.PENDING, EngagementStatus.FOLLOWING):
                # follow (if required), then comment - both gated by caps
                if eng.needs_follow and eng.status == EngagementStatus.PENDING:
                    if comments_today >= config["daily_comment_cap"]:
                        summary["deferred"] += 1
                        continue
                    uid = eng.creator_user_id or cl.user_id(eng.creator_username)
                    eng.creator_user_id = uid
                    _jitter_sleep(config, sleeper)
                    cl.follow(uid)
                    eng.status = EngagementStatus.FOLLOWING
                    follows_today += 1
                    summary["followed"] += 1
                    db.commit()

                if comments_today >= config["daily_comment_cap"]:
                    summary["deferred"] += 1
                    continue
                _jitter_sleep(config, sleeper)
                cl.comment(eng.media_pk, eng.keyword)
                eng.commented_at = now
                eng.status = EngagementStatus.AWAITING_REPLY
                comments_today += 1
                summary["commented"] += 1
                db.commit()

            elif eng.status in (EngagementStatus.AWAITING_REPLY, EngagementStatus.DM_SENT):
                uid = eng.creator_user_id or cl.user_id(eng.creator_username)
                eng.creator_user_id = uid
                since = eng.commented_at
                messages = cl.creator_messages(uid)
                resources = harvest_links_from_messages(messages, since)
                if resources:
                    item = db.get(SavedItem, eng.item_id)
                    existing = list(item.resources or [])
                    existing_urls = {r["url"] for r in existing}
                    new = [r for r in resources if r["url"] not in existing_urls]
                    item.resources = existing + new
                    eng.status = EngagementStatus.RESOURCE_RECEIVED
                    eng.resource_received_at = now
                    summary["resources"] += len(new)
                    db.commit()
                    continue

                # Creator replied but gated the link behind an in-app button click
                # (ManyChat-style). Record it so the dashboard can prompt a manual claim.
                opening = pending_interaction(messages, since)
                if opening and eng.status != EngagementStatus.DM_SENT:
                    item = db.get(SavedItem, eng.item_id)
                    existing = list(item.resources or [])
                    if not any(r.get("source") == "interaction_required" for r in existing):
                        item.resources = existing + [
                            {
                                "url": f"https://www.instagram.com/direct/t/{uid}",
                                "text": opening[:200],
                                "source": "interaction_required",
                                "received_at": now.isoformat(),
                            }
                        ]
                    eng.status = EngagementStatus.INTERACTION_REQUIRED
                    db.commit()
                    summary["resources"] += 1
                    continue

                age = (now - eng.commented_at).total_seconds() if eng.commented_at else 0
                can_dm = eng.channel in (EngagementChannel.DM, EngagementChannel.BOTH)
                if (
                    eng.status == EngagementStatus.AWAITING_REPLY
                    and can_dm
                    and not eng.dm_sent_at
                    and age >= config["dm_fallback_after_s"]
                ):
                    if dms_today >= config["daily_dm_cap"]:
                        summary["deferred"] += 1
                        continue
                    _jitter_sleep(config, sleeper)
                    cl.dm(uid, eng.keyword)
                    eng.dm_sent_at = now
                    eng.status = EngagementStatus.DM_SENT
                    dms_today += 1
                    summary["dm_sent"] += 1
                    db.commit()
                elif age >= config["exhaust_after_s"]:
                    eng.status = EngagementStatus.EXHAUSTED
                    db.commit()
        except Exception as exc:
            db.rollback()
            eng = db.get(Engagement, eng.id)
            eng.attempts += 1
            eng.last_error = f"{type(exc).__name__}: {exc}"
            if eng.attempts >= MAX_ATTEMPTS:
                eng.status = EngagementStatus.FAILED
            db.commit()
            logger.exception("engagement %s step failed", eng.id)

    return summary


def run_forever(poll_interval_s: int = 60) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    factory = get_session_factory()
    client = None
    while True:
        try:
            with factory() as db:
                config = get_engagement_config(db)
                if not config.get("enabled"):
                    time.sleep(poll_interval_s)
                    continue
                if client is None:
                    client = EngagementClientPool()
                summary = reconcile_once(db, client, config, datetime.now(UTC))
                if any(summary.values()):
                    logger.info("engagement reconcile: %s", summary)
        except Exception:
            logger.exception("engagement loop error")
            client = None
        time.sleep(poll_interval_s)


if __name__ == "__main__":
    run_forever()
