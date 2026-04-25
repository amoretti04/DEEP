"""FastAPI app entry point.

Run locally: ``make api`` (or ``uvicorn services.api.main:app --reload``).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.api.routers import documents, events, health, proceedings, sources, user_settings
from services.api.settings import get_settings

logger = logging.getLogger("dip.api")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format='{"ts":"%(asctime)s","lvl":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
    )
    logger.info("api.startup env=%s", settings.dip_env)
    try:
        yield
    finally:
        logger.info("api.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="DIP API",
        version="0.1.0",
        description="Distressed Investment Intelligence Platform — internal API.",
        lifespan=lifespan,
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url=None,
    )

    origins = [o.strip() for o in settings.api_cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(sources.router)
    app.include_router(events.router)
    app.include_router(proceedings.router)
    app.include_router(documents.router)
    app.include_router(user_settings.router)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"service": "dip-api", "version": "0.1.0", "docs": "/docs"}

    return app


app = create_app()
