#!/usr/bin/env python3
"""Ждёт завершения остальных проверок коммита и падает, если хоть одна упала.

Читает check runs коммита через GitHub REST API (нужен `checks: read`).
Свои check runs (имя задаётся --self) пропускает. Только стандартная
библиотека: на сервере не нужно ставить зависимости.

Переменные: GITHUB_TOKEN, GITHUB_REPOSITORY, GITHUB_API_URL (необязательно).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

OK = {"success", "neutral", "skipped"}


def fetch_check_runs(api: str, repo: str, sha: str, token: str) -> list[dict]:
    runs: list[dict] = []
    page = 1
    while True:
        url = f"{api}/repos/{repo}/commits/{sha}/check-runs?per_page=100&page={page}"
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
            payload = json.load(response)
        batch = payload.get("check_runs", [])
        runs.extend(batch)
        if len(runs) >= payload.get("total_count", 0) or not batch:
            return runs
        page += 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sha")
    parser.add_argument("--self", dest="own", action="append", default=[],
                        help="имя собственного check run, которое нужно пропустить")
    parser.add_argument("--timeout", type=int, default=2700, help="секунд всего")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--grace", type=int, default=60,
                        help="секунд подождать, чтобы проверки успели появиться")
    args = parser.parse_args()

    token = os.environ["GITHUB_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    own = set(args.own)

    time.sleep(args.grace)
    deadline = time.monotonic() + args.timeout
    while True:
        runs = [r for r in fetch_check_runs(api, repo, args.sha, token) if r["name"] not in own]
        pending = [r["name"] for r in runs if r["status"] != "completed"]
        failed = [f'{r["name"]} ({r["conclusion"]})' for r in runs
                  if r["status"] == "completed" and r["conclusion"] not in OK]
        if failed:
            print("CI коммита не прошёл, деплой отменён:", *failed, sep="\n  ", file=sys.stderr)
            return 1
        if not pending:
            print(f"CI коммита зелёный: {len(runs)} проверок (без учёта деплоя).")
            return 0
        if time.monotonic() >= deadline:
            print("Не дождался CI:", *pending, sep="\n  ", file=sys.stderr)
            return 1
        print(f"Жду {len(pending)} проверок: {', '.join(sorted(pending)[:5])}", flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
