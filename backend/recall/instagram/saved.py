"""Fetch the account's saved collection ("All Posts" virtual collection)."""
import logging

from instagrapi import Client

from recall.instagram.client import media_type_label
from recall.instagram.types import DiscoveredMedia

logger = logging.getLogger(__name__)

ALL_POSTS = "ALL_MEDIA_AUTO_COLLECTION"


def fetch_saved(cl: Client, amount: int = 50) -> list[DiscoveredMedia]:
    medias = cl.collection_medias(ALL_POSTS, amount=amount)
    found = []
    for m in medias:
        found.append(
            DiscoveredMedia(
                media_pk=str(m.pk),
                source="SAVED",
                media_type=media_type_label(m.media_type, m.product_type),
                instagram_url=f"https://www.instagram.com/p/{m.code}/" if m.code else None,
                author_username=m.user.username if m.user else None,
                author_full_name=m.user.full_name if m.user else None,
                caption=m.caption_text or None,
                post_created_at=m.taken_at,
            )
        )
    logger.info("saved collection: %d items", len(found))
    return found
