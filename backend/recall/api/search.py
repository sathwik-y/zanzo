"""Hybrid search: pgvector semantic ranking combined with plain text matching."""
import logging

from sqlalchemy import Select, Text, cast, or_, select
from sqlalchemy.orm import Session

from recall.models import Embedding, Extraction, SavedItem

logger = logging.getLogger(__name__)


def hybrid_search(
    db: Session,
    ai,
    query: str,
    base_filter: Select,
    limit: int = 20,
) -> list[tuple[SavedItem, str]]:
    """Returns (item, match_reason) ranked best-first.

    Semantic: cosine distance over embeddings. Text: ILIKE over caption,
    transcript and extraction payload. An item matched by both ranks highest.
    """
    filtered_ids = select(base_filter.subquery().c.id)

    # Semantic leg
    query_vec = ai.embed(db, None, query)
    semantic_rows = db.execute(
        select(SavedItem.id, Embedding.vector.cosine_distance(query_vec).label("dist"))
        .join(Embedding, Embedding.item_id == SavedItem.id)
        .where(SavedItem.id.in_(filtered_ids))
        .order_by("dist")
        .limit(limit * 2)
    ).all()
    semantic_score = {row.id: 1.0 - float(row.dist) for row in semantic_rows}

    # Text leg
    pattern = f"%{query}%"
    text_ids = set(
        db.scalars(
            select(SavedItem.id)
            .outerjoin(Extraction, Extraction.item_id == SavedItem.id)
            .where(SavedItem.id.in_(filtered_ids))
            .where(
                or_(
                    SavedItem.caption.ilike(pattern),
                    SavedItem.transcript.ilike(pattern),
                    cast(Extraction.payload, Text).ilike(pattern),
                )
            )
            .limit(limit * 2)
        ).all()
    )

    scores: dict = {}
    for item_id, s in semantic_score.items():
        scores[item_id] = (s, "semantic")
    for item_id in text_ids:
        if item_id in scores:
            scores[item_id] = (scores[item_id][0] + 0.3, "semantic + text")
        else:
            scores[item_id] = (0.5, "text")

    ranked = sorted(scores.items(), key=lambda kv: kv[1][0], reverse=True)[:limit]
    if not ranked:
        return []

    items = {
        i.id: i
        for i in db.scalars(select(SavedItem).where(SavedItem.id.in_([k for k, _ in ranked])))
    }
    return [(items[item_id], reason) for item_id, (_, reason) in ranked if item_id in items]
