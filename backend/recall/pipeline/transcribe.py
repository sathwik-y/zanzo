"""Stage 2: transcription for video items via the configured provider.

Deepgram (multilingual) when a key is set, otherwise local Whisper. The video
file is pulled from storage to a temp path and handed to the transcriber.
"""
import logging
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from recall.ai.transcription import Transcriber, build_transcriber
from recall.models import MediaKind, SavedItem
from recall.storage import MediaStorage

logger = logging.getLogger(__name__)


def make_transcribe_stage(storage: MediaStorage, transcriber: Transcriber | None = None) -> callable:
    _cache: dict = {}

    def get_transcriber() -> Transcriber:
        if transcriber is not None:
            return transcriber
        if "t" not in _cache:
            _cache["t"] = build_transcriber()
        return _cache["t"]

    def transcribe(db: Session, item: SavedItem) -> None:
        if item.transcript:  # idempotent re-run
            return
        video_ref = next((r for r in item.media_refs if r.media_kind == MediaKind.VIDEO), None)
        if video_ref is None:  # not a video; nothing to transcribe
            return

        with tempfile.TemporaryDirectory() as tmp:
            video_path = Path(tmp) / "video.mp4"
            storage.get_to_file(video_ref.s3_key, video_path)
            result = get_transcriber().transcribe(video_path)

        item.transcript = result.text or None
        item.transcript_segments = result.segments or None
        item.transcript_lang = result.lang
        item.transcript_provider = result.provider
        db.commit()
        logger.info(
            "transcribed %s: %d segments, lang=%s via %s",
            item.media_pk,
            len(result.segments),
            result.lang,
            result.provider,
        )

    return transcribe
