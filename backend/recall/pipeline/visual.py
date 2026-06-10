"""Decide when a reel needs visual (frame) analysis and gather media parts.

We send the video to the multimodal model when the audio gives us little to go
on: either the transcript is too short to be useful, or it explicitly points at
on-screen content ("as you can see on the screen", "link in bio", "shared
below"). Images (post photos, carousel frames, reel thumbnail) are always
gathered when present. The caption is always considered by the prompts.
"""
import logging
import re
import tempfile
from pathlib import Path

from recall.config import get_settings
from recall.models import MediaKind, SavedItem
from recall.storage import MediaStorage

logger = logging.getLogger(__name__)

# Phrases that mean "the useful information is shown, not spoken."
_SCREEN_REFERENCE_PATTERNS = [
    r"on (?:the |my )?screen",
    r"as you can see",
    r"shown (?:here|above|below)",
    r"\bshared\b.{0,20}\b(?:below|here|screen|above)",
    r"link in (?:bio|the description|comments|caption)",
    r"in the description",
    r"check (?:the |out the )?(?:link|description|caption|comment)",
    r"swipe (?:up|left|right)",
    r"(?:read|see) (?:the )?caption",
    r"down below",
    r"steps? (?:are )?(?:below|here|on (?:the )?screen)\b",
]
_SCREEN_RE = re.compile("|".join(_SCREEN_REFERENCE_PATTERNS), re.IGNORECASE)


def references_on_screen(transcript: str | None) -> bool:
    return bool(transcript) and bool(_SCREEN_RE.search(transcript))


def needs_video_analysis(item: SavedItem) -> bool:
    """True when a reel's audio is insufficient and we should look at frames."""
    if item.media_type not in ("REEL", "IGTV"):
        return False
    settings = get_settings()
    transcript = (item.transcript or "").strip()
    if len(transcript) < settings.transcript_weak_chars:
        return True
    return references_on_screen(transcript)


def gather_visual_parts(storage: MediaStorage, item: SavedItem) -> list[dict]:
    """Return a list of media descriptors for the AI client to attach.

    Each descriptor is {"kind": "image"|"video", "bytes": b"...", "mime": str}.
    Images are always included when present; video only when needed.
    """
    if not get_settings().visual_extraction:
        return []

    parts: list[dict] = []

    image_refs = [r for r in item.media_refs if r.media_kind == MediaKind.IMAGE]
    thumb_refs = [r for r in item.media_refs if r.media_kind == MediaKind.THUMBNAIL]
    chosen_images = image_refs or thumb_refs  # prefer real images; fall back to thumbnail
    for ref in chosen_images[:8]:  # cap carousel size
        data = _load(storage, ref.s3_key)
        if data:
            parts.append({"kind": "image", "bytes": data, "mime": "image/jpeg"})

    if needs_video_analysis(item):
        video_ref = next((r for r in item.media_refs if r.media_kind == MediaKind.VIDEO), None)
        if video_ref:
            data = _load(storage, video_ref.s3_key)
            if data:
                parts.append({"kind": "video", "bytes": data, "mime": "video/mp4"})
                logger.info("including video for visual analysis of %s", item.media_pk)

    return parts


def _load(storage: MediaStorage, key: str) -> bytes | None:
    try:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "m"
            storage.get_to_file(key, p)
            return p.read_bytes()
    except Exception:
        logger.warning("could not load media %s for visual analysis", key)
        return None
