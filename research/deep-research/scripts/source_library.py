#!/usr/bin/env python3
"""Owner source checklist and durable, cache-first podcast/video transcripts."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import sysconfig
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from community_sources import (
    ProviderError,
    normalize_youtube_transcript,
    public_youtube_transcript,
    transcriptapi_get_json,
    youtube_url,
    youtube_video_id,
)
from source_access import load_credentials

SKILL_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = SKILL_ROOT / "references/domains/hearthstone-sources.json"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def library_root() -> Path:
    configured = os.environ.get("HEARTHSTONE_SOURCE_LIBRARY")
    if configured:
        return Path(configured).expanduser().resolve()
    for parent in Path(__file__).resolve().parents:
        if (parent / "teams/registry.json").is_file():
            return parent / "research/library/transcripts"
    raise ValueError(
        "Set HEARTHSTONE_SOURCE_LIBRARY to a persistent project directory."
    )


def required_sources() -> list[dict[str, Any]]:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return [
        entry
        for section in ("hosts", "creators", "communities", "chinese")
        for entry in registry.get(section, [])
        if entry.get("owner_required")
    ]


def checklist() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "sources": [
            {
                "id": item["id"],
                "urls": item["owner_urls"],
                "language": item.get("language", "und"),
                "status": "planned",
                "query": None,
                "attempted_at": None,
                "inspected_urls": [],
                "findings": [],
                "reason": None,
            }
            for item in required_sources()
        ],
    }


def coverage(plan: dict[str, Any]) -> dict[str, Any]:
    entries = plan.get("sources", [])
    ids = [entry.get("id") for entry in entries]
    required = {entry["id"] for entry in required_sources()}
    invalid: list[str] = []
    pending = sorted(required - set(ids))
    if len(set(ids)) != len(ids):
        invalid.append("duplicate source ids")
    for entry in entries:
        sid, status = entry.get("id"), entry.get("status")
        if sid not in required:
            invalid.append(f"unknown source: {sid}")
        if status == "planned":
            pending.append(sid)
        elif status not in {"inspected", "no_relevant_results", "blocked", "excluded"}:
            invalid.append(f"{sid}: invalid status")
        elif not entry.get("attempted_at") or not entry.get("query"):
            invalid.append(f"{sid}: missing actual attempt")
        elif status == "inspected" and not entry.get("inspected_urls"):
            invalid.append(f"{sid}: missing inspected material")
        elif status != "inspected" and not entry.get("reason"):
            invalid.append(f"{sid}: missing reason")
    return {
        "required": len(required),
        "pending": sorted(set(pending)),
        "invalid": invalid,
        "checklist_complete": not pending and not invalid,
        "evidence_validated": False,
    }


def public_url(value: str) -> str:
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
    ):
        raise ValueError("Expected a public HTTPS source URL without credentials.")
    if any(
        key in parts.query.lower()
        for key in ("token=", "api_key=", "signature=", "password=")
    ):
        raise ValueError(
            "Use a canonical public URL without credentials or signed parameters."
        )
    return value


def fetch_source(source_id: str, url: str) -> dict[str, Any]:
    """Reuse the existing cost-aware public Scrape.do transport; no CN inference."""
    from chinese_hearthstone import (
        ScrapeDoClient,
        SlidingWindowRateLimiter,
        SourceProfile,
    )

    source = next((s for s in required_sources() if s["id"] == source_id), None)
    if source is None:
        raise ValueError("Unknown owner source id.")
    public_url(url)
    hosts = {
        (urlsplit(u).hostname or "").removeprefix("www.") for u in source["owner_urls"]
    }
    host = (urlsplit(url).hostname or "").removeprefix("www.")
    if host not in hosts:
        raise ValueError("URL host must match the selected source.")
    if host == "youtube.com":
        raise ValueError("Use the youtube command and TranscriptAPI for transcripts.")
    client = ScrapeDoClient(rate_limiter=SlidingWindowRateLimiter(), max_rate_wait=0)
    if not client.configured:
        raise ValueError("SCRAPE_DO_API_TOKEN is not configured.")
    profile = SourceProfile(
        source_id,
        source.get("name", source_id),
        tuple(hosts),
        source.get("source_kind", "article"),
        180,
    )
    result = client.fetch(url, profile).public_dict()
    result["interpretation"] = (
        "Public extraction only; inspect topic, dates, lineage and source body."
    )
    return result


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def validate_segments(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list) or not items:
        raise ValueError("No timed transcript segments; nothing will be archived.")
    result = []
    previous = -1.0
    for item in items:
        start = float(item["start"])
        end = float(item.get("end", start + float(item.get("duration", 0))))
        text = item.get("text")
        if (
            not math.isfinite(start)
            or not math.isfinite(end)
            or start < 0
            or end < start
            or start < previous
            or not isinstance(text, str)
            or not text.strip()
        ):
            raise ValueError("Invalid transcript timing or empty text.")
        result.append({"start": start, "end": end, "text": text})
        previous = start
    return result


def archive_key(series: str, episode: str, language: str) -> str:
    if not series.strip() or not episode.strip() or not language.strip():
        raise ValueError("Series, stable episode ID/GUID and language are required.")
    return digest([series.strip(), episode.strip(), language.strip()])


def read_archive(path: Path, key: str | None = None) -> dict[str, Any]:
    record = json.loads(path.read_text(encoding="utf-8"))
    expected = record.pop("record_sha256", None)
    if (
        record.get("schema_version") != 1
        or digest(record) != expected
        or (key is not None and record.get("archive_key") != key)
    ):
        raise ValueError(
            "Archive integrity failed; inspect it before explicit --refresh."
        )
    validate_segments(record.get("segments"))
    record["record_sha256"] = expected
    return record


def write_json(path: Path, value: Any, *, overwrite: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite:
        with path.open("x", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write("\n")
        return
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write("\n")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def archive_lock(root: Path, key: str):
    root.mkdir(parents=True, exist_ok=True)
    lock = root / f".{key}.lock"
    try:
        lock.mkdir()
    except FileExistsError:
        raise ValueError(
            "Episode is already being processed; no provider call made."
        ) from None
    try:
        yield
    finally:
        lock.rmdir()


def cached_transcript(
    root: Path,
    series: str,
    episode: str,
    language: str,
    producer: Callable[[], dict[str, Any]],
    *,
    refresh: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    key = archive_key(series, episode, language)
    path = root / f"{key}.json"
    with archive_lock(root, key):
        if path.exists() and not refresh:
            return {
                "cache": "HIT",
                "path": str(path),
                "record": read_archive(path, key),
            }
        # Validate provenance before paying for or starting a transcription.
        meta = dict(metadata or {})
        if not meta.get("source_url"):
            raise ValueError("A canonical source_url is required.")
        public_url(meta["source_url"])
        produced = producer()
        segments = validate_segments(produced.get("segments"))
        if not produced.get("provider"):
            raise ValueError("Transcript provider is required.")
        record = {
            "schema_version": 1,
            "archive_key": key,
            "series": series,
            "episode_id": episode,
            "language_requested": language,
            "metadata": meta,
            "created_at": utc_now(),
            "provider": produced["provider"],
            "segments": segments,
            "transcription": {k: v for k, v in produced.items() if k != "segments"},
            "segments_sha256": digest(segments),
            "evidence_status": "inspect_segments_before_claim",
        }
        record["record_sha256"] = digest(record)
        if path.exists():
            revisions = root / "revisions"
            revisions.mkdir(exist_ok=True)
            old = path.read_bytes()
            revision = revisions / f"{key}-{hashlib.sha256(old).hexdigest()}.json"
            if not revision.exists():
                revision.write_bytes(old)
        write_json(path, record)
        return {
            "cache": "REFRESH" if refresh else "MISS",
            "path": str(path),
            "record": record,
        }


def youtube_transcript(
    root: Path,
    video: str,
    language: str = "original",
    *,
    provider: str = "transcriptapi",
    refresh: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    video_id = youtube_video_id(video)

    def produce() -> dict[str, Any]:
        lang = None if language == "original" else language
        if provider == "transcriptapi":
            raw = transcriptapi_get_json(
                "/transcript", {"video_id": video_id, "language": lang}
            )
            envelope = normalize_youtube_transcript(raw, video_id, language=lang)
        elif provider == "public-captions":
            envelope = public_youtube_transcript(video_id, language=lang)
        else:
            raise ValueError("Unknown transcript provider.")
        return {
            "provider": envelope["provider"],
            "segments": envelope["results"][0]["segments"],
            "warnings": envelope.get("warnings", []),
        }

    return cached_transcript(
        root,
        "youtube",
        video_id,
        language,
        produce,
        refresh=refresh,
        metadata={**(metadata or {}), "source_url": youtube_url(video_id)},
    )


def local_transcription(
    audio: Path, model: str, language: str, device: str
) -> dict[str, Any]:
    if not audio.is_file():
        raise ValueError("Local audio file not found.")
    # Windows CUDA wheels bundle DLLs outside the default loader search path.
    dll_handles = []
    if device == "cuda" and os.name == "nt":
        dll_dirs = list(
            (Path(sysconfig.get_paths()["purelib"]) / "nvidia").glob("*/bin")
        )
        dll_handles = [os.add_dll_directory(str(p)) for p in dll_dirs]
        os.environ["PATH"] = (
            os.pathsep.join(str(p) for p in dll_dirs)
            + os.pathsep
            + os.environ.get("PATH", "")
        )
    from faster_whisper import BatchedInferencePipeline, WhisperModel

    engine = WhisperModel(
        model, device=device, compute_type="int8" if device == "cpu" else "float16"
    )
    transcriber = BatchedInferencePipeline(engine) if device == "cuda" else engine
    options = {"batch_size": 8} if device == "cuda" else {}
    segments, info = transcriber.transcribe(
        str(audio),
        language=None if language == "original" else language,
        vad_filter=True,
        beam_size=5,
        condition_on_previous_text=False,
        **options,
    )
    timed = [
        {"start": s.start, "end": s.end, "text": s.text}
        for s in segments
        if s.text.strip()
    ]
    with audio.open("rb") as stream:
        audio_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    for handle in dll_handles:
        handle.close()
    return {
        "provider": "faster-whisper",
        "model": model,
        "device": device,
        "detected_language": info.language,
        "duration_seconds": info.duration,
        "audio_sha256": audio_hash,
        "segments": timed,
        "warnings": [
            "ASR; no speaker attribution. Verify names, numbers and negation."
        ],
    }


def parse_feed(data: bytes, feed_url: str) -> list[dict[str, Any]]:
    """RSS/Atom + Podcasting 2.0 transcript links; listing is never a transcript."""
    root = ET.fromstring(data)
    records = []
    for node in root.iter():
        if node.tag.split("}")[-1] not in {"item", "entry"}:
            continue
        fields: dict[str, str] = {}
        audio = link = None
        transcripts = []
        for child in node:
            tag = child.tag.split("}")[-1]
            fields.setdefault(tag, (child.text or "").strip())
            if tag == "link" and child.get("rel") != "enclosure":
                link = child.get("href") or child.text
            if tag == "enclosure" or tag == "link" and child.get("rel") == "enclosure":
                audio = child.get("url") or child.get("href")
            if tag == "transcript" and child.get("url"):
                transcripts.append(
                    {
                        "url": child.get("url"),
                        "type": child.get("type"),
                        "language": child.get("language"),
                    }
                )
        episode_id = fields.get("guid") or fields.get("id") or link or audio
        if episode_id:
            records.append(
                {
                    "episode_id": episode_id,
                    "title": fields.get("title"),
                    "published_at": fields.get("pubDate") or fields.get("published"),
                    "source_url": link,
                    "audio_url": audio,
                    "feed_url": feed_url,
                    "publisher_transcripts": transcripts,
                    "status": "discovery_only",
                }
            )
    return records


def search_archive(root: Path, query: str) -> list[dict[str, Any]]:
    results = []
    for path in sorted(root.glob("*.json")):
        record = read_archive(path)
        matches = [
            s for s in record["segments"] if query.casefold() in s["text"].casefold()
        ]
        if matches:
            results.append(
                {
                    "path": str(path),
                    "series": record["series"],
                    "episode_id": record["episode_id"],
                    "metadata": record["metadata"],
                    "segments": matches,
                }
            )
    return results


def export_readable(root: Path, record: dict[str, Any]) -> Path:
    """Stable readable copy; never rewrite an existing export on a cache hit."""
    path = root / f"{record['archive_key']}.md"
    if path.exists():
        return path
    meta = record.get("metadata", {})

    def clock(value: float) -> str:
        seconds = int(value)
        return f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"

    lines = [
        f"# {meta.get('title') or record['episode_id']}",
        "",
        f"Source: {meta.get('source_url')}",
        "",
        f"Published: {meta.get('published_at') or 'unknown'}",
        "",
        f"Provider: {record['provider']}. Original ASR/captions; verify names and speakers.",
        "",
    ]
    for segment in record["segments"]:
        lines.extend(
            [
                f"[{clock(segment['start'])}–{clock(segment['end'])}] {segment['text'].strip()}",
                "",
            ]
        )
    with path.open("x", encoding="utf-8") as output:
        output.write("\n".join(lines))
    return path


def main(argv: list[str] | None = None) -> int:
    load_credentials()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    plan = sub.add_parser("plan")
    plan.add_argument("output", type=Path)
    audit = sub.add_parser("coverage")
    audit.add_argument("file", type=Path)
    fetch = sub.add_parser("fetch")
    fetch.add_argument("--source", required=True)
    fetch.add_argument("--url", required=True)
    fetch.add_argument("--output", required=True, type=Path)
    feed = sub.add_parser("feed")
    feed.add_argument("--file", required=True, type=Path)
    feed.add_argument("--url", required=True)
    feed.add_argument("--output", type=Path)
    search = sub.add_parser("search")
    search.add_argument("query")
    show = sub.add_parser("show")
    show.add_argument("key")
    for name in ("youtube", "transcribe", "import"):
        command = sub.add_parser(name)
        command.add_argument("--language", default="original")
        command.add_argument("--refresh", action="store_true")
        command.add_argument("--metadata", type=Path)
        if name == "youtube":
            command.add_argument("--video", required=True)
            command.add_argument(
                "--provider",
                choices=("transcriptapi", "public-captions"),
                default="transcriptapi",
            )
        else:
            command.add_argument("--series", required=True)
            command.add_argument("--episode-id", required=True)
            command.add_argument("--source-url", required=True)
        if name == "transcribe":
            command.add_argument("--audio", required=True, type=Path)
            command.add_argument("--model", default="small")
            command.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
        if name == "import":
            command.add_argument("--file", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            result = {
                "transcriptapi_configured": bool(os.environ.get("TRANSCRIPTAPI_TOKEN")),
                "scrape_do_configured": bool(os.environ.get("SCRAPE_DO_API_TOKEN")),
                "faster_whisper_installed": importlib.util.find_spec("faster_whisper")
                is not None,
                "required_sources": len(required_sources()),
                "library": str(args.library or library_root()),
            }
        elif args.command == "plan":
            result = checklist()
            write_json(args.output, result, overwrite=False)
        elif args.command == "coverage":
            result = coverage(json.loads(args.file.read_text(encoding="utf-8")))
        elif args.command == "fetch":
            result = fetch_source(args.source, args.url)
            write_json(args.output, result)
        elif args.command == "feed":
            result = parse_feed(args.file.read_bytes(), public_url(args.url))
            if args.output:
                write_json(args.output, result)
        else:
            root = (args.library or library_root()).resolve()
            if args.command == "search":
                result = search_archive(root, args.query)
            elif args.command == "show":
                if not re.fullmatch(r"[0-9a-f]{64}", args.key):
                    raise ValueError(
                        "Expected an archive key from search or transcription output."
                    )
                result = read_archive(root / f"{args.key}.json", args.key)
            else:
                metadata = (
                    json.loads(args.metadata.read_text(encoding="utf-8"))
                    if args.metadata
                    else {}
                )
                if args.command == "youtube":
                    result = youtube_transcript(
                        root,
                        args.video,
                        args.language,
                        provider=args.provider,
                        refresh=args.refresh,
                        metadata=metadata,
                    )
                else:
                    producer = (
                        (
                            lambda: local_transcription(
                                args.audio, args.model, args.language, args.device
                            )
                        )
                        if args.command == "transcribe"
                        else (lambda: json.loads(args.file.read_text(encoding="utf-8")))
                    )
                    result = cached_transcript(
                        root,
                        args.series,
                        args.episode_id,
                        args.language,
                        producer,
                        refresh=args.refresh,
                        metadata={**metadata, "source_url": args.source_url},
                    )
                # Full copyrighted text stays in the local archive, not terminal logs.
                readable = export_readable(root, result["record"])
                result = {
                    "cache": result["cache"],
                    "path": result["path"],
                    "archive_key": result["record"]["archive_key"],
                    "segments": len(result["record"]["segments"]),
                    "readable_path": str(readable),
                }
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        if args.command == "coverage" and not result["checklist_complete"]:
            return 1
        if args.command == "fetch" and result.get("status") != "SUCCESS":
            return 1
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        ImportError,
        ET.ParseError,
        ProviderError,
    ):
        # Do not leak provider URLs, token-bearing exceptions or transcript contents.
        print(
            "Source library operation failed. Check input, credentials and runtime; archive preserved.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
