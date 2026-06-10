import pytest

from recall.models import MediaRef
from recall.pipeline.visual import (
    gather_visual_parts,
    needs_video_analysis,
    references_on_screen,
)
from recall.storage import LocalDirStorage


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Here is how you do it, step one is to chop the onion", False),
        ("As you can see on the screen, the settings are here", True),
        ("link in bio for the full guide", True),
        ("I've shared the steps below", True),
        ("check the description for the code", True),
        ("", False),
    ],
)
def test_references_on_screen(text, expected):
    assert references_on_screen(text) is expected


def test_needs_video_analysis(make_item):
    # silent reel (no transcript) -> needs video
    assert needs_video_analysis(make_item(media_type="REEL", transcript=None)) is True
    # reel with on-screen reference -> needs video
    assert needs_video_analysis(make_item(media_type="REEL", transcript="link in bio for more")) is True
    # reel with good spoken transcript -> no video
    assert (
        needs_video_analysis(
            make_item(media_type="REEL", transcript="Today I'm explaining how compilers turn code into machine instructions step by step")
        )
        is False
    )
    # a post is never sent as video
    assert needs_video_analysis(make_item(media_type="POST", transcript=None)) is False


def test_gather_parts_uses_images_for_post(db, make_item, tmp_path):
    storage = LocalDirStorage(tmp_path)
    item = make_item(media_type="POST")
    key = f"media/{item.media_pk}/image.jpg"
    storage.put_bytes(b"imgbytes", key)
    item.media_refs.append(MediaRef(s3_key=key, media_kind="IMAGE", bytes=8))
    db.commit()

    parts = gather_visual_parts(storage, item)
    assert len(parts) == 1
    assert parts[0]["kind"] == "image"
    assert parts[0]["bytes"] == b"imgbytes"


def test_gather_parts_includes_video_for_silent_reel(db, make_item, tmp_path):
    storage = LocalDirStorage(tmp_path)
    item = make_item(media_type="REEL", transcript=None)
    vkey = f"media/{item.media_pk}/video.mp4"
    tkey = f"media/{item.media_pk}/thumb.jpg"
    storage.put_bytes(b"videobytes", vkey)
    storage.put_bytes(b"thumbbytes", tkey)
    item.media_refs.append(MediaRef(s3_key=vkey, media_kind="VIDEO", bytes=10))
    item.media_refs.append(MediaRef(s3_key=tkey, media_kind="THUMBNAIL", bytes=10))
    db.commit()

    parts = gather_visual_parts(storage, item)
    kinds = sorted(p["kind"] for p in parts)
    assert kinds == ["image", "video"]


def test_gather_parts_skips_video_for_spoken_reel(db, make_item, tmp_path):
    storage = LocalDirStorage(tmp_path)
    item = make_item(
        media_type="REEL",
        transcript="Today I walk through the entire deployment process in detail with examples",
    )
    vkey = f"media/{item.media_pk}/video.mp4"
    tkey = f"media/{item.media_pk}/thumb.jpg"
    storage.put_bytes(b"videobytes", vkey)
    storage.put_bytes(b"thumbbytes", tkey)
    item.media_refs.append(MediaRef(s3_key=vkey, media_kind="VIDEO", bytes=10))
    item.media_refs.append(MediaRef(s3_key=tkey, media_kind="THUMBNAIL", bytes=10))
    db.commit()

    parts = gather_visual_parts(storage, item)
    assert [p["kind"] for p in parts] == ["image"]  # thumbnail only, no video
