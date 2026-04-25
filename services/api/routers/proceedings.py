"""Proceedings detail endpoint.

Returns a proceeding with its events, documents, and source references —
the analyst's single-pane view per case.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.alembic.orm import (
    DocumentOrm,
    ProceedingEventOrm,
    ProceedingOrm,
    SourceReferenceOrm,
)
from services.api.db import get_session
from services.api.schemas import (
    DocumentRow,
    ProceedingDetailResponse,
    ProceedingEventWithContext,
    SourceReferenceRow,
)

router = APIRouter(prefix="/proceedings", tags=["proceedings"])


@router.get("/{proceeding_pid}", response_model=ProceedingDetailResponse)
async def get_proceeding(
    proceeding_pid: str,
    session: AsyncSession = Depends(get_session),
) -> ProceedingDetailResponse:
    """Return one proceeding with all linked events, documents, and source refs."""
    proc = await session.get(ProceedingOrm, proceeding_pid)
    if proc is None:
        raise HTTPException(status_code=404, detail=f"proceeding not found: {proceeding_pid}")

    events_rows = (
        await session.execute(
            select(ProceedingEventOrm)
            .where(ProceedingEventOrm.proceeding_pid == proceeding_pid)
            .order_by(ProceedingEventOrm.occurred_at_utc.asc())
        )
    ).scalars().all()

    docs_rows = (
        await session.execute(
            select(DocumentOrm)
            .where(DocumentOrm.proceeding_pid == proceeding_pid)
            .order_by(DocumentOrm.filed_at.asc().nulls_last())
        )
    ).scalars().all()

    # Source refs: union of refs pointing at the proceeding + each event.
    entity_ids = [proceeding_pid, *[e.event_pid for e in events_rows]]
    refs_rows = (
        await session.execute(
            select(SourceReferenceOrm)
            .where(SourceReferenceOrm.entity_id.in_(entity_ids))
            .order_by(SourceReferenceOrm.id.asc())
        )
    ).scalars().all()

    def _env_to_row(r: SourceReferenceOrm) -> SourceReferenceRow:
        env = r.envelope or {}
        return SourceReferenceRow(
            record_uid=r.record_uid,
            source_id=r.source_id,
            source_url=str(env.get("source_url", "")),
            fetched_at_utc=env.get("fetched_at_utc"),  # type: ignore[arg-type]
            parser_version=str(env.get("parser_version", "unknown")),
            raw_object_key=str(env.get("raw_object_key", "")),
        )

    return ProceedingDetailResponse(
        proceeding_pid=proc.proceeding_pid,
        company_pid=proc.company_pid,
        jurisdiction=proc.jurisdiction,
        court_name=proc.court_name,
        court_case_number=proc.court_case_number,
        proceeding_type=proc.proceeding_type,
        proceeding_type_original=proc.proceeding_type_original,
        administrator_name=proc.administrator_name,
        administrator_role=proc.administrator_role,
        opened_at=proc.opened_at.isoformat() if proc.opened_at else None,
        closed_at=proc.closed_at.isoformat() if proc.closed_at else None,
        status=proc.status,
        events=[
            ProceedingEventWithContext(
                event_pid=e.event_pid,
                event_type=e.event_type,
                occurred_at_utc=e.occurred_at_utc,
                description_original=e.description_original,
                description_english=e.description_english,
                language_original=e.language_original,
            )
            for e in events_rows
        ],
        documents=[
            DocumentRow(
                document_pid=d.document_pid,
                proceeding_pid=d.proceeding_pid,
                title=d.title,
                document_type=d.document_type,
                url=d.url,
                raw_object_key=d.raw_object_key,
                filed_at=d.filed_at.isoformat() if d.filed_at else None,
                language_original=d.language_original,
                page_count=d.page_count,
                has_translation=bool(d.text_english),
            )
            for d in docs_rows
        ],
        source_references=[_env_to_row(r) for r in refs_rows],
    )
