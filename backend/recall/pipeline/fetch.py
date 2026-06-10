"""Stage 1: hydrate metadata and download media into storage.

Idempotent: items that already have media_refs of a given kind are skipped.
Download order: instagrapi URLs first, yt-dlp as fallback for videos.
"""
import logging
import re
import tempfile
from pathlib import Path

import requests
from instagrapi import Client
from sqlalchemy.orm import Session

from recall.instagram.client import media_type_label
from recall.models import MediaKind, MediaRef, SavedItem
from recall.storage import MediaStorage

logger = logging.getLogger(__name__)

HASHTAG_RE = re.compile(r"#(\w+)")


def parse_hashtags(caption: str | None) -> list[str]:
    return HASHTAG_RE.findall(caption or "")


def make_fetch_stage(storage: MediaStorage, get_client) -> callable:
    """get_client: lazy () -> instagrapi Client, so the worker only logs in when needed."""

    def fetch(db: Session, item: SavedItem) -> None:
        cl: Client = get_client()
        info = cl.media_info(item.media_pk)

        item.media_type = media_type_label(info.media_type, info.product_type)
        item.instagram_url = (
            f"https://www.instagram.com/p/{info.code}/" if info.code else item.instagram_url
        )
        item.author_username = info.user.username if info.user else item.author_username
        item.author_full_name = info.user.full_name if info.user else item.author_full_name
        item.caption = info.caption_text or item.caption
        item.hashtags = parse_hashtags(item.caption)
        item.post_created_at = info.taken_at or item.post_created_at
        db.commit()

        existing_kinds = {ref.media_kind for ref in item.media_refs}

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)

            if MediaKind.THUMBNAIL not in existing_kinds and info.thumbnail_url:
                _store_url(
                    db, storage, item, str(info.thumbnail_url),
                    tmpdir / "thumb.jpg", MediaKind.THUMBNAIL,
                )

            if item.media_type in ("REEL", "IGTV") and MediaKind.VIDEO not in existing_kinds:
                video_path = tmpdir / "video.mp4"
                try:
                    _download_url(str(info.video_url), video_path)
                except Exception:
                    logger.warning("direct video download failed, trying yt-dlp", exc_info=True)
                    _ytdlp_download(item.instagram_url, video_path)
                _store_file(db, storage, item, video_path, MediaKind.VIDEO)

            elif item.media_type == "POST" and MediaKind.IMAGE not in existing_kinds:
                if info.thumbnail_url:
                    _store_url(
                        db, storage, item, str(info.thumbnail_url),
                        tmpdir / "image.jpg", MediaKind.IMAGE,
                    )

            elif item.media_type == "CAROUSEL" and MediaKind.IMAGE not in existing_kinds:
                for i, res in enumerate(info.resources or []):
                    url = str(res.video_url or res.thumbnail_url or "")
                    if not url:
                        continue
                    ext = "mp4" if res.video_url else "jpg"
                    kind = MediaKind.VIDEO if res.video_url else MediaKind.IMAGE
                    _store_url(db, storage, item, url, tmpdir / f"carousel_{i}.{ext}", kind)

        db.commit()

    return fetch


def _download_url(url: str, dest: Path) -> None:
    resp = requests.get(url, timeout=120, stream=True)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            f.write(chunk)


def _ytdlp_download(instagram_url: str | None, dest: Path) -> None:
    if not instagram_url:
        raise RuntimeError("no instagram_url for yt-dlp fallback")
    import yt_dlp

    opts = {"outtmpl": str(dest.with_suffix("")) + ".%(ext)s", "quiet": True, "format": "mp4/best"}
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([instagram_url])
    candidates = list(dest.parent.glob(dest.stem + ".*"))
    if not candidates:
        raise RuntimeError("yt-dlp produced no file")
    candidates[0].rename(dest)


def _store_url(db, storage, item, url: str, tmp_path: Path, kind: str) -> None:
    _download_url(url, tmp_path)
    _store_file(db, storage, item, tmp_path, kind)


def _store_file(db, storage, item, path: Path, kind: str) -> None:
    key = f"media/{item.media_pk}/{path.name}"
    size = storage.put_file(path, key)
    # append via the relationship so later stages see the new ref without a refresh
    item.media_refs.append(MediaRef(s3_key=key, media_kind=kind, bytes=size))
    db.commit()
