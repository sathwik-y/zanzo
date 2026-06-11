"""Password hashing and JWT issuance/validation for the multi-user API."""
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from recall.config import get_settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def _encode(user_id: uuid.UUID, token_type: str, ttl: timedelta) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "iat": now,
        "exp": now + ttl,
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, get_settings().jwt_secret, algorithm=ALGORITHM)


def create_access_token(user_id: uuid.UUID) -> str:
    return _encode(user_id, "access", timedelta(minutes=get_settings().jwt_access_ttl_minutes))


def create_refresh_token(user_id: uuid.UUID) -> str:
    return _encode(user_id, "refresh", timedelta(days=get_settings().jwt_refresh_ttl_days))


def decode_token(token: str, expected_type: str = "access") -> uuid.UUID | None:
    """Returns the user id, or None for any invalid/expired/wrong-type token."""
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != expected_type:
        return None
    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        return None


def generate_ig_verification_code() -> str:
    """Short, unambiguous code the user DMs to the bot account."""
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L
    return "".join(secrets.choice(alphabet) for _ in range(6))
