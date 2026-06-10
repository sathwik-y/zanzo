"""Detect 'comment KEYWORD / follow me to get the link' calls-to-action.

When a reel's caption or transcript asks the viewer to comment a keyword (and
often follow) to receive a resource by DM, we capture that intent so the
engagement reconciler can act on it. Detection uses a small structured Gemini
call; FakeGemini uses a keyword heuristic.
"""
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from recall.models import Engagement, EngagementChannel, EngagementStatus, SavedItem

logger = logging.getLogger(__name__)

CTA_SCHEMA = {
    "type": "object",
    "properties": {
        "is_cta": {"type": "boolean"},
        "keyword": {"type": "string", "nullable": True},
        "needs_follow": {"type": "boolean"},
        "channel": {"type": "string", "enum": ["comment", "dm", "both"]},
    },
    "required": ["is_cta", "needs_follow", "channel"],
}

CTA_PROMPT = """Decide whether this Instagram post asks the viewer to take an action to receive a resource (a link, guide, template, file, etc.).

Typical patterns: "comment X and I'll DM you the link", "comment 'GUIDE' for the free template", "follow me + comment LINK", "DM me the word START".

Return:
- is_cta: true only if the viewer must comment and/or DM a specific keyword to get something.
- keyword: the exact word/phrase to send (e.g. "GMB", "LINK", "GUIDE"). Null if none.
- needs_follow: true if following the creator is required or requested.
- channel: "comment" if they ask you to comment, "dm" if they ask you to DM them, "both" if either/both.

CAPTION:
{caption}

TRANSCRIPT:
{transcript}
"""


@dataclass
class CtaSpec:
    is_cta: bool
    keyword: str | None
    needs_follow: bool
    channel: str


def build_cta_prompt(caption: str | None, transcript: str | None) -> str:
    return CTA_PROMPT.format(
        caption=(caption or "(no caption)")[:4000],
        transcript=(transcript or "(no transcript)")[:8000],
    )


def detect_cta(ai, db: Session, item: SavedItem) -> CtaSpec:
    raw = ai.detect_cta(db, item.id, item.caption, item.transcript)
    return CtaSpec(
        is_cta=bool(raw.get("is_cta")),
        keyword=(raw.get("keyword") or None),
        needs_follow=bool(raw.get("needs_follow")),
        channel=raw.get("channel") or EngagementChannel.COMMENT,
    )


def queue_engagement(db: Session, item: SavedItem, spec: CtaSpec) -> Engagement | None:
    if not spec.is_cta or not spec.keyword or not item.author_username:
        return None
    existing = db.scalar(select(Engagement).where(Engagement.item_id == item.id))
    if existing:
        return existing  # already queued/handled
    eng = Engagement(
        item_id=item.id,
        creator_username=item.author_username,
        media_pk=item.media_pk,
        keyword=spec.keyword,
        needs_follow=spec.needs_follow,
        channel=spec.channel,
        status=EngagementStatus.PENDING,
    )
    db.add(eng)
    db.commit()
    logger.info(
        "queued engagement for %s: comment '%s' to @%s (follow=%s)",
        item.media_pk,
        spec.keyword,
        item.author_username,
        spec.needs_follow,
    )
    return eng


def make_cta_stage(ai) -> callable:
    """Pipeline stage: detect a CTA and queue an engagement if actionable.

    Secondary to the main pipeline - never raises, so a detection hiccup can
    not stop an item from reaching COMPLETED.
    """

    def cta(db: Session, item: SavedItem) -> None:
        try:
            spec = detect_cta(ai, db, item)
            queue_engagement(db, item, spec)
        except Exception:
            logger.exception("CTA detection failed for %s (non-fatal)", item.media_pk)
            db.rollback()

    return cta
