#!/usr/bin/env python3
"""Publish team-skill archives as GitHub Release assets; git tracks only manifests.

Dry run by default: prints the plan. --execute creates the release v<version> and
uploads assets through `gh`. Published assets are verified by SHA256 against the
tracked manifest and are never replaced.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import build_team_skills as builder

ROOT = builder.ROOT
REPOSITORY = "Manacost-Labs/ManacostTeam"
HISTORY = ROOT / "release/team-skills"


def run(*command: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8"
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"{' '.join(command[:3])} failed: {result.stderr.strip()}")
    return result


def manifest_digests(manifest: Path) -> dict[str, str]:
    """Asset name -> SHA256 for the archives and the manifest files themselves."""
    index = json.loads((manifest / "index.json").read_text(encoding="utf-8"))
    sums = "".join(
        f"{digest}  {name}\n" for name, digest in sorted(index["archives"].items())
    )
    if (manifest / "SHA256SUMS").read_text(encoding="utf-8") != sums:
        raise ValueError(f"{manifest.name}: SHA256SUMS differs from index.json")
    digests = dict(index["archives"])
    for name in builder.MANIFEST_FILES:
        digests[name] = builder.sha256(manifest / name)
    return digests


def local_assets(manifest: Path, archives: Path, digests: dict[str, str]) -> dict:
    files = {}
    for name, digest in sorted(digests.items()):
        file = (manifest if name in builder.MANIFEST_FILES else archives) / name
        if not file.is_file():
            raise ValueError(f"{manifest.name}: archive missing locally: {file}")
        if builder.sha256(file) != digest:
            raise ValueError(f"{manifest.name}: archive differs from manifest: {file}")
        files[name] = file
    return files


def manifest_commit(manifest: Path) -> str:
    """The pushed commit holding this manifest becomes the release tag target."""
    relative = manifest.relative_to(ROOT).as_posix()
    if run("git", "status", "--porcelain", "--", relative).stdout.strip():
        raise ValueError(f"commit the manifest first: {relative}")
    commit = run(
        "git", "log", "-1", "--format=%H", "--", f"{relative}/index.json"
    ).stdout.strip()
    if not commit:
        raise ValueError(f"manifest is not committed: {relative}")
    if not run("git", "branch", "-r", "--contains", commit).stdout.strip():
        raise ValueError(f"push commit {commit[:12]} before publishing {relative}")
    return commit


def remote_digests(tag: str) -> dict[str, str] | None:
    result = run(
        "gh", "release", "view", tag, "--repo", REPOSITORY, "--json", "assets",
        check=False,
    )
    if result.returncode != 0:
        if "release not found" in result.stderr:
            return None
        raise RuntimeError(f"gh release view {tag} failed: {result.stderr.strip()}")
    digests = {}
    for asset in json.loads(result.stdout)["assets"]:
        digest = asset.get("digest") or ""
        if not digest.startswith("sha256:"):
            with tempfile.TemporaryDirectory() as temporary:
                run(
                    "gh", "release", "download", tag, "--repo", REPOSITORY,
                    "--pattern", asset["name"], "--dir", temporary,
                )
                digest = "sha256:" + builder.sha256(Path(temporary) / asset["name"])
        digests[asset["name"]] = digest.removeprefix("sha256:")
    return digests


def missing_assets(tag: str, digests: dict[str, str]) -> tuple[bool, list[str]]:
    """Return whether the release exists and which assets it still lacks."""
    remote = remote_digests(tag)
    if remote is None:
        return False, sorted(digests)
    for name in sorted(set(remote) & set(digests)):
        if remote[name] != digests[name]:
            raise ValueError(
                f"{tag}: published asset differs from the manifest; "
                f"assets are never replaced: {name}"
            )
    return True, sorted(set(digests) - set(remote))


def publish(manifest: Path, archives: Path, *, execute: bool) -> bool:
    """Return True once every manifest asset is on GitHub with the same SHA256."""
    version = manifest.name
    tag = f"v{version}"
    digests = manifest_digests(manifest)
    exists, missing = missing_assets(tag, digests)
    if not missing:
        print(f"{tag}: all {len(digests)} assets published")
        return True
    files = local_assets(manifest, archives, {name: digests[name] for name in missing})
    target = manifest_commit(manifest)
    action = "upload to existing" if exists else f"create at {target[:12]}"
    print(f"{tag}: {action}, {len(missing)} assets: {', '.join(missing)}")
    if not execute:
        return False
    paths = [str(files[name]) for name in missing]
    if exists:
        run("gh", "release", "upload", tag, *paths, "--repo", REPOSITORY)
    else:
        notes = ROOT / "docs/releases" / f"{version}.md"
        run(
            "gh", "release", "create", tag, *paths, "--repo", REPOSITORY,
            "--target", target, "--title", f"ManacostTeam {version}",
            *(
                ["--notes-file", str(notes)]
                if notes.is_file()
                else ["--notes", f"Навыки ManacostTeam {version}; контрольные суммы — SHA256SUMS."]
            ),
        )
    if missing_assets(tag, digests)[1]:
        raise RuntimeError(f"{tag}: assets still missing after upload")
    print(f"{tag}: published")
    return True


def release(args) -> int:
    registry = json.loads((ROOT / "teams/registry.json").read_text(encoding="utf-8"))
    version = registry["release_version"]
    archives = args.archives or ROOT / "build/team-skills" / version
    manifest = HISTORY / version
    for name in builder.MANIFEST_FILES:
        built = archives / name
        if not built.is_file() or built.read_bytes() != (manifest / name).read_bytes():
            raise ValueError(
                f"{built} differs from the tracked manifest; "
                "run `python tools/build_team_skills.py` first"
            )
    publish(manifest, archives, execute=args.execute)
    return 0


def migrate(args) -> int:
    """Upload archives still committed in old snapshots; optionally untrack them."""
    snapshots = sorted(
        (path for path in HISTORY.iterdir() if builder.VERSION.fullmatch(path.name)),
        key=lambda path: tuple(map(int, path.name.split("."))),
    )
    tracked, failed = [], []
    for manifest in snapshots:
        try:
            published = publish(manifest, manifest, execute=args.execute)
        except (ValueError, RuntimeError, OSError, KeyError) as error:
            # One unpublished snapshot must not block the others; its archives stay.
            print(f"v{manifest.name}: FAILED: {error}")
            failed.append(manifest.name)
            continue
        if published:
            tracked += [
                file.relative_to(ROOT).as_posix()
                for file in sorted(manifest.iterdir())
                if file.suffix in {".zip", ".skill"}
            ]
    if args.remove_archives and args.execute and tracked:
        run("git", "rm", "--quiet", "--", *tracked)
        print(f"git rm: {len(tracked)} archives of verified snapshots; review and commit")
    elif args.remove_archives:
        print("--remove-archives: archives stay tracked until their assets are published")
    if failed:
        print(f"not migrated, archives kept: {', '.join(failed)}")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--execute", action="store_true", help="perform the GitHub writes")
    commands = parser.add_subparsers(dest="command", required=True)
    current = commands.add_parser(
        "release", parents=[common], help="publish the current local build"
    )
    current.add_argument("--archives", type=Path, help="default: build/team-skills/<version>")
    current.set_defaults(handler=release)
    legacy = commands.add_parser(
        "migrate", parents=[common], help="publish archives committed in old snapshots"
    )
    legacy.add_argument(
        "--remove-archives", action="store_true",
        help="with --execute: git rm the archives once every asset is verified on GitHub",
    )
    legacy.set_defaults(handler=migrate)
    args = parser.parse_args()
    try:
        return args.handler(args)
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        parser.exit(1, f"publish error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
