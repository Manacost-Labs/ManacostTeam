#!/usr/bin/env python3
"""Turn reader-question gaps into bounded search actions, never factual approval."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import community_sources as community
import source_access
from candidates import record_candidate
from plan_queries import (
    apply_budget,
    load_json,
    load_jsonl,
    question_queue,
    request_key,
    utc_now,
)
from search_coverage import reader_questions, source_followups

PLATFORMS = {"web", "reddit", "x", "youtube"}


def route(record: dict) -> dict:
    sites = re.findall(r"(?:^|\s)site:([^\s]+)", record["query"], re.IGNORECASE)
    if len(set(sites)) > 1:
        raise ValueError("use one explicit site per targeted search")
    site = sites[0].lower().removeprefix("www.") if sites else None
    if site and not re.fullmatch(r"[a-z0-9.-]+", site):
        raise ValueError("site scope must be a hostname without a path")
    platform = request_key(record)[0]
    if (
        site
        and platform != "web"
        and request_key({"query": "site:" + site})[0] != platform
    ):
        raise ValueError("declared platform conflicts with site scope")
    if platform not in PLATFORMS:
        raise ValueError("unsupported target_platform")
    return {
        "platform": platform,
        "site": site,
        "provider": {
            "web": "scrape.do",
            "reddit": "redditapi",
            "x": "getxapi",
            "youtube": "transcriptapi",
        }[platform],
    }


def fingerprint(record: dict) -> str:
    payload = {key: value for key, value in record.items() if key != "planned_at"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def next_step(
    root: Path, languages: list[str] | None = None, max_queries: int | None = None
) -> dict:
    root = Path(root)
    manifest = load_json(root / "manifest.json")
    plan = load_json(root / "plan.json") if (root / "plan.json").is_file() else {}
    questions = reader_questions(plan)
    executed, planned, sources = (
        load_jsonl(root / name)
        for name in ("queries.jsonl", "query-plan.jsonl", "sources.jsonl")
    )
    unresolved = [
        q
        for q in questions + source_followups(executed, sources, questions)
        if q.get("status", "open") not in {"answered", "excluded"}
    ]
    defaults = {"quick": 10, "deep": 30, "exhaustive": 60}
    depth = manifest.get("depth", "deep")
    if depth not in defaults:
        raise ValueError("invalid research depth")
    languages = languages or (
        ["en", "ru"] if "hearthstone" in manifest.get("domain_adapters", []) else ["en"]
    )
    budget_config = plan.get("research_budget", {})
    if not isinstance(budget_config, dict):
        raise TypeError("research_budget must be an object")
    budget = (
        max_queries
        if max_queries is not None
        else budget_config.get("max_queries", defaults[depth])
    )
    if budget is None:
        budget = defaults[depth]
    queue = apply_budget(
        question_queue(plan, executed, sources, planned, languages, []),
        executed,
        planned,
        budget,
    )
    context_hash = hashlib.sha256(
        json.dumps(
            {"manifest": manifest, "plan": plan}, sort_keys=True, ensure_ascii=False
        ).encode()
    ).hexdigest()
    interrupted = [
        q["query_id"]
        for q in queue
        if (root / "search-results" / f"{q['query_id']}.attempt.json").exists()
    ]
    tasks = []
    for query in queue:
        if query["query_id"] in interrupted:
            continue
        routing = route(query)
        task_hash = hashlib.sha256(
            (fingerprint(query) + context_hash).encode()
        ).hexdigest()
        tasks.append(
            {
                "query": query,
                "query_sha256": task_hash,
                "route": routing,
                "command": [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "search",
                    str(root.resolve()),
                    "--query-id",
                    query["query_id"],
                    "--query-sha256",
                    task_hash,
                    *[arg for lang in languages for arg in ("--language", lang)],
                    "--max-queries",
                    str(budget),
                ],
            }
        )
    return {
        "status": "needs_reader_questions"
        if not questions
        else "search_required"
        if tasks
        else "interrupted_search"
        if interrupted
        else "unresolved_no_search"
        if unresolved
        else "questions_answered",
        "factual_approval": False,
        "max_queries": budget,
        "tasks": tasks,
        "unresolved_questions": unresolved,
        "interrupted_query_ids": interrupted,
        "instructions": "Для каждой главы уточни решение читателя, причину выбора, условие и исключение по применимости. "
        "Выполни следующий поиск; результаты — discovery-only. Открой подходящие материалы прежним Collector/fetch_source.py, "
        "сохрани source IDs и подтверждённые evidence. После чтения запиши observations.summary, novelty с evidence_ids "
        "и followup_questions с parent_question_id и реальными EN/RU search_phrases, затем вызови next повторно. "
        "Не придумывай ответы, цитаты, игровые ситуации или переводы названий. Не повторяй сбой автоматически. "
        "Исчерпанный бюджет не закрывает пробел. Обход 39 источников, независимость и factual gates остаются отдельными требованиями.",
    }


def write_new(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    path.chmod(0o600)


def execute_search(
    root: Path,
    query_id: str,
    *,
    expected_sha256: str,
    languages: list[str] | None = None,
    max_queries: int | None = None,
) -> dict:
    root = Path(root)
    if root.is_symlink() or any(
        (root / name).is_symlink()
        for name in (
            "queries.jsonl",
            "query-plan.jsonl",
            "candidates.jsonl",
            "search-results",
        )
    ):
        raise ValueError("symlink output paths are forbidden")
    if not re.fullmatch(r"QRY-[A-Za-z0-9-]+", query_id):
        raise ValueError("invalid query_id")
    lock = root / ".reader-search.lock"
    with lock.open("x"):
        pass
    try:
        executed = load_jsonl(root / "queries.jsonl")
        if any(q.get("query_id") == query_id for q in executed):
            raise ValueError(
                "query already attempted; choose a new direction, not an automatic retry"
            )
        task = next(
            (
                t
                for t in next_step(root, languages, max_queries)["tasks"]
                if t["query"]["query_id"] == query_id
            ),
            None,
        )
        if task is None:
            raise ValueError(
                "query not in the current bounded queue or already reserved"
            )
        if expected_sha256 != task["query_sha256"]:
            raise ValueError(
                "stale query task; regenerate next before spending a request"
            )
        query, routing = task["query"], task["route"]
        directory = root / "search-results"
        directory.mkdir(exist_ok=True)
        write_new(
            directory / f"{query_id}.attempt.json",
            {
                "query": query,
                "query_sha256": expected_sha256,
                "started_at": utc_now(),
                "status": "attempt_reserved_not_evidence",
            },
        )
        # Freeze the chosen query before the provider call; no source/claim is created.
        if not any(
            q.get("query_id") == query_id for q in load_jsonl(root / "query-plan.jsonl")
        ):
            with (root / "query-plan.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(query, ensure_ascii=False) + "\n")
        phrase = re.sub(r"(?:^|\s)site:[^\s]+", " ", query["query"]).strip()
        try:
            if routing["platform"] == "web":
                payload = source_access.search(
                    phrase, site=routing["site"], language=query["language"]
                )
            else:
                args = community.build_parser().parse_args(
                    [routing["platform"] + "-search", "--query", phrase]
                )
                payload = community.execute(args)
            status = "executed" if payload.get("results") else "completed"
        except (source_access.AccessError, community.ProviderError) as exc:
            payload, status = (
                {"provider": routing["provider"], "error": str(exc), "results": []},
                "blocked",
            )
        relative = f"search-results/{query_id}.json"
        write_new(root / relative, payload)
        record = {
            **query,
            "status": status,
            "executed_at": utc_now(),
            "provider": routing["provider"],
            "target_platform": routing["platform"],
            "result_status": "no_results" if status == "completed" else status,
            "result_source_ids": [],
            "search_snapshot": relative,
            "search_sha256": hashlib.sha256((root / relative).read_bytes()).hexdigest(),
        }
        with (root / "queries.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        for result in payload.get("results", []):
            url = result.get("url") or result.get("source_url")
            if not isinstance(url, str):
                continue
            try:
                source_access.public_url(url)
            except source_access.AccessError:
                continue
            record_candidate(
                root,
                query_id=query_id,
                url=url,
                title=result.get("title"),
                rank=result.get("position"),
                decision="deferred",
                note="Search discovery only; body not inspected",
            )
        return record
    finally:
        lock.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("next", "search"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--language", choices=("en", "ru", "zh"), action="append")
    parser.add_argument("--max-queries", type=int)
    parser.add_argument("--query-id")
    parser.add_argument("--query-sha256")
    args = parser.parse_args()
    try:
        if args.command == "next":
            result = next_step(args.directory, args.language, args.max_queries)
        else:
            if not args.query_id or not args.query_sha256:
                raise ValueError("search requires query-id and query-sha256 from next")
            result = execute_search(
                args.directory,
                args.query_id,
                expected_sha256=args.query_sha256,
                languages=args.language,
                max_queries=args.max_queries,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if args.command == "search" and result["status"] == "blocked" else 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
