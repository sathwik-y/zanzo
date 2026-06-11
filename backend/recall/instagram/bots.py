"""Bot-account pool helpers: assignment and client resolution.

Users are assigned the least-loaded ACTIVE bot when they link their Instagram
account; every later interaction for that user (their DM ingestion, their
engagement actions) goes through their assigned bot. With no bot rows the
system falls back to the single account from .env — the self-host simple path.
"""
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from recall.instagram.client import build_client, build_client_for_bot
from recall.models import BotAccount, BotStatus, User

logger = logging.getLogger(__name__)


def active_bots(db: Session) -> list[BotAccount]:
    return list(
        db.scalars(
            select(BotAccount)
            .where(BotAccount.status == BotStatus.ACTIVE)
            .order_by(BotAccount.created_at)
        )
    )


def pick_least_loaded_bot(db: Session) -> BotAccount | None:
    """The ACTIVE bot with the fewest assigned users (ties: oldest first)."""
    bots = active_bots(db)
    if not bots:
        return None
    counts = dict(
        db.execute(
            select(User.bot_account_id, func.count())
            .where(User.bot_account_id.is_not(None))
            .group_by(User.bot_account_id)
        ).all()
    )
    return min(bots, key=lambda b: (counts.get(b.id, 0),))


class BotClientPool:
    """Caches one instagrapi client per bot; `None` key is the .env account."""

    def __init__(self):
        self._clients: dict[uuid.UUID | None, object] = {}

    def get(self, bot: BotAccount | None):
        key = bot.id if bot else None
        if key not in self._clients:
            self._clients[key] = (
                build_client_for_bot(bot.username, bot.sessionid) if bot else build_client()
            )
        return self._clients[key]

    def drop(self, bot: BotAccount | None) -> None:
        """Forget a client (after challenge/auth errors) so it re-logs next use."""
        self._clients.pop(bot.id if bot else None, None)

    def for_user(self, db: Session, user_id: uuid.UUID | None):
        """Client for a user's assigned bot; .env account when unassigned."""
        bot = None
        if user_id is not None:
            user = db.get(User, user_id)
            if user and user.bot_account_id:
                bot = db.get(BotAccount, user.bot_account_id)
                if bot and bot.status != BotStatus.ACTIVE:
                    bot = None
        return self.get(bot)
