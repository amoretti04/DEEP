"""Low-level extraction primitives.

Given a raw document (HTML/XML string or parsed JSON) and a
:class:`FieldConfig`, produce an :class:`ExtractedField` — a typed value
plus its :class:`FieldProvenance`.

Kept free of domain knowledge so the framework stays reusable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from services.extract.framework.config import FieldConfig, FieldProvenance, FieldType

if TYPE_CHECKING:
    from selectolax.parser import HTMLParser, Node


# ── Result type ──────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ExtractedField:
    """One successfully (or unsuccessfully) extracted field."""

    name: str
    value: Any  # may be None if the field was optional and missing
    provenance: FieldProvenance | None
    raw_text: str | None
    error: str | None = None


# ── Selector dispatch ────────────────────────────────────────────────
#
# We use ``selectolax`` for HTML — it's far faster than BeautifulSoup and
# handles the CSS extensions we care about. For the subset we need, CSS
# selectors are sufficient; XPath is available via lxml for the small
# number of sources that need it.
#
# Extension: ``sel::text`` returns the text content of the first match.
# ``sel::attr(name)`` returns an attribute. ``sel`` alone returns the
# element's outer HTML text.

_PSEUDO_TEXT_RE = re.compile(r"::text\s*$")
_PSEUDO_ATTR_RE = re.compile(r"::attr\(([a-zA-Z0-9_\-]+)\)\s*$")


def _split_pseudo(selector: str) -> tuple[str, str | None, str | None]:
    """Return (base_selector, 'text'|None, attr_name|None)."""
    if (m := _PSEUDO_ATTR_RE.search(selector)):
        return selector[: m.start()].strip(), None, m.group(1)
    if _PSEUDO_TEXT_RE.search(selector):
        return _PSEUDO_TEXT_RE.sub("", selector).strip(), "text", None
    return selector, None, None


def _apply_css(tree: HTMLParser | Node, selector: str) -> tuple[str | None, int | None, int | None]:
    """Return ``(matched_text, start_offset, end_offset)`` or all-None if no match."""
    base, pseudo_text, attr = _split_pseudo(selector)
    # selectolax supports css_first directly.
    node = tree.css_first(base)
    if node is None:
        return (None, None, None)

    if attr is not None:
        raw = node.attributes.get(attr)
        if raw is None:
            return (None, None, None)
        # Attributes: we can't give exact byte offsets because attribute
        # values aren't round-tripped with positions in selectolax. We
        # still report raw_length.
        return (raw, None, None)

    # Text content. selectolax returns concatenated text; for provenance
    # we report start/end of the matched HTML fragment.
    text = node.text(separator=" ", strip=False)
    try:
        # selectolax Nodes don't expose byte offsets in the public API,
        # but start/end are derivable via `html` attribute in a round-trip.
        # For R2 we accept None offsets and rely on selector + raw_length.
        return (text, None, None)
    except Exception:  # noqa: BLE001
        return (text, None, None)


def _apply_xpath(xml_str: str, xpath: str) -> tuple[str | None, int | None, int | None]:
    """XPath against an lxml tree. XML-heavy sources (BODACC) use this path."""
    from lxml import etree

    try:
        tree = etree.fromstring(xml_str.encode() if isinstance(xml_str, str) else xml_str)
    except etree.XMLSyntaxError:
        return (None, None, None)
    hits = tree.xpath(xpath)
    if not hits:
        return (None, None, None)
    hit = hits[0]
    if isinstance(hit, etree._Element):
        text = (hit.text or "").strip()
    else:
        text = str(hit).strip()
    return (text or None, None, None)


def _apply_json_path(payload: Any, path: str) -> tuple[str | None, int | None, int | None]:
    """Dotted JSON path with [i] indexing. Intentionally minimal (~jq -r)."""
    token_re = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)|\[(\d+)\]")
    cur = payload
    for m in token_re.finditer(path):
        key, idx = m.group(1), m.group(2)
        try:
            if key is not None:
                if not isinstance(cur, dict):
                    return (None, None, None)
                cur = cur[key]
            elif idx is not None:
                if not isinstance(cur, list):
                    return (None, None, None)
                cur = cur[int(idx)]
        except (KeyError, IndexError):
            return (None, None, None)
    if cur is None:
        return (None, None, None)
    return (str(cur), None, None)


# ── Type conversion ──────────────────────────────────────────────────

_BOOL_FALSY: frozenset[str] = frozenset({"", "0", "false", "no", "n", "nein", "nee", "non"})


def _convert(raw: str, cfg: FieldConfig) -> tuple[Any, str | None]:
    """Return ``(value, error_message_or_None)``. raw is post-regex, pre-type."""
    if cfg.type is FieldType.STRING:
        return (raw, None)

    if cfg.type is FieldType.INTEGER:
        try:
            return (int(raw.replace(cfg.decimal_thousands, "")), None)
        except ValueError:
            return (None, f"cannot parse integer: {raw!r}")

    if cfg.type is FieldType.DECIMAL:
        cleaned = raw.replace(cfg.decimal_thousands, "").replace(cfg.decimal_point, ".")
        try:
            return (Decimal(cleaned), None)
        except InvalidOperation:
            return (None, f"cannot parse decimal: {raw!r}")

    if cfg.type is FieldType.DATE:
        fmt = cfg.date_format
        try:
            if fmt:
                return (datetime.strptime(raw, fmt).date(), None)  # noqa: DTZ007
            return (date.fromisoformat(raw), None)
        except ValueError as e:
            return (None, f"cannot parse date ({e}): {raw!r}")

    if cfg.type is FieldType.DATETIME:
        fmt = cfg.date_format
        try:
            if fmt:
                dt = datetime.strptime(raw, fmt)  # noqa: DTZ007
            else:
                dt = datetime.fromisoformat(raw)
        except ValueError as e:
            return (None, f"cannot parse datetime ({e}): {raw!r}")
        # Assume UTC if tz-naive. Parsers that know better should convert
        # before handing to the canonical normalizer.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return (dt, None)

    if cfg.type is FieldType.URL:
        return (raw, None) if raw.startswith(("http://", "https://")) else (None, f"not an http(s) URL: {raw!r}")

    if cfg.type is FieldType.BOOLEAN:
        v = raw.strip().lower()
        if v in cfg.truthy or v in {"true", "yes", "1"}:
            return (True, None)
        if v in _BOOL_FALSY:
            return (False, None)
        return (None, f"cannot parse boolean: {raw!r}")

    if cfg.type is FieldType.LIST:
        parts = [p.strip() for p in raw.split("|") if p.strip()]
        return (parts, None)

    return (raw, None)


# ── Transforms ───────────────────────────────────────────────────────
_TRANSFORMS: dict[str, callable] = {  # type: ignore[type-arg]
    "upper": str.upper,
    "lower": str.lower,
    "nullempty": lambda v: v if (v or "").strip() else None,
    "trim_punctuation": lambda v: (v or "").strip(" .,;:—–-"),
}


def _apply_transforms(value: Any, names: list[str]) -> Any:
    """Apply named transforms in order. Unknown transforms raise."""
    for name in names:
        fn = _TRANSFORMS.get(name)
        if fn is None:
            raise ValueError(f"unknown transform: {name}")
        value = fn(value)
    return value


# ── Public entry ─────────────────────────────────────────────────────

def extract_field(
    *,
    name: str,
    cfg: FieldConfig,
    tree: Any,  # HTMLParser | Node | dict | XML str — dispatched on cfg
    raw_length_hint: int | None = None,
) -> ExtractedField:
    """Run a selector + transforms + type conversion on ``tree``.

    ``tree`` must match the selector kind: HTML selectors run against a
    ``selectolax`` tree, XPath against an lxml-parsable XML string,
    json_path against a parsed Python object.
    """
    raw_text: str | None
    start: int | None
    end: int | None

    if cfg.selector:
        raw_text, start, end = _apply_css(tree, cfg.selector)
        selector_str = cfg.selector
    elif cfg.xpath:
        raw_text, start, end = _apply_xpath(tree, cfg.xpath)
        selector_str = f"xpath={cfg.xpath}"
    elif cfg.json_path:
        raw_text, start, end = _apply_json_path(tree, cfg.json_path)
        selector_str = f"jsonpath={cfg.json_path}"
    else:
        return ExtractedField(
            name=name, value=None, provenance=None, raw_text=None,
            error="no selector configured",
        )

    if raw_text is None:
        if cfg.required:
            return ExtractedField(
                name=name, value=None, provenance=None, raw_text=None,
                error=f"required field {name} not found via {selector_str}",
            )
        return ExtractedField(
            name=name, value=cfg.default, provenance=None, raw_text=None,
        )

    # Regex post-process (first capture group wins).
    if cfg.regex is not None:
        m = re.search(cfg.regex, raw_text, re.DOTALL)
        if not m:
            if cfg.required:
                return ExtractedField(
                    name=name, value=None, provenance=None, raw_text=raw_text,
                    error=f"regex {cfg.regex!r} did not match",
                )
            return ExtractedField(
                name=name, value=cfg.default, provenance=None, raw_text=raw_text,
            )
        raw_text = m.group(1) if m.groups() else m.group(0)

    if cfg.strip and isinstance(raw_text, str):
        raw_text = raw_text.strip()

    value, err = _convert(raw_text, cfg)
    if err:
        return ExtractedField(
            name=name, value=None, provenance=None, raw_text=raw_text, error=err,
        )

    # Transforms (on the typed value, as strings only).
    if cfg.transforms:
        try:
            value = _apply_transforms(value, cfg.transforms)
        except Exception as e:  # noqa: BLE001
            return ExtractedField(
                name=name, value=None, provenance=None, raw_text=raw_text,
                error=f"transform failed: {e}",
            )

    prov = FieldProvenance(
        field_name=name,
        selector=selector_str,
        start_offset=start,
        end_offset=end,
        raw_length=raw_length_hint if raw_length_hint is not None
                   else (len(raw_text) if raw_text is not None else None),
        transforms=list(cfg.transforms),
        confidence=1.0,
    )
    return ExtractedField(name=name, value=value, provenance=prov, raw_text=raw_text)
