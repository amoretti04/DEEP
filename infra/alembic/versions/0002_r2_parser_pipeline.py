"""R2 — parser pipeline tables.

Adds:
* parsed_field        — field-level provenance
* proceeding_document — documents attached to a proceeding
* translation_cache   — on-demand translation cache (ADR-0005)
* user_settings       — per-user feature flags + preferences

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision: str | None = "0001"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # ── parsed_field ───────────────────────────────────────────────
    op.create_table(
        "parsed_field",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "record_uid",
            sa.String(80),
            sa.ForeignKey("extracted_record.record_uid", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field_name", sa.String(80), nullable=False),
        sa.Column("value", JSONB),
        sa.Column("raw_text", sa.Text),
        sa.Column("selector", sa.String(500), nullable=False),
        sa.Column("start_offset", sa.Integer),
        sa.Column("end_offset", sa.Integer),
        sa.Column("raw_length", sa.Integer),
        sa.Column("transforms", JSONB, nullable=False, server_default="[]"),
        sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"),
        sa.Column(
            "pii_tag",
            sa.String(30),
            nullable=False,
            server_default="non_personal",
        ),
        sa.Column("override_value", JSONB),
        sa.Column("overridden_at", sa.DateTime(timezone=True)),
        sa.Column("overridden_by", sa.String(200)),
        sa.UniqueConstraint("record_uid", "field_name", name="uq_parsed_field"),
    )
    op.create_index("ix_parsed_field_record", "parsed_field", ["record_uid"])
    op.create_index(
        "ix_parsed_field_name", "parsed_field", ["record_uid", "field_name"]
    )

    # ── proceeding_document ────────────────────────────────────────
    op.create_table(
        "proceeding_document",
        sa.Column("document_pid", sa.String(26), primary_key=True),
        sa.Column(
            "proceeding_pid",
            sa.String(26),
            sa.ForeignKey("proceeding.proceeding_pid", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column(
            "document_type", sa.String(50), nullable=False, server_default="other"
        ),
        sa.Column("url", sa.String(2048)),
        sa.Column("raw_object_key", sa.String(500)),
        sa.Column("filed_at", sa.Date),
        sa.Column("language_original", sa.String(10)),
        sa.Column("text_original", sa.Text),
        sa.Column("text_english", sa.Text),
        sa.Column("page_count", sa.Integer),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_document_proceeding", "proceeding_document", ["proceeding_pid"]
    )

    # ── translation_cache ──────────────────────────────────────────
    op.create_table(
        "translation_cache",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("source_language", sa.String(10), nullable=False),
        sa.Column("target_language", sa.String(10), nullable=False),
        sa.Column("translated_text", sa.Text, nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("model_version", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Float),
        sa.Column("character_count", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("use_count", sa.Integer, nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "source_sha256", "target_language", name="uq_translation_source_target"
        ),
    )
    op.create_index(
        "ix_translation_last_used", "translation_cache", ["last_used_at"]
    )

    # ── user_settings ──────────────────────────────────────────────
    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.String(120), primary_key=True),
        sa.Column("settings", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    for t in ("user_settings", "translation_cache", "proceeding_document", "parsed_field"):
        op.drop_table(t)
