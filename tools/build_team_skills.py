#!/usr/bin/env python3
"""Build portable, deterministic team skills and a Claude/OpenAI plugin."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote, unquote

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
}
TEXT = {
    ".md",
    ".py",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".ts",
    ".js",
    ".mjs",
    ".txt",
    ".tsv",
    ".toml",
}


def load_registry(root: Path) -> list[dict]:
    entries = json.loads(
        (root / "teams" / "registry.json").read_text(encoding="utf-8")
    )["skills"]
    names = [entry["name"] for entry in entries]
    if len(names) != len(set(names)):
        raise ValueError("duplicate skill name in registry")
    for name in names:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
            raise ValueError(f"invalid skill name: {name}")
    return entries


def confined(root: Path, relative: str) -> Path:
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"resource escapes its root: {relative}")
    return path


def copy_resource(source: Path, destination: Path) -> dict[Path, Path]:
    if not source.exists():
        raise ValueError(f"missing package resource: {source}")
    files = sorted(source.rglob("*")) if source.is_dir() else [source]
    mapping = {}
    for file in files:
        relative = file.relative_to(source) if source.is_dir() else Path(file.name)
        if any(part in IGNORED for part in relative.parts) or file.suffix in {
            ".pyc",
            ".pyo",
        }:
            continue
        if file.is_symlink():
            raise ValueError(f"symlink is not a portable resource: {file}")
        if not file.is_file():
            continue
        target = destination / relative if source.is_dir() else destination
        if target.name.lower() == "skill.md":
            target = target.with_name("WORKFLOW.md")
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = file.read_bytes()
        if file.suffix.lower() in TEXT:
            payload = payload.replace(b"\r\n", b"\n")
        if target.exists() and target.read_bytes() != payload:
            raise ValueError(f"resource destination collision: {target}")
        target.write_bytes(payload)
        mapping[file.resolve()] = target
    return mapping


def rewrite_resource_links(
    root: Path, destination: Path, mapping: dict[Path, Path]
) -> None:
    """Resolve source-relative links after relocating a supporting workflow."""
    for original, packaged in mapping.items():
        if packaged.suffix.lower() != ".md":
            continue

        def replacement(match, original=original, packaged=packaged):
            link = match.group(1)
            if "://" in link or link.startswith(("#", "mailto:")):
                return match.group(0)
            path, separator, fragment = link.partition("#")
            source_target = (original.parent / unquote(path)).resolve()
            target = mapping.get(source_target)
            if target is None:
                candidate = destination / unquote(path)
                if candidate.exists() and candidate.resolve().is_relative_to(
                    destination.resolve()
                ):
                    target = candidate
            if target is not None:
                relative = Path(os.path.relpath(target, packaged.parent)).as_posix()
                return (
                    "](" + relative + (separator + fragment if separator else "") + ")"
                )
            if source_target.exists() and source_target.is_relative_to(root.resolve()):
                kind = "tree" if source_target.is_dir() else "blob"
                public_path = quote(
                    source_target.relative_to(root.resolve()).as_posix(), safe="/"
                )
                return (
                    "](https://github.com/Manacost-Labs/ManacostTeam/"
                    + kind
                    + "/main/"
                    + public_path
                    + (separator + fragment if separator else "")
                    + ")"
                )
            return match.group(0)

        content = packaged.read_text(encoding="utf-8")
        packaged.write_text(
            re.sub(r"\]\(([^)]+)\)", replacement, content),
            encoding="utf-8",
            newline="\n",
        )


def validate_bundle(directory: Path) -> None:
    files = [path for path in directory.rglob("*") if path.is_file()]
    entrypoints = [path for path in files if path.name.lower() == "skill.md"]
    if entrypoints != [directory / "SKILL.md"]:
        raise ValueError("a skill must contain exactly one root SKILL.md")
    if len(files) > 500:
        raise ValueError(f"skill exceeds 500 files: {len(files)}")
    content = (directory / "SKILL.md").read_text(encoding="utf-8")
    if not content.startswith("---\n") or not re.search(
        r"(?m)^name: [a-z0-9-]+$", content
    ):
        raise ValueError("invalid skill frontmatter/name")
    if not re.search(r"(?m)^description: .+", content):
        raise ValueError("skill description is required")
    for file in files:
        relative = file.relative_to(directory)
        if file.is_symlink() or any(part in IGNORED for part in relative.parts):
            raise ValueError(f"unsafe package resource: {relative}")
        if (
            file.name == ".env"
            or file.name.startswith(".env.")
            or file.suffix in {".pyc", ".pyo"}
        ):
            raise ValueError(f"private/cache file in package: {relative}")
        if file.stat().st_size > 25 * 1024 * 1024:
            raise ValueError(f"file exceeds project package limit: {relative}")
    if sum(file.stat().st_size for file in files) > 100 * 1024 * 1024:
        raise ValueError("unpacked skill exceeds project limit of 100 MiB")
    for markdown in [path for path in files if path.suffix.lower() == ".md"]:
        prose = re.sub(
            r"(?ms)^```.*?^```[^\n]*", "", markdown.read_text(encoding="utf-8")
        )
        for link in re.findall(r"\]\(([^)]+)\)", prose):
            if "://" in link or link.startswith(("#", "mailto:", "/")):
                continue
            path = unquote(link.split("#", 1)[0])
            # Templates deliberately show symbolic citation/placeholder syntax.
            if (
                path in {"URL", "SOURCE_URL", "DIRECT_URL", "source-url", "url"}
                or "{{" in path
            ):
                continue
            linked = (markdown.parent / path).resolve()
            if not linked.is_relative_to(directory.resolve()) or not linked.exists():
                raise ValueError(
                    f"missing bundled reference in {markdown.relative_to(directory)}: {link}"
                )


def write_zip(
    directory: Path, archive: Path, prefix: str, *, skill: bool = True
) -> str:
    if skill:
        validate_bundle(directory)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for file in sorted(path for path in directory.rglob("*") if path.is_file()):
            info = zipfile.ZipInfo(f"{prefix}/{file.relative_to(directory).as_posix()}")
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, file.read_bytes())
    if archive.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("archive exceeds project limit of 50 MiB")
    return hashlib.sha256(archive.read_bytes()).hexdigest()


def assemble(root: Path, entry: dict, destination: Path) -> None:
    source = confined(root, entry["source"])
    destination.mkdir(parents=True)
    mapping = {}
    # This is the sole actual skill entrypoint; auxiliary skills become workflows.
    for file in sorted(source.rglob("*")):
        if not file.is_file() or any(
            part in IGNORED for part in file.relative_to(source).parts
        ):
            continue
        target = destination / file.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = file.read_bytes()
        if file.suffix.lower() in TEXT:
            payload = payload.replace(b"\r\n", b"\n")
        target.write_bytes(payload)
        mapping[file.resolve()] = target
    for resource in entry.get("resources", []):
        mapping.update(
            copy_resource(
                confined(root, resource["source"]),
                confined(destination, resource["destination"]),
            )
        )
    rewrite_resource_links(root, destination, mapping)
    validate_bundle(destination)
    declared = re.search(
        r"(?m)^name: (.+)$", (destination / "SKILL.md").read_text(encoding="utf-8")
    )
    if declared.group(1) != entry["name"]:
        raise ValueError(f"registry/entrypoint name mismatch: {entry['name']}")
    files = {
        path.relative_to(destination).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(destination.rglob("*"))
        if path.is_file()
    }
    manifest = {
        "team": entry["team"],
        "skill": entry["name"],
        "version": entry["version"],
        "source": entry["source"],
        "files": files,
    }
    (destination / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    validate_bundle(destination)


def build(root: Path, output: Path, *, check: bool = False) -> dict:
    entries = load_registry(root)
    registry = json.loads(
        (root / "teams" / "registry.json").read_text(encoding="utf-8")
    )
    version = registry["release_version"]
    with tempfile.TemporaryDirectory(prefix="manacost-team-skills-") as temporary:
        staging = Path(temporary)
        plugin = staging / "manacost-team"
        skills = plugin / "skills"
        skills.mkdir(parents=True)
        built = staging / "archives"
        checksums = {}
        for entry in entries:
            destination = skills / entry["name"]
            assemble(root, entry, destination)
            base = f"{entry['name']}-{entry['version']}"
            checksums[base + ".zip"] = write_zip(
                destination, built / (base + ".zip"), entry["name"]
            )
            shutil.copyfile(built / (base + ".zip"), built / (base + ".skill"))
            checksums[base + ".skill"] = checksums[base + ".zip"]
        metadata = {
            "name": "manacost-team",
            "version": version,
            "description": "Seven Manacost teams and context-aware Hearthstone card shortcodes.",
            "author": {"name": "Manacost Labs"},
            "repository": "https://github.com/Manacost-Labs/ManacostTeam",
        }
        (plugin / ".claude-plugin").mkdir()
        (plugin / ".claude-plugin" / "plugin.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        metadata["$schema"] = (
            "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
        )
        (plugin / "plugin.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        plugin_name = f"manacost-team-{version}-plugin.zip"
        checksums[plugin_name] = write_zip(
            plugin, built / plugin_name, "manacost-team", skill=False
        )
        sums = "".join(
            f"{digest}  {name}\n" for name, digest in sorted(checksums.items())
        )
        (built / "SHA256SUMS").write_text(sums, encoding="utf-8", newline="\n")
        index = {
            "version": version,
            "teams": len({entry["team"] for entry in entries}),
            "skills": len(entries),
            "archives": checksums,
        }
        (built / "index.json").write_text(
            json.dumps(index, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        if check:
            for file in built.iterdir():
                installed = output / file.name
                if not installed.is_file():
                    raise ValueError(
                        f"release archive missing: {file.name}; build the release first"
                    )
                if installed.read_bytes() != file.read_bytes():
                    raise ValueError(f"release differs from sources: {file.name}")
        else:
            output.mkdir(parents=True, exist_ok=True)
            for file in built.iterdir():
                target = output / file.name
                if target.is_file() and target.read_bytes() != file.read_bytes():
                    raise ValueError(
                        f"published archive is immutable; bump version: {file.name}"
                    )
                shutil.copyfile(file, target)
    return index


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    registry = json.loads(
        (ROOT / "teams" / "registry.json").read_text(encoding="utf-8")
    )
    output = (
        args.output or ROOT / "release" / "team-skills" / registry["release_version"]
    )
    try:
        result = build(ROOT, output, check=args.check)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"package error: {exc}\n")
    print(
        f"{result['teams']} teams; {result['skills']} portable skills; reproducible archives verified"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
