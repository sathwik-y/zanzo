"""Item listing, detail, media, recategorize, retry, archive, delete."""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from recall.api.deps import AuthContext, get_ai, get_auth, get_db, get_storage, scoped_items
from recall.api.schemas import (
    ArchiveRequest,
    EngagementInfo,
    ItemDetail,
    ItemListResponse,
    ItemSummary,
    MediaItem,
    RecategorizeRequest,
)
from recall.api.search import hybrid_search
from recall.categories import Category
from recall.models import Engagement, ItemStatus, MediaKind, SavedItem
from recall.pipeline.ai_stages import make_embed_stage, make_extract_stage
from recall.queueing import RedisQueue

router = APIRouter(prefix="/items", tags=["items"])


def _thumb_url(item: SavedItem, storage) -> str | None:
    ref = next((r for r in item.media_refs if r.media_kind == MediaKind.THUMBNAIL), None)
    if ref is None:
        ref = next((r for r in item.media_refs if r.media_kind == MediaKind.IMAGE), None)
    return storage.presigned_url(ref.s3_key) if ref else None


def _summary(item: SavedItem, storage, match_reason: str | None = None) -> ItemSummary:
    s = ItemSummary.model_validate(item)
    s.thumbnail_url = _thumb_url(item, storage)
    s.match_reason = match_reason
    return s


def _base_query(
    auth: AuthContext,
    category: str | None,
    status: str | None,
    source: str | None,
    archived: bool,
    date_from: datetime | None,
    date_to: datetime | None,
):
    q = scoped_items(select(SavedItem).where(SavedItem.archived == archived), auth)
    if category:
        q = q.where(SavedItem.category == category.upper())
    if status:
        if status == "failed":
            q = q.where(SavedItem.status.like("FAILED_%"))
        else:
            q = q.where(SavedItem.status == status.upper())
    if source:
        q = q.where(SavedItem.source == source.upper())
    if date_from:
        q = q.where(SavedItem.saved_at >= date_from)
    if date_to:
        q = q.where(SavedItem.saved_at <= date_to)
    return q


@router.get("", response_model=ItemListResponse)
def list_items(
    category: str | None = None,
    status: str | None = None,
    source: str | None = None,
    archived: bool = False,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search: str | None = None,
    limit: int = Query(default=20, le=100),
    offset: int = 0,
    db: Session = Depends(get_db),
    storage=Depends(get_storage),
    ai=Depends(get_ai),
    auth: AuthContext = Depends(get_auth),
):
    base = _base_query(auth, category, status, source, archived, date_from, date_to)

    if search and search.strip():
        results = hybrid_search(db, ai, search.strip(), base, limit=limit)
        items = [_summary(i, storage, reason) for i, reason in results]
        return ItemListResponse(items=items, total=len(items), limit=limit, offset=0)

    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.scalars(
        base.order_by(SavedItem.ingested_at.desc()).limit(limit).offset(offset)
    ).all()
    return ItemListResponse(
        items=[_summary(i, storage) for i in rows], total=total or 0, limit=limit, offset=offset
    )


def _get_item(db: Session, item_id: uuid.UUID, auth: AuthContext) -> SavedItem:
    item = db.scalar(scoped_items(select(SavedItem).where(SavedItem.id == item_id), auth))
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    return item


@router.get("/{item_id}", response_model=ItemDetail)
def get_item(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    storage=Depends(get_storage),
    auth: AuthContext = Depends(get_auth),
):
    item = _get_item(db, item_id, auth)
    detail = ItemDetail.model_validate(item)
    detail.thumbnail_url = _thumb_url(item, storage)
    detail.media = [
        MediaItem(kind=r.media_kind, url=storage.presigned_url(r.s3_key), bytes=r.bytes)
        for r in item.media_refs
    ]
    eng = db.scalar(select(Engagement).where(Engagement.item_id == item.id))
    if eng:
        detail.engagement = EngagementInfo.model_validate(eng)
    return detail


@router.get("/{item_id}/media")
def get_item_media(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    storage=Depends(get_storage),
    auth: AuthContext = Depends(get_auth),
):
    item = _get_item(db, item_id, auth)
    return [
        MediaItem(kind=r.media_kind, url=storage.presigned_url(r.s3_key), bytes=r.bytes)
        for r in item.media_refs
    ]


@router.post("/{item_id}/recategorize", response_model=ItemDetail)
def recategorize(
    item_id: uuid.UUID,
    body: RecategorizeRequest,
    db: Session = Depends(get_db),
    storage=Depends(get_storage),
    ai=Depends(get_ai),
    auth: AuthContext = Depends(get_auth),
):
    """Manual category override; re-runs extraction and embedding inline."""
    item = _get_item(db, item_id, auth)
    item.category = Category(body.category).value
    item.category_confidence = 1.0  # human said so
    db.commit()

    make_extract_stage(ai)(db, item)
    make_embed_stage(ai)(db, item)
    item.status = ItemStatus.COMPLETED
    item.error_log = None
    db.commit()
    return get_item(item_id, db, storage, auth)


@router.post("/{item_id}/retry", status_code=202)
def retry(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth),
):
    item = _get_item(db, item_id, auth)
    item.status = ItemStatus.PENDING
    item.error_log = None
    db.commit()
    RedisQueue().enqueue(str(item.id))
    return {"status": "queued"}


@router.patch("/{item_id}", response_model=ItemSummary)
def set_archived(
    item_id: uuid.UUID,
    body: ArchiveRequest,
    db: Session = Depends(get_db),
    storage=Depends(get_storage),
    auth: AuthContext = Depends(get_auth),
):
    item = _get_item(db, item_id, auth)
    item.archived = body.archived
    db.commit()
    return _summary(item, storage)


@router.delete("/{item_id}", status_code=204)
def delete_item(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth),
):
    """Removes the item from the index. Does NOT unsave it on Instagram."""
    item = _get_item(db, item_id, auth)
    db.delete(item)
    db.commit()
