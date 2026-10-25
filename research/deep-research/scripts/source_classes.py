#!/usr/bin/env python3
"""Map a source URL to one recall/coverage source class.

The classes are the lanes the recall benchmark scores and the coverage map
reports: ``official``, ``statistics``, ``reddit``, ``x``, ``youtube``,
``chinese``, ``podcast`` and ``web`` for everything else. Hosts come from the
Hearthstone source registry, so a venue added there is classified everywhere.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

SOURCE_CLASSES = ("official", "statistics", "reddit", "x", "youtube", "chinese", "podcast", "web")
REGISTRY = Path(__file__).resolve().parents[1] / "references/domains/hearthstone-sources.json"

PLATFORM_HOSTS = {
    "x": ("x.com", "twitter.com"),
    "reddit": ("reddit.com", "redd.it"),
    "youtube": ("youtube.com", "youtu.be"),
}
REGISTRY_CLASSES = {
    "official": "official",
    "official_social": "official",
    "statistics": "statistics",
    "podcast": "podcast",
}
# Venues outside the registry that are still unambiguous for the lanes.
EXTRA_HOSTS = {
    "playhearthstone.com": "official",
    "news.blizzard.com": "official",
    "eu.forums.blizzard.com": "official",
    "www.firestoneapp.com": "statistics",
    "firestoneapp.com": "statistics",
    "www.d0nkey.top": "statistics",
    "www.vicioussyndicate.com": "statistics",
    "www.heartharena.com": "statistics",
    "lushi.163.com": "chinese",
    "hs.blizzard.cn": "chinese",
    "space.bilibili.com": "chinese",
    "ngabbs.com": "chinese",
    "podcasts.apple.com": "podcast",
    "open.spotify.com": "podcast",
    "anchor.fm": "podcast",
    "podcasters.spotify.com": "podcast",
    "feeds.libsyn.com": "podcast",
}
# Path-specific venues win over their host class.
PATH_CLASSES = (
    ("www.vicioussyndicate.com", "/data-reaper-podcast", "podcast"),
    ("www.vicioussyndicate.com", "/vs-data-reaper-podcast", "podcast"),
    ("www.vicioussyndicate.com", "/category/data-reaper-podcast", "podcast"),
    ("open.spotify.com", "/episode", "podcast"),
    ("open.spotify.com", "/show", "podcast"),
)
# The registry lists Vicious Syndicate for its podcast; its Data Reaper reports
# are statistics, so the host defaults there and podcast paths win above.
HOST_OVERRIDES = {"vicioussyndicate.com": "statistics"}
SOURCE_TYPE_CLASSES = {"podcast": "podcast", "podcast_episode": "podcast"}


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _matches(host: str, domain: str) -> bool:
    domain = domain.lower().removeprefix("www.")
    bare = host.removeprefix("www.")
    return bare == domain or bare.endswith("." + domain)


@lru_cache(maxsize=1)
def registry_hosts() -> tuple[tuple[str, str], ...]:
    """(host, class) pairs; the Chinese section wins over a generic class."""
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    pairs: list[tuple[str, str]] = []
    for entry in data.get("chinese", []):
        if entry.get("host"):
            pairs.append((entry["host"].lower(), "chinese"))
    for entry in data.get("hosts", []):
        language = str(entry.get("language", ""))
        if entry.get("host") and language.lower().startswith("zh-cn"):
            pairs.append((entry["host"].lower(), "chinese"))
        mapped = REGISTRY_CLASSES.get(str(entry.get("class")))
        if entry.get("host") and mapped:
            pairs.append((entry["host"].lower(), mapped))
    pairs.extend(EXTRA_HOSTS.items())
    return tuple(pairs)


def source_class(url: str, source_type: str | None = None) -> str:
    """Return the lane for a URL. Order: Chinese, podcast, platform, registry."""
    host = _host(url)
    path = urlsplit(url).path if host else ""
    if source_type in SOURCE_TYPE_CLASSES:
        return SOURCE_TYPE_CLASSES[source_type]
    for domain, prefix, value in PATH_CLASSES:
        if _matches(host, domain) and path.startswith(prefix):
            return value
    for domain, value in HOST_OVERRIDES.items():
        if _matches(host, domain):
            return value
    pairs = registry_hosts()
    for wanted in ("chinese", "podcast"):
        if any(value == wanted and _matches(host, domain) for domain, value in pairs):
            return wanted
    for platform, domains in PLATFORM_HOSTS.items():
        if any(_matches(host, domain) for domain in domains):
            return platform
    for domain, value in pairs:
        if _matches(host, domain):
            return value
    return "web"


# Executor lane of a query: explicit ``executor``, Chinese language, or family.
FAMILY_EXECUTOR = {
    "primary": "official",
    "freshness": "official",
    "statistics": "statistics",
    "reddit": "reddit",
    "x": "x",
    "youtube": "youtube",
}


def query_lane(record: dict) -> str:
    if record.get("executor") in SOURCE_CLASSES:
        return str(record["executor"])
    if record.get("language") == "zh":
        return "chinese"
    return FAMILY_EXECUTOR.get(str(record.get("family")), "web")

