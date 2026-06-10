"""Stats, poller control, health."""
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from recall.api.deps import get_db, require_api_key
from recall.api.schemas import (
    EngagementConfig,
    EngagementRow,
    PollerStatus,
    ResourceRow,
    StatsResponse,
)
from recall.models import Engagement, LlmUsage, SavedItem
from recall.queueing import RedisQueue
from recall.state import (
    ENGAGEMENT_KEY,
    POLLER_KEY,
    get_engagement_config,
    get_state,
    set_state,
)

router = APIRouter(tags=["admin"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/stats", response_model=StatsResponse, dependencies=[Depends(require_api_key)])
def stats(db: Session = Depends(get_db)):
    by_category = dict(
        db.execute(
            select(SavedItem.category, func.count())
            .where(SavedItem.category.is_not(None))
            .group_by(SavedItem.category)
        ).all()
    )
    by_status = dict(db.execute(select(SavedItem.status, func.count()).group_by(SavedItem.status)).all())
    failed = sum(v for k, v in by_status.items() if k.startswith("FAILED_"))

    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    cost_total = db.scalar(select(func.coalesce(func.sum(LlmUsage.cost_usd), 0.0))) or 0.0
    cost_month = (
        db.scalar(
            select(func.coalesce(func.sum(LlmUsage.cost_usd), 0.0)).where(
                LlmUsage.created_at >= month_start
            )
        )
        or 0.0
    )
    week_ago = datetime.now(UTC) - timedelta(days=7)
    recent = db.scalar(
        select(func.count()).select_from(SavedItem).where(SavedItem.ingested_at >= week_ago)
    )

    return StatsResponse(
        total_items=sum(by_status.values()),
        by_category=by_category,
        by_status=by_status,
        failed_count=failed,
        llm_cost_total_usd=round(cost_total, 4),
        llm_cost_month_usd=round(cost_month, 4),
        items_last_7_days=recent or 0,
    )


@router.get("/poller/status", response_model=PollerStatus, dependencies=[Depends(require_api_key)])
def poller_status(db: Session = Depends(get_db)):
    state = get_state(db, POLLER_KEY)
    try:
        depth = RedisQueue().depth()
    except Exception:
        depth = None
    return PollerStatus(
        status=state.get("status", "unknown"),
        last_run_at=state.get("last_run_at"),
        last_new_items=state.get("last_new_items"),
        last_error=state.get("last_error"),
        queue_depth=depth,
    )


@router.post("/poller/resume", response_model=PollerStatus, dependencies=[Depends(require_api_key)])
def poller_resume(db: Session = Depends(get_db)):
    """Resume after you've resolved an Instagram challenge in the app."""
    set_state(db, POLLER_KEY, {"status": "running", "last_error": None})
    return poller_status(db)


@router.get(
    "/engagement/config", response_model=EngagementConfig, dependencies=[Depends(require_api_key)]
)
def engagement_config(db: Session = Depends(get_db)):
    return EngagementConfig(**get_engagement_config(db))


@router.put(
    "/engagement/config", response_model=EngagementConfig, dependencies=[Depends(require_api_key)]
)
def update_engagement_config(body: EngagementConfig, db: Session = Depends(get_db)):
    set_state(db, ENGAGEMENT_KEY, body.model_dump())
    return EngagementConfig(**get_engagement_config(db))


@router.get(
    "/engagement", response_model=list[EngagementRow], dependencies=[Depends(require_api_key)]
)
def engagement_list(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Engagement).order_by(Engagement.created_at.desc()).limit(limit)
    ).all()
    return [EngagementRow.model_validate(r) for r in rows]


@router.get(
    "/resources", response_model=list[ResourceRow], dependencies=[Depends(require_api_key)]
)
def resources_list(db: Session = Depends(get_db)):
    """Every auto-engagement and the resources harvested for it (Resources view)."""
    rows = db.scalars(select(Engagement).order_by(Engagement.created_at.desc())).all()
    out: list[ResourceRow] = []
    for eng in rows:
        item = db.get(SavedItem, eng.item_id)
        if item is None:
            continue
        payload = item.extraction.payload if item.extraction else {}
        headline = (
            payload.get("title")
            or payload.get("dish_name")
            or payload.get("destination")
            or payload.get("topic")
            or payload.get("subject")
            or (item.caption or "")[:80]
            or item.media_pk
        )
        out.append(
            ResourceRow(
                item_id=item.id,
                headline=headline,
                creator_username=eng.creator_username,
                keyword=eng.keyword,
                status=eng.status,
                needs_follow=eng.needs_follow,
                resources=item.resources or [],
                last_error=eng.last_error,
            )
        )
    return out
