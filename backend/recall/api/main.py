"""FastAPI application. Run with: uvicorn recall.api.main:app"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from recall.api import routes_actions, routes_admin, routes_auth, routes_items
from recall.config import get_settings

logger = logging.getLogger(__name__)


def _warn_on_default_secrets() -> None:
    settings = get_settings()
    if settings.api_key == "change-me":
        logger.warning(
            "API_KEY is the default 'change-me' — anyone who reads the docs has "
            "admin-equivalent service access. Set a real value before going public."
        )
    if settings.jwt_secret == "change-me-in-production":
        logger.warning(
            "JWT_SECRET is the default value — session tokens are forgeable. "
            "Set a real value (openssl rand -hex 32) before going public."
        )


def create_app() -> FastAPI:
    app = FastAPI(
        title="Zanzo",
        description="Zanzo - the afterimage of everything you scroll. Instagram saved-reels organizer with AI extraction.",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[get_settings().frontend_origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(routes_auth.router)
    app.include_router(routes_items.router)
    app.include_router(routes_admin.router)
    app.include_router(routes_actions.router)
    _warn_on_default_secrets()
    return app


app = create_app()
