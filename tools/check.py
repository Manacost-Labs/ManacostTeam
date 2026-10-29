#!/usr/bin/env python3
"""Запуск существующих проверок выбранной области из любого рабочего каталога."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def unit_tests(directory: str = "tests", pattern: str = "test_*.py") -> list[str]:
    return [
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        directory,
        "-p",
        pattern,
        "-v",
    ]


# Область: описание, рабочий каталог относительно ROOT, команды без shell.
# Модульные CI остаются источником полного набора проверок и требований к среде.
CHECKS = {
    "root": (
        "Все корневые тесты: контракты, упаковка, workflows",
        ".",
        [
            unit_tests(),
        ],
    ),
    "context": (
        "Общий task_context, игры и профили",
        ".",
        [
            unit_tests(pattern="test_context_resolution.py"),
        ],
    ),
    "server": (
        "Серверный API",
        ".",
        [
            unit_tests(pattern="test_server_api.py"),
        ],
    ),
    "install": (
        "Установщик и WordPress",
        ".",
        [
            unit_tests(pattern="test_installation.py"),
            unit_tests(pattern="test_wordpress_plugin.py"),
        ],
    ),
    "packages": (
        "Переносимые пакеты и сверка релизного манифеста",
        ".",
        [
            unit_tests(pattern="test_team_packages.py"),
            unit_tests(pattern="test_release_*.py"),
            [sys.executable, "tools/build_team_skills.py", "--check"],
        ],
    ),
    "funmeta": (
        "Локальный workflow /funmeta",
        ".",
        [
            unit_tests(pattern="test_funmeta*.py"),
        ],
    ),
    "meta-report": (
        "Локальный workflow /meta-report",
        ".",
        [
            unit_tests(pattern="test_meta_report.py"),
        ],
    ),
    "hero-guides": (
        "Проверки текста коротких гайдов",
        ".",
        [
            unit_tests(pattern="test_battlegrounds_hero_guides.py"),
        ],
    ),
    "editorial": (
        "Общий каталог редакционных практик Python/Go",
        ".",
        [
            unit_tests(pattern="test_editorial_practices_catalog.py"),
            [sys.executable, "tools/sync_editorial_practices.py", "--check"],
        ],
    ),
    "research": (
        "ResearchTeam: unit-тесты и аудит skill",
        "research",
        [
            unit_tests("deep-research/tests"),
            [sys.executable, "deep-research/scripts/audit_skill.py"],
        ],
    ),
    "translate": ("TranslateTeam: unit-тесты", "translate", [unit_tests()]),
    "editor": (
        "EditorTeam: pytest в выбранном Python-окружении",
        "editor",
        [
            [sys.executable, "-m", "pytest", "-q"],
        ],
    ),
    "editor-go": ("EditorTeam: Go-тесты", "editor/go", [["go", "test", "./..."]]),
    "xml": (
        "XMLTeam: TypeScript и тесты; нужны pnpm и node_modules",
        "XMLTeam",
        [
            ["pnpm", "run", "typecheck"],
            ["pnpm", "run", "test"],
        ],
    ),
}


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("areas", nargs="*", metavar="AREA", help="Области из --list")
    parser.add_argument("--list", action="store_true", help="Показать области")
    parser.add_argument(
        "--dry-run", action="store_true", help="Показать команды без запуска"
    )
    args = parser.parse_args(argv)
    unknown = sorted(set(args.areas) - CHECKS.keys())
    if unknown:
        parser.error(f"Неизвестные области: {', '.join(unknown)}. См. --list.")
    if args.list:
        if args.areas or args.dry_run:
            parser.error("--list используется отдельно от областей и --dry-run")
        for name, (description, _, _) in CHECKS.items():
            print(f"{name:14} {description}")
        return 0
    if not args.areas:
        parser.error("Укажите область проверки или --list")

    for area in dict.fromkeys(args.areas):
        description, directory, commands = CHECKS[area]
        print(f"\n[{area}] {description}", flush=True)
        for command in commands:
            display = (
                subprocess.list2cmdline(command)
                if os.name == "nt"
                else shlex.join(command)
            )
            print(f"  cwd: {ROOT / directory}\n  {display}", flush=True)
            if args.dry_run:
                continue
            executable = shutil.which(command[0])
            if executable is None:
                print(f"Не найден исполняемый файл: {command[0]}", file=sys.stderr)
                return 127
            try:
                result = subprocess.run(
                    [executable, *command[1:]], cwd=ROOT / directory, check=False
                )
            except OSError as error:
                print(f"Не удалось запустить {area}: {error}", file=sys.stderr)
                return 1
            if result.returncode:
                print(
                    f"Проверка {area} завершилась с кодом {result.returncode}.",
                    file=sys.stderr,
                )
                return result.returncode if result.returncode > 0 else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
