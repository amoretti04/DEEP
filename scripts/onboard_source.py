"""Scaffold a new source.

Usage: ``python -m scripts.onboard_source <country>/<slug>``

Creates:

* ``sources/<country>/<slug>.yaml`` — Source Card skeleton
* ``services/extract/parsers/<country>/<slug>.py`` — parser stub
* ``tests/canary/<country>/<slug>/`` — fixture directory with a README
* ``docs/lia/<country>/<slug>.md`` — LIA template

Never overwrites an existing file. The LIA and the legal_review fields
are intentionally left empty — a connector can't run in production until
both are filled.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent.parent

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scaffold a new DIP source.",
        epilog="Example: python -m scripts.onboard_source it/tribunale-milano",
    )
    parser.add_argument(
        "slug", help="Path as <country>/<source-slug>, both lowercase kebab."
    )
    parser.add_argument("--name", default=None, help="Human-readable source name.")
    parser.add_argument("--tier", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument(
        "--category",
        default="COURT",
        choices=("GAZ", "COURT", "INS-REG", "AUCT", "REG", "CRED", "NEWS", "REGU", "MKT"),
    )
    args = parser.parse_args(argv)

    if "/" not in args.slug:
        print("error: slug must be <country>/<source-slug>", file=sys.stderr)
        return 2
    country_part, slug_part = args.slug.split("/", 1)
    if not SLUG_RE.match(country_part):
        print(f"error: country segment '{country_part}' must be kebab-case lowercase", file=sys.stderr)
        return 2
    if not SLUG_RE.match(slug_part):
        print(f"error: slug segment '{slug_part}' must be kebab-case lowercase", file=sys.stderr)
        return 2

    source_id = f"{country_part}-{slug_part}"
    name = args.name or slug_part.replace("-", " ").title()
    tier = args.tier
    category = args.category

    created: list[Path] = []
    try:
        created.append(
            _write(
                ROOT / "sources" / country_part / f"{slug_part}.yaml",
                _source_card_template(source_id, name, country_part, category, tier),
            )
        )
        created.append(
            _write(
                ROOT / "services" / "extract" / "parsers" / country_part / f"{slug_part}.py",
                _parser_template(source_id, name),
            )
        )
        # Ensure __init__.py in the parser folder
        init_path = ROOT / "services" / "extract" / "parsers" / country_part / "__init__.py"
        if not init_path.exists():
            _write(init_path, "")
        canary_dir = ROOT / "tests" / "canary" / country_part / slug_part
        canary_dir.mkdir(parents=True, exist_ok=True)
        created.append(
            _write(
                canary_dir / "README.md",
                _canary_readme(source_id, name),
            )
        )
        created.append(
            _write(
                ROOT / "docs" / "lia" / country_part / f"{slug_part}.md",
                _lia_template(source_id, name, country_part),
            )
        )
    except FileExistsError as e:
        print(f"error: {e.filename} already exists — refusing to overwrite", file=sys.stderr)
        return 3

    print(f"Scaffolded {source_id}. Created:")
    for p in created:
        print(f"  {p.relative_to(ROOT)}")
    print()
    print("Next steps:")
    print("  1. Fill out the LIA at docs/lia/<country>/<slug>.md")
    print("  2. Capture 2–3 canary raw payloads into tests/canary/<country>/<slug>/")
    print("  3. Implement the parser in services/extract/parsers/...")
    print("  4. Run: make sources-validate && make test")
    return 0


def _write(path: Path, content: str) -> Path:
    if path.exists():
        raise FileExistsError(f"{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ── Templates ────────────────────────────────────────────────────────

def _source_card_template(
    source_id: str, name: str, country: str, category: str, tier: int
) -> str:
    return dedent(f"""\
        source_id: {source_id}
        name: "{name}"
        country: {country.upper()}
        language: {country}    # change if source publishes in a different language
        tier: {tier}
        category: {category}
        jurisdiction_class: eu_gdpr

        connector: HttpScrapeConnector
        fetch_mode: "list+detail"
        base_url: https://example.invalid/

        schedule:
          cron: "0 */3 * * *"
          timezone: Europe/Rome
          business_hours_only: true
          off_hours_cron: "0 */6 * * *"

        politeness:
          min_delay_s: 4
          max_delay_s: 9
          concurrency: 1
          user_agent_pool: default_eu
          respect_robots: true

        parser: parsers.{country}.{source_id.removeprefix(country + "-").replace('-', '_')}_v1

        owner: unassigned

        legal_review:
          verdict: pending   # MUST be 'approved' before enabling
          lia_path: docs/lia/{country}/{source_id.removeprefix(country + "-")}.md

        on_failure:
          alert_channel: "slack#ingest-alerts"
          severity_after_minutes: 30

        enabled: false
    """)


def _parser_template(source_id: str, name: str) -> str:
    mod_id = source_id.replace("-", "_")
    return dedent(f'''\
        """Parser for {name} ({source_id}).

        Semver: bump minor on additive changes, patch on bug fixes, major on
        canonical schema changes. Any parser_version bump triggers replay of
        the last 90 days of raw data (see scripts/replay.py).
        """

        from __future__ import annotations

        __version__ = "1.0.0"
        PARSER_NAME = "{source_id}_v1"


        def parse(html: bytes) -> list[dict[str, object]]:
            """Return a list of extracted records.

            Each record is a dict matching the parser-output contract; the
            normalizer maps it onto :class:`~libs.schemas.proceeding.Proceeding`
            + :class:`~libs.schemas.proceeding.ProceedingEvent`.

            TODO ({mod_id}):
              - Capture 2-3 canary HTML fixtures under tests/canary/
              - Implement extraction
              - Add test_canary.py asserting byte-for-byte parser output
            """
            raise NotImplementedError(
                "Parser for {source_id} is a stub — see tests/canary/ "
                "and the onboarding checklist in docs/runbooks/onboarding.md."
            )
    ''')


def _canary_readme(source_id: str, name: str) -> str:
    return dedent(f"""\
        # Canary fixtures for {source_id}

        Capture 2–3 known-good raw payloads for **{name}** and commit them here
        alongside expected canonical outputs. CI replays the parser against
        these fixtures on every change; any divergence fails the build.

        Layout:
        ```
        tests/canary/{source_id.split('-', 1)[0]}/{source_id.split('-', 1)[1]}/
          001_raw.html
          001_expected.json
          002_raw.html
          002_expected.json
        ```

        How to capture:
        1. From the live source, save one detail page as-is (no JS rendering).
        2. Redact any personal data that isn't required for regression (CLAUDE.md §3.2).
        3. Hand-produce the expected canonical JSON.
        4. Commit, push, open PR.
    """)


def _lia_template(source_id: str, name: str, country: str) -> str:
    return dedent(f"""\
        # Legitimate Interests Assessment — {name}

        **Source ID:** `{source_id}`
        **Country:** {country.upper()}
        **Jurisdiction class:** (fill: eu_gdpr | eea_gdpr_adequacy | non_eu_separate_regime | global_case_by_case)
        **Date:** (fill)
        **Reviewer:** (fill — lawyer email)

        ---

        ## 1. Purpose

        Describe why DIP is ingesting this source and what investment-intelligence
        purpose it serves (CLAUDE.md §3.2 / PRD §19.1).

        ## 2. Necessity test

        Is ingesting this source necessary to achieve the purpose? Are there
        less-intrusive alternatives?

        ## 3. Balancing test

        Data subjects' rights and freedoms vs. our legitimate interest.
        Document which categories of data are present, whether any are
        `personal_sensitive`, and what minimization applies.

        ## 4. Lawful basis

        Default: Art. 6(1)(f) GDPR legitimate interests. For UK sources, UK-GDPR.
        For CH sources, FADP + GDPR adequacy. For UAE, PDPL. For KSA, PDPL-KSA.

        ## 5. Data minimization

        List every personal / personal_sensitive field we capture and justify each.

        ## 6. Retention

        Default: 24 months in the raw lake, longer in canonical for active
        proceedings. Specific overrides for this source:

        ## 7. Data-subject rights

        DSAR / erasure / objection workflow reference: `docs/runbooks/dsar.md`

        ## 8. Verdict

        * **Approved:** date + reviewer sign-off → update Source Card
          `legal_review.verdict: approved` and fill `date` + `reviewer`.
        * **Rejected:** record the reason here; connector must never be
          enabled.

    """)


if __name__ == "__main__":
    raise SystemExit(main())
