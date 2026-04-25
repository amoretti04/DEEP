"""The normalizer: ParsedRecord → canonical Postgres rows.

The entry point is :meth:`Normalizer.normalize`. Given a session and a
``ParsedRecord`` (plus the matching ``ParseContext`` for provenance),
it upserts the full set of canonical rows and returns a
:class:`NormalizedOutput` summarizing what changed.

Design notes:

* **Natural keys drive idempotency.** A repeated ``record_uid`` for the
  same ``(entity_type, entity_id)`` does nothing (the unique constraint
  on ``source_reference`` catches it). Re-running the pipeline N times
  produces exactly one row each.
* **Company resolution is minimal in R3.** We look up by the tuple
  ``(jurisdiction, strongest_available_id)`` where the ID order is
  ``codice_fiscale > piva > siren > kvk > rsin > nif_cif > hrb_number_numeric``
  (mirrors PRD §12's entity-resolution order, minus the LEI lookup
  which requires an external lookup). If nothing matches, we create a
  new Company. This intentionally under-merges rather than over-merges:
  false splits are recoverable via the analyst merge tool (R5); false
  merges aren't.
* **Proceeding deduplication by ``(jurisdiction, court_case_number)``.**
  Two parsers reporting the same case → one Proceeding row, two
  SourceReferences. Missing case_number → new Proceeding each time
  (caller's responsibility to ensure one is present).
* **Events are per-record.** Each ParsedRecord produces exactly one
  ProceedingEvent — the event "observed by parser X at time T" — and
  its event_pid is a deterministic ULID from the record_uid so re-runs
  are stable.
* **Field-level provenance is always written.** Every ``FieldProvenance``
  from the parser becomes one ``parsed_field`` row.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from infra.alembic.orm import (
    CompanyIdentifierOrm,
    CompanyOrm,
    ParsedFieldOrm,
    ProceedingEventOrm,
    ProceedingOrm,
    SourceReferenceOrm,
)
from libs.provenance import new_ulid
from services.extract.framework.base import ParseContext, ParsedRecord

logger = logging.getLogger("dip.normalize")


# Order in which we look up companies by external identifier. More-specific
# identifiers first — a codice_fiscale mismatch is stronger evidence than a
# SIREN match in a different jurisdiction.
_ID_SCHEME_ORDER: list[tuple[str, str]] = [
    # (field name in ParsedRecord, identifier scheme tag)
    ("codice_fiscale", "codice_fiscale"),
    ("piva", "vat"),
    ("debtor_siren", "siren"),
    ("kvk_number", "kvk"),
    ("rsin", "rsin"),
    ("debtor_nif_cif", "nif_cif"),
    ("hrb_number_numeric", "hrb"),
]


@dataclass
class NormalizedOutput:
    """What the normalizer produced — for tests and metrics."""

    company_pid: str
    proceeding_pid: str
    event_pid: str
    source_ref_new: bool
    parsed_fields_written: int
    company_created: bool
    proceeding_created: bool
    # Set when the normalizer skipped the whole record because the
    # ``record_uid`` was already processed. In that case the pids above
    # point to the pre-existing rows.
    skipped_duplicate_record: bool = False


class Normalizer:
    """Stateless normalizer — all state lives in the session it's given."""

    async def normalize(
        self,
        session: AsyncSession,
        parsed: ParsedRecord,
        ctx: ParseContext,
    ) -> NormalizedOutput:
        """Upsert the full canonical graph for one ``ParsedRecord``.

        Raises ``ValueError`` if the parsed record is missing fields the
        canonical schema treats as not-null (debtor_name, proceeding_type,
        jurisdiction, opened_at). Those are invariants every reference
        parser already satisfies; catching them here gives a clear error
        path for new parsers that haven't been selector-verified.
        """
        # 0. Short-circuit on a repeated record_uid for the same entity.
        #    We check the source_reference table: if a row exists with
        #    this (record_uid) on a proceeding, we return pointing at
        #    that existing graph without creating anything new.
        existing_refs = (
            await session.execute(
                select(SourceReferenceOrm).where(
                    SourceReferenceOrm.record_uid == ctx.envelope.record_uid,
                    SourceReferenceOrm.entity_type == "proceeding",
                )
            )
        ).scalars().all()
        if existing_refs:
            prior_proc_pid = existing_refs[0].entity_id
            prior_proc = await session.get(ProceedingOrm, prior_proc_pid)
            if prior_proc is None:
                raise RuntimeError(
                    f"dangling source_reference: record_uid={ctx.envelope.record_uid} "
                    f"→ proceeding_pid={prior_proc_pid} but proceeding row is missing"
                )
            return NormalizedOutput(
                company_pid=prior_proc.company_pid,
                proceeding_pid=prior_proc_pid,
                event_pid="(not created, idempotent short-circuit)",
                source_ref_new=False,
                parsed_fields_written=0,
                company_created=False,
                proceeding_created=False,
                skipped_duplicate_record=True,
            )

        self._validate_invariants(parsed)

        # 1. Company — find or create.
        company_pid, company_created = await self._upsert_company(session, parsed)

        # 2. Proceeding — find by (jurisdiction, court_case_number) or create.
        proceeding_pid, proceeding_created = await self._upsert_proceeding(
            session, parsed, company_pid
        )

        # 3. Event — one per parsed record, deterministic pid from record_uid.
        event_pid = await self._insert_event(session, parsed, proceeding_pid, ctx)

        # 4. SourceReferences — proceeding + event.
        source_ref_new = await self._insert_source_refs(
            session, proceeding_pid, event_pid, ctx
        )

        # 5. Field-level provenance for this record.
        parsed_fields_written = await self._insert_parsed_fields(session, parsed, ctx)

        await session.commit()

        return NormalizedOutput(
            company_pid=company_pid,
            proceeding_pid=proceeding_pid,
            event_pid=event_pid,
            source_ref_new=source_ref_new,
            parsed_fields_written=parsed_fields_written,
            company_created=company_created,
            proceeding_created=proceeding_created,
        )

    # ── Steps ──────────────────────────────────────────────────────
    @staticmethod
    def _validate_invariants(parsed: ParsedRecord) -> None:
        missing = [
            k for k in ("debtor_name", "proceeding_type", "jurisdiction", "opened_at")
            if k not in parsed.fields or parsed.fields[k] in (None, "")
        ]
        if missing:
            raise ValueError(
                f"normalizer invariants: ParsedRecord missing required canonical "
                f"fields {missing}. Parser {parsed.natural_key!r} must provide them."
            )

    async def _upsert_company(
        self, session: AsyncSession, parsed: ParsedRecord
    ) -> tuple[str, bool]:
        """Find company by external ID, else create new."""
        jurisdiction = parsed.fields["jurisdiction"]

        # 1a. Try to resolve by external identifier, in specificity order.
        for record_field, scheme in _ID_SCHEME_ORDER:
            value = parsed.fields.get(record_field)
            if not value:
                continue
            stmt = (
                select(CompanyIdentifierOrm)
                .where(
                    CompanyIdentifierOrm.scheme == scheme,
                    CompanyIdentifierOrm.value == str(value),
                )
                .limit(1)
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing is not None:
                return existing.company_pid, False

        # 1b. Fall through: create a new company + register any IDs we saw.
        company_pid = new_ulid()
        session.add(
            CompanyOrm(
                company_pid=company_pid,
                legal_name=parsed.fields["debtor_name"],
                country=jurisdiction,
                status="in_proceeding",
            )
        )
        await session.flush()  # emit INSERT so the company_pid FK is live

        for record_field, scheme in _ID_SCHEME_ORDER:
            value = parsed.fields.get(record_field)
            if value:
                session.add(
                    CompanyIdentifierOrm(
                        company_pid=company_pid,
                        scheme=scheme,
                        value=str(value),
                    )
                )
        return company_pid, True

    async def _upsert_proceeding(
        self, session: AsyncSession, parsed: ParsedRecord, company_pid: str
    ) -> tuple[str, bool]:
        """Find proceeding by (jurisdiction, court_case_number) or create."""
        jurisdiction = parsed.fields["jurisdiction"]
        case_number = parsed.fields.get("court_case_number") or parsed.fields.get("case_number")

        if case_number:
            stmt = (
                select(ProceedingOrm)
                .where(
                    ProceedingOrm.jurisdiction == jurisdiction,
                    ProceedingOrm.court_case_number == str(case_number),
                )
                .limit(1)
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing is not None:
                return existing.proceeding_pid, False

        proceeding_pid = new_ulid()
        session.add(
            ProceedingOrm(
                proceeding_pid=proceeding_pid,
                company_pid=company_pid,
                jurisdiction=jurisdiction,
                court_name=parsed.fields.get("court_name"),
                court_case_number=str(case_number) if case_number else None,
                proceeding_type=parsed.fields["proceeding_type"],
                proceeding_type_original=parsed.fields.get(
                    "proceeding_type_original", parsed.fields["proceeding_type"]
                ),
                administrator_name=parsed.fields.get("administrator_name"),
                administrator_role=parsed.fields.get("administrator_role"),
                opened_at=_coerce_date(parsed.fields.get("opened_at")),
                closed_at=_coerce_date(parsed.fields.get("closed_at")),
                status="open",
            )
        )
        await session.flush()
        return proceeding_pid, True

    async def _insert_event(
        self,
        session: AsyncSession,
        parsed: ParsedRecord,
        proceeding_pid: str,
        ctx: ParseContext,
    ) -> str:
        """Write exactly one event per parsed record, deterministic pid."""
        event_pid = _deterministic_pid("event", ctx.envelope.record_uid)

        # If an event with this pid already exists, return it (shouldn't
        # happen given the record_uid short-circuit at the top, but
        # belt-and-braces).
        existing = await session.get(ProceedingEventOrm, event_pid)
        if existing is not None:
            return event_pid

        session.add(
            ProceedingEventOrm(
                event_pid=event_pid,
                proceeding_pid=proceeding_pid,
                event_type=_infer_event_type(parsed),
                occurred_at_utc=_derive_occurred_at(parsed, ctx),
                description_original=_derive_description(parsed),
                description_english=None,
                language_original=parsed.language,
                extra={
                    "parser_version": ctx.parser_version,
                    "confidence": parsed.confidence,
                },
            )
        )
        await session.flush()
        return event_pid

    async def _insert_source_refs(
        self,
        session: AsyncSession,
        proceeding_pid: str,
        event_pid: str,
        ctx: ParseContext,
    ) -> bool:
        """Insert source_references for (proceeding, event). Returns True if new."""
        envelope_json = ctx.envelope.model_dump(mode="json")

        dialect = session.bind.dialect.name if session.bind else "postgresql"
        insert = sqlite_insert if dialect == "sqlite" else pg_insert

        any_new = False
        for entity_type, entity_id in (("proceeding", proceeding_pid), ("event", event_pid)):
            row = {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "record_uid": ctx.envelope.record_uid,
                "source_id": ctx.envelope.source_id,
                "envelope": envelope_json,
            }
            stmt = insert(SourceReferenceOrm).values(**row).on_conflict_do_nothing(
                index_elements=["entity_type", "entity_id", "record_uid"],
            )
            result = await session.execute(stmt)
            if result.rowcount and result.rowcount > 0:
                any_new = True
        return any_new

    async def _insert_parsed_fields(
        self,
        session: AsyncSession,
        parsed: ParsedRecord,
        ctx: ParseContext,
    ) -> int:
        """Persist FieldProvenance rows. Re-entry-safe via uq_parsed_field."""
        dialect = session.bind.dialect.name if session.bind else "postgresql"
        insert = sqlite_insert if dialect == "sqlite" else pg_insert

        written = 0
        for name, prov in parsed.field_provenance.items():
            value = parsed.fields.get(name)
            row = {
                "record_uid": ctx.envelope.record_uid,
                "field_name": name,
                "value": {"v": _serializable(value)} if value is not None else None,
                "raw_text": None,  # framework doesn't thread raw text through yet
                "selector": prov.selector,
                "start_offset": prov.start_offset,
                "end_offset": prov.end_offset,
                "raw_length": prov.raw_length,
                "transforms": list(prov.transforms),
                "confidence": prov.confidence,
                "pii_tag": "non_personal",  # set by the PIITag in config, defaulted here
            }
            stmt = (
                insert(ParsedFieldOrm)
                .values(**row)
                .on_conflict_do_nothing(index_elements=["record_uid", "field_name"])
            )
            result = await session.execute(stmt)
            if result.rowcount and result.rowcount > 0:
                written += 1
        return written


# ── Helpers ──────────────────────────────────────────────────────────
def _deterministic_pid(prefix: str, record_uid: str) -> str:
    """Make an event_pid deterministic from the record_uid so re-runs are stable.

    Re-runs of the same parser over the same raw artifact must produce
    the same event_pid, otherwise idempotency falls apart. We hash the
    prefix + record_uid and format as a ULID-shaped 26-char uppercase
    alphanumeric string. Not a real ULID (no time component), but it
    fits in the String(26) primary key and is deterministic.
    """
    digest = hashlib.sha256((prefix + ":" + record_uid).encode()).digest()
    # Crockford base32-style alphabet (no I/L/O/U), 26 chars.
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    n = int.from_bytes(digest[:16], "big")
    chars: list[str] = []
    for _ in range(26):
        chars.append(alphabet[n & 0x1F])
        n >>= 5
    return "".join(reversed(chars))


def _coerce_date(v: Any) -> Any:
    """Passthrough for None/date, isoformat-parse for strings."""
    if v is None:
        return None
    if hasattr(v, "isoformat") and not isinstance(v, str):
        # date or datetime
        if hasattr(v, "date") and callable(v.date):
            return v.date() if isinstance(v, datetime) else v
        return v
    if isinstance(v, str):
        from datetime import date as _date
        try:
            return _date.fromisoformat(v)
        except ValueError:
            return None
    return None


def _infer_event_type(parsed: ParsedRecord) -> str:
    """Map proceeding_type + stage hints to a canonical event_type.

    Kept minimal in R3: the most important distinction is filing vs.
    liquidation-announcement, with a fallback of 'proceeding_update' so
    nothing ends up event-type-less. R4 can refine as the scoring layer
    adds stage-awareness.
    """
    ptype = parsed.fields.get("proceeding_type", "UNKNOWN")
    if ptype == "LIQUIDATION":
        return "liquidation_announced"
    if ptype in ("REORGANIZATION", "MORATORIUM"):
        return "bankruptcy_filing"
    if ptype == "RECEIVERSHIP":
        return "receivership_opened"
    return "proceeding_update"


def _derive_occurred_at(parsed: ParsedRecord, ctx: ParseContext) -> datetime:
    """Prefer opened_at from the parsed record; fall back to fetched_at."""
    from datetime import date as _date

    opened = parsed.fields.get("opened_at")
    if isinstance(opened, datetime):
        return opened if opened.tzinfo else opened.replace(tzinfo=UTC)
    if isinstance(opened, _date):
        return datetime(opened.year, opened.month, opened.day, tzinfo=UTC)
    return ctx.envelope.fetched_at_utc


def _derive_description(parsed: ParsedRecord) -> str:
    """Short human-readable summary. UI can still pull richer text from the raw artifact."""
    name = parsed.fields.get("debtor_name", "(unknown debtor)")
    ptype = parsed.fields.get("proceeding_type_original") or parsed.fields.get("proceeding_type", "")
    court = parsed.fields.get("court_name", "")
    case = parsed.fields.get("court_case_number") or parsed.fields.get("case_number", "")
    pieces = [name, ptype]
    if court:
        pieces.append(court)
    if case:
        pieces.append(f"case {case}")
    return " — ".join(str(p) for p in pieces if p)


def _serializable(v: Any) -> Any:
    """Convert datetime/date/Decimal to JSONable primitives for the JSONB column."""
    from datetime import date as _date
    from decimal import Decimal

    if v is None or isinstance(v, (bool, int, float, str, list, dict)):
        return v
    if isinstance(v, (datetime, _date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    return str(v)
