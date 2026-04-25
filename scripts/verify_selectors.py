"""Verify a parser's selectors against a real captured HTML file.

This is the human-in-the-loop for promoting an ``unverified`` Source
Card (ADR-0006) to ``verified``. The operator captures a real detail
page (browser "Save As"), runs this script, and reads a pass/fail
report per field with the extracted values side-by-side with the
selectors that produced them.

    $ python -m scripts.verify_selectors it-tribunale-roma captures/it/tribunale-roma/001_raw.html

    source_id:      it-tribunale-roma
    parser:         parsers.it.tribunale_roma_v1 (v1.0.0)
    file:           captures/it/tribunale-roma/001_raw.html (14,523 bytes)

    ✓ debtor_name         [required]  ACME Manifatture S.p.A.
                                      selector: h1.debtor::text
    ✓ case_number         [required]  4523/2026
                                      selector: span.case-no::text
    ✗ codice_fiscale      [optional]  (empty)
                                      selector: dl.meta dd.codice-fiscale::text
                                      → selector did not match; check for
                                        DOM variation on this page.
    ...

    STATUS: 8/10 required fields extracted, 2 optional fields empty.
    Ready to promote? Run:
        $ python -m scripts.promote_canary it-tribunale-roma

An exit code of 0 means all required fields extracted. Non-zero means
at least one required field came up empty — the parser or the Source
Card needs adjustment before promotion.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from libs.provenance import build_envelope, new_ulid
from services.extract.framework import (
    DeclarativeParser,
    DeclarativeXmlBulkParser,
    ParseContext,
    ParseError,
)
from services.extract.framework.config import FieldConfig
from services.extract.framework.extractors import extract_field

logger = logging.getLogger("dip.verify_selectors")


@dataclass(frozen=True, slots=True)
class FieldReport:
    name: str
    required: bool
    selector_str: str
    value: object
    raw_text: str | None
    error: str | None


@dataclass
class VerifyResult:
    source_id: str
    parser_id: str
    parser_version: str
    file_path: Path
    file_size: int
    fields: list[FieldReport]

    @property
    def required_ok(self) -> int:
        return sum(1 for f in self.fields if f.required and f.value is not None)

    @property
    def required_total(self) -> int:
        return sum(1 for f in self.fields if f.required)

    @property
    def optional_empty(self) -> int:
        return sum(1 for f in self.fields if not f.required and f.value is None)

    @property
    def ready_to_promote(self) -> bool:
        return self.required_ok == self.required_total


# ── Source Card lookup ───────────────────────────────────────────────
def _find_source_card(source_id: str, repo_root: Path) -> Path:
    """Find sources/<country>/<slug>.yaml by source_id. Repo-local only."""
    for candidate in (repo_root / "sources").rglob("*.yaml"):
        try:
            data = yaml.safe_load(candidate.read_text())
        except yaml.YAMLError:
            continue
        if isinstance(data, dict) and data.get("source_id") == source_id:
            return candidate
    raise FileNotFoundError(
        f"no Source Card for source_id={source_id!r} under {repo_root / 'sources'}"
    )


def _load_parser_class(parser_module_path: str) -> type[DeclarativeParser | DeclarativeXmlBulkParser]:
    """Map 'parsers.it.tribunale_milano_v1' → the parser class."""
    # The Source Card's ``parser`` field is a module path like
    # ``parsers.it.tribunale_milano_v1``. The actual module lives at
    # ``services.extract.parsers.it.tribunale_milano``. Map by stripping
    # the trailing version suffix.
    parts = parser_module_path.split(".")
    if not parts[-1].startswith("tribunale") and not parts[-1].startswith("tc_") \
            and not parts[-1].startswith("insolvenz") and not parts[-1].startswith("bodacc") \
            and not parts[-1].startswith("prc") and not parts[-1].startswith("insolventi"):
        # Pattern: drop trailing _vN → 'tribunale_milano'
        trimmed_last = parts[-1].rsplit("_v", 1)[0]
        parts[-1] = trimmed_last
    else:
        parts[-1] = parts[-1].rsplit("_v", 1)[0]
    module_path = "services.extract." + ".".join(parts)

    mod = importlib.import_module(module_path)
    candidates = [
        obj for name, obj in vars(mod).items()
        if isinstance(obj, type)
        and issubclass(obj, (DeclarativeParser, DeclarativeXmlBulkParser))
        and obj not in (DeclarativeParser, DeclarativeXmlBulkParser)
        and not name.startswith("_")
    ]
    # Prefer the concrete class (with PARSER_ID set) over any shared base.
    concrete = [c for c in candidates if getattr(c, "PARSER_ID", None)]
    if not concrete:
        raise RuntimeError(f"no concrete parser class found in {module_path}")
    return concrete[0]


# ── Core verification ────────────────────────────────────────────────
def verify(
    source_id: str,
    capture_path: Path,
    repo_root: Path | None = None,
) -> VerifyResult:
    """Run parser selectors against ``capture_path``; return a structured report."""
    repo_root = repo_root or Path.cwd()
    card_path = _find_source_card(source_id, repo_root)
    card = yaml.safe_load(card_path.read_text())

    parser_cls = _load_parser_class(card["parser"])

    # Build a minimal ParseContext. This verify path doesn't hit the DB.
    env = build_envelope(
        source_id=source_id,
        source_url=str(card["base_url"]),
        stable_natural_key=f"verify-{source_id}",
        fetched_at_utc=__import__("datetime").datetime.now(__import__("datetime").UTC),
        published_at_local=None,
        raw_object_key=f"verify/{source_id}/" + "a" * 64 + ".html",
        raw_sha256="a" * 64,
        parser_version=card["parser"] + ".0.0",  # synthesize valid semver
        extractor_run_id=new_ulid(),
        data_owner="verify",
        legal_basis="selector verification",
    )
    ctx = ParseContext(
        source_id=source_id,
        parser_version=env.parser_version,
        run_id=env.extractor_run_id,
        envelope=env,
        raw_object_key=env.raw_object_key,
        source_url=env.source_url,
        natural_key_hint="verify",
    )
    parser = parser_cls(ctx)
    payload = capture_path.read_bytes()

    # Build the tree using the parser's own machinery, then run each
    # field individually so we can report per-field status even when a
    # required field fails (full parse() would raise on the first miss).
    reports: list[FieldReport] = []
    try:
        tree = parser._parse_tree(payload)  # type: ignore[attr-defined]
    except ParseError as e:
        # Couldn't even parse the document — return a single synthetic
        # report so the caller sees *something*.
        return VerifyResult(
            source_id=source_id,
            parser_id=parser.PARSER_ID,
            parser_version=parser.VERSION,
            file_path=capture_path,
            file_size=len(payload),
            fields=[FieldReport(
                name="(document)", required=True,
                selector_str="(content_type parse)",
                value=None, raw_text=None, error=f"parse failed: {e}",
            )],
        )

    if isinstance(parser, DeclarativeParser):
        try:
            rooted = parser._apply_root(tree)  # type: ignore[attr-defined]
        except ParseError as e:
            return VerifyResult(
                source_id=source_id,
                parser_id=parser.PARSER_ID,
                parser_version=parser.VERSION,
                file_path=capture_path,
                file_size=len(payload),
                fields=[FieldReport(
                    name="(root)", required=True,
                    selector_str=parser.config.record.root_selector or "(none)",
                    value=None, raw_text=None, error=str(e),
                )],
            )
        for name, fc in parser.config.record.fields.items():
            reports.append(_report_field(name, fc, rooted))
    else:
        # XML bulk parser — report per field on the first matched record,
        # if any. Otherwise report "no records matched".
        from lxml import etree
        try:
            xml_tree = etree.fromstring(payload)
        except etree.XMLSyntaxError as e:
            return VerifyResult(
                source_id=source_id,
                parser_id=parser.PARSER_ID,
                parser_version=parser.VERSION,
                file_path=capture_path,
                file_size=len(payload),
                fields=[FieldReport(
                    name="(xml)", required=True,
                    selector_str="(xml parse)",
                    value=None, raw_text=None, error=str(e),
                )],
            )
        nodes = xml_tree.xpath(parser.records_xpath)  # type: ignore[attr-defined]
        if not nodes:
            return VerifyResult(
                source_id=source_id,
                parser_id=parser.PARSER_ID,
                parser_version=parser.VERSION,
                file_path=capture_path,
                file_size=len(payload),
                fields=[FieldReport(
                    name="(records)", required=True,
                    selector_str=f"xpath={parser.records_xpath}",  # type: ignore[attr-defined]
                    value=None, raw_text=None,
                    error=f"records_xpath matched 0 nodes — check the file "
                           f"or the xpath template",
                )],
            )
        first_node = nodes[0]
        for name, fc in parser.config.record.fields.items():
            value, raw_text, err = parser._extract_field(first_node, fc)  # type: ignore[attr-defined]
            reports.append(FieldReport(
                name=name, required=fc.required,
                selector_str=f"xpath={fc.xpath}" if fc.xpath else (fc.selector or ""),
                value=value, raw_text=raw_text, error=err,
            ))

    return VerifyResult(
        source_id=source_id,
        parser_id=parser.PARSER_ID,
        parser_version=parser.VERSION,
        file_path=capture_path,
        file_size=len(payload),
        fields=reports,
    )


def _report_field(name: str, fc: FieldConfig, rooted: object) -> FieldReport:
    """Run one field's selector and wrap the result in a FieldReport."""
    result = extract_field(name=name, cfg=fc, tree=rooted)
    selector_str = fc.selector or (f"xpath={fc.xpath}" if fc.xpath else f"jsonpath={fc.json_path}")
    return FieldReport(
        name=name,
        required=fc.required,
        selector_str=selector_str or "(none)",
        value=result.value,
        raw_text=result.raw_text,
        error=result.error,
    )


# ── CLI ──────────────────────────────────────────────────────────────
def render_report(result: VerifyResult) -> str:
    lines: list[str] = []
    lines.append(f"source_id:      {result.source_id}")
    lines.append(f"parser:         {result.parser_id} (v{result.parser_version})")
    lines.append(f"file:           {result.file_path} ({result.file_size:,} bytes)")
    lines.append("")

    for f in result.fields:
        tag = "✓" if f.value is not None else ("✗" if f.required else "–")
        req_label = "[required]" if f.required else "[optional]"
        value_str = _format_value(f.value) if f.value is not None else "(empty)"
        lines.append(f"  {tag} {f.name:28s} {req_label:11s} {value_str}")
        lines.append(f"      selector: {f.selector_str}")
        if f.error:
            lines.append(f"      → {f.error}")

    lines.append("")
    lines.append(
        f"STATUS: {result.required_ok}/{result.required_total} required fields "
        f"extracted, {result.optional_empty} optional fields empty."
    )
    if result.ready_to_promote:
        lines.append("")
        lines.append("Ready to promote. Next step:")
        lines.append(f"    python -m scripts.promote_canary {result.source_id}")
    else:
        lines.append("")
        lines.append("Not ready: at least one required field is empty. Check the")
        lines.append("failing selector against the captured HTML structure, update")
        lines.append(f"the Source Card or parser, and re-run.")
    return "\n".join(lines)


def _format_value(v: object) -> str:
    s = str(v)
    if len(s) > 72:
        return s[:69] + "..."
    return s


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_id", help="source_id from a Source Card YAML")
    parser.add_argument("capture", type=Path, help="path to captured HTML/XML file")
    parser.add_argument(
        "--repo-root", type=Path, default=Path.cwd(),
        help="repo root (default: cwd). Used to find Source Cards.",
    )
    args = parser.parse_args()

    if not args.capture.exists():
        print(f"ERROR: {args.capture} does not exist", file=sys.stderr)
        return 2

    try:
        result = verify(args.source_id, args.capture, repo_root=args.repo_root)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    print(render_report(result))
    return 0 if result.ready_to_promote else 1


if __name__ == "__main__":
    raise SystemExit(main())
