"""Stats, poller control, engagement config, user administration, health.

- /stats and /resources are scoped to the caller (each user sees their own).
- Poller and engagement control write to the shared bot account, so they are
  admin-only, as is the /admin/* user directory.
"""
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from recall.api.deps import (
    AuthContext,
    get_auth,
    get_db,
    require_admin,
    scoped_items,
)
from recall.api.schemas import (
    EngagementConfig,
    EngagementRow,
    PollerStatus,
    ResourceRow,
    StatsResponse,
)
from recall.models import BotAccount, BotStatus, Engagement, LlmUsage, SavedItem, User
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


@router.get("/stats", response_model=StatsResponse)
def stats(db: Session = Depends(get_db), auth: AuthContext = Depends(get_auth)):
    visible = scoped_items(select(SavedItem), auth).subquery()
    by_category = dict(
        db.execute(
            select(visible.c.category, func.count())
            .where(visible.c.category.is_not(None))
            .group_by(visible.c.category)
        ).all()
    )
    by_status = dict(db.execute(select(visible.c.status, func.count()).group_by(visible.c.status)).all())
    failed = sum(v for k, v in by_status.items() if k.startswith("FAILED_"))

    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    cost_q = select(func.coalesce(func.sum(LlmUsage.cost_usd), 0.0))
    if not auth.is_service:
        cost_q = cost_q.where(LlmUsage.item_id.in_(select(visible.c.id)))
    cost_total = db.scalar(cost_q) or 0.0
    cost_month = db.scalar(cost_q.where(LlmUsage.created_at >= month_start)) or 0.0

    week_ago = datetime.now(UTC) - timedelta(days=7)
    recent = db.scalar(
        select(func.count()).select_from(visible).where(visible.c.ingested_at >= week_ago)
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


class NextPoll(BaseModel):
    status: str
    last_run_at: str | None = None
    next_poll_at: str | None = None
    interval_s: int


@router.get("/poller/next", response_model=NextPoll)
def poller_next(db: Session = Depends(get_db), auth: AuthContext = Depends(get_auth)):
    """When the next ingestion sweep is expected — for the dashboard countdown.
    Available to every signed-in user (read-only, no internals)."""
    from recall.config import get_settings

    state = get_state(db, POLLER_KEY)
    interval = get_settings().poll_interval_seconds
    last_raw = state.get("last_run_at")
    next_at = None
    if last_raw:
        try:
            next_at = (datetime.fromisoformat(last_raw) + timedelta(seconds=interval)).isoformat()
        except ValueError:
            pass
    return NextPoll(
        status=state.get("status", "unknown"),
        last_run_at=last_raw,
        next_poll_at=next_at,
        interval_s=interval,
    )


@router.get("/poller/status", response_model=PollerStatus, dependencies=[Depends(require_admin)])
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


@router.post("/poller/resume", response_model=PollerStatus, dependencies=[Depends(require_admin)])
def poller_resume(db: Session = Depends(get_db)):
    """Resume after you've resolved an Instagram challenge in the app."""
    set_state(db, POLLER_KEY, {"status": "running", "last_error": None})
    return poller_status(db)


@router.get(
    "/engagement/config", response_model=EngagementConfig, dependencies=[Depends(require_admin)]
)
def engagement_config(db: Session = Depends(get_db)):
    return EngagementConfig(**get_engagement_config(db))


@router.put(
    "/engagement/config", response_model=EngagementConfig, dependencies=[Depends(require_admin)]
)
def update_engagement_config(body: EngagementConfig, db: Session = Depends(get_db)):
    set_state(db, ENGAGEMENT_KEY, body.model_dump())
    return EngagementConfig(**get_engagement_config(db))


@router.get(
    "/engagement", response_model=list[EngagementRow], dependencies=[Depends(require_admin)]
)
def engagement_list(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Engagement).order_by(Engagement.created_at.desc()).limit(limit)
    ).all()
    return [EngagementRow.model_validate(r) for r in rows]


@router.get("/resources", response_model=list[ResourceRow])
def resources_list(db: Session = Depends(get_db), auth: AuthContext = Depends(get_auth)):
    """Every auto-engagement and the resources harvested for it (Resources view)."""
    visible_ids = select(scoped_items(select(SavedItem), auth).subquery().c.id)
    rows = db.scalars(
        select(Engagement)
        .where(Engagement.item_id.in_(visible_ids))
        .order_by(Engagement.created_at.desc())
    ).all()
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


class AdminUserRow(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    role: str
    ig_username: str | None
    ig_verified: bool
    bot_username: str | None
    created_at: datetime
    last_login_at: datetime | None
    item_count: int


@router.get(
    "/admin/users", response_model=list[AdminUserRow], dependencies=[Depends(require_admin)]
)
def admin_users(db: Session = Depends(get_db)):
    counts = dict(
        db.execute(
            select(SavedItem.user_id, func.count())
            .where(SavedItem.user_id.is_not(None))
            .group_by(SavedItem.user_id)
        ).all()
    )
    bot_names = dict(db.execute(select(BotAccount.id, BotAccount.username)).all())
    users = db.scalars(select(User).order_by(User.created_at)).all()
    return [
        AdminUserRow(
            id=u.id,
            email=u.email,
            display_name=u.display_name,
            role=u.role,
            ig_username=u.ig_username,
            ig_verified=u.ig_verified,
            bot_username=bot_names.get(u.bot_account_id),
            created_at=u.created_at,
            last_login_at=u.last_login_at,
            item_count=counts.get(u.id, 0),
        )
        for u in users
    ]


class BotRow(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    username: str
    status: str
    note: str | None
    last_poll_at: datetime | None
    last_error: str | None
    created_at: datetime
    assigned_users: int = 0


class BotCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    sessionid: str = Field(min_length=8)
    note: str | None = Field(default=None, max_length=200)


class BotUpdate(BaseModel):
    status: str | None = None  # ACTIVE | DISABLED (CHALLENGE is set by the poller)
    sessionid: str | None = Field(default=None, min_length=8)
    note: str | None = Field(default=None, max_length=200)


def _bot_rows(db: Session) -> list[BotRow]:
    counts = dict(
        db.execute(
            select(User.bot_account_id, func.count())
            .where(User.bot_account_id.is_not(None))
            .group_by(User.bot_account_id)
        ).all()
    )
    bots = db.scalars(select(BotAccount).order_by(BotAccount.created_at)).all()
    out = []
    for b in bots:
        row = BotRow.model_validate(b)
        row.assigned_users = counts.get(b.id, 0)
        out.append(row)
    return out


@router.get("/admin/bots", response_model=list[BotRow], dependencies=[Depends(require_admin)])
def list_bots(db: Session = Depends(get_db)):
    return _bot_rows(db)


@router.post(
    "/admin/bots", response_model=list[BotRow], status_code=201,
    dependencies=[Depends(require_admin)],
)
def create_bot(body: BotCreate, db: Session = Depends(get_db)):
    username = body.username.lstrip("@").lower()
    if db.scalar(select(BotAccount).where(BotAccount.username == username)):
        raise HTTPException(status_code=409, detail="bot with this username already exists")
    db.add(BotAccount(username=username, sessionid=body.sessionid, note=body.note))
    db.commit()
    return _bot_rows(db)


@router.patch(
    "/admin/bots/{bot_id}", response_model=list[BotRow], dependencies=[Depends(require_admin)]
)
def update_bot(bot_id: uuid.UUID, body: BotUpdate, db: Session = Depends(get_db)):
    bot = db.get(BotAccount, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="bot not found")
    if body.status is not None:
        if body.status not in (BotStatus.ACTIVE, BotStatus.DISABLED):
            raise HTTPException(status_code=422, detail="status must be ACTIVE or DISABLED")
        bot.status = body.status
        if body.status == BotStatus.ACTIVE:
            bot.last_error = None
    if body.sessionid is not None:
        bot.sessionid = body.sessionid
        bot.last_error = None
        if bot.status == BotStatus.CHALLENGE:
            bot.status = BotStatus.ACTIVE
    if body.note is not None:
        bot.note = body.note
    db.commit()
    return _bot_rows(db)


@router.delete(
    "/admin/bots/{bot_id}", response_model=list[BotRow], dependencies=[Depends(require_admin)]
)
def delete_bot(bot_id: uuid.UUID, db: Session = Depends(get_db)):
    """Remove a bot; its users are respread across the remaining active bots."""
    from recall.instagram.bots import pick_least_loaded_bot

    bot = db.get(BotAccount, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="bot not found")
    orphans = db.scalars(select(User).where(User.bot_account_id == bot.id)).all()
    db.delete(bot)
    db.flush()
    for user in orphans:
        replacement = pick_least_loaded_bot(db)
        user.bot_account_id = replacement.id if replacement else None
    db.commit()
    return _bot_rows(db)


@router.get("/admin/stats", response_model=StatsResponse, dependencies=[Depends(require_admin)])
def admin_stats(db: Session = Depends(get_db)):
    """Global, unscoped stats for the admin panel."""
    return stats(db, AuthContext(user=None, is_service=True))
