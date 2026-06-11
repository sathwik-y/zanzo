"""Normalized shape for anything discovered by ingestion."""
from dataclasses import dataclass
from datetime import datetime


@dataclass
class DiscoveredMedia:
    media_pk: str
    source: str  # ItemSource value: SAVED | DM
    media_type: str = "REEL"  # MediaType value; best-effort at discovery time
    instagram_url: str | None = None
    author_username: str | None = None
    author_full_name: str | None = None
    caption: str | None = None
    post_created_at: datetime | None = None
    saved_at: datetime | None = None
    # DM-only: who shared it with the bot (stable numeric pk + handle at the time)
    dm_sender_pk: str | None = None
    dm_sender_username: str | None = None


@dataclass
class DmText:
    """A plain text DM, used to match Instagram-account verification codes."""

    sender_pk: str
    sender_username: str | None
    text: str
