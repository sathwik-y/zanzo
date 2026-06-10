"""DM ingestion: reels shared to the bot account land here.

Modern Instagram shares arrive as `xma_clip` / `xma_media_share` items (XMA =
cross-app media attachment). instagrapi's parsed models do not surface XMA
payloads, so we read the raw inbox endpoints and parse items ourselves.

The reel permalink lives at item["xma_clip"][0]["target_url"], e.g.
  https://www.instagram.com/reel/DYz7y55zEon/?id=3905728284751317543_60605511491&...
The numeric media_pk is the first segment of the `id` query parameter.

Pending threads (from accounts the bot doesn't follow) are approved after
parsing so later shares arrive in the normal inbox.
"""
import logging
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from instagrapi import Client

from recall.instagram.types import DiscoveredMedia

logger = logging.getLogger(__name__)


def _pk_from_target_url(target_url: str) -> str | None:
    query = parse_qs(urlparse(target_url).query)
    raw_id = query.get("id", [None])[0]
    if raw_id:
        pk = raw_id.split("_")[0]
        if pk.isdigit():
            return pk
    return None


def parse_inbox_items(threads: list[dict]) -> list[DiscoveredMedia]:
    """Parse raw direct_v2 thread dicts into discovered media."""
    found: list[DiscoveredMedia] = []
    for thread in threads:
        for item in thread.get("items", []):
            media = _parse_item(item)
            if media:
                found.append(media)
    return found


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


def fetch_dm_shares(cl: Client, approve_pending: bool = True) -> list[DiscoveredMedia]:
    found: list[DiscoveredMedia] = []

    pending = cl.private_request("direct_v2/pending_inbox/", params={"limit": 20})
    pending_threads = pending.get("inbox", {}).get("threads", [])
    found.extend(parse_inbox_items(pending_threads))
    if approve_pending:
        for thread in pending_threads:
            thread_id = thread.get("thread_id")
            if thread_id:
                try:
                    cl.direct_pending_approve(thread_id)
                except Exception:
                    logger.exception("failed to approve pending thread %s", thread_id)

    inbox = cl.private_request("direct_v2/inbox/", params={"limit": 20, "thread_message_limit": 10})
    found.extend(parse_inbox_items(inbox.get("inbox", {}).get("threads", [])))

    logger.info("dm shares discovered: %d", len(found))
    return found
