"""Canary regression test for Tribunale di Milano parser.

Per `docs/runbooks/onboarding.md`: any parser change that alters the
canonical output of a fixture fails this test and blocks merge. Parser
semver must be bumped appropriately when canary output legitimately
changes.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from libs.provenance import build_envelope, new_ulid
from services.extract.framework import ParseContext
from services.extract.parsers.it.tribunale_milano import TribunaleMilanoParser

FIXTURE_DIR = Path(__file__).parent


def _ctx(natural_key_hint: str = "hint") -> ParseContext:
    env = build_envelope(
        source_id="it-tribunale-milano-fallimenti",
        source_url="https://www.tribunale.milano.giustizia.it/fallimenti/4523-2026",
        stable_natural_key=natural_key_hint,
        fetched_at_utc=__import__("datetime").datetime(2026, 4, 21, tzinfo=__import__("datetime").UTC),
        published_at_local=None,
        raw_object_key="it-tribunale-milano-fallimenti/2026/04/21/" + "a" * 64 + ".html",
        raw_sha256="a" * 64,
        parser_version="it.tribunale_milano_v1.0.0",
        extractor_run_id=new_ulid(),
        data_owner="team-ingest-it",
        legal_basis="Art. 6(1)(f) GDPR — public register",
    )
    return ParseContext(
        source_id=env.source_id,
        parser_version=env.parser_version,
        run_id=env.extractor_run_id,
        envelope=env,
        raw_object_key=env.raw_object_key,
        source_url=env.source_url,
        natural_key_hint=natural_key_hint,
    )


class TestTribunaleMilanoCanary:
    def test_canary_001_reproduces_expected(self) -> None:
        raw = (FIXTURE_DIR / "001_raw.html").read_bytes()
        expected = json.loads((FIXTURE_DIR / "001_expected.json").read_text())

        parser = TribunaleMilanoParser(_ctx())
        records = parser.parse(raw)

        assert len(records) == 1
        rec = records[0]

        # Natural key
        assert rec.natural_key == expected["natural_key"]

        # Field-by-field — compare strings (including date ISOs).
        for field_name, exp_value in expected["fields"].items():
            actual = rec.fields.get(field_name)
            if isinstance(actual, date):
                actual = actual.isoformat()
            elif hasattr(actual, "isoformat"):
                actual = actual.isoformat()
            assert actual == exp_value, (
                f"field {field_name!r}: expected {exp_value!r}, got {actual!r}"
            )

        # Field-level provenance: every expected field must carry a
        # FieldProvenance record.
        for field_name in expected["provenance_fields"]:
            assert field_name in rec.field_provenance, (
                f"missing provenance for {field_name}"
            )
            p = rec.field_provenance[field_name]
            assert p.field_name == field_name
            assert p.selector, "selector must be non-empty on provenance"

        # Confidence
        assert rec.confidence == pytest.approx(expected["confidence"])

        # PII tagging: administrator_name is flagged personal in config;
        # the provenance contains the selector, but the pipeline-level
        # minimization happens downstream. Sanity check the config side.
        from services.extract.parsers.it.tribunale_milano import (
            TribunaleMilanoParser as TM,
        )
        from services.extract.framework.config import PIITag

        assert TM.config.record.fields["administrator_name"].pii is PIITag.PERSONAL
        assert TM.config.record.fields["debtor_name"].pii is PIITag.NON_PERSONAL

    def test_proceeding_type_maps_to_unified(self) -> None:
        """Italian 'Liquidazione giudiziale' must map to unified LIQUIDATION."""
        raw = (FIXTURE_DIR / "001_raw.html").read_bytes()
        parser = TribunaleMilanoParser(_ctx())
        rec = parser.parse(raw)[0]
        assert rec.fields["proceeding_type"] == "LIQUIDATION"
        assert rec.fields["proceeding_type_original"] == "Liquidazione giudiziale"

    def test_missing_required_quarantines(self) -> None:
        """A broken page must raise ParseError, not silently produce garbage."""
        from services.extract.framework import ParseError

        # Strip the required <h1 class="debtor"> element.
        raw = (FIXTURE_DIR / "001_raw.html").read_bytes().replace(
            b'<h1 class="debtor">Esempio Manifatture S.p.A.</h1>',
            b"",
        )
        parser = TribunaleMilanoParser(_ctx())
        with pytest.raises(ParseError, match="required"):
            parser.parse(raw)
