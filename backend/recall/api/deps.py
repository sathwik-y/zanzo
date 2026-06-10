"""Shared FastAPI dependencies: API-key auth, DB session, singletons."""
from functools import lru_cache

from fastapi import Depends, Header, HTTPException

from recall.ai.gemini import build_ai_client
from recall.config import get_settings
from recall.db import get_db  # re-exported for routes
from recall.storage import S3Storage

__all__ = ["get_db", "require_api_key", "get_storage", "get_ai"]


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if x_api_key != get_settings().api_key:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


@lru_cache
def get_storage() -> S3Storage:
    return S3Storage()


@lru_cache
def get_ai():
    return build_ai_client()


ApiKey = Depends(require_api_key)
