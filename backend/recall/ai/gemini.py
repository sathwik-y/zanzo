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
        self._embedding_model = settings.gemini_embedding_model
        self._dims = settings.embedding_dimensions

    def classify(
        self,
        db: Session,
        item_id,
        caption: str | None,
        transcript: str | None,
        thumbnail: bytes | None = None,
    ) -> dict:
        from google.genai import types

        contents: list = [build_classifier_prompt(caption, transcript)]
        if thumbnail:
            contents.append(types.Part.from_bytes(data=thumbnail, mime_type="image/jpeg"))

        resp = self._client.models.generate_content(
            model=self._model,
            contents=contents,
            config={
                "response_mime_type": "application/json",
                "response_schema": CLASSIFIER_SCHEMA,
                "temperature": 0,
            },
        )
        self._record(db, item_id, "classify", resp)
        return json.loads(resp.text)

    def extract(
        self,
        db: Session,
        item_id,
        category: Category,
        caption: str | None,
        transcript: str | None,
        kind: str = "reel",
    ) -> dict:
        resp = self._client.models.generate_content(
            model=self._model,
            contents=build_extractor_prompt(category, caption, transcript, kind),
            config={
                "response_mime_type": "application/json",
                "response_schema": EXTRACTION_SCHEMAS[category],
                "temperature": 0,
            },
        )
        self._record(db, item_id, "extract", resp)
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

    def _record(self, db: Session, item_id, stage: str, resp) -> None:
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
                model=self._model,
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

    def classify(self, db, item_id, caption, transcript, thumbnail=None) -> dict:
        text = f"{caption or ''} {transcript or ''}".lower()
        for category, words in self.KEYWORDS.items():
            if any(w in text for w in words):
                return {"category": category.value, "confidence": 0.9, "reasoning": "keyword match (fake mode)"}
        return {"category": "OTHER", "confidence": 0.5, "reasoning": "no keyword match (fake mode)"}

    def extract(self, db, item_id, category, caption, transcript, kind="reel") -> dict:
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
