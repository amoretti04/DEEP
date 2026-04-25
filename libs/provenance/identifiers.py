"""Deterministic identifier helpers.

The PRD §16.2 and CLAUDE.md §4.1 both require idempotent upserts. We achieve
that by deriving a ``record_uid`` from fields that are *stable across time
and across re-fetches* of the same underlying event:

    sha256(source_id | stable_natural_key | published_at_utc)

``stable_natural_key`` is whatever the source treats as its primary handle
for the record: a gazette notice number, a tribunal case number, an auction
lot id. Parsers are responsible for choosing it deterministically — if the
source has no stable key, the parser constructs one from ``(court, debtor,
event_type, event_date)`` and the choice is documented in the Source Card.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import ulid


def new_ulid() -> str:
    """Generate a fresh ULID (Crockford base32, 26 chars).

    ULIDs sort chronologically, making them friendlier than UUIDv4 for
    time-based browsing of rows in the DB.
    """
    return str(ulid.new())


def new_extractor_run_id() -> str:
    """One ULID per extractor invocation. Used to group all records a
    single run produced — useful for cohort rollbacks."""
    return new_ulid()


def record_uid(
    source_id: str,
    stable_natural_key: str,
    published_at_utc: datetime | None,
) -> str:
    """Compute the deterministic record_uid for a canonical record.

    Args:
        source_id: Kebab-case source identifier from the Source Card.
        stable_natural_key: Primary handle the source assigns the record.
            Must be consistent across re-fetches of the same logical item.
        published_at_utc: UTC publication timestamp. ``None`` allowed for
            sources that don't emit a publication timestamp (then we
            guarantee uniqueness via the natural key alone).

    Returns:
        A ``sha256:<hex>`` string prefixed so callers can tell at a glance
        that this is a content-addressed identifier.
    """
    if not source_id:
        raise ValueError("record_uid: source_id must be non-empty")
    if not stable_natural_key:
        raise ValueError("record_uid: stable_natural_key must be non-empty")

    if published_at_utc is not None and published_at_utc.tzinfo is None:
        raise ValueError(
            "record_uid: published_at_utc must be timezone-aware"
        )

    published_part = (
        published_at_utc.astimezone(UTC).isoformat() if published_at_utc else ""
    )
    raw = f"{source_id}|{stable_natural_key}|{published_part}".encode()
    digest = hashlib.sha256(raw).hexdigest()
    return f"sha256:{digest}"


def compute_raw_sha256(payload: bytes) -> str:
    """Content hash of a raw payload. Used for integrity checks and for
    detecting idempotent re-fetches before writing to S3."""
    return hashlib.sha256(payload).hexdigest()


def derive_raw_object_key(
    *,
    source_id: str,
    fetched_at_utc: datetime,
    raw_sha256: str,
    extension: str,
) -> str:
    """Deterministic S3 key for a raw artifact.

    Layout: ``{source_id}/{YYYY}/{MM}/{DD}/{sha256}.{ext}``

    Partitioning by source and date keeps lifecycle rules and scans cheap,
    and using the content hash in the filename ensures the same payload
    always lands at the same key (so re-fetches are no-ops).
    """
    if fetched_at_utc.tzinfo is None:
        raise ValueError("derive_raw_object_key: fetched_at_utc must be tz-aware")
    ext = extension.lstrip(".")
    if not ext:
        raise ValueError("derive_raw_object_key: extension must be non-empty")

    dt = fetched_at_utc.astimezone(UTC)
    return (
        f"{source_id}/"
        f"{dt.year:04d}/{dt.month:02d}/{dt.day:02d}/"
        f"{raw_sha256}.{ext}"
    )
