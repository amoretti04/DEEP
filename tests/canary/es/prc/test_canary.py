"""BOE Sección IV — Registro Público Concursal canary test."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from libs.provenance import build_envelope, new_ulid
from services.extract.framework import ParseContext
from services.extract.parsers.es.prc import PrcParser

FIXTURE_DIR = Path(__file__).parent


def _ctx() -> ParseContext:
    env = build_envelope(
        source_id="es-boe-prc",
        source_url="https://www.boe.es/boe/dias/2026/04/15/secciones/4/sumario.xml",
        stable_natural_key="boe-2026-04-15-s4",
        fetched_at_utc=datetime(2026, 4, 15, 8, 0, tzinfo=UTC),
        published_at_local=None,
        raw_object_key="es-boe-prc/2026/04/15/" + "a" * 64 + ".xml",
        raw_sha256="a" * 64,
        parser_version="es.prc_v1.0.0",
        extractor_run_id=new_ulid(),
        data_owner="team-ingest-es",
        legal_basis="Art. 6(1)(f) GDPR — statutory publication (BOE)",
    )
    return ParseContext(
        source_id=env.source_id,
        parser_version=env.parser_version,
        run_id=env.extractor_run_id,
        envelope=env,
        raw_object_key=env.raw_object_key,
        source_url=env.source_url,
        natural_key_hint="boe-2026-04-15-s4",
    )


class TestPrcCanary:
    def test_yields_two_records(self) -> None:
        raw = (FIXTURE_DIR / "001_raw.xml").read_bytes()
        records = PrcParser(_ctx()).parse(raw)
        assert len(records) == 2

    def test_liquidation_record(self) -> None:
        raw = (FIXTURE_DIR / "001_raw.xml").read_bytes()
        r = PrcParser(_ctx()).parse(raw)[0]

        assert r.fields["edicto_id"] == "BOE-B-2026-12345"
        assert r.fields["debtor_name"] == "Industrias Ejemplo S.L."
        assert r.fields["debtor_nif_cif"] == "B12345678"
        assert r.fields["court_name"] == "Juzgado de lo Mercantil nº 2 de Barcelona"
        assert r.fields["court_case_number"] == "0456/2026"
        assert r.fields["proceeding_type_code"] == "CL"
        assert r.fields["proceeding_type_original"] == "Concurso en liquidación"
        assert r.fields["proceeding_type"] == "LIQUIDATION"
        assert r.fields["administrator_name"] == "D. Javier García Martínez"
        assert r.fields["jurisdiction"] == "ES"

    def test_preconcurso_maps_to_moratorium(self) -> None:
        raw = (FIXTURE_DIR / "001_raw.xml").read_bytes()
        r = PrcParser(_ctx()).parse(raw)[1]

        assert r.fields["proceeding_type_code"] == "PC"
        assert r.fields["proceeding_type_original"] == "Preconcurso"
        assert r.fields["proceeding_type"] == "MORATORIUM"

    def test_natural_keys_are_unique(self) -> None:
        raw = (FIXTURE_DIR / "001_raw.xml").read_bytes()
        records = PrcParser(_ctx()).parse(raw)
        keys = [r.natural_key for r in records]
        assert keys == ["BOE-B-2026-12345", "BOE-B-2026-12346"]

    def test_provenance_present(self) -> None:
        raw = (FIXTURE_DIR / "001_raw.xml").read_bytes()
        r = PrcParser(_ctx()).parse(raw)[0]
        for name in ("edicto_id", "debtor_name", "court_name", "proceeding_type_code"):
            assert name in r.field_provenance
            assert r.field_provenance[name].selector.startswith("xpath=")
