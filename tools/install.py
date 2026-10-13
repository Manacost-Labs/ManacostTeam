#!/usr/bin/env python3
"""Install released agent skills, a server configuration, or the WordPress plugin."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import secrets
import stat
import zipfile
from pathlib import Path, PurePosixPath

import build_team_skills as packages
from resolve_context import ROOT, resolve_context


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def install_files(directory: Path, files: dict[str, bytes]) -> None:
    """Preflight the whole selection; preserve existing files, including edited skills."""
    directory = directory.resolve()
    for relative, payload in files.items():
        path = directory / relative
        if not path.is_relative_to(directory) or ".." in Path(relative).parts:
            raise ValueError("unsafe destination")
        for parent in (path, *path.parents):
            if parent.is_symlink():
                raise ValueError(f"symlink destination is not supported: {parent}")
        if path.exists() and (not path.is_file() or path.read_bytes() != payload):
            raise ValueError(
                f"existing file differs; install into a new directory: {path}"
            )
    for relative, payload in files.items():
        path = directory / relative
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as output:
                output.write(payload)
            if relative == ".env" or relative.startswith("secrets/"):
                path.chmod(0o600)


def unpack_skill(payload: bytes, name: str) -> dict[str, bytes]:
    files = {}
    portable_names = set()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        entries = archive.infolist()
        if len(entries) > 500 or sum(e.file_size for e in entries) > 100 * 1024 * 1024:
            raise ValueError("skill exceeds package limits")
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if (
                not path.parts
                or path.is_absolute()
                or path.parts[0] != name
                or any(
                    part in ("", ".", "..")
                    for part in entry.filename.rstrip("/").split("/")
                )
                or "\\" in entry.filename
                or stat.S_ISLNK(entry.external_attr >> 16)
                or entry.file_size > 25 * 1024 * 1024
            ):
                raise ValueError("unsafe archive member")
            if not entry.is_dir():
                if entry.filename.casefold() in portable_names:
                    raise ValueError("duplicate archive member")
                portable_names.add(entry.filename.casefold())
                files[entry.filename] = archive.read(entry)
    if f"{name}/SKILL.md" not in files:
        raise ValueError("skill has no entrypoint")
    return files


def install_agent(directory: Path, client: str, names: list[str], game: str) -> dict:
    entries = {entry["name"]: entry for entry in packages.load_registry(ROOT)}
    if (
        not names
        or len(set(names)) != len(names)
        or any(name not in entries for name in names)
    ):
        raise ValueError("select unique skill names from teams/registry.json")
    registry = json.loads((ROOT / "teams/registry.json").read_text())
    release = ROOT / "release/team-skills" / registry["release_version"]
    manifest = json.loads((release / "index.json").read_text())
    prefix = {"codex": ".agents/skills/", "claude": ".claude/skills/", "generic": ""}[
        client
    ]
    context = resolve_context(ROOT, game=game)
    files = {}
    installed = {}
    for name in names:
        filename = f"{name}-{entries[name]['version']}.zip"
        payload = (release / filename).read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if manifest["archives"].get(filename) != digest:
            raise ValueError(f"archive checksum mismatch: {filename}")
        files.update(
            {prefix + path: data for path, data in unpack_skill(payload, name).items()}
        )
        installed[name] = {"version": entries[name]["version"], "sha256": digest}
    # The context is explicit: no existing AGENTS.md or client configuration is edited.
    files[".manacost/context.json"] = json_bytes(context)
    files[".manacost/install.json"] = json_bytes(
        {"release": registry["release_version"], "client": client, "skills": installed}
    )
    install_files(directory, files)
    return {"directory": str(directory.absolute()), "skills": names, "game": game}


def install_server(directory: Path, game: str, port: int) -> dict:
    context = resolve_context(ROOT, game=game, execution="server")
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    secret = directory / "secrets/api-token.txt"
    if secret.is_symlink():
        raise ValueError("token file must not be a symlink")
    token = (
        secret.read_bytes()
        if secret.is_file()
        else (secrets.token_urlsafe(32) + "\n").encode()
    )
    compose = (
        (ROOT / "deploy/compose.yaml")
        .read_text()
        .replace("@@ROOT@@", json.dumps(str(ROOT)))
    )
    files = {
        "compose.yaml": compose.encode(),
        ".env": f"MANACOST_GAME={game}\nMANACOST_PORT={port}\nMANACOST_BIND=127.0.0.1\nEDITOR_PROVIDER=none\nEDITOR_MODEL=\nEDITOR_API_KEY=\nEDITOR_BASE_URL=\n".encode(),
        "secrets/api-token.txt": token,
        "context.json": json_bytes(context),
    }
    install_files(directory, files)
    return {
        "directory": str(directory.absolute()),
        "game": game,
        "api": f"http://127.0.0.1:{port}",
        "token_file": str(secret.absolute()),
        "start": "docker compose up -d --build",
    }


def wordpress_files() -> dict[str, bytes]:
    source = ROOT / "integrations/wordpress/manacost-team"
    return {
        f"manacost-team/{path.relative_to(source).as_posix()}": path.read_bytes()
        for path in sorted(source.rglob("*"))
        if path.is_file()
    }


def wordpress_zip(path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, payload in wordpress_files().items():
            info = zipfile.ZipInfo(filename, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, payload)
    install_files(path.parent, {path.name: buffer.getvalue()})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    agent = commands.add_parser(
        "agent", help="install portable skills into another project"
    )
    agent.add_argument("--directory", type=Path, required=True)
    agent.add_argument(
        "--client", choices=("codex", "claude", "generic"), default="codex"
    )
    agent.add_argument("--skills", default="editor-team,translate-team")
    agent.add_argument("--game", default="hearthstone")
    server = commands.add_parser(
        "server", help="prepare Docker Compose; does not start containers"
    )
    server.add_argument("--directory", type=Path, required=True)
    server.add_argument("--game", default="hearthstone")
    server.add_argument("--port", type=int, default=8800)
    wordpress = commands.add_parser(
        "wordpress", help="install the plugin or create an uploadable ZIP"
    )
    target = wordpress.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--directory", type=Path, help="WordPress wp-content/plugins directory"
    )
    target.add_argument("--zip", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "agent":
            result = install_agent(
                args.directory, args.client, args.skills.split(","), args.game
            )
        elif args.command == "server":
            result = install_server(args.directory, args.game, args.port)
        elif args.zip:
            wordpress_zip(args.zip)
            result = {"zip": str(args.zip.absolute())}
        else:
            install_files(args.directory, wordpress_files())
            result = {
                "plugin_directory": str(args.directory.absolute() / "manacost-team")
            }
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
