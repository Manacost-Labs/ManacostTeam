"""Pinned local Windows analyzers; binaries and receipts stay outside Git.

Install with Python 3.14 (stdlib zstd), uv, Node >=22 and Go available.
No global PATH edits, administrator access, shell scripts from the network,
or silent fallback to an incomplete analyzer.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EDITOR = ROOT / "editor"
DEFAULT = ROOT / "build/editor-windows-tools"
HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def command(args, **kwargs):
    return subprocess.run([str(arg) for arg in args], creationflags=HIDDEN, check=True, **kwargs)


def download(package, base):
    destination = base / "downloads" / package["url"].rsplit("/", 1)[-1]
    if (
        not destination.exists()
        or hashlib.sha256(destination.read_bytes()).hexdigest() != package["sha256"]
    ):
        request = urllib.request.Request(
            package["url"], headers={"User-Agent": "ManacostTeam-local-tools"}
        )
        temporary = destination.with_suffix(".part")
        digest = hashlib.sha256()
        with (
            urllib.request.urlopen(request, timeout=120) as response,
            temporary.open("wb") as output,
        ):
            while chunk := response.read(1 << 20):
                output.write(chunk)
                digest.update(chunk)
        if digest.hexdigest() != package["sha256"]:
            raise RuntimeError("SHA256 mismatch: " + package["name"])
        temporary.replace(destination)
    return destination


def install(args):
    if os.name != "nt" or sys.version_info < (3, 14):
        raise RuntimeError("Install requires Windows and Python >=3.14 for zstd archives")
    base = args.root.resolve()
    base.mkdir(parents=True, exist_ok=True)
    state = base / "running.json"
    if state.exists() and json.loads(state.read_text(encoding="utf-8-sig")):
        raise RuntimeError(
            "Run Start-EditorTools.ps1 -Action Stop before installing into this runtime"
        )
    (base / "downloads").mkdir(exist_ok=True)
    packages = json.loads((EDITOR / "config/windows-toolchain.lock.json").read_text())
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        archives = list(pool.map(lambda package: download(package, base), packages))
    # Packages share the MinGW directory; extraction is deliberately sequential.
    for package, archive in zip(packages, archives, strict=True):
        target = (base / package["target"]).resolve()
        target.mkdir(exist_ok=True)
        if package["archive"] == "zip":
            with zipfile.ZipFile(archive) as content:
                for entry in content.namelist():
                    if not (target / entry).resolve().is_relative_to(target):
                        raise RuntimeError("Archive path outside destination")
                content.extractall(target)
        else:
            with tarfile.open(archive) as content:
                content.extractall(target, filter="data")
    uv = args.uv or shutil.which("uv")
    node = args.node or shutil.which("node")
    go = args.go or shutil.which("go")
    if not all((uv, node, go)):
        raise RuntimeError("Provide --uv, --node and --go, or put them on PATH")
    node = Path(node).resolve()
    if (
        int(
            subprocess.check_output([str(node), "--version"], text=True)
            .strip()
            .lstrip("v")
            .split(".")[0]
        )
        < 22
    ):
        raise RuntimeError("Markdownlint requires Node >=22")
    python = base / "nlp-venv/Scripts/python.exe"
    if not python.exists():
        command([uv, "venv", "--python", "3.12", python.parents[1]])
    command(
        [
            uv,
            "pip",
            "sync",
            "--python",
            python,
            "--require-hashes",
            EDITOR / "sidecars/nlp/requirements.lock",
        ]
    )
    npm = node.parent / "node_modules/npm/bin/npm-cli.js"
    markdown = base / "markdownlint"
    markdown.mkdir(exist_ok=True)
    for name in ("package.json", "package-lock.json"):
        shutil.copy2(EDITOR / "config/windows-markdownlint" / name, markdown / name)
    command([node, npm, "ci", "--prefix", markdown, "--ignore-scripts", "--no-audit", "--no-fund"])
    launcher = base / "markdownlint.exe"
    command(
        [go, "build", "-trimpath", "-o", launcher, "./cmd/markdownlint-launcher"], cwd=EDITOR / "go"
    )
    save(
        Path(str(launcher) + ".json"),
        {
            "Node": str(node),
            "Script": str(markdown / "node_modules/markdownlint-cli/markdownlint.js"),
        },
    )
    hunspell = base / "hunspell.exe"
    command(
        [go, "build", "-trimpath", "-o", hunspell, "./cmd/hunspell-launcher"], cwd=EDITOR / "go"
    )
    save(Path(str(hunspell) + ".json"), {"Binary": str(base / "hunspell/mingw64/bin/hunspell.exe")})
    environment = {
        "NATASHA_URL": "http://127.0.0.1:8742",
        "LANGUAGETOOL_URL": "http://127.0.0.1:8010",
        "HUNSPELL_BIN": str(hunspell),
        "RU_DICT_PATH": str(base / "dictionary/ru_RU.dic"),
        "VALE_BIN": str(base / "vale/vale.exe"),
        "VALE_CONFIG": str(EDITOR / ".vale.ini"),
        "MARKDOWNLINT_BIN": str(launcher),
        "MARKDOWNLINT_CONFIG": str(EDITOR / "config/markdownlint/.markdownlint.json"),
        "EDITOR_ALLOW_UNAVAILABLE": "false",
        "PYTHONUTF8": "1",
    }
    save(base / "environment.json", environment)
    save(
        base / "services.json",
        [
            {
                "name": "natasha",
                "exe": str(python),
                "args": [
                    str(EDITOR / "sidecars/nlp/server.py"),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8742",
                ],
                "port": 8742,
            },
            {
                "name": "languagetool",
                "exe": str(next((base / "java").glob("*/bin/java.exe"))),
                "args": [
                    "-Xmx768m",
                    "-cp",
                    str(base / "languagetool/LanguageTool-6.6/languagetool-server.jar"),
                    "org.languagetool.server.HTTPServer",
                    "--port",
                    "8010",
                ],
                "port": 8010,
            },
        ],
    )
    save(
        base / "installation.json",
        {
            "packages": packages,
            "markdownlint": "0.49.1",
            "natasha_lock_sha256": hashlib.sha256(
                (EDITOR / "sidecars/nlp/requirements.lock").read_bytes()
            ).hexdigest(),
            "python": subprocess.check_output([str(python), "--version"], text=True).strip(),
        },
    )
    print("Installed. Start services with editor/tools/Start-EditorTools.ps1", flush=True)


def request(url, body=None, form=False):
    data = None
    headers = {}
    if body is not None:
        data = (urllib.parse.urlencode(body) if form else json.dumps(body)).encode()
        headers["Content-Type"] = (
            "application/x-www-form-urlencoded" if form else "application/json"
        )
    with urllib.request.urlopen(
        urllib.request.Request(url, data=data, headers=headers), timeout=30
    ) as response:
        return json.load(response)


def check(args):
    base = args.root.resolve()
    env = json.loads((base / "environment.json").read_text(encoding="utf-8"))
    health = request(env["NATASHA_URL"] + "/health")
    if not health.get("complete") or health.get("natasha", {}).get("status") != "ok":
        raise RuntimeError("Natasha is not complete: " + json.dumps(health))
    nlp = request(
        env["NATASHA_URL"] + "/analyze",
        {
            "text": "Игроки получили награды. Игроки получили награды.",
            "language": "ru-RU",
            "game": "hearthstone",
            "profile": "news",
        },
    )
    if not nlp.get("meta", {}).get("complete") or not nlp.get("tokens"):
        raise RuntimeError("Natasha analysis degraded or returned no tokens")
    lt = request(
        env["LANGUAGETOOL_URL"] + "/v2/check",
        {"language": "ru-RU", "text": "Это это пример."},
        form=True,
    )
    if not lt.get("matches"):
        raise RuntimeError("LanguageTool produced no finding for a duplicate word")
    hunspell = command(
        [env["HUNSPELL_BIN"], "-a", "-d", str(Path(env["RU_DICT_PATH"]).with_suffix(""))],
        input="сабака\n",
        text=True,
        encoding="utf-8",
        capture_output=True,
    ).stdout
    if "сабака" not in hunspell or "собака" not in hunspell:
        raise RuntimeError("Hunspell did not use the Russian dictionary: " + hunspell)
    with tempfile.TemporaryDirectory(prefix="editorteam-toolcheck-") as directory:
        sample = Path(directory) / "input.news.md"
        sample.write_text(
            "В этой статье будет рассмотрен важный момент.\n\n# Заголовок\n### Пропущен уровень\n",
            encoding="utf-8",
        )
        vale = subprocess.run(
            [env["VALE_BIN"], "--output=JSON", "--config=" + env["VALE_CONFIG"], str(sample)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            creationflags=HIDDEN,
            timeout=30,
        )
        vale_findings = json.loads(vale.stdout)
        if not any(vale_findings.values()):
            raise RuntimeError("Vale did not produce an editorial finding")
        markdown = subprocess.run(
            [
                env["MARKDOWNLINT_BIN"],
                "--json",
                "--config",
                env["MARKDOWNLINT_CONFIG"],
                str(sample),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            creationflags=HIDDEN,
            timeout=30,
        )
        md_findings = json.loads(markdown.stdout or markdown.stderr)
        if not md_findings:
            raise RuntimeError("Markdownlint did not detect the skipped heading level")
    receipt = {
        "natasha": health,
        "nlp_sample": nlp,
        "hunspell": hunspell,
        "languagetool": lt,
        "vale": vale_findings,
        "markdownlint": md_findings,
    }
    save(base / "smoke-check.json", receipt)
    print("All five analyzers returned real results; smoke-check.json saved", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "check"))
    parser.add_argument("--root", type=Path, default=DEFAULT)
    parser.add_argument("--uv")
    parser.add_argument("--go")
    parser.add_argument("--node")
    options = parser.parse_args()
    {"install": install, "check": check}[options.action](options)
