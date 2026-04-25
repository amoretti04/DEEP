"""Health + readiness endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.db import get_session
from services.api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(session: AsyncSession = Depends(get_session)) -> HealthResponse:
    """Liveness + DB reachability check. Used by k8s and the compose stack."""
    db_status = "ok"
    try:
        result = await session.execute(text("SELECT 1"))
        if result.scalar() != 1:
            db_status = "degraded"
    except Exception:  # noqa: BLE001
        db_status = "unreachable"
    return HealthResponse(
        status="ok" if db_status == "ok" else "degraded",
        database=db_status,
    )
