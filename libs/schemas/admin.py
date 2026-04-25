"""User and audit-log schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRole(str, Enum):
    """RBAC roles (CLAUDE.md §3.4, PRD §21)."""

    ANALYST = "analyst"
    LEAD = "lead"
    ADMIN = "admin"
    DPO = "dpo"


class User(BaseModel):
    """Authenticated user (SSO/OIDC upstream)."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    email: EmailStr
    display_name: str = Field(..., min_length=1, max_length=200)
    roles: list[UserRole] = Field(..., min_length=1)
    is_active: bool = True
    created_at_utc: datetime
    last_login_utc: datetime | None = None


class AuditLog(BaseModel):
    """Immutable audit record for data accesses, exports, and admin actions.

    Entries are append-only and hashed with the prior entry's hash to form
    a tamper-evident chain. Hashing is done at persistence time, not here.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    audit_pid: str = Field(..., min_length=26, max_length=26)
    actor_id: str
    action: str = Field(
        ...,
        description=(
            "data_access | export | suppress | merge | unmerge | override_score"
            " | enable_source | disable_source | admin_config | dsar_suppress"
        ),
    )
    entity_type: str = Field(..., min_length=1, max_length=80)
    entity_id: str = Field(..., min_length=1, max_length=200)
    metadata: dict[str, object] = Field(default_factory=dict)
    occurred_at_utc: datetime
