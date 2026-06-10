"""Stages 3-5: classify, extract, embed."""
import logging
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from recall.categories import SCHEMA_VERSION, Category
from recall.models import Embedding, Extraction, MediaKind, SavedItem
from recall.storage import MediaStorage

logger = logging.getLogger(__name__)


def make_classify_stage(ai, storage: MediaStorage) -> callable:
    def classify(db: Session, item: SavedItem) -> None:
        thumbnail = None
        thumb_ref = next(
            (r for r in item.media_refs if r.media_kind == MediaKind.THUMBNAIL), None
        )
        if thumb_ref:
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    p = Path(tmp) / "thumb.jpg"
                    storage.get_to_file(thumb_ref.s3_key, p)
                    thumbnail = p.read_bytes()
            except Exception:
                logger.warning("thumbnail unavailable for %s; classifying text-only", item.media_pk)

        result = ai.classify(db, item.id, item.caption, item.transcript, thumbnail)
        item.category = Category(result["category"]).value
        item.category_confidence = float(result.get("confidence", 0.0))
        db.commit()
        logger.info("classified %s as %s (%.2f)", item.media_pk, item.category, item.category_confidence)

    return classify


def make_extract_stage(ai) -> callable:
    def extract(db: Session, item: SavedItem) -> None:
        category = Category(item.category or Category.OTHER)
        kind = "reel" if item.media_type in ("REEL", "IGTV") else "post"
        payload = ai.extract(db, item.id, category, item.caption, item.transcript, kind)

        existing = db.scalar(select(Extraction).where(Extraction.item_id == item.id))
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

        vector = ai.embed(db, item.id, build_embed_text(item))
        model_name = get_settings().gemini_embedding_model
        existing = db.scalar(select(Embedding).where(Embedding.item_id == item.id))
        if existing:
            existing.vector = vector
            existing.model = model_name
        else:
            db.add(Embedding(item_id=item.id, vector=vector, model=model_name))
        db.commit()

    return embed
