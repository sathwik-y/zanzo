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
