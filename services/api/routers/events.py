"""Event feed — powers the analyst inbox."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.alembic.orm import ProceedingEventOrm
from services.api.db import get_session
from services.api.schemas import EventListResponse, EventRow

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=EventListResponse)
async def list_events(
    session: AsyncSession = Depends(get_session),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> EventListResponse:
    stmt = select(ProceedingEventOrm)
    if event_type:
        stmt = stmt.where(ProceedingEventOrm.event_type == event_type)

    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))

    stmt = stmt.order_by(ProceedingEventOrm.occurred_at_utc.desc())
    stmt = stmt.limit(limit).offset(offset)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    items = [
        EventRow(
            event_pid=r.event_pid,
            proceeding_pid=r.proceeding_pid,
            event_type=r.event_type,
            occurred_at_utc=r.occurred_at_utc,
            description_original=r.description_original,
            description_english=r.description_english,
            language_original=r.language_original,
        )
        for r in rows
    ]
    return EventListResponse(
        items=items, total=int(total or 0), limit=limit, offset=offset
    )
