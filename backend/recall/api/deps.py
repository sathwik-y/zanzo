"""Shared FastAPI dependencies: auth (JWT bearer or service API key), DB session, singletons.

Auth model:
- Users authenticate with a Bearer JWT (login/signup flow). All item queries are
  scoped to the authenticated user.
- The legacy X-API-Key is kept as a *service* credential (scripts, self-host
  curl, CI). It is admin-equivalent and unscoped.
- Admins additionally see unassigned items (user_id IS NULL): saved-collection
  ingestion from the bot account itself lands there.
"""
from dataclasses import dataclass
from functools import lru_cache

from fastapi import Depends, Header, HTTPException
from sqlalchemy import Select, or_
from sqlalchemy.orm import Session

from recall.ai.gemini import build_ai_client
from recall.auth import decode_token
from recall.config import get_settings
from recall.db import get_db  # re-exported for routes
from recall.models import SavedItem, User, UserRole
from recall.storage import S3Storage

__all__ = [
    "get_db",
    "require_api_key",
    "get_storage",
    "get_ai",
    "AuthContext",
    "get_auth",
    "require_admin",
    "scoped_items",
]


@dataclass
class AuthContext:
    user: User | None  # None for the service API key
    is_service: bool = False

    @property
    def is_admin(self) -> bool:
        return self.is_service or (self.user is not None and self.user.role == UserRole.ADMIN)


def get_auth(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthContext:
    if x_api_key and x_api_key == get_settings().api_key:
        return AuthContext(user=None, is_service=True)
    if authorization and authorization.lower().startswith("bearer "):
        user_id = decode_token(authorization[7:], expected_type="access")
        if user_id:
            user = db.get(User, user_id)
            if user:
                return AuthContext(user=user)
    raise HTTPException(status_code=401, detail="not authenticated")


def require_admin(auth: AuthContext = Depends(get_auth)) -> AuthContext:
    if not auth.is_admin:
        raise HTTPException(status_code=403, detail="admin access required")
    return auth


def scoped_items(q: Select, auth: AuthContext) -> Select:
    """Restrict a saved_items select to what the caller may see."""
    if auth.is_service:
        return q
    if auth.user.role == UserRole.ADMIN:
        return q.where(or_(SavedItem.user_id == auth.user.id, SavedItem.user_id.is_(None)))
    return q.where(SavedItem.user_id == auth.user.id)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Legacy service-key check; user-facing routes use get_auth instead."""
    if x_api_key != get_settings().api_key:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


@lru_cache
def get_storage() -> S3Storage:
    return S3Storage()


@lru_cache
def get_ai():
    return build_ai_client()


ApiKey = Depends(require_api_key)
