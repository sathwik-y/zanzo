"""Stage 2: Whisper transcription for video items.

faster-whisper decodes the mp4's audio track directly (bundled PyAV), so no
ffmpeg binary or separate audio extraction is needed. The model loads lazily
and is cached for the worker's lifetime.
"""
import logging
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from recall.config import get_settings
from recall.models import MediaKind, SavedItem
from recall.storage import MediaStorage

logger = logging.getLogger(__name__)

_model = None


def get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        settings = get_settings()
        logger.info("loading whisper model %s", settings.whisper_model_size)
        _model = WhisperModel(
            settings.whisper_model_size, device="cpu", compute_type=settings.whisper_compute_type
        )
    return _model


def make_transcribe_stage(storage: MediaStorage) -> callable:
    def transcribe(db: Session, item: SavedItem) -> None:
        if item.transcript:  # idempotent re-run
            return
        video_ref = next(
            (r for r in item.media_refs if r.media_kind == MediaKind.VIDEO), None
        )
        if video_ref is None:  # not a video; nothing to transcribe
            return

        with tempfile.TemporaryDirectory() as tmp:
            video_path = Path(tmp) / "video.mp4"
            storage.get_to_file(video_ref.s3_key, video_path)
            segments_iter, info = get_model().transcribe(str(video_path), vad_filter=True)
            segments = [
                {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
                for s in segments_iter
            ]

        item.transcript = " ".join(s["text"] for s in segments).strip() or None
        item.transcript_segments = segments or None
        item.transcript_lang = info.language
        db.commit()
        logger.info(
            "transcribed %s: %d segments, lang=%s", item.media_pk, len(segments), info.language
        )

    return transcribe
