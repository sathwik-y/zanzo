"""Gemini client: classification, extraction, embeddings, with usage recording.

Set RECALL_FAKE_GEMINI=true to swap in FakeGemini (deterministic, offline) -
used by tests and the credential-less demo mode.
"""
import hashlib
import json
import logging
import math
import random

from sqlalchemy.orm import Session

from recall.ai.prompts import (
    CLASSIFIER_SCHEMA,
    build_classifier_prompt,
    build_extractor_prompt,
)
from recall.categories import EXTRACTION_SCHEMAS, Category
from recall.config import get_settings
from recall.models import LlmUsage

logger = logging.getLogger(__name__)


class GeminiClient:
    def __init__(self):
        from google import genai

        settings = get_settings()
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model
        self._fallbacks = [
            m.strip() for m in settings.gemini_fallback_models.split(",") if m.strip()
        ]
        self._embedding_model = settings.gemini_embedding_model
        self._dims = settings.embedding_dimensions

    def _generate(self, contents, config) -> tuple:
        """Try the primary model, then fallbacks on 5xx capacity errors.

        Returns (response, model_used).
        """
        from google.genai import errors

        last_exc: Exception | None = None
        for model in [self._model, *self._fallbacks]:
            try:
                resp = self._client.models.generate_content(
                    model=model, contents=contents, config=config
                )
                return resp, model
            except errors.ServerError as exc:
                logger.warning("model %s unavailable (%s); trying fallback", model, exc)
                last_exc = exc
        raise last_exc

    def _media_parts(self, media: list[dict] | None) -> list:
        """Turn visual descriptors into Gemini Parts.

        Images go inline; videos are uploaded via the Files API (handles size
        and lets the model sample frames), then deleted after the call.
        """
        from google.genai import types

        parts: list = []
        self._uploaded_files = []
        for m in media or []:
            if m["kind"] == "image":
                parts.append(types.Part.from_bytes(data=m["bytes"], mime_type=m["mime"]))
            elif m["kind"] == "video":
                import io

                uploaded = self._client.files.upload(
                    file=io.BytesIO(m["bytes"]), config={"mime_type": m["mime"]}
                )
                uploaded = self._wait_active(uploaded)
                parts.append(uploaded)
                self._uploaded_files.append(uploaded)
        return parts

    def _wait_active(self, file, timeout_s: int = 120):
        import time as _time

        waited = 0
        while getattr(file.state, "name", str(file.state)) == "PROCESSING" and waited < timeout_s:
            _time.sleep(2)
            waited += 2
            file = self._client.files.get(name=file.name)
        return file

    def _cleanup_files(self) -> None:
        for f in getattr(self, "_uploaded_files", []):
            try:
                self._client.files.delete(name=f.name)
            except Exception:
                logger.warning("could not delete uploaded file %s", getattr(f, "name", "?"))
        self._uploaded_files = []

    def classify(
        self,
        db: Session,
        item_id,
        caption: str | None,
        transcript: str | None,
        thumbnail: bytes | None = None,
        media: list[dict] | None = None,
    ) -> dict:
        from google.genai import types

        contents: list = [build_classifier_prompt(caption, transcript)]
        if media:
            contents.extend(self._media_parts(media))
        elif thumbnail:
            contents.append(types.Part.from_bytes(data=thumbnail, mime_type="image/jpeg"))

        try:
            resp, model = self._generate(
                contents,
                {
                    "response_mime_type": "application/json",
                    "response_schema": CLASSIFIER_SCHEMA,
                    "temperature": 0,
                },
            )
        finally:
            self._cleanup_files()
        self._record(db, item_id, "classify", resp, model)
        return json.loads(resp.text)

    def extract(
        self,
        db: Session,
        item_id,
        category: Category,
        caption: str | None,
        transcript: str | None,
        kind: str = "reel",
        media: list[dict] | None = None,
    ) -> dict:
        contents: list = [build_extractor_prompt(category, caption, transcript, kind)]
        if media:
            contents.extend(self._media_parts(media))
        try:
            resp, model = self._generate(
                contents,
                {
                    "response_mime_type": "application/json",
                    "response_schema": EXTRACTION_SCHEMAS[category],
                    "temperature": 0,
                },
            )
        finally:
            self._cleanup_files()
        self._record(db, item_id, "extract", resp, model)
        return json.loads(resp.text)

    def detect_cta(self, db: Session, item_id, caption: str | None, transcript: str | None) -> dict:
        from recall.pipeline.cta import CTA_SCHEMA, build_cta_prompt

        resp, model = self._generate(
            build_cta_prompt(caption, transcript),
            {
                "response_mime_type": "application/json",
                "response_schema": CTA_SCHEMA,
                "temperature": 0,
            },
        )
        self._record(db, item_id, "cta", resp, model)
        return json.loads(resp.text)

    def embed(self, db: Session, item_id, text: str) -> list[float]:
        resp = self._client.models.embed_content(
            model=self._embedding_model,
            contents=text[:8000],
            config={"output_dimensionality": self._dims},
        )
        # embed_content does not return token usage; estimate chars/4 for the dashboard
        est_tokens = len(text[:8000]) // 4
        db.add(
            LlmUsage(
                item_id=item_id,
                stage="embed",
                model=self._embedding_model,
                input_tokens=est_tokens,
                output_tokens=0,
                cost_usd=0.0,
            )
        )
        db.commit()
        return list(resp.embeddings[0].values)

    def _record(self, db: Session, item_id, stage: str, resp, model: str | None = None) -> None:
        settings = get_settings()
        usage = getattr(resp, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0
        cost = (
            input_tokens / 1e6 * settings.gemini_input_price_per_mtok
            + output_tokens / 1e6 * settings.gemini_output_price_per_mtok
        )
        db.add(
            LlmUsage(
                item_id=item_id,
                stage=stage,
                model=model or self._model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=round(cost, 6),
            )
        )
        db.commit()


class FakeGemini:
    """Deterministic offline stand-in. Keyword classifier + minimal valid payloads."""

    KEYWORDS = {
        Category.RECIPE: ["recipe", "ingredients", "cook", "bake", "dish", "ramen"],
        Category.EVENT: ["event", "festival", "concert", "tickets", "rsvp", "meetup"],
        Category.TRAVEL: ["travel", "visit", "trip", "itinerary", "tokyo", "destination"],
        Category.TECH_REFERENCE: ["code", "app", "tool", "postgres", "api", "command"],
        Category.EDUCATIONAL: ["learn", "tutorial", "how to", "tips", "guide", "explain"],
    }

    def classify(self, db, item_id, caption, transcript, thumbnail=None, media=None) -> dict:
        text = f"{caption or ''} {transcript or ''}".lower()
        for category, words in self.KEYWORDS.items():
            if any(w in text for w in words):
                return {"category": category.value, "confidence": 0.9, "reasoning": "keyword match (fake mode)"}
        return {"category": "OTHER", "confidence": 0.5, "reasoning": "no keyword match (fake mode)"}

    def extract(self, db, item_id, category, caption, transcript, kind="reel", media=None) -> dict:
        summary = (caption or transcript or "no content")[:200]
        payloads = {
            Category.EDUCATIONAL: {"topic": summary[:60], "key_takeaways": ["fake takeaway"], "summary": summary},
            Category.EVENT: {"title": summary[:60], "event_type": "other", "summary": summary},
            Category.RECIPE: {"dish_name": summary[:60], "ingredients": [{"item": "fake ingredient"}], "steps": ["fake step"]},
            Category.TRAVEL: {"destination": summary[:60], "summary": summary},
            Category.TECH_REFERENCE: {"subject": summary[:60], "summary": summary},
            Category.OTHER: {"summary": summary, "tags": ["fake"]},
        }
        return payloads[Category(category)]

    CTA_KEYWORDS = ["comment", "link in", "dm me", "dm the word", "follow me", "comment below"]

    def detect_cta(self, db, item_id, caption, transcript) -> dict:
        import re

        text = f"{caption or ''} {transcript or ''}".lower()
        if not any(k in text for k in self.CTA_KEYWORDS):
            return {"is_cta": False, "keyword": None, "needs_follow": False, "channel": "comment"}
        # pull a likely keyword: a quoted word, or an ALL-CAPS token in the original text
        keyword = None
        m = re.search(r'["“‘]([A-Za-z0-9 ]{2,20})["”’]', f"{caption or ''} {transcript or ''}")
        if m:
            keyword = m.group(1).strip()
        else:
            caps = re.findall(r"\b[A-Z]{3,15}\b", f"{caption or ''} {transcript or ''}")
            keyword = caps[0] if caps else "LINK"
        needs_follow = "follow" in text
        channel = "dm" if ("dm me" in text or "dm the word" in text) else "comment"
        return {"is_cta": True, "keyword": keyword, "needs_follow": needs_follow, "channel": channel}

    def embed(self, db, item_id, text: str) -> list[float]:
        settings = get_settings()
        seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        vec = [rng.uniform(-1, 1) for _ in range(settings.embedding_dimensions)]
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec]


def build_ai_client():
    if get_settings().recall_fake_gemini:
        return FakeGemini()
    return GeminiClient()
