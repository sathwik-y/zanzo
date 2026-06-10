"""Stages 3-5: classify, extract, embed."""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from recall.categories import SCHEMA_VERSION, Category
from recall.models import Embedding, Extraction, SavedItem
from recall.pipeline.visual import gather_visual_parts
from recall.storage import MediaStorage

logger = logging.getLogger(__name__)


def make_classify_stage(ai, storage: MediaStorage) -> callable:
    def classify(db: Session, item: SavedItem) -> None:
        media = gather_visual_parts(storage, item)
        try:
            result = ai.classify(db, item.id, item.caption, item.transcript, media=media)
        except Exception:
            # Non-destructive: a transient failure (e.g. LLM quota) must not wipe
            # a category from a prior successful run. Keep it and move on.
            if item.category:
                logger.warning(
                    "classify failed for %s; keeping existing category %s",
                    item.media_pk,
                    item.category,
                )
                db.rollback()
                return
            raise
        item.category = Category(result["category"]).value
        item.category_confidence = float(result.get("confidence", 0.0))
        db.commit()
        logger.info(
            "classified %s as %s (%.2f, %d visual parts)",
            item.media_pk,
            item.category,
            item.category_confidence,
            len(media),
        )

    return classify


def make_extract_stage(ai, storage: MediaStorage | None = None) -> callable:
    def extract(db: Session, item: SavedItem) -> None:
        category = Category(item.category or Category.OTHER)
        kind = "reel" if item.media_type in ("REEL", "IGTV") else "post"
        media = gather_visual_parts(storage, item) if storage is not None else None
        existing = db.scalar(select(Extraction).where(Extraction.item_id == item.id))
        try:
            payload = ai.extract(
                db, item.id, category, item.caption, item.transcript, kind, media=media
            )
        except Exception:
            if existing:
                logger.warning(
                    "extract failed for %s; keeping existing extraction", item.media_pk
                )
                db.rollback()
                return
            raise

        if existing:
            existing.payload = payload
            existing.schema_version = SCHEMA_VERSION
        else:
            db.add(Extraction(item_id=item.id, schema_version=SCHEMA_VERSION, payload=payload))
        db.commit()
        db.refresh(item)

    return extract


def build_embed_text(item: SavedItem) -> str:
    parts = [item.caption or ""]
    if item.transcript:
        parts.append(item.transcript[:4000])
    if item.extraction:
        payload = item.extraction.payload
        summary = payload.get("summary") or ""
        parts.append(summary)
        # surface key names so semantic search can find "that ramen place"
        for key in ("dish_name", "destination", "title", "topic", "subject"):
            if payload.get(key):
                parts.append(str(payload[key]))
    if item.author_username:
        parts.append(f"by @{item.author_username}")
    return "\n".join(p for p in parts if p).strip() or "(empty)"


def make_embed_stage(ai) -> callable:
    def embed(db: Session, item: SavedItem) -> None:
        from recall.config import get_settings

        existing = db.scalar(select(Embedding).where(Embedding.item_id == item.id))
        try:
            vector = ai.embed(db, item.id, build_embed_text(item))
        except Exception:
            if existing:
                logger.warning("embed failed for %s; keeping existing embedding", item.media_pk)
                db.rollback()
                return
            raise
        model_name = get_settings().gemini_embedding_model
        if existing:
            existing.vector = vector
            existing.model = model_name
        else:
            db.add(Embedding(item_id=item.id, vector=vector, model=model_name))
        db.commit()

    return embed
