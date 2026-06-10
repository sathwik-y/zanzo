"""Pluggable transcription.

Deepgram (nova-2) is the primary provider when DEEPGRAM_API_KEY is set: it has
dedicated support for English, Hindi and Telugu and auto-detects the language
per reel. faster-whisper is the local, zero-cost fallback so the self-hosted
story still works with no external key.

Both providers return the same TranscriptResult so the pipeline stage is
provider-agnostic.
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from recall.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class TranscriptResult:
    text: str
    segments: list[dict] = field(default_factory=list)  # [{start, end, text}]
    lang: str | None = None
    provider: str = "unknown"


class Transcriber(Protocol):
    name: str

    def transcribe(self, video_path: Path) -> TranscriptResult: ...


class DeepgramTranscriber:
    name = "deepgram"

    def __init__(self):
        from deepgram import DeepgramClient

        settings = get_settings()
        self._client = DeepgramClient(api_key=settings.deepgram_api_key)
        self._model = settings.deepgram_model

    def transcribe(self, video_path: Path) -> TranscriptResult:
        data = Path(video_path).read_bytes()
        resp = self._client.listen.v1.media.transcribe_file(
            request=data,
            model=self._model,
            detect_language=True,
            smart_format=True,
            punctuate=True,
            utterances=True,
        )
        return self.parse_response(resp)

    @staticmethod
    def parse_response(resp) -> TranscriptResult:
        """Map a Deepgram v7 response to TranscriptResult.

        Accepts either the SDK object or a plain dict (used by tests).
        """
        results = resp["results"] if isinstance(resp, dict) else resp.results
        channels = results["channels"] if isinstance(results, dict) else results.channels
        channel = channels[0]
        alt = (channel["alternatives"] if isinstance(channel, dict) else channel.alternatives)[0]
        text = alt["transcript"] if isinstance(alt, dict) else alt.transcript
        lang = (
            channel.get("detected_language")
            if isinstance(channel, dict)
            else getattr(channel, "detected_language", None)
        )
        raw_utts = (
            results.get("utterances")
            if isinstance(results, dict)
            else getattr(results, "utterances", None)
        ) or []
        segments = []
        for u in raw_utts:
            if isinstance(u, dict):
                start, end, utext = u.get("start"), u.get("end"), u.get("transcript", "")
            else:
                start, end, utext = u.start, u.end, u.transcript
            segments.append(
                {"start": round(float(start), 2), "end": round(float(end), 2), "text": utext.strip()}
            )
        return TranscriptResult(text=text.strip(), segments=segments, lang=lang, provider="deepgram")


class WhisperTranscriber:
    name = "whisper"
    _model = None

    def _get_model(self):
        if WhisperTranscriber._model is None:
            from faster_whisper import WhisperModel

            settings = get_settings()
            logger.info("loading whisper model %s", settings.whisper_model_size)
            WhisperTranscriber._model = WhisperModel(
                settings.whisper_model_size,
                device="cpu",
                compute_type=settings.whisper_compute_type,
            )
        return WhisperTranscriber._model

    def transcribe(self, video_path: Path) -> TranscriptResult:
        segments_iter, info = self._get_model().transcribe(str(video_path), vad_filter=True)
        segments = [
            {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
            for s in segments_iter
        ]
        text = " ".join(s["text"] for s in segments).strip()
        return TranscriptResult(text=text, segments=segments, lang=info.language, provider="whisper")


def build_transcriber() -> Transcriber:
    settings = get_settings()
    if settings.deepgram_api_key:
        logger.info("using Deepgram transcription (%s)", settings.deepgram_model)
        return DeepgramTranscriber()
    logger.info("using local Whisper transcription (no Deepgram key set)")
    return WhisperTranscriber()
