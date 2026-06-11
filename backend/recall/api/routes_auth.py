"""Signup, login, token refresh, profile, and Instagram account linking.

Instagram linking flow:
1. POST /auth/instagram/link with the user's IG username → a short code is
   generated (expires in ~30 min). The dashboard shows it.
2. The user DMs ``ZANZO <code>`` to the bot account *from that IG account*.
3. The poller sees the text message, matches the code, and binds the sender's
   stable numeric pk to the user (``ig_user_pk``). From then on every reel that
   account DMs to the bot is ingested into this user's library — even if they
   later rename their IG handle.
"""
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from recall.api.deps import AuthContext, get_auth, get_db
from recall.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_ig_verification_code,
    hash_password,
    verify_password,
)
from recall.config import get_settings
from recall.models import User, UserRole, utcnow

router = APIRouter(prefix="/auth", tags=["auth"])


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=80)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID | None = None
    email: str
    display_name: str | None
    role: str
    ig_username: str | None
    ig_verified: bool
    created_at: datetime


class IgLinkStatus(BaseModel):
    ig_username: str | None
    ig_verified: bool
    pending_code: str | None = None
    code_expires_at: datetime | None = None
    bot_username: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


class IgLinkRequest(BaseModel):
    ig_username: str = Field(min_length=1, max_length=64)


def _user_out(user: User) -> UserOut:
    return UserOut.model_validate(user)


def _tokens(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        user=_user_out(user),
    )


def _admin_emails() -> set[str]:
    return {e.strip().lower() for e in get_settings().admin_emails.split(",") if e.strip()}


@router.post("/signup", response_model=TokenResponse, status_code=201)
def signup(body: SignupRequest, db: Session = Depends(get_db)):
    if not get_settings().allow_signup:
        raise HTTPException(status_code=403, detail="signups are disabled on this instance")
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="an account with this email already exists")

    # First account ever, or an email on the admin list, becomes ADMIN.
    is_first = (db.scalar(select(func.count()).select_from(User)) or 0) == 0
    role = UserRole.ADMIN if (is_first or email in _admin_emails()) else UserRole.USER

    user = User(
        email=email,
        password_hash=hash_password(body.password),
        display_name=body.display_name or email.split("@")[0],
        role=role,
        last_login_at=utcnow(),
    )
    db.add(user)
    db.commit()
    return _tokens(user)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid email or password")
    # Late promotion: the admin list may have changed since signup.
    if user.email in _admin_emails() and user.role != UserRole.ADMIN:
        user.role = UserRole.ADMIN
    user.last_login_at = utcnow()
    db.commit()
    return _tokens(user)


@router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)):
    user_id = decode_token(body.refresh_token, expected_type="refresh")
    if user_id is None:
        raise HTTPException(status_code=401, detail="invalid or expired refresh token")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="account no longer exists")
    return _tokens(user)


@router.get("/me", response_model=UserOut)
def me(auth: AuthContext = Depends(get_auth)):
    if auth.user is None:  # service API key
        return UserOut(
            email="service@local",
            display_name="Service",
            role=UserRole.ADMIN,
            ig_username=None,
            ig_verified=False,
            created_at=datetime.now(UTC),
        )
    return _user_out(auth.user)


def _require_user(auth: AuthContext) -> User:
    if auth.user is None:
        raise HTTPException(status_code=400, detail="this endpoint needs a user account token")
    return auth.user


@router.get("/instagram/link", response_model=IgLinkStatus)
def ig_link_status(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    user = _require_user(auth)
    pending = (
        user.ig_verification_code
        if user.ig_verification_expires_at
        and user.ig_verification_expires_at > datetime.now(UTC)
        and not user.ig_verified
        else None
    )
    return IgLinkStatus(
        ig_username=user.ig_username,
        ig_verified=user.ig_verified,
        pending_code=pending,
        code_expires_at=user.ig_verification_expires_at if pending else None,
        bot_username=get_settings().ig_username or None,
    )


@router.post("/instagram/link", response_model=IgLinkStatus)
def ig_link(body: IgLinkRequest, auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    user = _require_user(auth)
    settings = get_settings()
    user.ig_username = body.ig_username.lstrip("@").lower()
    user.ig_verified = False
    user.ig_user_pk = None
    user.ig_verification_code = generate_ig_verification_code()
    user.ig_verification_expires_at = datetime.now(UTC) + timedelta(
        minutes=settings.ig_verification_ttl_minutes
    )
    db.commit()
    return ig_link_status(auth, db)


@router.delete("/instagram/link", response_model=IgLinkStatus)
def ig_unlink(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    user = _require_user(auth)
    user.ig_username = None
    user.ig_user_pk = None
    user.ig_verified = False
    user.ig_verification_code = None
    user.ig_verification_expires_at = None
    db.commit()
    return ig_link_status(auth, db)
