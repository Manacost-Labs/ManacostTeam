"""Network receipts: was a source really retrieved, and by which tool?

A snapshot proves only that some text sits in the bundle. Decision-relevant
claims additionally need a source that a known retrieval tool fetched over the
network. A page saved by hand (``fetch_source.py --file``), a search snippet or a
hand-written record is a ``local_import`` at best and cannot carry a critical or
material claim alone. Author notes and XML replays are first-hand by nature.
"""

from __future__ import annotations

LOCAL_IMPORT = "local_import"
LOCAL_EXPERIENCE_TYPES = frozenset({"author_note", "xml_replay"})
SNIPPET_INTEGRITY = frozenset({"snippet", "search_snippet", "snippet_only"})
# Evidence that retells a search engine or WebFetch answer instead of quoting a page.
SEARCH_SUMMARY_TYPES = frozenset(
    {"search_summary", "search_snippet", "snippet", "web_search_summary", "webfetch_summary"}
)
# Tools that talk HTTP themselves: their records must carry a 2xx status.
HTTP_TOOLS = frozenset({"fetch_source.py", "curl"})
# Adapters for public APIs (Reddit, X, YouTube transcripts, Koloda stats):
# the saved response snapshot must be fingerprinted.
API_TOOLS = frozenset({"community_sources.py"})
RECEIPT_TOOLS = HTTP_TOOLS | API_TOOLS


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def is_local_import(source: dict) -> bool:
    tool = _text(source.get("retrieved_by"))
    return source.get("access_integrity") == LOCAL_IMPORT or tool.endswith("--file")


def receipt_problem(source: dict) -> str | None:
    """Return why ``source`` has no network receipt, or ``None`` when it has one."""

    if source.get("source_type") in LOCAL_EXPERIENCE_TYPES:
        return None
    if is_local_import(source):
        return "local_import (file saved outside a retrieval tool)"
    if source.get("access_integrity") in SNIPPET_INTEGRITY:
        return "search snippet, not an opened page"
    tool = _text(source.get("retrieved_by"))
    if not tool:
        return "no retrieved_by"
    name = tool.split()[0]
    if name not in RECEIPT_TOOLS:
        return f"retrieved_by {tool!r} is not a known retrieval tool"
    if name in HTTP_TOOLS:
        status = source.get("http_status")
        if not isinstance(status, int) or isinstance(status, bool) or not 200 <= status < 300:
            return f"{name} without http_status 2xx"
        if not _text(source.get("final_url")):
            return f"{name} without final_url"
    elif source.get("fingerprint_status") != "verified":
        return f"{name} response without a verified snapshot"
    return None


def record_problems(source: dict) -> list[str]:
    """Contradictions inside one source record, independent of any claim."""

    problems: list[str] = []
    tool = _text(source.get("retrieved_by"))
    if tool.endswith("--file") and source.get("access_integrity") != LOCAL_IMPORT:
        problems.append("a --file import must use access_integrity local_import")
    name = tool.split()[0] if tool else ""
    if name in HTTP_TOOLS and not tool.endswith("--file"):
        status = source.get("http_status")
        if not isinstance(status, int) or isinstance(status, bool) or not 200 <= status < 300:
            problems.append(f"{name} record needs http_status 2xx")
    return problems


def snapshot_url_mismatch(source: dict, snapshot_text: str) -> str | None:
    """``fetch_source.py`` writes ``URL: <final_url>`` into the snapshot header."""

    tool = _text(source.get("retrieved_by"))
    if not tool.startswith("fetch_source.py") or tool.endswith("--file"):
        return None
    for line in snapshot_text.splitlines()[:8]:
        if line.startswith("URL: "):
            recorded = line[len("URL: "):].strip()
            final_url = _text(source.get("final_url"))
            if recorded != final_url:
                return f"snapshot URL {recorded!r} differs from final_url {final_url!r}"
            return None
    return "fetch_source snapshot has no URL header"
