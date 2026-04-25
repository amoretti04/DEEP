"""Initial schema — Release 1 tables.

Revision ID: 0001
Revises:
Create Date: 2026-04-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# ── Alembic identifiers ──────────────────────────────────────────────
revision = "0001"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # ── source ─────────────────────────────────────────────────────
    op.create_table(
        "source",
        sa.Column("source_id", sa.String(120), primary_key=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("workbook_country", sa.String(40), nullable=False),
        sa.Column("workbook_category", sa.String(300)),
        sa.Column("workbook_row", sa.Integer),
        sa.Column("country", sa.String(4), nullable=False),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("tier", sa.Integer, nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("jurisdiction_class", sa.String(40), nullable=False),
        sa.Column("connector", sa.String(40), nullable=False),
        sa.Column("fetch_mode", sa.String(40), nullable=False),
        sa.Column("base_url", sa.String(2048), nullable=False),
        sa.Column("schedule", JSONB, nullable=False),
        sa.Column("politeness", JSONB, nullable=False),
        sa.Column("parser", sa.String(300)),
        sa.Column("legal_review", JSONB, nullable=False),
        sa.Column("owner", sa.String(120), nullable=False, server_default="unassigned"),
        sa.Column("on_failure", JSONB, nullable=False),
        sa.Column("cost_budget_eur_month", sa.Integer),
        sa.Column("release_wave", sa.Integer),
        sa.Column(
            "in_priority_scope",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("notes", sa.Text),
        sa.Column("keyword_pack", JSONB),
        sa.Column("company_info_profile", JSONB),
        sa.Column("document_collection_profile", JSONB),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("tier IN (1, 2, 3)", name="ck_source_tier"),
    )
    op.create_index("ix_source_country_tier", "source", ["country", "tier"])
    op.create_index(
        "ix_source_priority_enabled", "source", ["in_priority_scope", "enabled"]
    )
    op.create_index("ix_source_category", "source", ["category"])

    # ── source_card_version ─────────────────────────────────────────
    op.create_table(
        "source_card_version",
        sa.Column(
            "source_id",
            sa.String(120),
            sa.ForeignKey("source.source_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column("committed_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_by", sa.String(200), nullable=False),
        sa.Column("card", JSONB, nullable=False),
        sa.Column("changelog", sa.Text),
    )

    # ── connector_run ──────────────────────────────────────────────
    op.create_table(
        "connector_run",
        sa.Column("run_id", sa.String(26), primary_key=True),
        sa.Column(
            "source_id",
            sa.String(120),
            sa.ForeignKey("source.source_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("started_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at_utc", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("artifacts_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("records_parsed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("records_quarantined", sa.Integer, nullable=False, server_default="0"),
        sa.Column("records_duplicate", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text),
        sa.Column(
            "triggered_by", sa.String(30), nullable=False, server_default="scheduler"
        ),
        sa.Column("source_card_version", sa.Integer, nullable=False),
    )
    op.create_index("ix_run_source_started", "connector_run", ["source_id", "started_at_utc"])
    op.create_index("ix_run_status", "connector_run", ["status"])

    # ── raw_artifact ───────────────────────────────────────────────
    op.create_table(
        "raw_artifact",
        sa.Column("object_key", sa.String(500), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(26),
            sa.ForeignKey("connector_run.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.String(120),
            sa.ForeignKey("source.source_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_url", sa.String(2048), nullable=False),
        sa.Column("content_type", sa.String(200), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("fetched_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at_local", sa.DateTime(timezone=True)),
        sa.Column("http_status", sa.Integer),
        sa.UniqueConstraint("content_sha256", name="uq_raw_sha"),
    )
    op.create_index("ix_raw_source_fetched", "raw_artifact", ["source_id", "fetched_at_utc"])

    # ── extracted_record ───────────────────────────────────────────
    op.create_table(
        "extracted_record",
        sa.Column("record_uid", sa.String(80), primary_key=True),
        sa.Column("run_id", sa.String(26), nullable=False),
        sa.Column(
            "source_id",
            sa.String(120),
            sa.ForeignKey("source.source_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parser_version", sa.String(80), nullable=False),
        sa.Column("raw_object_key", sa.String(500), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("language", sa.String(10)),
        sa.Column("errors", JSONB, nullable=False, server_default="[]"),
    )
    op.create_index(
        "ix_extracted_source_status", "extracted_record", ["source_id", "status"]
    )

    # ── company ────────────────────────────────────────────────────
    op.create_table(
        "company",
        sa.Column("company_pid", sa.String(26), primary_key=True),
        sa.Column("legal_name", sa.String(500), nullable=False),
        sa.Column("country", sa.String(4), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="active"),
        sa.Column("nace_code", sa.String(12)),
        sa.Column("hq_address", sa.String(500)),
        sa.Column("website", sa.String(2048)),
        sa.Column("date_founded", sa.Date),
        sa.Column("ultimate_parent_pid", sa.String(26)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_company_country_status", "company", ["country", "status"])
    op.create_index("ix_company_legal_name_trgm", "company", ["legal_name"])

    # ── company_identifier ─────────────────────────────────────────
    op.create_table(
        "company_identifier",
        sa.Column(
            "company_pid",
            sa.String(26),
            sa.ForeignKey("company.company_pid", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("scheme", sa.String(30), primary_key=True),
        sa.Column("value", sa.String(64), primary_key=True),
        sa.Column("verified", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.UniqueConstraint("scheme", "value", name="uq_identifier_scheme_value"),
    )

    # ── proceeding ─────────────────────────────────────────────────
    op.create_table(
        "proceeding",
        sa.Column("proceeding_pid", sa.String(26), primary_key=True),
        sa.Column(
            "company_pid",
            sa.String(26),
            sa.ForeignKey("company.company_pid", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("jurisdiction", sa.String(4), nullable=False),
        sa.Column("court_name", sa.String(300)),
        sa.Column("court_case_number", sa.String(120)),
        sa.Column("proceeding_type", sa.String(40), nullable=False),
        sa.Column("proceeding_type_original", sa.String(300), nullable=False),
        sa.Column("administrator_name", sa.String(300)),
        sa.Column("administrator_role", sa.String(100)),
        sa.Column("opened_at", sa.Date),
        sa.Column("closed_at", sa.Date),
        sa.Column("status", sa.String(30), nullable=False, server_default="open"),
    )
    op.create_index("ix_proc_company", "proceeding", ["company_pid"])
    op.create_index("ix_proc_status_opened", "proceeding", ["status", "opened_at"])

    # ── proceeding_event ───────────────────────────────────────────
    op.create_table(
        "proceeding_event",
        sa.Column("event_pid", sa.String(26), primary_key=True),
        sa.Column(
            "proceeding_pid",
            sa.String(26),
            sa.ForeignKey("proceeding.proceeding_pid", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("occurred_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("description_original", sa.Text, nullable=False),
        sa.Column("description_english", sa.Text),
        sa.Column("language_original", sa.String(10)),
        sa.Column("extra", JSONB, nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_event_proc_occurred", "proceeding_event", ["proceeding_pid", "occurred_at_utc"]
    )
    op.create_index(
        "ix_event_type_occurred", "proceeding_event", ["event_type", "occurred_at_utc"]
    )

    # ── source_reference ───────────────────────────────────────────
    op.create_table(
        "source_reference",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("entity_id", sa.String(80), nullable=False),
        sa.Column("record_uid", sa.String(80), nullable=False),
        sa.Column("source_id", sa.String(120), nullable=False),
        sa.Column("envelope", JSONB, nullable=False),
        sa.UniqueConstraint(
            "entity_type", "entity_id", "record_uid", name="uq_srcref_entity_record"
        ),
    )
    op.create_index("ix_srcref_entity", "source_reference", ["entity_type", "entity_id"])
    op.create_index("ix_srcref_source", "source_reference", ["source_id"])

    # ── source_review_queue ────────────────────────────────────────
    op.create_table(
        "source_review_queue",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.String(120), nullable=False),
        sa.Column("reason", sa.String(80), nullable=False),
        sa.Column("detail", JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_note", sa.Text),
    )
    op.create_index(
        "ix_review_unresolved", "source_review_queue", ["resolved_at", "reason"]
    )


def downgrade() -> None:
    for t in (
        "source_review_queue",
        "source_reference",
        "proceeding_event",
        "proceeding",
        "company_identifier",
        "company",
        "extracted_record",
        "raw_artifact",
        "connector_run",
        "source_card_version",
        "source",
    ):
        op.drop_table(t)
