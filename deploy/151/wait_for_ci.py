#!/usr/bin/env python3
"""Ждёт CI коммита: обязательные workflow блокируют деплой, остальные — нет.

Читает workflow runs коммита через GitHub REST API (`actions: read`).
Обязательные workflow (--required) должны завершиться успешно, если они
запускались для этого коммита (у CI фильтры путей, поэтому отсутствие — норма).
Падение прочих workflow выводится как предупреждение: от поломки деплоя
защищают health-check и откат в deploy.sh. Свой workflow (--self) пропускается.

Только стандартная библиотека. Переменные: GITHUB_TOKEN, GITHUB_REPOSITORY,
GITHUB_API_URL (необязательно).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

OK = {"success", "neutral", "skipped"}


def fetch_runs(api: str, repo: str, sha: str, token: str) -> list[dict]:
    url = f"{api}/repos/{repo}/actions/runs?head_sha={sha}&per_page=100"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "deploy-151-ci-gate",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        runs = json.load(response).get("workflow_runs", [])
    latest: dict[str, dict] = {}
    for run in runs:  # повторные запуски: берём последний по каждому workflow
        name = run["name"]
        if name not in latest or run["run_attempt"] >= latest[name]["run_attempt"]:
            latest[name] = run
    return list(latest.values())


def classify(runs: list[dict], required: set[str]) -> tuple[list[str], list[str], list[str]]:
    pending = [r["name"] for r in runs if r["name"] in required and r["status"] != "completed"]
    failed = [f'{r["name"]} ({r["conclusion"]})' for r in runs
              if r["name"] in required and r["status"] == "completed" and r["conclusion"] not in OK]
    advisory = [f'{r["name"]} ({r["conclusion"]})' for r in runs
                if r["name"] not in required and r["status"] == "completed"
                and r["conclusion"] not in OK]
    return pending, failed, advisory


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sha")
    parser.add_argument("--self", dest="own", action="append", default=[],
                        help="имя собственного workflow, которое нужно пропустить")
    parser.add_argument("--required", action="append", default=[],
                        help="workflow, падение которого отменяет деплой")
    parser.add_argument("--timeout", type=int, default=2700, help="секунд всего")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--grace", type=int, default=60,
                        help="секунд подождать, чтобы workflow успели появиться")
    args = parser.parse_args()

    token = os.environ["GITHUB_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    own, required = set(args.own), set(args.required)

    time.sleep(args.grace)
    deadline = time.monotonic() + args.timeout
    while True:
        runs = [r for r in fetch_runs(api, repo, args.sha, token) if r["name"] not in own]
        pending, failed, advisory = classify(runs, required)
        if failed:
            print("Обязательный CI не прошёл, деплой отменён:", *failed, sep="\n  ", file=sys.stderr)
            return 1
        if not pending:
            for item in advisory:
                print(f"::warning::CI не блокирует деплой, но упал: {item}")
            seen = sorted(r["name"] for r in runs if r["name"] in required)
            print(f"Обязательный CI зелёный: {', '.join(seen) or 'не запускался для этого коммита'}.")
            return 0
        if time.monotonic() >= deadline:
            print("Не дождался CI:", *pending, sep="\n  ", file=sys.stderr)
            return 1
        print(f"Жду: {', '.join(sorted(pending))}", flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
