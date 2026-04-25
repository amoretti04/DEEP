"""Source registry endpoints.

Read-only in R1. Source Card edits go through PR workflow, not the API.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.alembic.orm import SourceOrm
from services.api.db import get_session
from services.api.schemas import (
    CountsByDimension,
    SourceListResponse,
    SourceSummary,
)

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=SourceListResponse)
async def list_sources(
    session: AsyncSession = Depends(get_session),
    country: str | None = Query(default=None, description="ISO country code, e.g. 'IT'"),
    tier: int | None = Query(default=None, ge=1, le=3),
    category: str | None = Query(default=None),
    in_priority_scope: bool | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    q: str | None = Query(
        default=None, max_length=120, description="Substring search on name"
    ),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> SourceListResponse:
    stmt = select(SourceOrm)
    if country:
        stmt = stmt.where(SourceOrm.country == country.upper())
    if tier is not None:
        stmt = stmt.where(SourceOrm.tier == tier)
    if category:
        stmt = stmt.where(SourceOrm.category == category.upper())
    if in_priority_scope is not None:
        stmt = stmt.where(SourceOrm.in_priority_scope.is_(in_priority_scope))
    if enabled is not None:
        stmt = stmt.where(SourceOrm.enabled.is_(enabled))
    if q:
        stmt = stmt.where(SourceOrm.name.ilike(f"%{q}%"))

    # Total count (without limit/offset)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))

    stmt = stmt.order_by(SourceOrm.tier, SourceOrm.country, SourceOrm.name)
    stmt = stmt.limit(limit).offset(offset)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    items = [SourceSummary.from_orm_row(r) for r in rows]
    return SourceListResponse(
        items=items, total=int(total or 0), limit=limit, offset=offset
    )


@router.get("/counts", response_model=CountsByDimension)
async def source_counts(
    session: AsyncSession = Depends(get_session),
) -> CountsByDimension:
    """Aggregate counts for the dashboard."""
    counts = CountsByDimension()

    # Total
    counts.total = int(
        (await session.scalar(select(func.count()).select_from(SourceOrm))) or 0
    )

    counts.in_priority_scope = int(
        (
            await session.scalar(
                select(func.count())
                .select_from(SourceOrm)
                .where(SourceOrm.in_priority_scope.is_(True))
            )
        )
        or 0
    )
    counts.enabled = int(
        (
            await session.scalar(
                select(func.count())
                .select_from(SourceOrm)
                .where(SourceOrm.enabled.is_(True))
            )
        )
        or 0
    )

    for col, bucket in (
        (SourceOrm.country, counts.by_country),
        (SourceOrm.tier, counts.by_tier),
        (SourceOrm.category, counts.by_category),
        (SourceOrm.jurisdiction_class, counts.by_jurisdiction_class),
    ):
        rows = (
            await session.execute(
                select(col, func.count()).group_by(col).order_by(func.count().desc())
            )
        ).all()
        for key, n in rows:
            bucket[str(key)] = int(n)

    return counts


@router.get("/{source_id}", response_model=SourceSummary)
async def get_source(
    source_id: str,
    session: AsyncSession = Depends(get_session),
) -> SourceSummary:
    row = await session.get(SourceOrm, source_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"source not found: {source_id}")
    return SourceSummary.from_orm_row(row)
