"""SQLAlchemy models. Mirrors the spec's data model (section 6) plus:

- saved_items.source: SAVED (from the saved collection) or DM (shared to the bot account)
- saved_items.transcript_segments: timestamped segments for clickable transcripts
- app_state: key/value store for poller status and ingestion cursors
- llm_usage: per-call token usage for the cost dashboard
"""
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from recall.db import Base

EMBEDDING_DIMS = 1536


def utcnow() -> datetime:
    return datetime.now(UTC)


class UserRole(StrEnum):
    USER = "USER"
    ADMIN = "ADMIN"


class BotStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CHALLENGE = "CHALLENGE"  # Instagram wants manual verification
    DISABLED = "DISABLED"


class BotAccount(Base):
    """A burner Instagram account users DM their reels to.

    Users are spread across active bots (least-loaded assignment at link time)
    so no single account carries all the traffic. Credentials are a sessionid
    cookie; each bot keeps its own instagrapi device file under data/.
    """

    __tablename__ = "bot_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(Text, unique=True, index=True)
    sessionid: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default=BotStatus.ACTIVE, index=True)
    note: Mapped[str | None] = mapped_column(Text)
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    users: Mapped[list["User"]] = relationship(back_populates="bot_account")


class User(Base):
    """An account on the hosted app. Items are scoped to their owner.

    Instagram identity is bound by ig_user_pk (Instagram's stable numeric id),
    captured when the user DMs their verification code to the bot account —
    so an Instagram username change never breaks the mapping.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(8), default=UserRole.USER)
    ig_username: Mapped[str | None] = mapped_column(Text, index=True)
    ig_user_pk: Mapped[str | None] = mapped_column(Text, unique=True, index=True)
    ig_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    ig_verification_code: Mapped[str | None] = mapped_column(String(16))
    ig_verification_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bot_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bot_accounts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list["SavedItem"]] = relationship(back_populates="user")
    bot_account: Mapped["BotAccount | None"] = relationship(back_populates="users")


class MediaType(StrEnum):
    POST = "POST"
    REEL = "REEL"
    CAROUSEL = "CAROUSEL"
    IGTV = "IGTV"


class ItemSource(StrEnum):
    SAVED = "SAVED"
    DM = "DM"


class ItemStatus(StrEnum):
    PENDING = "PENDING"
    FETCHING = "FETCHING"
    TRANSCRIBING = "TRANSCRIBING"
    CLASSIFYING = "CLASSIFYING"
    EXTRACTING = "EXTRACTING"
    EMBEDDING = "EMBEDDING"
    COMPLETED = "COMPLETED"
    FAILED_FETCH = "FAILED_FETCH"
    FAILED_TRANSCRIBE = "FAILED_TRANSCRIBE"
    FAILED_CLASSIFY = "FAILED_CLASSIFY"
    FAILED_EXTRACT = "FAILED_EXTRACT"
    FAILED_EMBED = "FAILED_EMBED"

    @property
    def is_failed(self) -> bool:
        return self.name.startswith("FAILED_")


class MediaKind(StrEnum):
    VIDEO = "VIDEO"
    IMAGE = "IMAGE"
    THUMBNAIL = "THUMBNAIL"
    AUDIO_EXTRACT = "AUDIO_EXTRACT"


class SavedItem(Base):
    __tablename__ = "saved_items"
    # The same reel DMed by two different users is two rows; NULLS NOT DISTINCT
    # keeps legacy/unassigned rows (user_id IS NULL) deduplicated too.
    __table_args__ = (
        UniqueConstraint("user_id", "media_pk", name="uq_saved_items_user_media",
                         postgresql_nulls_not_distinct=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    media_pk: Mapped[str] = mapped_column(Text, index=True)
    media_type: Mapped[str] = mapped_column(String(16), default=MediaType.REEL)
    source: Mapped[str] = mapped_column(String(8), default=ItemSource.SAVED)
    instagram_url: Mapped[str | None] = mapped_column(Text)
    author_username: Mapped[str | None] = mapped_column(Text)
    author_full_name: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text)
    hashtags: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    post_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    category: Mapped[str | None] = mapped_column(String(16), index=True)
    category_confidence: Mapped[float | None] = mapped_column(Float)
    transcript: Mapped[str | None] = mapped_column(Text)
    transcript_segments: Mapped[list | None] = mapped_column(JSONB)
    transcript_lang: Mapped[str | None] = mapped_column(String(8))
    transcript_provider: Mapped[str | None] = mapped_column(String(16))
    resources: Mapped[list | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(24), default=ItemStatus.PENDING, index=True)
    error_log: Mapped[dict | None] = mapped_column(JSONB)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped["User | None"] = relationship(back_populates="items")
    extraction: Mapped["Extraction | None"] = relationship(
        back_populates="item", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def extraction_payload(self) -> dict | None:
        return self.extraction.payload if self.extraction else None
    media_refs: Mapped[list["MediaRef"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )
    embedding: Mapped["Embedding | None"] = relationship(
        back_populates="item", uselist=False, cascade="all, delete-orphan"
    )


class Extraction(Base):
    __tablename__ = "extractions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("saved_items.id", ondelete="CASCADE"), unique=True
    )
    schema_version: Mapped[str] = mapped_column(String(8), default="1")
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    item: Mapped[SavedItem] = relationship(back_populates="extraction")


class MediaRef(Base):
    __tablename__ = "media_refs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("saved_items.id", ondelete="CASCADE"))
    s3_key: Mapped[str] = mapped_column(Text)
    media_kind: Mapped[str] = mapped_column(String(16))
    bytes: Mapped[int | None] = mapped_column(BigInteger)

    item: Mapped[SavedItem] = relationship(back_populates="media_refs")


class Embedding(Base):
    __tablename__ = "embeddings"

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("saved_items.id", ondelete="CASCADE"), primary_key=True
    )
    vector: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMS))
    model: Mapped[str] = mapped_column(Text)

    item: Mapped[SavedItem] = relationship(back_populates="embedding")


class EngagementStatus(StrEnum):
    PENDING = "PENDING"
    FOLLOWING = "FOLLOWING"
    COMMENTED = "COMMENTED"
    AWAITING_REPLY = "AWAITING_REPLY"
    DM_SENT = "DM_SENT"
    RESOURCE_RECEIVED = "RESOURCE_RECEIVED"
    INTERACTION_REQUIRED = "INTERACTION_REQUIRED"  # creator replied but a manual in-app click is needed
    EXHAUSTED = "EXHAUSTED"
    FAILED = "FAILED"


class EngagementChannel(StrEnum):
    COMMENT = "comment"
    DM = "dm"
    BOTH = "both"


class Engagement(Base):
    """Tracks an automated 'comment KEYWORD to get the link' interaction."""

    __tablename__ = "engagements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("saved_items.id", ondelete="CASCADE"), unique=True
    )
    creator_username: Mapped[str | None] = mapped_column(Text)
    creator_user_id: Mapped[str | None] = mapped_column(Text)
    media_pk: Mapped[str] = mapped_column(Text)
    keyword: Mapped[str] = mapped_column(Text)
    needs_follow: Mapped[bool] = mapped_column(Boolean, default=False)
    channel: Mapped[str] = mapped_column(String(8), default=EngagementChannel.COMMENT)
    status: Mapped[str] = mapped_column(String(20), default=EngagementStatus.PENDING, index=True)
    attempts: Mapped[int] = mapped_column(BigInteger, default=0)
    commented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dm_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resource_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    item: Mapped[SavedItem] = relationship()


class AppState(Base):
    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class LlmUsage(Base):
    __tablename__ = "llm_usage"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("saved_items.id", ondelete="SET NULL"), nullable=True
    )
    stage: Mapped[str] = mapped_column(String(16))  # classify | extract | embed
    model: Mapped[str] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("ix_saved_items_ingested_at", SavedItem.ingested_at.desc())
