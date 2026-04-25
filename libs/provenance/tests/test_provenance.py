"""Tests for the provenance envelope and identifiers.

The idempotence properties here are load-bearing for the whole pipeline —
they are what make re-runs safe. Treat failures in this file as high
severity.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from libs.provenance import (
    ProvenanceEnvelope,
    build_envelope,
    compute_raw_sha256,
    derive_raw_object_key,
    new_extractor_run_id,
    new_ulid,
    record_uid,
)


# ── record_uid ────────────────────────────────────────────────────────
class TestRecordUid:
    def test_deterministic(self) -> None:
        pub = datetime(2026, 4, 21, 8, 0, tzinfo=UTC)
        a = record_uid("it-milano", "key-123", pub)
        b = record_uid("it-milano", "key-123", pub)
        assert a == b
        assert a.startswith("sha256:")
        assert len(a) == len("sha256:") + 64

    def test_varies_by_source(self) -> None:
        pub = datetime(2026, 4, 21, tzinfo=UTC)
        assert record_uid("it-milano", "k", pub) != record_uid(
            "it-roma", "k", pub
        )

    def test_varies_by_key(self) -> None:
        pub = datetime(2026, 4, 21, tzinfo=UTC)
        assert record_uid("s", "k1", pub) != record_uid("s", "k2", pub)

    def test_varies_by_published_at(self) -> None:
        t1 = datetime(2026, 4, 21, tzinfo=UTC)
        t2 = t1 + timedelta(seconds=1)
        assert record_uid("s", "k", t1) != record_uid("s", "k", t2)

    def test_accepts_none_published_at(self) -> None:
        # Some sources don't publish a timestamp — the natural key alone
        # must be sufficient. Assert determinism still holds.
        a = record_uid("s", "k", None)
        b = record_uid("s", "k", None)
        assert a == b

    def test_rejects_empty_source(self) -> None:
        with pytest.raises(ValueError, match="source_id"):
            record_uid("", "k", None)

    def test_rejects_empty_key(self) -> None:
        with pytest.raises(ValueError, match="stable_natural_key"):
            record_uid("s", "", None)

    def test_rejects_naive_datetime(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            record_uid("s", "k", datetime(2026, 4, 21))  # noqa: DTZ001

    def test_tz_normalization(self) -> None:
        # Same instant, different tz representation → same uid.
        from datetime import timezone
        utc = datetime(2026, 4, 21, 10, 0, tzinfo=UTC)
        plus2 = datetime(2026, 4, 21, 12, 0, tzinfo=timezone(timedelta(hours=2)))
        assert record_uid("s", "k", utc) == record_uid("s", "k", plus2)


# ── raw_object_key ────────────────────────────────────────────────────
class TestRawObjectKey:
    def test_format(self) -> None:
        key = derive_raw_object_key(
            source_id="it-milano",
            fetched_at_utc=datetime(2026, 4, 21, 8, 14, 22, tzinfo=UTC),
            raw_sha256="a" * 64,
            extension="html",
        )
        assert key == f"it-milano/2026/04/21/{'a' * 64}.html"

    def test_strips_dot_from_extension(self) -> None:
        key = derive_raw_object_key(
            source_id="s",
            fetched_at_utc=datetime(2026, 1, 2, tzinfo=UTC),
            raw_sha256="b" * 64,
            extension=".pdf",
        )
        assert key.endswith(".pdf")
        assert ".pdf.pdf" not in key

    def test_rejects_naive_dt(self) -> None:
        with pytest.raises(ValueError, match="tz-aware"):
            derive_raw_object_key(
                source_id="s",
                fetched_at_utc=datetime(2026, 1, 1),  # noqa: DTZ001
                raw_sha256="c" * 64,
                extension="html",
            )


# ── compute_raw_sha256 ────────────────────────────────────────────────
def test_raw_sha256_matches_known_value() -> None:
    # 'abc' -> known sha256
    expected = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert compute_raw_sha256(b"abc") == expected


# ── ULID ──────────────────────────────────────────────────────────────
def test_ulid_is_26_chars() -> None:
    uid = new_ulid()
    assert len(uid) == 26
    assert new_extractor_run_id() != new_extractor_run_id()  # randomness


# ── Envelope model ────────────────────────────────────────────────────
def _valid_envelope_kwargs() -> dict[str, object]:
    return dict(
        record_uid="sha256:" + "a" * 64,
        source_id="it-tribunale-milano-fallimenti",
        source_url="https://www.tribunale.milano.giustizia.it/case/123",
        fetched_at_utc=datetime(2026, 4, 21, 8, 14, 22, tzinfo=UTC),
        published_at_local=datetime(2026, 4, 21, 10, 0, tzinfo=UTC),
        raw_object_key=f"it-tribunale-milano-fallimenti/2026/04/21/{'a' * 64}.html",
        raw_sha256="a" * 64,
        parser_version="it.tribunale_milano_v1.0.0",
        extractor_run_id=new_ulid(),
        data_owner="team-ingest-it",
        legal_basis="Art. 6(1)(f) GDPR — public register",
    )


class TestProvenanceEnvelope:
    def test_valid(self) -> None:
        env = ProvenanceEnvelope(**_valid_envelope_kwargs())  # type: ignore[arg-type]
        assert env.source_id == "it-tribunale-milano-fallimenti"
        assert env.record_uid.startswith("sha256:")

    def test_is_frozen(self) -> None:
        env = ProvenanceEnvelope(**_valid_envelope_kwargs())  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            env.source_id = "other"  # type: ignore[misc]

    def test_rejects_future_fetch(self) -> None:
        kwargs = _valid_envelope_kwargs()
        kwargs["fetched_at_utc"] = datetime.now(UTC) + timedelta(days=1)
        with pytest.raises(ValidationError, match="future"):
            ProvenanceEnvelope(**kwargs)  # type: ignore[arg-type]

    def test_rejects_bad_parser_version(self) -> None:
        kwargs = _valid_envelope_kwargs()
        kwargs["parser_version"] = "not-semver"
        with pytest.raises(ValidationError):
            ProvenanceEnvelope(**kwargs)  # type: ignore[arg-type]

    def test_rejects_bad_record_uid(self) -> None:
        kwargs = _valid_envelope_kwargs()
        kwargs["record_uid"] = "md5:abc"
        with pytest.raises(ValidationError):
            ProvenanceEnvelope(**kwargs)  # type: ignore[arg-type]


class TestBuildEnvelope:
    def test_computes_record_uid_deterministically(self) -> None:
        kw = dict(
            source_id="s",
            source_url="https://x",
            stable_natural_key="nk1",
            fetched_at_utc=datetime(2026, 4, 21, tzinfo=UTC),
            published_at_local=datetime(2026, 4, 21, 10, 0, tzinfo=UTC),
            raw_object_key="s/2026/04/21/" + "a" * 64 + ".html",
            raw_sha256="a" * 64,
            parser_version="s.p_v1.0.0",
            extractor_run_id=new_ulid(),
            data_owner="team",
            legal_basis="LIA on file",
        )
        a = build_envelope(**kw)  # type: ignore[arg-type]
        b = build_envelope(**kw)  # type: ignore[arg-type]
        # record_uid must match even though extractor_run_id differs
        kw2 = {**kw, "extractor_run_id": new_ulid()}
        c = build_envelope(**kw2)  # type: ignore[arg-type]
        assert a.record_uid == b.record_uid == c.record_uid
