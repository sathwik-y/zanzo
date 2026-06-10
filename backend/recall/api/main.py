"""FastAPI application. Run with: uvicorn recall.api.main:app"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from recall.api import routes_actions, routes_admin, routes_items


def create_app() -> FastAPI:
    app = FastAPI(
        title="Zanzo",
        description="Zanzo - the afterimage of everything you scroll. Instagram saved-reels organizer with AI extraction.",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(routes_items.router)
    app.include_router(routes_admin.router)
    app.include_router(routes_actions.router)
    return app


app = create_app()
