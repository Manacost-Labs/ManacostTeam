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
BINARY = {
    ".zip",
    ".skill",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".woff",
    ".woff2",
    ".otf",
    ".ttf",
    ".pdf",
    ".gz",
    ".tgz",
}
VERSION = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")


def portable_bytes(file: Path) -> bytes:
    """Normalize UTF-8 text, including extensionless LICENSE/METADATA files."""
    payload = file.read_bytes()
    if file.suffix.lower() in BINARY or b"\0" in payload:
        return payload
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError:
        return payload
    return payload.replace(b"\r\n", b"\n")


def load_registry(root: Path) -> list[dict]:
    registry = json.loads(
        (root / "teams" / "registry.json").read_text(encoding="utf-8")
    )
    if (
        not isinstance(registry, dict)
        or type(registry.get("schema_version")) is not int
        or registry["schema_version"] != 1
    ):
        raise ValueError("registry requires schema_version 1")
    release = registry.get("release_version")
    if not isinstance(release, str) or not VERSION.fullmatch(release):
        raise ValueError(
            "registry requires a release_version in MAJOR.MINOR.PATCH form"
        )
    entries = registry.get("skills")
    if not isinstance(entries, list) or not entries:
        raise ValueError("registry skills must be a nonempty array")
    for entry in entries:
        if not isinstance(entry, dict):
            raise TypeError("registry skill must be an object")
        for field in ("name", "team", "module", "source", "version"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise ValueError(f"registry skill requires a nonempty {field}")
        if not VERSION.fullmatch(entry["version"]):
            raise ValueError(f"invalid skill version: {entry['name']}")
        for field in ("module", "source"):
            confined(root, entry[field])
        resources = entry.get("resources", [])
        if not isinstance(resources, list):
            raise TypeError(f"{entry['name']}: resources must be an array")
        for resource in resources:
            if not isinstance(resource, dict) or any(
                not isinstance(resource.get(field), str) or not resource[field].strip()
                for field in ("source", "destination")
            ):
                raise ValueError(
                    f"{entry['name']}: resource requires source and destination"
                )
    names = [entry["name"] for entry in entries]
    if len(names) != len(set(names)):
        raise ValueError("duplicate skill name in registry")
    for name in names:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
            raise ValueError(f"invalid skill name: {name}")
    return entries


def scalar(content: str, field: str, *, indent: int = 0) -> str | None:
    """Read a scalar from the project's simple name/version metadata format."""
    matches = re.findall(
        rf"(?m)^{' ' * indent}{re.escape(field)}:[ \t]*([^\n]+)$", content
    )
    if len(matches) != 1:
        return None
    value = matches[0].strip()
    quoted = re.fullmatch(r'"([^"\n]+)"|\x27([^\x27\n]+)\x27|([^\s#"\x27]+)', value)
    return (
        next((item for item in quoted.groups() if item is not None), None)
        if quoted
        else None
    )


def validate_metadata(source: Path, entry: dict) -> None:
    content = (source / "SKILL.md").read_text(encoding="utf-8")
    parts = content.split("---\n", 2)
    if len(parts) != 3 or parts[0]:
        raise ValueError(f"{entry['name']}: invalid SKILL.md frontmatter")
    metadata = (source / "skill.yaml").read_text(encoding="utf-8")
    expected = {
        "name": entry["name"],
        "version": entry["version"],
        "team": entry["team"],
        "entrypoint": "SKILL.md",
    }
    for field, value in expected.items():
        if scalar(metadata, field) != value:
            raise ValueError(
                f"{entry['name']}: skill.yaml {field} differs from registry"
            )
    if scalar(parts[1], "name") != entry["name"]:
        raise ValueError(f"{entry['name']}: SKILL.md name differs from registry")
    if scalar(parts[1], "version", indent=2) != entry["version"]:
        raise ValueError(
            f"{entry['name']}: SKILL.md metadata version differs from registry"
        )


def confined(root: Path, relative: str) -> Path:
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"resource escapes its root: {relative}")
    return path


def copy_resource(source: Path, destination: Path) -> dict[Path, Path]:
    if not source.exists():
        raise ValueError(f"missing package resource: {source}")
    files = (
        sorted(source.rglob("*"), key=lambda path: path.relative_to(source).as_posix())
        if source.is_dir()
        else [source]
    )
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
        payload = portable_bytes(file)
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
        for file in sorted(
            (path for path in directory.rglob("*") if path.is_file()),
            key=lambda path: path.relative_to(directory).as_posix(),
        ):
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
    validate_metadata(source, entry)
    destination.mkdir(parents=True)
    mapping = {}
    # This is the sole actual skill entrypoint; auxiliary skills become workflows.
    for file in sorted(
        source.rglob("*"), key=lambda path: path.relative_to(source).as_posix()
    ):
        if file.is_symlink():
            raise ValueError(f"symlink is not a portable resource: {file}")
        if not file.is_file() or any(
            part in IGNORED for part in file.relative_to(source).parts
        ):
            continue
        target = destination / file.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(portable_bytes(file))
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
    files = {
        path.relative_to(destination).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(
            destination.rglob("*"),
            key=lambda path: path.relative_to(destination).as_posix(),
        )
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


def verify_release(built: Path, output: Path) -> None:
    """Require the exact file inventory as well as reproducible bytes."""
    if not output.is_dir():
        raise ValueError("release directory missing; build the release first")
    expected = {file.name for file in built.iterdir()}
    actual = {file.name for file in output.iterdir()}
    if expected != actual:
        missing, extra = sorted(expected - actual), sorted(actual - expected)
        raise ValueError(
            f"release inventory differs: missing={missing}; unexpected={extra}"
        )
    for file in sorted(built.iterdir()):
        installed = output / file.name
        if not installed.is_file() or installed.read_bytes() != file.read_bytes():
            raise ValueError(f"release differs from sources: {file.name}; bump version")


def publish_release(built: Path, output: Path, history: Path, *, check: bool) -> None:
    """Preflight every archive and publish a complete new directory in one rename."""
    archives = [file for file in built.iterdir() if file.suffix in {".zip", ".skill"}]
    if history.is_dir():
        for release in sorted(history.iterdir()):
            if not VERSION.fullmatch(release.name) or not release.is_dir():
                continue
            for archive in archives:
                previous = release / archive.name
                if previous.exists() and (
                    not previous.is_file()
                    or previous.read_bytes() != archive.read_bytes()
                ):
                    raise ValueError(
                        f"published archive is immutable across releases; bump version: "
                        f"{release.name}/{archive.name}"
                    )
    if check or output.exists():
        verify_release(built, output)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}-", dir=output.parent
    ) as temporary:
        staged = Path(temporary)
        for file in built.iterdir():
            shutil.copyfile(file, staged / file.name)
        if output.exists():
            raise ValueError(
                "release directory appeared during publication; retry verification"
            )
        staged.rename(output)


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
        publish_release(built, output, root / "release" / "team-skills", check=check)
    return index


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        load_registry(ROOT)
        registry = json.loads(
            (ROOT / "teams" / "registry.json").read_text(encoding="utf-8")
        )
        output = (
            args.output
            or ROOT / "release" / "team-skills" / registry["release_version"]
        )
        result = build(ROOT, output, check=args.check)
    except (ValueError, TypeError, OSError) as exc:
        parser.exit(1, f"package error: {exc}\n")
    print(
        f"{result['teams']} teams; {result['skills']} portable skills; reproducible archives verified"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
