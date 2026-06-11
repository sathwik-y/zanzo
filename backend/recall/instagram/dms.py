"""DM ingestion: reels shared to the bot account land here.

Modern Instagram shares arrive as `xma_clip` / `xma_media_share` items (XMA =
cross-app media attachment). instagrapi's parsed models do not surface XMA
payloads, so we read the raw inbox endpoints and parse items ourselves.

The reel permalink lives at item["xma_clip"][0]["target_url"], e.g.
  https://www.instagram.com/reel/DYz7y55zEon/?id=3905728284751317543_60605511491&...
The numeric media_pk is the first segment of the `id` query parameter.

Each parsed share also records who sent it (item["user_id"], resolved to a
username via the thread participant list) so the poller can route the item to
the right app user. Plain text messages are collected too — that's how users
verify ownership of their Instagram account (they DM their verification code).

Pending threads (from accounts the bot doesn't follow) are approved after
parsing so later shares arrive in the normal inbox.
"""
import logging
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from instagrapi import Client

from recall.instagram.types import DiscoveredMedia, DmText

logger = logging.getLogger(__name__)


def _pk_from_target_url(target_url: str) -> str | None:
    query = parse_qs(urlparse(target_url).query)
    raw_id = query.get("id", [None])[0]
    if raw_id:
        pk = raw_id.split("_")[0]
        if pk.isdigit():
            return pk
    return None


def _thread_usernames(thread: dict) -> dict[str, str]:
    """Participant pk → username for one raw thread dict."""
    out: dict[str, str] = {}
    for u in thread.get("users", []) or []:
        pk = u.get("pk") or u.get("pk_id") or u.get("id")
        if pk and u.get("username"):
            out[str(pk)] = u["username"]
    return out


def parse_inbox_items(threads: list[dict]) -> list[DiscoveredMedia]:
    """Parse raw direct_v2 thread dicts into discovered media."""
    found: list[DiscoveredMedia] = []
    for thread in threads:
        usernames = _thread_usernames(thread)
        for item in thread.get("items", []):
            media = _parse_item(item)
            if media:
                sender_pk = item.get("user_id")
                if sender_pk is not None:
                    media.dm_sender_pk = str(sender_pk)
                    media.dm_sender_username = usernames.get(str(sender_pk))
                found.append(media)
    return found


def parse_inbox_texts(threads: list[dict]) -> list[DmText]:
    """Plain text DMs (for verification-code matching)."""
    out: list[DmText] = []
    for thread in threads:
        usernames = _thread_usernames(thread)
        for item in thread.get("items", []):
            if item.get("item_type") != "text" or not item.get("text"):
                continue
            sender_pk = item.get("user_id")
            if sender_pk is None:
                continue
            out.append(
                DmText(
                    sender_pk=str(sender_pk),
                    sender_username=usernames.get(str(sender_pk)),
                    text=item["text"],
                )
            )
    return out


def _parse_item(item: dict) -> DiscoveredMedia | None:
    item_type = item.get("item_type")
    media_pk: str | None = None
    url: str | None = None
    media_type = "REEL"

    if item_type in ("xma_clip", "xma_media_share"):
        xma_list = item.get(item_type) or []
        if not xma_list:
            return None
        target_url = xma_list[0].get("target_url") or ""
        media_pk = _pk_from_target_url(target_url)
        url = target_url.split("?")[0] if target_url else None
        if media_pk is None and url:
            # Defer pk resolution: fetch stage can resolve from the permalink.
            logger.warning("xma item without parsable id param: %s", url)
            return None
        media_type = "REEL" if item_type == "xma_clip" else "POST"
    elif item_type == "clip":
        clip = (item.get("clip") or {}).get("clip") or item.get("clip") or {}
        if clip.get("pk"):
            media_pk = str(clip["pk"])
            code = clip.get("code")
            url = f"https://www.instagram.com/reel/{code}/" if code else None
    elif item_type == "media_share":
        share = item.get("media_share") or {}
        if share.get("pk"):
            media_pk = str(share["pk"])
            code = share.get("code")
            url = f"https://www.instagram.com/p/{code}/" if code else None
            media_type = "REEL" if share.get("product_type") == "clips" else "POST"

    if not media_pk:
        return None

    shared_at = None
    ts = item.get("timestamp")
    if ts:
        try:
            shared_at = datetime.fromtimestamp(int(ts) / 1_000_000, tz=UTC)
        except (ValueError, OSError):
            shared_at = None

    return DiscoveredMedia(
        media_pk=media_pk,
        source="DM",
        media_type=media_type,
        instagram_url=url,
        saved_at=shared_at,
    )


def fetch_dm_inbox(
    cl: Client, approve_pending: bool = True
) -> tuple[list[DiscoveredMedia], list[DmText]]:
    """One inbox sweep: shared media plus plain text messages."""
    threads: list[dict] = []

    pending = cl.private_request("direct_v2/pending_inbox/", params={"limit": 20})
    pending_threads = pending.get("inbox", {}).get("threads", [])
    threads.extend(pending_threads)
    if approve_pending:
        for thread in pending_threads:
            thread_id = thread.get("thread_id")
            if thread_id:
                try:
                    cl.direct_pending_approve(thread_id)
                except Exception:
                    logger.exception("failed to approve pending thread %s", thread_id)

    inbox = cl.private_request("direct_v2/inbox/", params={"limit": 20, "thread_message_limit": 10})
    threads.extend(inbox.get("inbox", {}).get("threads", []))

    found = parse_inbox_items(threads)
    texts = parse_inbox_texts(threads)
    logger.info("dm shares discovered: %d (texts: %d)", len(found), len(texts))
    return found, texts


def fetch_dm_shares(cl: Client, approve_pending: bool = True) -> list[DiscoveredMedia]:
    return fetch_dm_inbox(cl, approve_pending=approve_pending)[0]
