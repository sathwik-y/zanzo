from pathlib import Path

from recall.ai.transcription import DeepgramTranscriber, TranscriptResult
from recall.models import MediaRef
from recall.pipeline.transcribe import make_transcribe_stage
from recall.storage import LocalDirStorage


def test_deepgram_parse_response_maps_dict():
    # shape mirrors the verified Deepgram v7 response
    resp = {
        "results": {
            "channels": [
                {
                    "detected_language": "te",
                    "alternatives": [{"transcript": "Namaskaram idi oka manchi recipe"}],
                }
            ],
            "utterances": [
                {"start": 0.0, "end": 2.5, "transcript": "Namaskaram"},
                {"start": 2.5, "end": 5.0, "transcript": "idi oka manchi recipe"},
            ],
        }
    }
    result = DeepgramTranscriber.parse_response(resp)
    assert result.provider == "deepgram"
    assert result.lang == "te"
    assert result.text == "Namaskaram idi oka manchi recipe"
    assert len(result.segments) == 2
    assert result.segments[0] == {"start": 0.0, "end": 2.5, "text": "Namaskaram"}


class _FakeTranscriber:
    name = "fake"

    def transcribe(self, video_path: Path) -> TranscriptResult:
        return TranscriptResult(
            text="hello world",
            segments=[{"start": 0.0, "end": 1.0, "text": "hello world"}],
            lang="en",
            provider="fake",
        )


def test_transcribe_stage_stores_provider_and_lang(db, make_item, tmp_path):
    storage = LocalDirStorage(tmp_path)
    item = make_item()
    (tmp_path / "media" / item.media_pk).mkdir(parents=True)
    (tmp_path / "media" / item.media_pk / "video.mp4").write_bytes(b"fakevideo")
    item.media_refs.append(
        MediaRef(s3_key=f"media/{item.media_pk}/video.mp4", media_kind="VIDEO", bytes=9)
    )
    db.commit()

    stage = make_transcribe_stage(storage, transcriber=_FakeTranscriber())
    stage(db, item)
    db.refresh(item)
    assert item.transcript == "hello world"
    assert item.transcript_lang == "en"
    assert item.transcript_provider == "fake"
    assert item.transcript_segments[0]["text"] == "hello world"


def test_transcribe_skips_non_video(db, make_item, tmp_path):
    stage = make_transcribe_stage(LocalDirStorage(tmp_path), transcriber=_FakeTranscriber())
    item = make_item()  # no media refs
    stage(db, item)
    db.refresh(item)
    assert item.transcript is None
