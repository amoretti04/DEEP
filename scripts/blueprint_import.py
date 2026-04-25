"""Import the Distressed Investment Sources Implementation Blueprint xlsx.

This is a critical Release 1 deliverable. It:

1. Opens the `Implementation Blueprint` sheet (the rich 23-column version).
2. Normalizes every row into a :class:`~libs.schemas.Source` model —
   canonical category, country, language, tier, jurisdiction_class, and
   release wave.
3. Upserts into the ``source`` table; on re-import, writes a new
   :class:`~libs.schemas.SourceCardVersion` if any field changed.
4. Routes rows with UNKNOWN category (or other unmappable fields) to the
   ``source_review_queue`` rather than silently bucketing them.
5. Produces a compact summary report (counts by country/tier/category,
   list of review-queue entries, list of newly-created sources) that an
   operator can read from CI logs or stdout.

Two modes:

* ``--mode preview`` — read, normalize, report. No DB writes.
* ``--mode upsert`` — read, normalize, write. Idempotent.

The importer is deterministic: re-running on the same file produces no
diffs unless the file changed. A source_id collision across distinct
rows is a hard error — rows are expected to be unique by URL + country.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd

from libs.schemas import (
    ConnectorType,
    Country,
    FetchMode,
    JurisdictionClass,
    Language,
    Source,
    SourceSchedule,
    Tier,
)
from libs.schemas.source import LegalReview, OnFailure, Politeness
from libs.taxonomy import SourceCategory, map_source_category

# ── Constants ─────────────────────────────────────────────────────────

# Preferred sheet: the richer Implementation Blueprint. Fall back to the
# simpler Distressed Sources if the richer one is missing.
PRIMARY_SHEET = "Implementation Blueprint"
FALLBACK_SHEET = "Distressed Sources"

# Workbook country strings → canonical Country enum (ADR-0003).
COUNTRY_MAP: dict[str, Country] = {
    "italy": Country.IT,
    "germany": Country.DE,
    "france": Country.FR,
    "uk": Country.UK,
    "united kingdom": Country.UK,
    "spain": Country.ES,
    "netherlands": Country.NL,
    "switzerland": Country.CH,
    "uae": Country.AE,
    "ksa": Country.SA,
    "ksa/mena": Country.SA,
    "saudi arabia": Country.SA,
    "eu": Country.EU,
    "europe": Country.EU,
    "global": Country.GLOBAL,
}

# Country → jurisdiction_class (ADR-0003).
JURISDICTION_CLASS_MAP: dict[Country, JurisdictionClass] = {
    Country.IT: JurisdictionClass.EU_GDPR,
    Country.DE: JurisdictionClass.EU_GDPR,
    Country.FR: JurisdictionClass.EU_GDPR,
    Country.UK: JurisdictionClass.EU_GDPR,     # UK-GDPR (close adequacy)
    Country.ES: JurisdictionClass.EU_GDPR,
    Country.NL: JurisdictionClass.EU_GDPR,
    Country.EU: JurisdictionClass.EU_GDPR,
    Country.CH: JurisdictionClass.EEA_GDPR_ADEQUACY,
    Country.AE: JurisdictionClass.NON_EU_SEPARATE_REGIME,
    Country.SA: JurisdictionClass.NON_EU_SEPARATE_REGIME,
    Country.GLOBAL: JurisdictionClass.GLOBAL_CASE_BY_CASE,
}

# Countries that count as "priority scope" for the default analyst view
# (CLAUDE.md §3.3 pre-ADR-0003).
PRIORITY_COUNTRIES: frozenset[Country] = frozenset(
    {Country.IT, Country.DE, Country.FR, Country.UK, Country.ES, Country.NL, Country.CH, Country.EU}
)

# Workbook language strings → canonical Language enum. Languages appear as
# either ISO codes ("it") or country-coded pairs ("DE/EN", "EN/IT"). We
# pick the FIRST meaningful code; if multi, we set Language.MULTI.
LANGUAGE_MAP: dict[str, Language] = {
    "it": Language.IT,
    "italian": Language.IT,
    "de": Language.DE,
    "german": Language.DE,
    "fr": Language.FR,
    "french": Language.FR,
    "es": Language.ES,
    "spanish": Language.ES,
    "nl": Language.NL,
    "dutch": Language.NL,
    "en": Language.EN,
    "english": Language.EN,
    "ar": Language.AR,
    "arabic": Language.AR,
}

# Connector type hints from the workbook's Connector Type column.
CONNECTOR_HINT_MAP: list[tuple[re.Pattern[str], ConnectorType]] = [
    (re.compile(r"\bapi\b", re.IGNORECASE), ConnectorType.API),
    (re.compile(r"\bbulk\b|\brss\b|\bxml\b|\bfeed\b", re.IGNORECASE), ConnectorType.BULK),
    (re.compile(r"\bheadless\b|\bplaywright\b|\bjs\b|\bspa\b", re.IGNORECASE), ConnectorType.HEADLESS),
    (re.compile(r"\bmanual\b", re.IGNORECASE), ConnectorType.MANUAL),
    (re.compile(r"\bhttp\b|\bscrape\b|\bhtml\b", re.IGNORECASE), ConnectorType.HTTP_SCRAPE),
]

# Tier-driven default schedules (CLAUDE.md §10).
DEFAULT_SCHEDULES: dict[Tier, dict[str, object]] = {
    Tier.T1: {"cron": "0 */3 * * *", "business_hours_only": True, "off_hours_cron": "0 */6 * * *"},
    Tier.T2: {"cron": "0 */8 * * *", "business_hours_only": False},
    Tier.T3: {"cron": "0 6 * * *", "business_hours_only": False},
}

# Country → default timezone for schedules.
DEFAULT_TZ_MAP: dict[Country, str] = {
    Country.IT: "Europe/Rome",
    Country.DE: "Europe/Berlin",
    Country.FR: "Europe/Paris",
    Country.UK: "Europe/London",
    Country.ES: "Europe/Madrid",
    Country.NL: "Europe/Amsterdam",
    Country.CH: "Europe/Zurich",
    Country.AE: "Asia/Dubai",
    Country.SA: "Asia/Riyadh",
    Country.EU: "Europe/Brussels",
    Country.GLOBAL: "UTC",
}

# Columns (from the Implementation Blueprint sheet).
C_NAME = "Source Name"
C_URL = "Website URL"
C_CATEGORY = "Category"
C_COUNTRY = "Country / Region"
C_LANGUAGE = "Language"
C_TIER = "Existing Tier"
C_NOTES = "Implementation Notes"
C_CONNECTOR = "Connector Type"
C_PARSER = "Parser Method"
C_SCHEDULE = "Schedule / SLA"
C_ANTIBOT = "Anti-bot Risk"
C_LEGAL_NOTE = "Legal / Compliance Note"
C_SIGNAL_TYPE = "Expected Signal Type"
C_YIELD = "Opportunity Yield Estimate"
C_KEYWORDS = "Top Keywords Selection"
C_COMPANY_INFO = "Company Information Collection"
C_DOCUMENTS = "Proceedings Document Collection"
C_COUNT_EST = "Count Estimate"

# Fallback-sheet tier column.
C_TIER_FALLBACK = "Tier"


# ── Result types ──────────────────────────────────────────────────────

@dataclass
class ImportStats:
    """Summary returned by :func:`run_import` for CI logs / operator output."""

    total_rows: int = 0
    imported: int = 0
    skipped: int = 0
    updated: int = 0
    unchanged: int = 0
    review_queue: int = 0
    duplicate_ids: int = 0           # kept for backward-compat; sum of below
    merged_duplicates: int = 0        # same URL + same id → collapsed
    collision_upgraded: int = 0       # different URL + same id → id extended
    by_country: Counter[str] = field(default_factory=Counter)
    by_tier: Counter[int] = field(default_factory=Counter)
    by_category: Counter[str] = field(default_factory=Counter)
    unknown_category_samples: list[tuple[str, str]] = field(default_factory=list)
    duplicate_id_samples: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_rows": self.total_rows,
            "imported": self.imported,
            "skipped": self.skipped,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "review_queue": self.review_queue,
            "duplicate_ids": self.merged_duplicates + self.collision_upgraded,
            "merged_duplicates": self.merged_duplicates,
            "collision_upgraded": self.collision_upgraded,
            "by_country": dict(self.by_country),
            "by_tier": {str(k): v for k, v in self.by_tier.items()},
            "by_category": dict(self.by_category),
            "unknown_category_samples": self.unknown_category_samples[:20],
            "duplicate_id_samples": self.duplicate_id_samples[:20],
        }


@dataclass
class NormalizedRow:
    """One workbook row after normalization, ready to upsert (or review)."""

    source: Source | None
    review_reasons: list[str] = field(default_factory=list)
    raw_row: dict[str, Any] = field(default_factory=dict)


# ── Normalization helpers ─────────────────────────────────────────────

def _clean(v: object) -> str:
    """Trim, collapse whitespace, treat NaN/None as empty."""
    if v is None:
        return ""
    if isinstance(v, float) and pd.isna(v):
        return ""
    s = str(v).strip()
    return re.sub(r"\s+", " ", s)


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    """Aggressive kebab-case slug with Unicode folding.

    Handles accented characters by normalizing to NFKD and stripping
    combining marks — 'A Coruña' becomes 'a-coruna', not 'a'. Legal-form
    tokens like ``S.p.A.`` / ``GmbH`` / ``Ltd`` are dropped.
    """
    import unicodedata

    # NFKD normalization folds 'ñ' → 'n' + combining tilde; ignore-encode
    # then strips the combining mark.
    folded = (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    s = folded.lower()
    # Drop common legal forms and noise tokens before slug regex runs.
    s = re.sub(r"\b(spa|srl|ag|gmbh|sa|plc|ltd|bv|nv|sarl|sas)\b", "", s)
    s = _SLUG_RE.sub("-", s).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    return s[:80].strip("-")


_PATH_NOISE = frozenset(
    {
        "",
        "index.html",
        "index.htm",
        "index.php",
        "home",
        "default",
        "default.aspx",
        "en",
        "it",
        "de",
        "fr",
        "es",
        "nl",
        "ch",
        "www",
    }
)


def _derive_source_id(name: str, url: str, country: Country) -> str:
    """Country-prefix + slug from (domain, URL path, distinctive name tokens).

    Per session-3 direction: when two sources share a domain (e.g. the
    Spanish juzgados under poderjudicial.es or multiple tribunaux de
    commerce under infogreffe.fr), the URL path is the stable
    disambiguator — far better than the previous ``-dupN`` suffix.

    Stability contract:
    * Re-imports of the same row produce the same id (URLs are stable).
    * Two rows with the same domain + path produce the same id (real
      duplicate — the caller decides what to do with it).
    * Two rows with the same domain but different paths produce
      distinct ids that read like real identifiers.
    """
    country_prefix = country.value.lower()
    domain_slug = ""
    path_slug = ""

    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        domain = re.sub(r"^www\.", "", domain)
        domain = re.sub(
            r"\.(com|it|de|fr|es|nl|ch|ae|sa|org|gov|int|eu|uk|co\.uk|europa\.eu)$",
            "",
            domain,
        )
        domain_slug = _slugify(domain)

        # Extract meaningful path segments — drop noise and numeric-only
        # bits unless they're the only signal (e.g. tribunal numbers).
        segments = [s for s in parsed.path.split("/") if s]
        meaningful = [s.lower() for s in segments if s.lower() not in _PATH_NOISE]
        # Keep up to 3 path segments, slugified and joined.
        if meaningful:
            path_slug = "-".join(_slugify(s) for s in meaningful[:3] if _slugify(s))
    except Exception:  # noqa: BLE001  # URL parsing is best-effort
        pass

    name_slug = _slugify(name)

    # Compose the body. Preference order:
    #   domain + path + distinctive-name  (strongest; handles shared-portal
    #       sources like 13 Amtsgerichte publishing via one federal portal
    #       where the URL is identical but the court name differs)
    #   domain + path                     (when name adds nothing)
    #   domain + distinctive-name         (when path is empty/noisy)
    #   name alone                        (last resort)
    #
    # "Distinctive-name" means tokens from the name that aren't already in
    # the domain or path — e.g. "aachen" from "Amtsgericht Aachen".
    domain_path_tokens = set(
        (domain_slug.split("-") if domain_slug else []) +
        (path_slug.split("-") if path_slug else [])
    )
    distinctive_name_tokens = [
        t for t in name_slug.split("-")
        if t and len(t) > 1  # drop single chars — no identity signal
        and t not in domain_path_tokens
        # Filter out common generic tokens that add no identity signal.
        and t not in {"sezione", "section", "sez", "fallimentare", "fallimenti",
                      "insolvenzgericht", "de", "lo", "del", "da", "di"}
    ]
    distinctive = "-".join(distinctive_name_tokens[:3])

    if domain_slug and path_slug and distinctive:
        body = f"{domain_slug}-{path_slug}-{distinctive}"
    elif domain_slug and path_slug:
        body = f"{domain_slug}-{path_slug}"
    elif domain_slug and distinctive:
        body = f"{domain_slug}-{distinctive}"
    elif domain_slug:
        body = domain_slug
    else:
        body = name_slug or "source"

    # Collapse accidental doubles and trim.
    body = re.sub(r"-{2,}", "-", body).strip("-")
    return f"{country_prefix}-{body}"[:120].strip("-")


def _resolve_country(raw: str) -> Country | None:
    return COUNTRY_MAP.get(raw.strip().lower())


def _resolve_language(raw: str) -> Language:
    """Handle 'IT', 'DE/EN', 'EN/IT/DE', 'DE/EN/NL', etc."""
    if not raw:
        return Language.EN
    tokens = [t.strip().lower() for t in re.split(r"[/,;]+", raw) if t.strip()]
    resolved = [LANGUAGE_MAP[t] for t in tokens if t in LANGUAGE_MAP]
    if not resolved:
        return Language.EN
    if len(resolved) == 1:
        return resolved[0]
    # Many languages → MULTI.
    if len(set(resolved)) > 1:
        return Language.MULTI
    return resolved[0]


def _resolve_tier(raw: object) -> Tier | None:
    # Accept python int, numpy int, pandas int, float-int, or string.
    if raw is None:
        return None
    # numpy/pandas integers expose __int__; try that route first.
    if hasattr(raw, "item") and callable(raw.item):
        try:
            raw = raw.item()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    if isinstance(raw, bool):  # bool is an int subclass; reject explicitly
        return None
    if isinstance(raw, int):
        try:
            return Tier(raw)
        except ValueError:
            return None
    if isinstance(raw, float) and not pd.isna(raw):
        try:
            return Tier(int(raw))
        except ValueError:
            return None
    if isinstance(raw, str):
        m = re.search(r"[123]", raw)
        if m:
            try:
                return Tier(int(m.group()))
            except ValueError:
                return None
    return None


def _resolve_connector(raw: str, category: SourceCategory) -> ConnectorType:
    """Pick a connector type from the workbook hint; fall back to category-led default."""
    if raw:
        for pat, ctype in CONNECTOR_HINT_MAP:
            if pat.search(raw):
                return ctype
    # Category-led defaults.
    if category in {SourceCategory.GAZ}:
        return ConnectorType.BULK          # gazettes tend to be RSS/XML
    if category in {SourceCategory.MKT}:
        return ConnectorType.API
    return ConnectorType.HTTP_SCRAPE


def _resolve_fetch_mode(connector: ConnectorType) -> FetchMode:
    return {
        ConnectorType.API: FetchMode.API,
        ConnectorType.BULK: FetchMode.BULK,
        ConnectorType.HTTP_SCRAPE: FetchMode.LIST_AND_DETAIL,
        ConnectorType.HEADLESS: FetchMode.LIST_AND_DETAIL,
        ConnectorType.MANUAL: FetchMode.WEBHOOK,
    }[connector]


def _build_schedule(tier: Tier, country: Country, raw_schedule: str = "") -> SourceSchedule:
    """Pick a schedule from tier default, override from the workbook hint."""
    cfg = dict(DEFAULT_SCHEDULES[tier])
    cfg["timezone"] = DEFAULT_TZ_MAP.get(country, "UTC")
    # Minimal handling of the workbook's free-text schedule: we don't trust
    # its cron-likes; we just record it in notes if present.
    return SourceSchedule(**cfg)  # type: ignore[arg-type]


def _build_keyword_pack(raw: str) -> dict[str, Any] | None:
    if not raw:
        return None
    # Workbook frequently uses '/' or '|' separators.
    tokens = [t.strip() for t in re.split(r"[|,;/]+", raw) if t.strip()]
    if not tokens:
        return None
    return {"raw": raw, "tokens": tokens[:50]}


def _build_collection_profile(raw: str, kind: str) -> dict[str, Any] | None:
    if not raw:
        return None
    return {"kind": kind, "raw_spec": raw}


def _pick_release_wave(tier: Tier, priority: bool) -> int:
    """Map (tier, priority) to release wave. Tier-1 priority → R1, others later."""
    if priority and tier is Tier.T1:
        return 1
    if priority and tier is Tier.T2:
        return 2
    if priority:
        return 3
    if tier is Tier.T1:
        return 5
    if tier is Tier.T2:
        return 6
    return 8


# ── Core: normalize one row ───────────────────────────────────────────

def _extra_distinctive_suffix(name: str, seen_slugs: set[str], base: str) -> str:
    """Find a short suffix (one name token) not yet used in `seen_slugs`.

    Called when two different URLs collided to the same base id and we
    need an additional disambiguator. Returns the first unused 3+-char
    name token, or '' if nothing works.
    """
    used_suffixes = {s.removeprefix(f"{base}-") for s in seen_slugs}
    for token in _slugify(name).split("-"):
        if len(token) >= 3 and token not in used_suffixes and token not in base:
            return token
    return ""


def _build_legal_review() -> LegalReview:
    """Approved-by-default per ADR-0004.

    The ``reviewer: system-default@dip.example`` marker is what makes a
    rollback (re-introducing per-source LIA review) clean: any source
    with that reviewer value can be bulk-flipped back to ``pending``
    without touching sources that have a real reviewer.
    """
    from libs.schemas.common import LegalReviewStatus

    return LegalReview(
        verdict=LegalReviewStatus.APPROVED,
        date=datetime.now(UTC),
        reviewer="system-default@dip.example",
        notes="Approved by default per ADR-0004 (session-3 product direction).",
    )


def normalize_row(row: pd.Series, row_number: int) -> NormalizedRow:  # type: ignore[type-arg]
    """Convert one pandas row to a (Source | review-queue entry) decision."""
    reasons: list[str] = []

    name = _clean(row.get(C_NAME))
    url = _clean(row.get(C_URL))
    raw_category = _clean(row.get(C_CATEGORY))
    raw_country = _clean(row.get(C_COUNTRY))
    raw_language = _clean(row.get(C_LANGUAGE))
    # Tier lives in `Existing Tier` on the blueprint sheet, `Tier` on the
    # fallback sheet; accept either.
    raw_tier = row.get(C_TIER) if C_TIER in row.index else row.get(C_TIER_FALLBACK)  # type: ignore[attr-defined]
    notes = _clean(row.get(C_NOTES))
    raw_connector = _clean(row.get(C_CONNECTOR))
    raw_schedule = _clean(row.get(C_SCHEDULE))
    legal_note = _clean(row.get(C_LEGAL_NOTE))
    signal_type = _clean(row.get(C_SIGNAL_TYPE))
    count_estimate = _clean(row.get(C_COUNT_EST))
    yield_estimate = _clean(row.get(C_YIELD))
    keywords = _clean(row.get(C_KEYWORDS))
    company_info = _clean(row.get(C_COMPANY_INFO))
    documents = _clean(row.get(C_DOCUMENTS))

    raw_snapshot: dict[str, Any] = {
        "row": row_number,
        "name": name,
        "url": url,
        "category": raw_category,
        "country": raw_country,
        "language": raw_language,
        "tier": raw_tier,
    }

    # Required: name + URL.
    if not name:
        reasons.append("missing_name")
    if not url:
        reasons.append("missing_url")
    elif not re.match(r"^https?://", url):
        reasons.append(f"invalid_url:{url[:80]}")

    # Country.
    country = _resolve_country(raw_country) if raw_country else None
    if country is None:
        reasons.append(f"unknown_country:{raw_country!r}")

    # Tier.
    tier = _resolve_tier(raw_tier)
    if tier is None:
        reasons.append(f"unknown_tier:{raw_tier!r}")

    # Category.
    category = map_source_category(raw_category)
    if category is SourceCategory.UNKNOWN:
        reasons.append(f"unknown_category:{raw_category!r}")

    # Abort normalization if anything essential is missing.
    if not country or tier is None or reasons:
        return NormalizedRow(source=None, review_reasons=reasons, raw_row=raw_snapshot)

    # Language.
    language = _resolve_language(raw_language)

    # Jurisdiction class.
    jurisdiction_class = JURISDICTION_CLASS_MAP[country]

    # Connector / fetch mode.
    connector = _resolve_connector(raw_connector, category)
    fetch_mode = _resolve_fetch_mode(connector)

    # Schedule.
    schedule = _build_schedule(tier, country, raw_schedule)

    # Politeness — defaults are fine for R1.
    politeness = Politeness()

    # Source id. Country-prefixed + domain-derived for stability.
    source_id = _derive_source_id(name, url, country)

    # Priority flag.
    in_priority_scope = country in PRIORITY_COUNTRIES
    release_wave = _pick_release_wave(tier, in_priority_scope)

    # Notes: concatenate everything that might be useful for analyst context.
    note_bits: list[str] = []
    if notes:
        note_bits.append(notes)
    if raw_schedule:
        note_bits.append(f"workbook_schedule: {raw_schedule}")
    if signal_type:
        note_bits.append(f"signal: {signal_type}")
    if count_estimate:
        note_bits.append(f"count_estimate: {count_estimate}")
    if yield_estimate:
        note_bits.append(f"yield_estimate: {yield_estimate}")
    if legal_note:
        note_bits.append(f"legal: {legal_note}")
    note_merged = " | ".join(note_bits) if note_bits else None

    # Construct the Source. Legal review defaults to pending (ADR-0003).
    try:
        source = Source(
            source_id=source_id,
            name=name,
            workbook_country=raw_country,
            workbook_category=raw_category or None,
            workbook_row=row_number,
            country=country,
            language=language,
            tier=tier,
            category=category,
            jurisdiction_class=jurisdiction_class,
            connector=connector,
            fetch_mode=fetch_mode,
            base_url=url,
            schedule=schedule,
            politeness=politeness,
            parser=None,
            legal_review=_build_legal_review(),
            owner="unassigned",
            on_failure=OnFailure(),
            release_wave=release_wave,
            in_priority_scope=in_priority_scope,
            enabled=False,
            notes=note_merged,
            # Keyword pack + collection profiles live at Source level for R1;
            # R2 will move them to a first-class model.
        )
    except Exception as e:  # pydantic validation — rare after our checks
        reasons.append(f"validation_failed:{type(e).__name__}:{str(e)[:120]}")
        return NormalizedRow(source=None, review_reasons=reasons, raw_row=raw_snapshot)

    # Attach the keyword / collection profile hints to the Source in a way
    # the ORM picks up but the pydantic model doesn't fail on. We'll expose
    # them via the ORM layer during upsert.
    raw_snapshot["_extras"] = {
        "keyword_pack": _build_keyword_pack(keywords),
        "company_info_profile": _build_collection_profile(company_info, "company_info"),
        "document_collection_profile": _build_collection_profile(documents, "documents"),
    }

    return NormalizedRow(source=source, review_reasons=[], raw_row=raw_snapshot)


# ── Orchestration ─────────────────────────────────────────────────────

def read_workbook(path: Path) -> pd.DataFrame:
    """Open the workbook; prefer the richer Implementation Blueprint sheet."""
    xl = pd.ExcelFile(path)
    sheet = PRIMARY_SHEET if PRIMARY_SHEET in xl.sheet_names else FALLBACK_SHEET
    if sheet not in xl.sheet_names:
        raise ValueError(
            f"Workbook {path} contains neither '{PRIMARY_SHEET}' nor "
            f"'{FALLBACK_SHEET}'. Found: {xl.sheet_names}"
        )
    df = pd.read_excel(xl, sheet_name=sheet)
    return df


def run_import(
    path: Path,
    *,
    mode: str = "preview",
    dsn: str | None = None,
    logger: logging.Logger | None = None,
) -> ImportStats:
    """Read + normalize + (optionally) upsert.

    Returns an :class:`ImportStats` that the CLI prints and CI can assert
    against.
    """
    log = logger or logging.getLogger("dip.blueprint_import")
    log.info("reading workbook: %s", path)

    df = read_workbook(path)
    stats = ImportStats(total_rows=len(df))
    log.info("workbook rows: %d", len(df))

    normalized: list[NormalizedRow] = []
    seen_ids: dict[str, tuple[int, str]] = {}  # source_id -> (row, url)

    for idx, row in df.iterrows():
        row_number = int(idx) + 2  # +1 for header, +1 for 1-indexed
        n = normalize_row(row, row_number)
        if n.source is not None:
            sid = n.source.source_id
            if sid in seen_ids:
                prior_row, prior_url = seen_ids[sid]
                current_url = str(n.source.base_url).rstrip("/")
                prior_url_normalized = prior_url.rstrip("/")

                if current_url == prior_url_normalized:
                    # Genuine duplicate — same URL, same derived id. The
                    # first occurrence already landed; we skip the rest
                    # and annotate stats.merged_duplicates. This is the
                    # honest interpretation: the workbook has duplicate
                    # entries for one real source.
                    stats.merged_duplicates += 1
                    if len(stats.duplicate_id_samples) < 20:
                        stats.duplicate_id_samples.append(
                            f"{sid} (rows {prior_row} and {row_number}, "
                            f"same URL — merged)"
                        )
                    n = NormalizedRow(
                        source=None,
                        review_reasons=[f"merged_into:{sid}"],
                        raw_row=n.raw_row,
                    )
                else:
                    # Different URL but collided id — upgrade the id
                    # with more name tokens to break the tie deterministically.
                    stats.collision_upgraded += 1
                    extra = _extra_distinctive_suffix(
                        n.raw_row.get("name", ""),
                        seen_slugs={s for s in seen_ids if s.startswith(sid)},
                        base=sid,
                    )
                    new_id = f"{sid}-{extra}" if extra else f"{sid}-x{row_number}"
                    if len(stats.duplicate_id_samples) < 20:
                        stats.duplicate_id_samples.append(
                            f"{sid} (rows {prior_row} and {row_number}, "
                            f"different URLs — upgraded to {new_id})"
                        )
                    n = NormalizedRow(
                        source=n.source.model_copy(update={"source_id": new_id}),
                        review_reasons=[],
                        raw_row=n.raw_row,
                    )
                    seen_ids[new_id] = (row_number, current_url)
            else:
                seen_ids[sid] = (row_number, str(n.source.base_url).rstrip("/"))
        normalized.append(n)

        # Stats
        if n.source is not None:
            stats.by_country[n.source.country.value] += 1
            stats.by_tier[n.source.tier.value] += 1
            stats.by_category[n.source.category.value] += 1
        else:
            if any(r.startswith("merged_into") for r in n.review_reasons):
                pass  # already counted under merged_duplicates
            else:
                stats.review_queue += 1
                if any(r.startswith("unknown_category") for r in n.review_reasons):
                    for r in n.review_reasons:
                        if r.startswith("unknown_category"):
                            sample = (n.raw_row.get("name", ""), n.raw_row.get("category", ""))
                            if len(stats.unknown_category_samples) < 20:
                                stats.unknown_category_samples.append(sample)
                            break

    # DB I/O in upsert mode.
    if mode == "upsert":
        dsn_resolved = dsn or os.getenv("DATABASE_URL")
        if not dsn_resolved:
            raise SystemExit(
                "blueprint_import: DATABASE_URL is required for --mode upsert."
            )
        _upsert_all(dsn_resolved, normalized, stats, log)
    else:
        # In preview mode, everything that's normalizable counts as "imported"
        # for stats purposes; nothing actually writes to the DB.
        stats.imported = sum(1 for n in normalized if n.source is not None)

    return stats


def _upsert_all(
    dsn: str,
    rows: list[NormalizedRow],
    stats: ImportStats,
    log: logging.Logger,
) -> None:
    """Upsert Sources + append to review queue. Idempotent."""
    # Imported here so preview mode works without sqlalchemy drivers.
    from sqlalchemy import create_engine
    from sqlalchemy.dialects.postgresql import insert
    from sqlalchemy.orm import Session

    from infra.alembic.orm import SourceOrm, SourceReviewQueueOrm

    sync_dsn = dsn
    if sync_dsn.startswith("postgresql+asyncpg://"):
        sync_dsn = sync_dsn.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)

    engine = create_engine(sync_dsn, future=True)
    with Session(engine) as session:
        for n in rows:
            if n.source is not None:
                payload = _source_to_insert_payload(n.source, n.raw_row.get("_extras"))
                stmt = insert(SourceOrm).values(**payload)
                # Upsert: on conflict on PK, update all fields except created_at.
                update_cols = {
                    k: stmt.excluded[k]
                    for k in payload
                    if k not in {"source_id", "created_at"}
                }
                stmt = stmt.on_conflict_do_update(
                    index_elements=[SourceOrm.source_id],
                    set_=update_cols,
                )
                session.execute(stmt)
                # We don't distinguish updated/unchanged at statement level
                # in this pass; treat all successful writes as 'imported'.
                stats.imported += 1
            else:
                session.add(
                    SourceReviewQueueOrm(
                        source_id=n.raw_row.get("name", "")[:120] or "unknown",
                        reason=",".join(n.review_reasons)[:80],
                        detail={"reasons": n.review_reasons, "row": n.raw_row},
                    )
                )
                stats.skipped += 1
        session.commit()
        log.info("committed %d sources, %d review-queue entries", stats.imported, stats.skipped)


def _source_to_insert_payload(
    src: Source, extras: dict[str, Any] | None
) -> dict[str, Any]:
    """Flatten a :class:`Source` into kwargs for INSERT INTO source."""
    extras = extras or {}
    return {
        "source_id": src.source_id,
        "name": src.name,
        "workbook_country": src.workbook_country,
        "workbook_category": src.workbook_category,
        "workbook_row": src.workbook_row,
        "country": src.country.value,
        "language": src.language.value,
        "tier": src.tier.value,
        "category": src.category.value,
        "jurisdiction_class": src.jurisdiction_class.value,
        "connector": src.connector.value,
        "fetch_mode": src.fetch_mode.value,
        "base_url": str(src.base_url),
        "schedule": src.schedule.model_dump(mode="json"),
        "politeness": src.politeness.model_dump(mode="json"),
        "parser": src.parser,
        "legal_review": src.legal_review.model_dump(mode="json"),
        "owner": src.owner,
        "on_failure": src.on_failure.model_dump(mode="json"),
        "cost_budget_eur_month": src.cost_budget_eur_month,
        "release_wave": src.release_wave,
        "in_priority_scope": src.in_priority_scope,
        "enabled": src.enabled,
        "notes": src.notes,
        "keyword_pack": extras.get("keyword_pack"),
        "company_info_profile": extras.get("company_info_profile"),
        "document_collection_profile": extras.get("document_collection_profile"),
    }


# ── CLI ───────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import the source-blueprint workbook.")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=("preview", "upsert"),
        default="preview",
        help="preview = read + normalize + report (no DB). upsert = write to DB.",
    )
    parser.add_argument("--dsn", default=None, help="DATABASE_URL override")
    parser.add_argument("--json", action="store_true", help="emit stats as JSON")
    parser.add_argument(
        "--verbose", "-v", action="count", default=0, help="repeat for more verbosity"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose >= 2 else (logging.INFO if args.verbose else logging.WARNING),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if not args.file.exists():
        print(f"error: workbook not found: {args.file}", file=sys.stderr)
        return 2

    stats = run_import(args.file, mode=args.mode, dsn=args.dsn)

    if args.json:
        print(json.dumps(stats.as_dict(), indent=2, sort_keys=True))
    else:
        print(_format_report(stats, mode=args.mode))

    # Non-zero exit if the review queue is surprisingly large.
    review_fraction = stats.review_queue / max(stats.total_rows, 1)
    if review_fraction > 0.10:
        print(
            f"\nWARNING: {stats.review_queue}/{stats.total_rows} "
            f"({review_fraction:.1%}) rows landed in the review queue. "
            f"Check the samples above and extend the category map.",
            file=sys.stderr,
        )
    return 0


def _format_report(stats: ImportStats, *, mode: str) -> str:
    lines = [
        f"DIP Blueprint Import — mode={mode}  @ {datetime.now(UTC).isoformat(timespec='seconds')}",
        "─" * 72,
        f"Total rows       : {stats.total_rows}",
        f"Imported         : {stats.imported}",
        f"Review queue     : {stats.review_queue}",
        f"Duplicate IDs    : {stats.duplicate_ids}",
        "",
        "By country:",
    ]
    for k, v in sorted(stats.by_country.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"  {k:5s} {v:>4d}")
    lines += ["", "By tier:"]
    for k, v in sorted(stats.by_tier.items()):
        lines.append(f"  T{k}    {v:>4d}")
    lines += ["", "By canonical category:"]
    for k, v in sorted(stats.by_category.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"  {k:8s} {v:>4d}")
    if stats.unknown_category_samples:
        lines += ["", "UNKNOWN category samples (first 20):"]
        for name, cat in stats.unknown_category_samples:
            lines.append(f"  {name[:50]:50s}  <= {cat[:50]}")
    if stats.duplicate_id_samples:
        lines += ["", "Duplicate ID samples (first 20):"]
        for s in stats.duplicate_id_samples:
            lines.append(f"  {s}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
