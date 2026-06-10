from recall.ai.gemini import FakeGemini
from recall.categories import EXTRACTION_SCHEMAS, Category
from recall.models import EMBEDDING_DIMS
from recall.pipeline.ai_stages import (
    build_embed_text,
    make_classify_stage,
    make_embed_stage,
    make_extract_stage,
)
from recall.pipeline.runner import process_item
from recall.storage import LocalDirStorage


def _stages(tmp_path):
    ai = FakeGemini()
    storage = LocalDirStorage(tmp_path)
    return {
        "classify": make_classify_stage(ai, storage),
        "extract": make_extract_stage(ai),
        "embed": make_embed_stage(ai),
    }


def test_classify_sets_category(db, make_item, tmp_path):
    item = make_item(caption="Best ramen recipe, ingredients below")
    stages = _stages(tmp_path)
    stages["classify"](db, item)
    assert item.category == "RECIPE"
    assert item.category_confidence == 0.9


def test_extract_stores_required_fields_for_every_category(db, make_item, tmp_path):
    stages = _stages(tmp_path)
    for category in Category:
        item = make_item(caption=f"content for {category}", category=category.value)
        stages["extract"](db, item)
        db.refresh(item)
        required = EXTRACTION_SCHEMAS[category]["required"]
        for field in required:
            assert field in item.extraction.payload, f"{category}: missing {field}"
        assert item.extraction.schema_version == "1"


def test_extract_is_idempotent_update(db, make_item, tmp_path):
    stages = _stages(tmp_path)
    item = make_item(caption="travel to tokyo", category="TRAVEL")
    stages["extract"](db, item)
    first_id = item.extraction.id
    stages["extract"](db, item)
    db.refresh(item)
    assert item.extraction.id == first_id  # updated, not duplicated


def test_embed_writes_vector(db, make_item, tmp_path):
    stages = _stages(tmp_path)
    item = make_item(caption="postgres replication tutorial", category="TECH_REFERENCE")
    stages["embed"](db, item)
    db.refresh(item)
    assert item.embedding is not None
    assert len(item.embedding.vector) == EMBEDDING_DIMS


def test_full_ai_pipeline_completes(db, make_item, tmp_path):
    item = make_item(caption="music festival in november, get tickets now")
    assert process_item(db, str(item.id), _stages(tmp_path)) is True
    db.refresh(item)
    assert item.status == "COMPLETED"
    assert item.category == "EVENT"
    assert item.extraction is not None
    assert item.embedding is not None


def test_build_embed_text_includes_key_fields(db, make_item, tmp_path):
    stages = _stages(tmp_path)
    item = make_item(caption="ramen tour", category="TRAVEL", author_username="foodie")
    stages["extract"](db, item)
    db.refresh(item)
    text = build_embed_text(item)
    assert "ramen tour" in text
    assert "@foodie" in text
