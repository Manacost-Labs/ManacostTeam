#!/usr/bin/env python3
"""Shared search taxonomy and normalization helpers for research bundles.

This module is imported by ``plan_queries.py``, ``search_coverage.py``,
``fetch_source.py``, and the bundle validator. It has no side effects and no
dependencies beyond the standard library.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Canonical research passes from references/search-strategy.md "Pass discipline".
QUERY_PASSES: frozenset[str] = frozenset(
    {"discovery", "collection", "gap", "contradiction", "freshness", "audit"}
)

# Canonical query families from references/search-strategy.md "Search from
# research-tree leaves". ``localized`` covers non-English or regional
# vocabulary passes that the table describes under query expansion.
QUERY_FAMILIES: frozenset[str] = frozenset(
    {
        "general",
        "primary",
        "statistics",
        "experts",
        "reddit",
        "x",
        "youtube",
        "mistakes",
        "synergies",
        "counterargument",
        "freshness",
        "localized",
    }
)

QUERY_STATUSES: frozenset[str] = frozenset(
    {"planned", "executed", "completed", "partial", "blocked", "skipped"}
)

# Families whose absence on a material branch is a coverage warning by depth.
FAMILY_MINIMUMS: dict[str, frozenset[str]] = {
    "quick": frozenset({"primary", "counterargument", "freshness"}),
    "deep": frozenset(
        {"primary", "statistics", "experts", "counterargument", "freshness", "reddit"}
    ),
    "exhaustive": frozenset(
        {
            "general",
            "primary",
            "statistics",
            "experts",
            "reddit",
            "x",
            "youtube",
            "mistakes",
            "counterargument",
            "freshness",
        }
    ),
}

CANDIDATE_DECISIONS: frozenset[str] = frozenset({"opened", "rejected", "deferred"})

CANDIDATE_REJECT_REASONS: frozenset[str] = frozenset(
    {
        "duplicate_lineage",
        "off_topic",
        "stale_version",
        "low_authority",
        "snippet_only",
        "paywalled",
        "login_required",
        "unavailable",
        "wrong_mode",
        "wrong_language",
        "already_saturated",
        "other",
    }
)

_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAMS = frozenset(
    {
        "fbclid",
        "gclid",
        "dclid",
        "msclkid",
        "yclid",
        "mc_cid",
        "mc_eid",
        "igshid",
        "ref",
        "ref_src",
        "ref_url",
        "feature",
        "si",
        "spm",
        "share_source",
        "share_medium",
        "vd_source",
    }
)
_DEFAULT_PORTS = {"http": 80, "https": 443}
_WHITESPACE_RE = re.compile(r"\s+")
_QUERY_PUNCTUATION_RE = re.compile(r"[\"'“”‘’«»]")
_MOBILE_HOST_PREFIXES = ("m.", "mobile.", "amp.")


def canonical_url(url: str) -> str:
    """Return a stable comparison form of ``url`` without changing its identity.

    Lowercases scheme and host, removes default ports, fragments, tracking
    parameters, and common mobile/AMP host prefixes, and sorts the remaining
    query parameters. The result is for deduplication and lineage hints, not
    for fetching; always fetch the URL the source actually exposes.
    """

    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = parts.hostname or ""
    host = host.lower()
    for prefix in _MOBILE_HOST_PREFIXES:
        if host.startswith(prefix) and host.count(".") >= 2:
            host = host[len(prefix) :]
            break
    if host.startswith("www."):
        host = host[4:]
    port = parts.port
    netloc = host
    if port is not None and _DEFAULT_PORTS.get(scheme) != port:
        netloc = f"{host}:{port}"
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/") or "/"
    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in _TRACKING_PARAMS and not key.startswith(_TRACKING_PARAM_PREFIXES)
    ]
    query = urlencode(sorted(kept), doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def url_host(url: str) -> str:
    return (urlsplit(canonical_url(url)).hostname or "").lower()


def lineage_hint(url: str) -> str:
    """Derive a default lineage ID from the canonical URL.

    A lineage ID identifies the upstream origin of content. When the
    researcher has not established that a page reposts another, the page is
    its own origin, so the hint is a stable digest of its canonical URL.
    """

    canonical = canonical_url(url)
    host = (urlsplit(canonical).hostname or "unknown").upper().replace(".", "-")
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8].upper()
    return f"LIN-{host}-{digest}"


def normalize_query(text: str) -> str:
    """Normalize a search query for duplicate detection."""

    lowered = _QUERY_PUNCTUATION_RE.sub("", text.strip().lower())
    return _WHITESPACE_RE.sub(" ", lowered)


def next_id(prefix: str, existing: set[str], width: int = 4) -> str:
    """Return the next ``PREFIX-0001``-style ID after the largest existing one."""

    highest = 0
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    for value in existing:
        match = pattern.match(value)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}-{highest + 1:0{width}d}"


MIN_EXCERPT_WORDS = 4
_MATCH_TRANSLATION = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "«": '"',
        "»": '"',
        "–": "-",
        "—": "-",
        "−": "-",
        " ": " ",
        "­": "",
        "…": "...",
    }
)


def normalize_for_match(text: str) -> str:
    """Normalize text for tolerant substring matching of quotes."""

    translated = text.translate(_MATCH_TRANSLATION).casefold()
    return _WHITESPACE_RE.sub(" ", translated).strip()


_ELLIPSIS_RE = re.compile(r"\s*(?:\.\.\.|…)\s*")


def quote_in_text(text: str, quote: str) -> bool:
    """Return whether ``quote`` appears in ``text`` after normalization.

    An excerpt may elide words with ``...``; each fragment must then appear in
    order, and every fragment needs at least two words so a lone token cannot
    anchor a claim.
    """

    haystack = normalize_for_match(text)
    fragments = [
        fragment.strip() for fragment in _ELLIPSIS_RE.split(normalize_for_match(quote))
    ]
    fragments = [fragment for fragment in fragments if fragment]
    if not fragments:
        return False
    if len(fragments) > 1 and any(len(fragment.split()) < 2 for fragment in fragments):
        return False
    position = 0
    for fragment in fragments:
        found = haystack.find(fragment, position)
        if found < 0:
            return False
        position = found + len(fragment)
    return True


GAME_MODE_KEYS = ("mode", "game_mode", "format", "format_name")


def infer_game_mode(context: object) -> str:
    """Map a manifest ``current_context`` to battlegrounds, constructed, arena, or all."""

    if not isinstance(context, dict):
        return "all"
    text = " ".join(
        str(context.get(key, "")) for key in GAME_MODE_KEYS if context.get(key)
    ).casefold()
    if "battleground" in text or "поля сражений" in text:
        return "battlegrounds"
    if "arena" in text or "арена" in text:
        return "arena"
    if any(word in text for word in ("standard", "wild", "twist", "constructed", "стандарт", "вольн")):
        return "constructed"
    return "all"
