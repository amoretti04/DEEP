"""Documents endpoints — read + on-demand translation.

The translate endpoint is gated by the user's ``translation.enabled``
flag. When off, we return 403 rather than silently translating — the
policy is explicit per-user opt-in (ADR-0005).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from infra.alembic.orm import DocumentOrm, UserSettingsOrm
from services.api.db import get_session
from services.api.schemas import (
    DocumentRow,
    TranslateDocumentRequest,
    TranslateDocumentResponse,
    UserSettings,
)
from services.translation.client import TranslationClient, TranslationError

logger = logging.getLogger("dip.api.documents")
router = APIRouter(prefix="/documents", tags=["documents"])


async def _load_user_settings(session: AsyncSession, user_id: str) -> UserSettings:
    """Load settings for the current user, falling back to defaults."""
    row = await session.get(UserSettingsOrm, user_id)
    if row is None or not row.settings:
        return UserSettings()
    try:
        return UserSettings.model_validate(row.settings)
    except Exception:  # noqa: BLE001
        # Settings got corrupted somehow — don't fail the request, fall
        # back to defaults. The next settings write repairs the row.
        logger.warning("user_settings.invalid user=%s — falling back to defaults", user_id)
        return UserSettings()


# Simple header-based auth stub — R7 replaces with OIDC + RBAC.
async def current_user(x_dip_user: str | None = Header(default=None)) -> str:
    return x_dip_user or "anonymous"


@router.get("/{document_pid}", response_model=DocumentRow)
async def get_document(
    document_pid: str,
    session: AsyncSession = Depends(get_session),
) -> DocumentRow:
    """Read a single document (metadata + optional cached translation)."""
    doc = await session.get(DocumentOrm, document_pid)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"document not found: {document_pid}")
    return DocumentRow(
        document_pid=doc.document_pid,
        proceeding_pid=doc.proceeding_pid,
        title=doc.title,
        document_type=doc.document_type,
        url=doc.url,
        raw_object_key=doc.raw_object_key,
        filed_at=doc.filed_at.isoformat() if doc.filed_at else None,
        language_original=doc.language_original,
        page_count=doc.page_count,
        has_translation=bool(doc.text_english),
    )


@router.post("/{document_pid}/translate", response_model=TranslateDocumentResponse)
async def translate_document(
    document_pid: str,
    body: TranslateDocumentRequest = TranslateDocumentRequest(),  # noqa: B008
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(current_user),
) -> TranslateDocumentResponse:
    """On-demand translation. Feature-flag gated per user (ADR-0005).

    Happy path:
      1. Check user's ``translation.enabled`` — 403 if off.
      2. Load document; 404 if missing; 400 if no text to translate.
      3. Hit the translation client (which consults the cache).
      4. Persist the translated text back onto the document row so
         subsequent reads return it without another round-trip.
    """
    settings = await _load_user_settings(session, user_id)
    if not settings.translation.enabled:
        raise HTTPException(
            status_code=403,
            detail=(
                "Translation is disabled in your user settings. "
                "Enable it at Settings → Translation before using this endpoint."
            ),
        )

    doc = await session.get(DocumentOrm, document_pid)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"document not found: {document_pid}")
    if not doc.text_original or not doc.text_original.strip():
        raise HTTPException(
            status_code=400,
            detail=f"document {document_pid} has no original text to translate",
        )
    if not doc.language_original:
        raise HTTPException(
            status_code=400,
            detail=f"document {document_pid} has no language_original set",
        )

    client = TranslationClient()
    try:
        result = await client.translate(
            session=session,
            text=doc.text_original,
            source_language=doc.language_original,
            target_language=body.target_language,
        )
    except TranslationError as e:
        # Service unreachable or errored — distinct from cache-miss; we
        # surface as 502 so the UI can retry later rather than the user
        # thinking their settings are broken.
        logger.warning("translate.service_error doc=%s err=%s", document_pid, e)
        raise HTTPException(status_code=502, detail="translation service unavailable") from e

    # Persist the English text onto the document for future reads —
    # translate once, show instantly forever.
    if body.target_language == "en":
        await session.execute(
            update(DocumentOrm)
            .where(DocumentOrm.document_pid == document_pid)
            .values(text_english=result.translated_text)
        )
        await session.commit()

    return TranslateDocumentResponse(
        document_pid=document_pid,
        source_language=result.source_language,
        target_language=result.target_language,
        translated_text=result.translated_text,
        model_name=result.model_name,
        model_version=result.model_version,
        from_cache=result.from_cache,
        character_count=result.character_count,
    )
