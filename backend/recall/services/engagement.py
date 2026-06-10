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
from recall.instagram.client import build_client
from recall.models import Engagement, EngagementChannel, EngagementStatus, SavedItem
from recall.state import get_engagement_config

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
_URL_RE = re.compile(r"https?://[^\s\"'<>)]+")


def harvest_links_from_messages(messages: list[dict], since: datetime | None) -> list[dict]:
    """Pull resource links from a creator's DM messages newer than `since`.

    Each message dict: {timestamp: datetime|None, text: str|None, urls: [str]}.
    Returns resource dicts {url, text, source, received_at}.
    """
    resources: list[dict] = []
    seen: set[str] = set()
    for msg in messages:
        ts = msg.get("timestamp")
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
        """Recent DM messages from a creator's thread, normalized."""
        try:
            thread = self.cl.direct_thread_by_participants([int(user_id)])
            thread_id = thread["thread"]["thread_id"] if isinstance(thread, dict) else thread.id
        except Exception:
            return []
        out: list[dict] = []
        for m in self.cl.direct_messages(thread_id, amount=20):
            urls = []
            if getattr(m, "xma_share", None) and getattr(m.xma_share, "video_url", None):
                urls.append(str(m.xma_share.video_url))
            if getattr(m, "link", None) and getattr(m.link, "link_url", None):
                urls.append(str(m.link.link_url))
            out.append(
                {
                    "timestamp": getattr(m, "timestamp", None),
                    "text": getattr(m, "text", None),
                    "urls": urls,
                }
            )
        return out


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
            if eng.status in (EngagementStatus.PENDING, EngagementStatus.FOLLOWING):
                # follow (if required), then comment - both gated by caps
                if eng.needs_follow and eng.status == EngagementStatus.PENDING:
                    if comments_today >= config["daily_comment_cap"]:
                        summary["deferred"] += 1
                        continue
                    uid = eng.creator_user_id or client.user_id(eng.creator_username)
                    eng.creator_user_id = uid
                    _jitter_sleep(config, sleeper)
                    client.follow(uid)
                    eng.status = EngagementStatus.FOLLOWING
                    follows_today += 1
                    summary["followed"] += 1
                    db.commit()

                if comments_today >= config["daily_comment_cap"]:
                    summary["deferred"] += 1
                    continue
                _jitter_sleep(config, sleeper)
                client.comment(eng.media_pk, eng.keyword)
                eng.commented_at = now
                eng.status = EngagementStatus.AWAITING_REPLY
                comments_today += 1
                summary["commented"] += 1
                db.commit()

            elif eng.status in (EngagementStatus.AWAITING_REPLY, EngagementStatus.DM_SENT):
                uid = eng.creator_user_id or client.user_id(eng.creator_username)
                eng.creator_user_id = uid
                since = eng.commented_at
                messages = client.creator_messages(uid)
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
                    client.dm(uid, eng.keyword)
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
                    client = IgEngagementClient(build_client())
                summary = reconcile_once(db, client, config, datetime.now(UTC))
                if any(summary.values()):
                    logger.info("engagement reconcile: %s", summary)
        except Exception:
            logger.exception("engagement loop error")
            client = None
        time.sleep(poll_interval_s)


if __name__ == "__main__":
    run_forever()
