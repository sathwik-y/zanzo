from sqlalchemy import select

from recall.models import (
    EMBEDDING_DIMS,
    AppState,
    Embedding,
    Extraction,
    MediaRef,
    SavedItem,
)


def test_saved_item_round_trip(db, make_item):
    item = make_item(caption="ramen in tokyo", hashtags=["ramen", "tokyo"])
    found = db.scalar(select(SavedItem).where(SavedItem.media_pk == item.media_pk))
    assert found is not None
    assert found.hashtags == ["ramen", "tokyo"]
    assert found.status == "PENDING"
    assert found.archived is False


def test_extraction_and_media_refs_cascade(db, make_item):
    item = make_item()
    db.add(Extraction(item_id=item.id, schema_version="1", payload={"summary": "x"}))
    db.add(MediaRef(item_id=item.id, s3_key=f"media/{item.media_pk}/v.mp4", media_kind="VIDEO", bytes=123))
    db.commit()

    found = db.get(SavedItem, item.id)
    assert found.extraction.payload == {"summary": "x"}
    assert len(found.media_refs) == 1

    db.delete(found)
    db.commit()
    assert db.scalar(select(Extraction).where(Extraction.item_id == item.id)) is None


def test_embedding_vector_round_trip_and_similarity(db, make_item):
    a = make_item(caption="ramen")
    b = make_item(caption="postgres")
    vec_a = [1.0] + [0.0] * (EMBEDDING_DIMS - 1)
    vec_b = [0.0, 1.0] + [0.0] * (EMBEDDING_DIMS - 2)
    db.add(Embedding(item_id=a.id, vector=vec_a, model="test"))
    db.add(Embedding(item_id=b.id, vector=vec_b, model="test"))
    db.commit()

    # nearest neighbour to vec_a must be item a
    query = (
        select(Embedding.item_id)
        .order_by(Embedding.vector.cosine_distance(vec_a))
        .limit(1)
    )
    assert db.scalar(query) == a.id


def test_app_state_upsert(db):
    db.add(AppState(key="test.poller", value={"status": "running"}))
    db.commit()
    row = db.get(AppState, "test.poller")
    row.value = {"status": "challenge_required"}
    db.commit()
    assert db.get(AppState, "test.poller").value["status"] == "challenge_required"
