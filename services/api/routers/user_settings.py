"""User settings endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from infra.alembic.orm import UserSettingsOrm
from services.api.db import get_session
from services.api.routers.documents import current_user
from services.api.schemas import UserSettings, UserSettingsResponse

router = APIRouter(prefix="/settings", tags=["settings"])


def _upsert_settings_stmt(session: AsyncSession, row_values: dict[str, object]) -> object:
    """Dialect-aware upsert (handles both Postgres and the SQLite test harness)."""
    dialect = session.bind.dialect.name if session.bind else "postgresql"
    if dialect == "sqlite":
        stmt = sqlite_insert(UserSettingsOrm).values(**row_values)
        return stmt.on_conflict_do_update(
            index_elements=[UserSettingsOrm.user_id],
            set_={k: v for k, v in row_values.items() if k != "user_id"},
        )
    stmt = pg_insert(UserSettingsOrm).values(**row_values)
    return stmt.on_conflict_do_update(
        index_elements=[UserSettingsOrm.user_id],
        set_={k: v for k, v in row_values.items() if k != "user_id"},
    )


@router.get("", response_model=UserSettingsResponse)
async def get_settings(
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(current_user),
) -> UserSettingsResponse:
    row = await session.get(UserSettingsOrm, user_id)
    if row is None:
        return UserSettingsResponse(
            user_id=user_id,
            settings=UserSettings(),
            updated_at=datetime.now(UTC),
        )
    try:
        parsed = UserSettings.model_validate(row.settings or {})
    except Exception:  # noqa: BLE001
        parsed = UserSettings()  # corrupted → defaults; next write fixes it
    return UserSettingsResponse(
        user_id=user_id, settings=parsed, updated_at=row.updated_at
    )


@router.put("", response_model=UserSettingsResponse)
async def update_settings(
    body: UserSettings,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(current_user),
) -> UserSettingsResponse:
    row_values = {
        "user_id": user_id,
        "settings": body.model_dump(mode="json"),
        "updated_at": datetime.now(UTC),
    }
    stmt = _upsert_settings_stmt(session, row_values)
    await session.execute(stmt)
    await session.commit()
    return UserSettingsResponse(
        user_id=user_id, settings=body, updated_at=row_values["updated_at"]  # type: ignore[arg-type]
    )
