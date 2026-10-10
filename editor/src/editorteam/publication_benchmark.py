"""Prepare private human annotations and report measured paired editorial comparisons."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .editorial_lab import canonical_url, write_new


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"nonempty {name} required")
    return value


def _human_review(row: dict) -> None:
    _text(row.get("reviewer"), "reviewer")
    timestamp = _text(row.get("reviewed_at"), "reviewed_at ISO timestamp")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("reviewed_at must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("reviewed_at timezone required")


def prepare(rows: list[dict], output: Path, seed: int = 17) -> dict:
    """Freeze splits by source identity; connected URL/content duplicates stay together."""
    if output.exists():
        raise FileExistsError(
            "prepare requires a new output directory; frozen bundles are immutable"
        )
    if not isinstance(rows, list) or not rows:
        raise ValueError("nonempty candidate array required")
    candidates, seen, parents, duplicates = [], set(), {}, {}

    def find(identity: str) -> str:
        while parents[identity] != identity:
            parents[identity] = parents[parents[identity]]
            identity = parents[identity]
        return identity

    for row in rows:
        identity = _text(row.get("id"), "source id")
        text = _text(row.get("text"), "full source text")
        if identity in seen or row.get("access") not in {"full", "public"}:
            raise ValueError("unique IDs and full/public sources required")
        seen.add(identity)
        digest, url = _sha(text), canonical_url(_text(row.get("url"), "source URL"))
        if row.get("sha256") != digest:
            raise ValueError("candidate source hash mismatch")
        parents[identity] = identity
        for key in (("url", url), ("hash", digest)):
            if key in duplicates:
                parents[find(identity)] = find(duplicates[key])
            else:
                duplicates[key] = identity
        candidates.append({**row, "canonical_url": url})
    groups = defaultdict(list)
    for identity in seen:
        groups[find(identity)].append(identity)
    membership = {}
    for ids in groups.values():
        group = _sha(json.dumps(sorted(ids), ensure_ascii=False))
        split = "holdout" if int(_sha(f"{seed}:{group}")[:8], 16) % 5 == 0 else "train"
        for identity in ids:
            membership[identity] = (group, split)
    cases, documents = [], []
    for row in sorted(candidates, key=lambda r: r["id"]):
        case_id = "case-" + _sha(row["id"])[:20]
        group, split = membership[row["id"]]
        case = {
            "case_id": case_id,
            "source_id": row["id"],
            "title": row.get("title"),
            "url": row["canonical_url"],
            "source_sha256": row["sha256"],
            "duplicate_group": group,
            "split": split,
            "review_status": "pending",
            "source_path": f"{case_id}/source.md",
            "annotation_path": f"{case_id}/annotation.json",
        }
        annotation = {
            **case,
            "patch": None,
            "required_claims": None,
            "conditions": None,
            "errors": None,
            "reference": None,
            "reference_edit_confirmed": False,
            "approval": {"human_confirmed": False, "reviewer": None, "reviewed_at": None},
            "notes": "",
            "factual_use": "requires_current_patch_verification",
        }
        cases.append(case)
        documents.append((case, annotation, row["text"]))
    manifest = {
        "schema_version": 1,
        "seed": seed,
        "split_policy": "source-id hash; duplicate groups atomic",
        "cases": cases,
        "publication_approved": False,
    }
    output.mkdir(parents=True, exist_ok=False)
    for case, annotation, source in documents:
        source_path = output / case["source_path"]
        source_path.parent.mkdir()
        with source_path.open("x", encoding="utf-8", newline="") as handle:
            handle.write(source)
        write_new(output / case["annotation_path"], annotation)
    write_new(output / "manifest.json", manifest)
    guide = [
        "# Разметка редакционного benchmark",
        "",
        "Все материалы — кандидаты. Патч, качество и пригодность к публикации не подтверждены.",
        "Разметку выполняет человек: откройте source.md и соответствующий annotation.json.",
        "Заполните patch; required_claims — список claim_id, meaning, action, condition, exception,",
        "evidence_quote (точная цитата source.md); conditions — список обязательных условий;",
        "errors — список обнаруженных ошибок (пустой список означает, что проверка выполнена).",
        "Исправленный эталон вставьте в reference и подтвердите reference_edit_confirmed=true.",
        "После проверки задайте review_status=approved и approval: human_confirmed=true,",
        "reviewer — имя редактора, reviewed_at — ISO дата и время с часовым поясом.",
        "Это подтверждение делает человек. Автоматически заполнять его нельзя.",
        "Не меняйте source.md, manifest.json, идентификаторы и split: они фиксируют источник и выборку.",
        "Holdout не используйте для настройки промптов. Старые статьи требуют проверки актуального патча.",
        "Время правки и ошибки сравнения измеряются отдельно на слепых baseline/candidate парах.",
        "",
    ]
    guide.extend(
        f"- `{case['split']}`: [{case['source_id']}]({case['annotation_path']}) · [исходник]({case['source_path']})"
        for case in cases
    )
    with (output / "index.md").open("x", encoding="utf-8") as handle:
        handle.write("\n".join(guide) + "\n")
    return manifest


def export_approved(directory: Path) -> list[dict]:
    """Export only explicit human attestations; never infer approval from model output."""
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    approved, seen = [], set()
    for case in manifest["cases"]:
        case_id = _text(case.get("case_id"), "case_id")
        if case_id != "case-" + _sha(case["source_id"])[:20] or case_id in seen:
            raise ValueError("invalid or duplicate frozen case")
        seen.add(case_id)
        if case["split"] not in {"train", "holdout"}:
            raise ValueError("invalid frozen split")
        for field, filename in (
            ("source_path", "source.md"),
            ("annotation_path", "annotation.json"),
        ):
            if case[field] != f"{case_id}/{filename}":
                raise ValueError("unexpected case file path")
        source = (directory / case["source_path"]).read_bytes().decode("utf-8")
        if _sha(source) != case["source_sha256"]:
            raise ValueError("source hash changed")
        row = json.loads((directory / case["annotation_path"]).read_text(encoding="utf-8"))
        for field in ("case_id", "source_id", "source_sha256", "split", "duplicate_group", "url"):
            if row.get(field) != case[field]:
                raise ValueError("annotation changed frozen identity")
        if row.get("review_status") == "pending":
            continue
        if row.get("review_status") != "approved":
            raise ValueError("annotation status must be pending or approved")
        approval = row.get("approval")
        if not isinstance(approval, dict) or approval.get("human_confirmed") is not True:
            raise ValueError("explicit human_confirmed approval required")
        _human_review(approval)
        reference = _text(row.get("reference"), "edited reference")
        _text(row.get("patch"), "verified patch")
        if row.get("reference_edit_confirmed") is not True:
            raise ValueError("human reference_edit_confirmed required")
        claims = row.get("required_claims")
        if not isinstance(claims, list) or not claims:
            raise ValueError("annotated required_claims required")
        claim_ids = set()
        for claim in claims:
            identity = _text(claim.get("claim_id"), "claim_id")
            if identity in claim_ids:
                raise ValueError("duplicate required claim")
            claim_ids.add(identity)
            for field in ("meaning", "action", "evidence_quote"):
                _text(claim.get(field), field)
            if claim["evidence_quote"] not in source:
                raise ValueError("claim evidence_quote must occur in source")
            if any(not isinstance(claim.get(field), str) for field in ("condition", "exception")):
                raise ValueError("explicit condition and exception strings required")
        if any(not isinstance(row.get(field), list) for field in ("conditions", "errors")):
            raise ValueError("human conditions and errors lists required")
        approved.append(
            {
                "id": case_id,
                "case_id": case_id,
                "source_id": case["source_id"],
                "source": source,
                "source_sha256": case["source_sha256"],
                "url": case["url"],
                "split": case["split"],
                "patch": row["patch"],
                "reference": reference,
                "reference_sha256": _sha(reference),
                "required_claims": claims,
                "conditions": row["conditions"],
                "errors": row["errors"],
                "review_status": "approved",
                "human_approved": True,
                "approval": approval,
                "publication_approved": False,
            }
        )
    if not approved:
        raise ValueError("no explicitly human-approved cases; candidates are not gold")
    return approved


def paired_summary(rows: list[dict], key: list[dict] | None = None) -> dict:
    """Compute improvements only on identical reviewed case/patch pairs."""
    if not isinstance(rows, list):
        raise ValueError("ratings array required")
    mapping = {}
    if key is not None:
        for item in key:
            blind_id = _text(item.get("blind_id"), "blind_id")
            if blind_id in mapping or item.get("variant") not in {"baseline", "candidate"}:
                raise ValueError("unique valid blind key required")
            mapping[blind_id] = item
    cases, patches, seen = defaultdict(dict), {}, set()
    for original in rows:
        row = dict(original)
        if key is not None:
            item = mapping.get(row.get("blind_id"))
            if item is None or item.get("case_id") != row.get("case_id"):
                raise ValueError("rating does not match blind key")
            if row.get("variant", item["variant"]) != item["variant"]:
                raise ValueError("rating conflicts with blind key")
            row["variant"] = item["variant"]
        case_id, patch = _text(row.get("case_id"), "case_id"), _text(row.get("patch"), "patch")
        variant = row.get("variant")
        if variant not in {"baseline", "candidate"}:
            raise ValueError("variant must be baseline or candidate")
        identity = (case_id, variant)
        if identity in seen:
            raise ValueError("duplicate paired rating")
        seen.add(identity)
        if case_id in patches and patches[case_id] != patch:
            raise ValueError("paired patches do not match")
        patches[case_id] = patch
        status = row.get("review_status")
        if status not in {"pending", "reviewed"}:
            raise ValueError("rating status must be pending or reviewed")
        if status == "reviewed":
            _human_review(row)
            minutes, errors = row.get("editor_minutes"), row.get("critical_errors")
            if (
                type(minutes) not in {int, float}
                or not math.isfinite(minutes)
                or minutes < 0
                or type(errors) is not int
                or errors < 0
            ):
                raise ValueError("finite nonnegative measured minutes and integer errors required")
        elif any(row.get(field) is not None for field in ("editor_minutes", "critical_errors")):
            raise ValueError("pending ratings must not contain invented measurements")
        cases[case_id][variant] = row
    complete = [
        case_id
        for case_id, pair in cases.items()
        if set(pair) == {"baseline", "candidate"}
        and all(row["review_status"] == "reviewed" for row in pair.values())
    ]
    totals = {
        variant: {
            field: sum(cases[case_id][variant][field] for case_id in complete) if complete else None
            for field in ("editor_minutes", "critical_errors")
        }
        for variant in ("baseline", "candidate")
    }

    def reduction(field: str) -> float | None:
        baseline = totals["baseline"][field]
        if baseline is None or baseline == 0:
            return None
        return 100 * (baseline - totals["candidate"][field]) / baseline

    return {
        "cases": len(cases),
        "complete_pairs": len(complete),
        "incomplete_cases": len(cases) - len(complete),
        "paired_case_ids": sorted(complete),
        "variants": totals,
        "editor_minutes_reduction_percent": reduction("editor_minutes"),
        "critical_errors_reduction_percent": reduction("critical_errors"),
        "publication_approved": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "export-approved", "summarize"):
        command = sub.add_parser(name)
        command.add_argument("input", type=Path)
        command.add_argument("--output", type=Path, required=True)
        if name == "prepare":
            command.add_argument("--seed", type=int, default=17)
        elif name == "summarize":
            command.add_argument("--key", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            value = prepare(
                json.loads(args.input.read_text(encoding="utf-8")), args.output, args.seed
            )
            print(
                json.dumps(
                    {"cases": len(value["cases"]), "output": str(args.output)}, ensure_ascii=False
                )
            )
        else:
            if args.output.exists():
                raise FileExistsError("output already exists")
            if args.command == "export-approved":
                value = export_approved(args.input)
            else:
                key = json.loads(args.key.read_text(encoding="utf-8")) if args.key else None
                value = paired_summary(json.loads(args.input.read_text(encoding="utf-8")), key)
            write_new(args.output, value)
        return 0
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
