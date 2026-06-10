"""Spike: confirm the Deepgram v7 key works and returns segments + detected language.

Downloads one already-stored reel video from MinIO and transcribes it.
nova-2 is used because it has dedicated Telugu (te) and Hindi (hi) support.
"""
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from deepgram import DeepgramClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from recall.db import get_session_factory  # noqa: E402
from recall.models import MediaKind, MediaRef  # noqa: E402
from recall.storage import S3Storage  # noqa: E402

storage = S3Storage()
with get_session_factory()() as db:
    ref = db.scalar(select(MediaRef).where(MediaRef.media_kind == MediaKind.VIDEO))
    if ref is None:
        raise SystemExit("no video media in db; run the pipeline first")
    print("using", ref.s3_key)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "v.mp4"
        storage.get_to_file(ref.s3_key, path)
        data = path.read_bytes()

dg = DeepgramClient(api_key=os.environ["DEEPGRAM_API_KEY"])
resp = dg.listen.v1.media.transcribe_file(
    request=data,
    model="nova-2",
    detect_language=True,
    smart_format=True,
    punctuate=True,
    utterances=True,
)
channel = resp.results.channels[0]
alt = channel.alternatives[0]
print("DETECTED LANG:", getattr(channel, "detected_language", None))
print("TRANSCRIPT (first 200):", alt.transcript[:200])
utterances = resp.results.utterances or []
print("UTTERANCES:", len(utterances))
if utterances:
    u = utterances[0]
    print("first utterance:", round(u.start, 2), round(u.end, 2), u.transcript[:80])
