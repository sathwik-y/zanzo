"""API response/request models."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from recall.categories import Category


class ItemSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    media_pk: str
    media_type: str
    source: str
    instagram_url: str | None
    author_username: str | None
    author_full_name: str | None
    caption: str | None
    category: str | None
    category_confidence: float | None
    status: str
    archived: bool
    saved_at: datetime | None
    ingested_at: datetime
    thumbnail_url: str | None = None
    extraction: dict | None = Field(default=None, validation_alias="extraction_payload")
    match_reason: str | None = None  # set on search results


class MediaItem(BaseModel):
    kind: str
    url: str
    bytes: int | None


class EngagementInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    keyword: str
    needs_follow: bool
    channel: str
    creator_username: str | None
    commented_at: datetime | None = None
    dm_sent_at: datetime | None = None
    last_error: str | None = None


class ItemDetail(ItemSummary):
    hashtags: list[str] | None
    post_created_at: datetime | None
    transcript: str | None
    transcript_segments: list | None = None
    transcript_lang: str | None
    transcript_provider: str | None = None
    resources: list | None = None
    error_log: dict | None
    media: list[MediaItem] = []
    engagement: EngagementInfo | None = None


class ItemListResponse(BaseModel):
    items: list[ItemSummary]
    total: int
    limit: int
    offset: int


class RecategorizeRequest(BaseModel):
    category: Category


class ArchiveRequest(BaseModel):
    archived: bool


class StatsResponse(BaseModel):
    total_items: int
    by_category: dict[str, int]
    by_status: dict[str, int]
    failed_count: int
    llm_cost_total_usd: float
    llm_cost_month_usd: float
    items_last_7_days: int


class PollerStatus(BaseModel):
    status: str
    last_run_at: str | None = None
    last_new_items: int | None = None
    last_error: str | None = None
    queue_depth: int | None = None


class EngagementConfig(BaseModel):
    enabled: bool
    daily_follow_cap: int
    daily_comment_cap: int
    daily_dm_cap: int
    min_delay_s: int
    max_delay_s: int
    dm_fallback_after_s: int
    exhaust_after_s: int


class EngagementRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_id: uuid.UUID
    creator_username: str | None
    keyword: str
    needs_follow: bool
    channel: str
    status: str
    attempts: int
    last_error: str | None
    commented_at: datetime | None
    resource_received_at: datetime | None
    created_at: datetime
