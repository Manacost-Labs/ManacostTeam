#!/usr/bin/env python3
"""Operational CLI for resuming, comparing, exporting, and releasing research."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any


EXCLUDED_PARTS = {"__pycache__", ".DS_Store"}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def effective_output_profile(manifest: dict[str, Any]) -> tuple[str, bool]:
    profile = manifest.get("output_profile")
    if isinstance(profile, str) and profile in {
        "editor-ready",
        "research-report",
        "raw-research",
    }:
        return profile, False
    modifiers = manifest.get("modifiers")
    inferred = (
        "raw-research"
        if isinstance(modifiers, list) and "raw-research" in modifiers
        else "research-report"
    )
    return inferred, True


def run_checked(command: list[str], cwd: Path | None = None) -> None:
    result = subprocess.run(command, cwd=cwd, check=False, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"gate failed ({result.returncode}): {' '.join(command)}")


def deterministic_zip(source: Path, destination: Path, prefix: str) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = [
        path for path in source.rglob("*")
        if path.is_file()
        and not any(part in EXCLUDED_PARTS for part in path.relative_to(source).parts)
        and path.suffix not in {".pyc", ".pyo"}
    ]
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(files, key=lambda item: item.relative_to(source).as_posix()):
            relative = path.relative_to(source).as_posix()
            info = zipfile.ZipInfo(f"{prefix}/{relative}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if path.suffix == ".py" else 0o644) << 16
            archive.writestr(info, path.read_bytes())
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def command_resume(args: argparse.Namespace) -> int:
    run = Path(args.run).expanduser().resolve()
    validator = Path(__file__).with_name("validate_research_run.py")
    run_checked([sys.executable, str(validator), str(run), "--stage", "working"])
    manifest = load_json(run / "manifest.json")
    output_profile, profile_inferred = effective_output_profile(manifest)
    checkpoints = load_jsonl(run / "checkpoints.jsonl")
    latest = checkpoints[-1] if checkpoints else {}
    summary = {
        "research_id": manifest.get("research_id"),
        "status": manifest.get("status"),
        "as_of": manifest.get("as_of"),
        "output_profile": output_profile,
        "output_profile_inferred": profile_inferred,
        "modifiers": manifest.get("modifiers", []),
        "latest_checkpoint": latest.get("checkpoint_id"),
        "missing_data": latest.get("missing_data", []),
        "unsaturated_branches": latest.get("unsaturated_branches", []),
        "next_actions": latest.get("next_actions", []),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def command_compare(args: argparse.Namespace) -> int:
    left = Path(args.left).expanduser().resolve()
    right = Path(args.right).expanduser().resolve()
    validator = Path(__file__).with_name("validate_research_run.py")
    for run in (left, right):
        run_checked([sys.executable, str(validator), str(run), "--stage", "working"])
    left_manifest, right_manifest = load_json(left / "manifest.json"), load_json(right / "manifest.json")
    left_claims = {item["claim_id"]: item for item in load_jsonl(left / "claims.jsonl")}
    right_claims = {item["claim_id"]: item for item in load_jsonl(right / "claims.jsonl")}
    changed: list[dict[str, Any]] = []
    for claim_id in sorted(set(left_claims) | set(right_claims)):
        before, after = left_claims.get(claim_id), right_claims.get(claim_id)
        if before != after:
            changed.append({
                "claim_id": claim_id,
                "before": None if before is None else {key: before.get(key) for key in ("claim", "status", "confidence")},
                "after": None if after is None else {key: after.get(key) for key in ("claim", "status", "confidence")},
            })
    output = {
        "left_research_id": left_manifest.get("research_id"),
        "right_research_id": right_manifest.get("research_id"),
        "left_as_of": left_manifest.get("as_of"),
        "right_as_of": right_manifest.get("as_of"),
        "changed_claims": changed,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def command_export(args: argparse.Namespace) -> int:
    run = Path(args.run).expanduser().resolve()
    destination = Path(args.output).expanduser().resolve()
    validator = Path(__file__).with_name("validate_research_run.py")
    run_checked([sys.executable, str(validator), str(run), "--stage", "final"])
    manifest = load_json(run / "manifest.json")
    digest = deterministic_zip(run, destination, str(manifest.get("research_id", run.name)))
    print(json.dumps({"archive": str(destination), "sha256": digest}, indent=2))
    return 0


def command_release(args: argparse.Namespace) -> int:
    skill = Path(args.skill).expanduser().resolve()
    benchmark = Path(args.benchmark).expanduser().resolve()
    evaluation = benchmark.parent.resolve()
    output = Path(args.output).expanduser().resolve()
    version = (skill / "VERSION").read_text(encoding="utf-8").strip()
    if version != "1.0.0":
        raise RuntimeError(f"release requires VERSION=1.0.0, got {version}")
    if not (skill / "LICENSE").is_file():
        raise RuntimeError("release requires an explicit LICENSE file")
    if "ChatGPT Search/Web" not in (skill / "README.md").read_text(encoding="utf-8"):
        raise RuntimeError("README must state the ChatGPT Search/Web boundary")

    run_checked([sys.executable, str(skill / "scripts/audit_skill.py"), str(skill)])
    run_checked([
        sys.executable, "-m", "unittest", "discover", "-s", str(skill / "tests"),
        "-p", "test_*.py", "-v",
    ])
    run_checked([
        sys.executable, str(skill / "scripts/validate_benchmark.py"), str(benchmark),
        "--stage", "release",
    ])
    run_checked([
        sys.executable, str(skill / "scripts/score_semantic_gold.py"),
        str(evaluation / "gold/semantic-cases.jsonl"),
        str(evaluation / "gold/semantic-predictions.jsonl"),
    ])
    if args.quick_validator:
        validator_python = (
            str(Path(args.quick_validator_python).expanduser().absolute())
            if args.quick_validator_python else sys.executable
        )
        run_checked([validator_python, str(Path(args.quick_validator).expanduser().resolve()), str(skill)])

    skill_archive = output / f"deep-research-{version}.zip"
    evidence_archive = output / f"deep-research-evaluation-{version}.zip"
    skill_sha = deterministic_zip(skill, skill_archive, "deep-research")
    evidence_sha = deterministic_zip(evaluation, evidence_archive, "evaluation")
    manifest = {
        "version": version,
        "skill_archive": skill_archive.name,
        "skill_sha256": skill_sha,
        "evaluation_archive": evidence_archive.name,
        "evaluation_sha256": evidence_sha,
    }
    (output / "release-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    resume = sub.add_parser("resume", help="Validate and summarize a resumable run")
    resume.add_argument("run")
    resume.set_defaults(func=command_resume)
    compare = sub.add_parser("compare", help="Compare claims between two runs")
    compare.add_argument("left")
    compare.add_argument("right")
    compare.set_defaults(func=command_compare)
    export = sub.add_parser("export", help="Validate and export a deterministic run archive")
    export.add_argument("run")
    export.add_argument("output")
    export.set_defaults(func=command_export)
    release = sub.add_parser("release", help="Run release gates and build deterministic archives")
    release.add_argument("--skill", required=True)
    release.add_argument("--benchmark", required=True)
    release.add_argument("--output", required=True)
    release.add_argument("--quick-validator")
    release.add_argument("--quick-validator-python")
    release.set_defaults(func=command_release)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        return int(args.func(args))
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
