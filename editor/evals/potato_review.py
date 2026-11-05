#!/usr/bin/env python3
"""Optional local Potato UI for the existing frozen blind-review protocol.

Only the serve command requires potato-annotation. No model calls are made.
"""

import argparse
import hashlib
import html
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

POTATO_VERSION = "2.14.0"
ATTESTATION = "Лично оценено человеком"
HERE = Path(__file__).resolve().parent
RUBRIC = json.loads((HERE / "rubric/interest.json").read_text(encoding="utf-8"))
QUESTIONS = {row["id"]: row["question"] for row in RUBRIC["criteria"]}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    Path(path).chmod(0o600)


def key_ids(path):
    key = read_json(path)
    if (
        not isinstance(key, dict)
        or not isinstance(key.get("pairs"), list)
        or any(
            not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in key["pairs"]
        )
    ):
        raise ValueError("valid blind key required")
    return [row["id"] for row in key["pairs"]]


def load_pairs(path):
    pairs = read_json(path)
    if not isinstance(pairs, list) or not pairs:
        raise ValueError("nonempty frozen pairs.json required")
    seen = set()
    for row in pairs:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("id"), str)
            or not row["id"]
            or row["id"] in seen
        ):
            raise ValueError("unique presentation IDs required")
        seen.add(row["id"])
        if any(not isinstance(row.get(field), str) for field in ("source", "A", "B")):
            raise ValueError("source and A/B text required")
        criteria = row.get("criteria")
        if (
            not isinstance(criteria, list)
            or not criteria
            or any(not isinstance(c, str) or not c.replace("_", "").isalnum() for c in criteria)
            or len(set(criteria)) != len(criteria)
        ):
            raise ValueError("unique criterion identifiers required")
        if criteria != pairs[0]["criteria"]:
            raise ValueError("all presentations must use the same rubric")
    return pairs


def dataset(pairs):
    # Potato renders pairwise text as HTML. Keep article/model markup inert.
    return "".join(
        json.dumps(
            {
                "id": row["id"],
                "source": html.escape(row["source"]),
                "text": [html.escape(row["A"]), html.escape(row["B"])],
            },
            ensure_ascii=False,
        )
        + "\n"
        for row in pairs
    )


def export_project(pairs_path, output, key_path=None):
    pairs_path, output = Path(pairs_path), Path(output)
    pairs = load_pairs(pairs_path)
    key_path = Path(key_path) if key_path else pairs_path.with_name("key.json")
    if key_ids(key_path) != [row["id"] for row in pairs]:
        raise ValueError("blind key does not match presentations")
    schemes = [
        {
            "annotation_type": "pairwise",
            "name": "preference",
            "description": "Какой вариант лучше в целом?",
            "items_key": "text",
            "mode": "binary",
            "labels": ["Вариант A", "Вариант B"],
            "allow_tie": True,
            "tie_label": "Равноценны",
            "randomize_order": False,
            "label_requirement": {"required": True},
        }
    ]
    for criterion in pairs[0]["criteria"]:
        for side in ("A", "B"):
            schemes.append(
                {
                    "annotation_type": "likert",
                    "name": f"{side}__{criterion}",
                    "description": f"{side}: {QUESTIONS.get(criterion, criterion)}",
                    "size": 5,
                    "min_label": "1 — плохо",
                    "max_label": "5 — хорошо",
                    "label_requirement": {"required": True},
                }
            )
    schemes += [
        {
            "annotation_type": "text",
            "name": "evidence",
            "description": "Конкретная цитата и причина оценки (обязательно)",
            "multiline": True,
            "label_requirement": {"required": True},
        },
        {
            "annotation_type": "text",
            "name": "comment",
            "description": "Дополнительный комментарий",
            "multiline": True,
        },
        {
            "annotation_type": "radio",
            "name": "attestation",
            "description": "Подтверждение после заполнения оценок",
            "labels": [ATTESTATION],
            "label_requirement": {"required": True},
        },
    ]
    config = {
        "annotation_task_name": "Слепая оценка Манакоста",
        "task_dir": str(output.resolve()),
        "site_dir": "default",
        "output_annotation_dir": str((output / "annotations").resolve()),
        "data_files": [str((output / "data.jsonl").resolve())],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "instance_display": {
            "fields": [{"key": "source", "type": "text", "label": "Исходный черновик"}]
        },
        "annotation_schemes": schemes,
        "export_annotation_format": "jsonl",
        "user_config": {"allow_all_users": True, "users": []},
        "require_password": True,
        "ai_support": {"enabled": False},
        "jumping_to_id_disabled": True,
    }
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    (output / "data.jsonl").write_text(dataset(pairs), encoding="utf-8")
    (output / "data.jsonl").chmod(0o600)
    # JSON is valid YAML and avoids a runtime PyYAML dependency in this adapter.
    write_json(output / "config.yaml", config)
    write_json(
        output / "manifest.json",
        {
            "potato_version": POTATO_VERSION,
            "timezone": "UTC",
            "pairs_sha256": hashlib.sha256(pairs_path.read_bytes()).hexdigest(),
            "key_sha256": hashlib.sha256(key_path.read_bytes()).hexdigest(),
        },
    )
    return {"pairs": len(pairs), "project": str(output)}


def normalize_labels(raw):
    if not isinstance(raw, (list, dict)):
        raise ValueError("invalid Potato label state")
    labels = raw if isinstance(raw, dict) else {}
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, list) or len(entry) != 2 or not isinstance(entry[0], dict):
                raise ValueError("invalid Potato label entry")
            key, value = entry
            schema, name = key.get("schema"), key.get("name")
            if not isinstance(schema, str) or not isinstance(name, str):
                raise ValueError("invalid Potato label identity")
            target = labels.setdefault(schema, {})
            if name in target:
                raise ValueError("duplicate label in Potato state")
            target[name] = value
    if any(not isinstance(value, dict) for value in labels.values()):
        raise ValueError("Potato label groups must be objects")
    return labels


def confirmation(value):
    return str(value).lower() in {"true", "1", ATTESTATION.lower()}


def score(labels, name):
    values = labels.get(name, {})
    if not isinstance(values, dict) or len(values) != 1:
        raise ValueError(f"one score required: {name}")
    key, value = next(iter(values.items()))
    if key not in "12345" or len(key) != 1 or str(value) != key:
        raise ValueError(f"score must be 1..5: {name}")
    return int(key)


def review_time(user_dir, user_id, instance_id):
    history = user_dir / "annotation_history.jsonl"
    if not history.is_file() or history.is_symlink():
        raise ValueError("Potato annotation history required")
    times = []
    attestations = []
    for line in history.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError("invalid annotation history row")
        if row.get("instance_id") != instance_id or row.get("user_id") != user_id:
            continue
        if row.get("action_type") not in {"add_label", "update_label", "delete_label"}:
            continue
        if not isinstance(row.get("timestamp"), str):
            raise ValueError("annotation history timestamp required")
        stamp = datetime.fromisoformat(row["timestamp"])
        # serve always launches the pinned app in UTC. Potato writes naive local times.
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        stamp = stamp.astimezone(timezone.utc)
        times.append(stamp)
        if row.get("schema_name") == "attestation" and row.get("label_name") == ATTESTATION:
            attestations.append(
                (
                    stamp,
                    row.get("action_type") != "delete_label" and confirmation(row.get("new_value")),
                )
            )
    if not times or not attestations:
        raise ValueError("human attestation missing from annotation history")
    latest = max(stamp for stamp, _ in attestations)
    if {value for stamp, value in attestations if stamp == latest} != {True}:
        raise ValueError("human attestation removed or ambiguous in annotation history")
    return max(times).astimezone(timezone.utc).isoformat()


def import_project(project, pairs_path, key_path, output):
    project, pairs_path, key_path, output = map(Path, (project, pairs_path, key_path, output))
    pairs = load_pairs(pairs_path)
    manifest = read_json(project / "manifest.json")
    if (
        not isinstance(manifest, dict)
        or manifest.get("potato_version") != POTATO_VERSION
        or manifest.get("timezone") != "UTC"
    ):
        raise ValueError("unsupported Potato project/version/timezone")
    if manifest.get("pairs_sha256") != hashlib.sha256(pairs_path.read_bytes()).hexdigest() or (
        project / "data.jsonl"
    ).read_text(encoding="utf-8") != dataset(pairs):
        raise ValueError("frozen pairs or Potato dataset changed")
    if hashlib.sha256(key_path.read_bytes()).hexdigest() != manifest.get("key_sha256") or key_ids(
        key_path
    ) != [row["id"] for row in pairs]:
        raise ValueError("blind key does not match presentations")
    by_id = {row["id"]: row for row in pairs}
    ratings, seen, completed = [], set(), set()
    annotations = project / "annotations"
    for user_dir in sorted(annotations.iterdir()) if annotations.exists() else []:
        state_file = user_dir / "user_state.json"
        if not user_dir.is_dir() or not state_file.is_file():
            continue
        if user_dir.is_symlink() or state_file.is_symlink():
            raise ValueError("symlinked annotations are not supported")
        state = read_json(state_file)
        if not isinstance(state, dict) or not isinstance(
            state.get("instance_id_to_label_to_value", {}), dict
        ):
            raise ValueError("invalid Potato user state")
        reviewer = state.get("user_id", "")
        origin = state.get("origin")
        # Potato 2.14 persists {} for an ordinary human account.
        if origin is None or origin == {}:
            origin = {"kind": "human"}
        if (
            not isinstance(reviewer, str)
            or not reviewer.strip()
            or reviewer.startswith("judge:")
            or not isinstance(origin, dict)
            or origin.get("kind") != "human"
        ):
            raise ValueError("identified human reviewer required")
        for instance_id, raw in state.get("instance_id_to_label_to_value", {}).items():
            if instance_id not in by_id or (instance_id, reviewer) in seen:
                raise ValueError("unknown or duplicate reviewer/presentation")
            seen.add((instance_id, reviewer))
            labels = normalize_labels(raw)
            if not confirmation(labels.get("attestation", {}).get(ATTESTATION)):
                continue
            preferred = labels.get("preference", {}).get("selection")
            evidence = labels.get("evidence", {}).get("text_box", "")
            if (
                not isinstance(preferred, str)
                or preferred not in {"A", "B", "tie"}
                or not isinstance(evidence, str)
                or not evidence.strip()
            ):
                raise ValueError("completed preference and specific evidence required")
            comment = labels.get("comment", {}).get("text_box", "")
            if not isinstance(comment, str):
                raise ValueError("comment must be text")
            rating = {
                "id": instance_id,
                "review_status": "reviewed",
                "reviewer": reviewer,
                "reviewed_at": review_time(user_dir, reviewer, instance_id),
                "preferred": preferred,
                "evidence": [evidence.strip()],
                "comment": comment,
            }
            for side in ("A", "B"):
                rating[side] = {
                    c: score(labels, f"{side}__{c}") for c in by_id[instance_id]["criteria"]
                }
            ratings.append(rating)
            completed.add(instance_id)
    reviewed = len(ratings)
    ratings += [
        {"id": row["id"], "review_status": "pending"} for row in pairs if row["id"] not in completed
    ]
    if output.exists():
        raise FileExistsError(output)
    # Use the canonical validator before writing any output.
    script = (
        "require(process.argv[1]).importRatings(process.argv[2], process.argv[3], process.argv[4])"
    )
    with tempfile.TemporaryDirectory(prefix="manacost-potato-import-") as temp:
        temp = Path(temp)
        write_json(temp / "ratings.json", ratings)
        subprocess.run(
            [
                "node",
                "-e",
                script,
                str(HERE / "blind_review.js"),
                str(temp / "ratings.json"),
                str(key_path.resolve()),
                str(temp),
            ],
            check=True,
            capture_output=True,
        )
        output.mkdir(parents=True, mode=0o700, exist_ok=False)
        for name in ("ratings.json", "report.json", "report.md"):
            (output / name).write_bytes((temp / name).read_bytes())
            (output / name).chmod(0o600)
    return {
        "reviewed": reviewed,
        "pending": len(pairs) - len(completed),
    }


def serve_project(project, port):
    if version("potato-annotation") != POTATO_VERSION:
        raise ValueError(f"potato-annotation=={POTATO_VERSION} required")
    project = Path(project).resolve()
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    if read_json(project / "config.yaml").get("ai_support") != {"enabled": False}:
        raise ValueError("AI assistance must stay disabled for blind human review")
    # Keep Potato's project/file sandbox inside the blind dataset, away from key.json.
    os.chdir(project)
    # Replace this process: Ctrl-C or test cleanup stops the actual server.
    os.execve(
        sys.executable,
        [
            sys.executable,
            "-m",
            "potato",
            "start",
            str(project / "config.yaml"),
            "--host",
            "127.0.0.1",
            "-p",
            str(port),
        ],
        {**os.environ, "TZ": "UTC"},
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--pairs", type=Path, required=True)
    export.add_argument("--out", type=Path, required=True)
    export.add_argument(
        "--key", type=Path, help="default: key.json beside pairs.json; only its hash is exported"
    )
    serve = commands.add_parser("serve")
    serve.add_argument("--project", type=Path, required=True)
    serve.add_argument("--port", type=int, default=8765)
    load = commands.add_parser("import")
    for flag in ("project", "pairs", "key", "out"):
        load.add_argument(f"--{flag}", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "serve":
        return serve_project(args.project, args.port)
    result = (
        export_project(args.pairs, args.out, args.key)
        if args.command == "export"
        else import_project(args.project, args.pairs, args.key, args.out)
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, PackageNotFoundError, subprocess.CalledProcessError) as error:
        print(f"potato review: {error}", file=sys.stderr)
        raise SystemExit(1)
