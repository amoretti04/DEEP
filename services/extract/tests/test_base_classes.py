"""Unit tests for the shared parser base classes (IT tribunali + FR Greffe).

These tests verify that:
  1. The base classes correctly parameterize COURT_NAME via subclass.
  2. The shared selectors extract fields consistently.
  3. Subclasses refuse to run without a COURT_NAME set.

They are NOT canary regression locks — the 12 R3 sources are marked
``status: unverified`` (ADR-0006) until a real captured page proves
the selectors against production DOM. The fixtures here are minimal
synthetic HTML chosen to exercise the base class's logic, labeled as
such.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from libs.provenance import build_envelope, new_ulid
from services.extract.framework import ParseContext, ParseError
from services.extract.parsers.fr._greffe_base import GreffeTribunalParser
from services.extract.parsers.fr.tc_lyon import TcLyonParser
from services.extract.parsers.fr.tc_paris import TcParisParser
from services.extract.parsers.it._tribunale_base import ItalianTribunaleParser
from services.extract.parsers.it.tribunale_bologna import TribunaleBolognaParser
from services.extract.parsers.it.tribunale_roma import TribunaleRomaParser


def _ctx(source_id: str, parser_version: str) -> ParseContext:
    env = build_envelope(
        source_id=source_id,
        source_url="https://example.invalid/case/x",
        stable_natural_key="test",
        fetched_at_utc=datetime(2026, 4, 21, tzinfo=UTC),
        published_at_local=None,
        raw_object_key=f"{source_id}/2026/04/21/{'a' * 64}.html",
        raw_sha256="a" * 64,
        parser_version=parser_version,
        extractor_run_id=new_ulid(),
        data_owner="t",
        legal_basis="t",
    )
    return ParseContext(
        source_id=source_id,
        parser_version=parser_version,
        run_id=new_ulid(),
        envelope=env,
        raw_object_key=env.raw_object_key,
        source_url=env.source_url,
        natural_key_hint="test",
    )


# ─────────────────────────────────────────────────────────────────
# Italian tribunale base
# ─────────────────────────────────────────────────────────────────
class TestItalianTribunaleBase:
    # Minimal fixture matching the IT base selectors. Clearly synthetic.
    FIXTURE = b"""
    <div class="case-detail">
      <h1 class="debtor">ACME S.p.A.</h1>
      <span class="case-no">R.G. 9999/2026</span>
      <dl class="meta">
        <dd class="type">Liquidazione giudiziale</dd>
        <dd class="administrator">Avv. Test</dd>
      </dl>
      <time class="opened" datetime="2026-04-15"></time>
    </div>
    """

    def test_bologna_subclass_sets_court_name(self) -> None:
        """Bologna subclass must substitute court_name correctly."""
        ctx = _ctx("it-tribunale-bologna", "it.tribunale_bologna_v1.0.0")
        rec = TribunaleBolognaParser(ctx).parse(self.FIXTURE)[0]
        assert rec.fields["court_name"] == "Tribunale di Bologna — Sezione Fallimentare"
        assert rec.fields["debtor_name"] == "ACME S.p.A."
        assert rec.fields["jurisdiction"] == "IT"
        assert rec.fields["proceeding_type"] == "LIQUIDATION"

    def test_roma_subclass_sets_different_court_name(self) -> None:
        """Different subclass of the same base → different court_name, same fields."""
        ctx = _ctx("it-tribunale-roma", "it.tribunale_roma_v1.0.0")
        rec = TribunaleRomaParser(ctx).parse(self.FIXTURE)[0]
        assert rec.fields["court_name"] == "Tribunale di Roma — Sezione Fallimentare"
        # Same fixture; only court_name differs.
        assert rec.fields["debtor_name"] == "ACME S.p.A."
        assert rec.fields["case_number"] == "9999/2026"
        assert rec.fields["opened_at"] == date(2026, 4, 15)

    def test_instantiating_the_base_directly_fails(self) -> None:
        """Trying to parse with the base class (no COURT_NAME) must raise —
        prevents accidentally losing court identity in produced records."""
        class _Uninit(ItalianTribunaleParser):
            PARSER_ID = "x"
            VERSION = "1.0.0"
            # COURT_NAME deliberately NOT set

        ctx = _ctx("x", "x.y_v1.0.0")
        with pytest.raises(RuntimeError, match="COURT_NAME"):
            _Uninit(ctx).parse(self.FIXTURE)


# ─────────────────────────────────────────────────────────────────
# French Greffe base
# ─────────────────────────────────────────────────────────────────
class TestGreffeTribunalBase:
    # Minimal fixture matching the FR Greffe base selectors.
    FIXTURE = """
    <div class="annonce-detail">
      <h1 class="denomination">Exemple Manufacture SARL</h1>
      <span class="forme-juridique">SARL</span>
      <span class="siren">123456789</span>
      <span class="rcs">Paris B 123 456 789</span>
      <span class="code-ape">2511Z</span>
      <span class="numero-dossier">2026B01234</span>
      <dd class="type-procedure">Liquidation judiciaire</dd>
      <time class="jugement" datetime="2026-04-12"></time>
      <dd class="mandataire">Maître Jean Test</dd>
      <dd class="qualite">Liquidateur judiciaire</dd>
    </div>
    """.encode("utf-8")

    def test_paris_subclass(self) -> None:
        ctx = _ctx("fr-tc-paris", "fr.tc_paris_v1.0.0")
        rec = TcParisParser(ctx).parse(self.FIXTURE)[0]
        assert rec.fields["court_name"] == "Tribunal de Commerce de Paris"
        assert rec.fields["debtor_name"] == "Exemple Manufacture SARL"
        assert rec.fields["debtor_siren"] == "123456789"
        assert rec.fields["debtor_naf"] == "2511Z"
        assert rec.fields["case_number"] == "2026B01234"
        assert rec.fields["proceeding_type"] == "LIQUIDATION"
        assert rec.fields["proceeding_type_original"] == "Liquidation judiciaire"
        assert rec.fields["jurisdiction"] == "FR"

    def test_lyon_subclass_different_court_name(self) -> None:
        ctx = _ctx("fr-tc-lyon", "fr.tc_lyon_v1.0.0")
        rec = TcLyonParser(ctx).parse(self.FIXTURE)[0]
        assert rec.fields["court_name"] == "Tribunal de Commerce de Lyon"
        # SIREN and case_number come from the same fixture, so they're equal —
        # this proves the subclass doesn't mutate the shared config accidentally.
        assert rec.fields["debtor_siren"] == "123456789"

    def test_missing_denomination_quarantines(self) -> None:
        """Required debtor_name → ParseError → quarantine. Inherited from framework."""
        bad = self.FIXTURE.replace(b'<h1 class="denomination">Exemple Manufacture SARL</h1>', b"")
        ctx = _ctx("fr-tc-paris", "fr.tc_paris_v1.0.0")
        with pytest.raises(ParseError, match="required"):
            TcParisParser(ctx).parse(bad)

    def test_shared_base_refuses_without_court_name(self) -> None:
        """Base abstraction discipline: bare base class cannot produce records."""
        class _Uninit(GreffeTribunalParser):
            PARSER_ID = "x"
            VERSION = "1.0.0"

        ctx = _ctx("x", "x.y_v1.0.0")
        with pytest.raises(RuntimeError, match="COURT_NAME"):
            _Uninit(ctx).parse(self.FIXTURE)
