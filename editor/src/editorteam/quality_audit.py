"""Independent, evidence-bound source/prose audits of a frozen private corpus.

This tool validates reviewer evidence, not semantic truth. Model reviews never
become human gold. Historical support, edit preservation and current accuracy
are deliberately reported separately.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from .editorial_lab import canonical_url, write_new

DIMENSIONS = ("usefulness", "coherence", "natural_russian", "author_voice")
STATUSES = ("supported", "contradicted", "unverified", "outdated")


def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("nonempty text required")
    return value


def _timestamp(value: object) -> datetime:
    parsed = datetime.fromisoformat(_text(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp timezone required")
    return parsed


def _inside(root: Path, relative: str) -> Path:
    path = root / _text(relative)
    if Path(relative).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("file must stay inside its evidence/corpus directory")
    return path


def _quote(text: str, quote: object) -> None:
    if _text(quote) not in text:
        raise ValueError("review quote is absent from source/snapshot")


def load_cases(directory: Path) -> dict[str, dict]:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or not manifest.get("cases"):
        raise ValueError("nonempty frozen v1 corpus required")
    cases = {}
    for case in manifest["cases"]:
        identity = _text(case.get("case_id"))
        expected_id = "case-" + _hash(_text(case.get("source_id")).encode())[:20]
        if identity != expected_id or identity in cases:
            raise ValueError("invalid or duplicate frozen case")
        if case.get("split") not in {"train", "holdout"}:
            raise ValueError("explicit frozen train/holdout split required")
        if case.get("source_path") != f"{identity}/source.md":
            raise ValueError("unexpected frozen source path")
        source = _inside(directory, case["source_path"]).read_bytes()
        if _hash(source) != case.get("source_sha256"):
            raise ValueError("frozen source hash changed")
        cases[identity] = {**case, "text": source.decode("utf-8")}
    return cases


def prepare_reviews(directory: Path, output: Path) -> dict:
    """Make a review assignment, preserving original sources and held-out split."""
    cases = load_cases(directory)
    if output.exists():
        raise FileExistsError("review packet requires a new directory")
    packet = {
        "schema_version": 1,
        "corpus": str(directory.resolve()),
        "human_approved": False,
        "cases": [
            {
                key: row[key]
                for key in ("case_id", "title", "url", "source_path", "source_sha256", "split")
            }
            for row in cases.values()
        ],
        "instructions": [
            "Read the entire source. Keep dated historical evidence separate from current facts.",
            "Assess usefulness, coherence, natural Russian and author voice with exact quotes.",
            "Retain good passages and normal gaming jargon; distinguish extraction artifacts.",
            "Inspect original sources for polarity, thresholds, comparison scope and confidence.",
            "Record sampled/complete claim coverage explicitly. Missing proof is unverified.",
            "Use train findings for improvements; never tune prompts on holdout findings.",
            "Model reports do not approve human gold or publication.",
        ],
    }
    output.mkdir(parents=True)
    write_new(output / "tasks.json", packet)
    return packet


def _evidence(item: dict, claim: dict, case: dict, root: Path, reviewed_at: datetime) -> bool:
    parsed = urlsplit(_text(item.get("url")))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise ValueError("public evidence URL required")
    if canonical_url(item["url"]) == canonical_url(case["url"]):
        raise ValueError("article cannot independently confirm itself")
    payload = _inside(root, item.get("snapshot_path")).read_bytes()
    if _hash(payload) != item.get("sha256"):
        raise ValueError("evidence snapshot hash mismatch")
    capture = json.loads(_inside(root, item.get("capture_path")).read_text(encoding="utf-8"))
    if (
        capture.get("source_url") != item["url"]
        or capture.get("snapshot_sha256") != item["sha256"]
        or capture.get("retrieved_at") != item.get("retrieved_at")
        or capture.get("method") not in {"web.open", "web.find", "mcp"}
        or capture.get("content_scope") not in {"excerpt", "full"}
    ):
        raise ValueError("capture provenance does not match evidence URL/time/bytes")
    _text(capture.get("tool_reference"))
    _quote(payload.decode("utf-8"), item.get("quote"))
    if _timestamp(item.get("retrieved_at")) > reviewed_at:
        raise ValueError("evidence retrieved after its review")
    allowed = {"official", "statistics", "expert"}
    if item.get("authority") not in allowed:
        raise ValueError("explicit evidence authority required")
    for field in ("scope_matches", "time_matches"):
        if type(item.get(field)) is not bool:
            raise ValueError("explicit evidence scope/time match required")
    authority_ok = (
        item["authority"] == "official"
        if claim["kind"] == "mechanic"
        else item["authority"] in {"official", "statistics"}
        if claim["kind"] == "numeric"
        else True
    )
    return item["scope_matches"] and item["time_matches"] and authority_ok


def _literary(source: str, literary: dict) -> str:
    dimensions = literary.get("dimensions", {})
    if any(dimensions.get(key) not in {"pass", "needs_work"} for key in DIMENSIONS):
        raise ValueError("all four literary dimensions required")
    strengths, findings = literary.get("strengths"), literary.get("findings")
    if not isinstance(strengths, list) or not strengths or not isinstance(findings, list):
        raise ValueError("quoted strengths and findings arrays required")
    for strength in strengths:
        _quote(source, strength.get("quote"))
        _text(strength.get("reason"))
    for item in findings:
        _quote(source, item.get("quote"))
        if item.get("severity") not in {"info", "warning", "error", "blocker"}:
            raise ValueError("unknown literary severity")
        for field in ("category", "reason", "suggestion"):
            _text(item.get(field))
    needs_work = any(value == "needs_work" for value in dimensions.values())
    substantial = any(item["severity"] != "info" for item in findings)
    if needs_work != substantial:
        raise ValueError("literary dimensions and actionable findings disagree")
    return "needs_work" if needs_work else "pass"


def _preservation(edit: dict | None, claims: list[dict]) -> str:
    if edit is None:
        return "not_run"
    candidate = _text(edit.get("candidate"))
    if edit.get("candidate_sha256") != _hash(candidate.encode("utf-8")):
        raise ValueError("candidate hash mismatch")
    rows = edit.get("claims")
    if not isinstance(rows, list):
        raise ValueError("edit claim attestations required")
    expected, seen = {claim["claim_id"] for claim in claims}, set()
    preserved = edit.get("all_changes_checked") is True and edit.get("unsupported_additions") == []
    for row in rows:
        identity = row.get("claim_id")
        if identity not in expected or identity in seen:
            raise ValueError("duplicate or unknown edit claim")
        seen.add(identity)
        if row.get("status") not in {"preserved", "changed", "lost"}:
            raise ValueError("explicit preservation verdict required")
        if row["status"] != "lost":
            _quote(candidate, row.get("quote"))
        preserved = preserved and row["status"] == "preserved"
    if seen != expected:
        raise ValueError("missing edit claim attestation")
    return "passed_model_review" if preserved else "needs_repair"


def audit_summary(directory: Path, reviews: list[dict], evidence_root: Path) -> dict:
    """Count every frozen case; never infer truth or improvement from preservation."""
    cases = load_cases(directory)
    if not isinstance(reviews, list):
        raise ValueError("review array required")
    indexed, results, queue = {}, [], []
    totals = Counter(dict.fromkeys(STATUSES, 0))
    for review in reviews:
        identity = review.get("case_id")
        if identity not in cases or identity in indexed:
            raise ValueError("unknown or duplicate review case")
        indexed[identity] = review
    for identity, case in cases.items():
        result = {key: case[key] for key in ("case_id", "title", "url", "split")}
        result.update(
            source_accuracy="not_reviewed",
            literary="not_reviewed",
            edit_preservation="not_run",
            current_facts_verified=False,
            model_current_support=False,
        )
        row = indexed.get(identity)
        if row is None:
            results.append(result)
            continue
        if row.get("source_sha256") != case["source_sha256"]:
            raise ValueError("review source hash mismatch")
        if row.get("reviewer_kind") != "model":
            raise ValueError("this audit accepts model reviews; human gold is separate")
        _text(row.get("reviewer"))
        reviewed_at = _timestamp(row.get("reviewed_at"))
        if row.get("temporal_scope") not in {"historical", "current"}:
            raise ValueError("explicit historical/current scope required")
        _text(row.get("target_period"))
        if row.get("claim_scope") not in {"sampled", "complete"}:
            raise ValueError("explicit sampled/complete claim scope required")
        if not isinstance(row.get("limitations"), list):
            raise ValueError("limitations list required")
        result["literary"] = _literary(case["text"], row.get("literary", {}))
        claims = row.get("source_facts", {}).get("claims")
        if not isinstance(claims, list) or not claims:
            raise ValueError("nonempty sampled/complete factual claim list required")
        seen, counts = set(), Counter(dict.fromkeys(STATUSES, 0))
        for claim in claims:
            cid = _text(claim.get("claim_id"))
            if cid in seen:
                raise ValueError("duplicate factual claim")
            seen.add(cid)
            _quote(case["text"], claim.get("quote"))
            _text(claim.get("reason"))
            if claim.get("kind") not in {"mechanic", "numeric", "recommendation", "meta", "other"}:
                raise ValueError("unknown factual claim kind")
            status = claim.get("status")
            if status not in STATUSES:
                raise ValueError("unknown factual claim status")
            evidence = claim.get("evidence")
            queries = claim.get("search_queries")
            if not isinstance(evidence, list) or not isinstance(queries, list):
                raise ValueError("explicit evidence and search query lists required")
            matching = [
                _evidence(item, claim, case, evidence_root, reviewed_at) for item in evidence
            ]
            if status != "unverified" and not any(matching):
                raise ValueError("factual verdict requires matching independent evidence")
            counts[status] += 1
            if status == "unverified":
                queue.append(
                    {
                        "case_id": identity,
                        "split": case["split"],
                        "claim_id": cid,
                        "quote": claim["quote"],
                        "reason": claim["reason"],
                        "queries": queries,
                        "target_period": row["target_period"],
                        "status": "attempted_unresolved" if queries else "pending",
                    }
                )
        totals.update(counts)
        accuracy = "reviewed_support" if row["claim_scope"] == "complete" else "sampled_support"
        if counts["unverified"]:
            accuracy = "needs_research"
        if counts["contradicted"] or counts["outdated"]:
            accuracy = "issues_found"
        result.update(
            source_accuracy=accuracy,
            claim_counts=dict(counts),
            factual_claims=claims,
            source_sha256=case["source_sha256"],
            reviewer=row["reviewer"],
            reviewed_at=row["reviewed_at"],
            temporal_scope=row["temporal_scope"],
            target_period=row["target_period"],
            claim_scope=row["claim_scope"],
            model_current_support=(
                accuracy == "reviewed_support" and row["temporal_scope"] == "current"
            ),
            edit_preservation=_preservation(row.get("edit_review"), claims),
            literary_review=row["literary"],
            limitations=row["limitations"],
        )
        results.append(result)
    return {
        "schema_version": 1,
        "cases": len(cases),
        "reviewed": len(indexed),
        "pending": len(cases) - len(indexed),
        "claim_counts": dict(totals),
        "human_approved": False,
        "publication_approved": False,
        "quality_improvement_percent": None,
        "editor_time_savings_percent": None,
        "results": results,
        "search_queue": queue,
    }


def markdown_report(report: dict) -> str:
    """Readable private review; quoted findings remain attributed model judgments."""
    labels = {
        "supported": "подтверждено",
        "contradicted": "противоречит источнику",
        "unverified": "не подтверждено",
        "outdated": "устарело",
    }
    lines = [
        "# Проверка качества текста и исходных фактов",
        "",
        f"Материалов: {report['cases']}; отзывов: {report['reviewed']}; ожидают: {report['pending']}.",
        "Проверка модельная и выборочная. Человеческого gold и измеренного улучшения нет.",
        "Сохранение исходных утверждений при правке не подтверждает их истинность.",
        "",
        "Факты: "
        + "; ".join(f"{labels[k]} — {v}" for k, v in report["claim_counts"].items())
        + ".",
        "",
    ]
    for row in report["results"]:
        lines += [
            f"## {row['title']}",
            "",
            f"[Исходная статья]({row['url']}) · `{row['split']}`",
            f"Текст: `{row['literary']}`; факты: `{row['source_accuracy']}`; "
            f"сохранение при правке: `{row['edit_preservation']}`.",
            "",
        ]
        if "literary_review" not in row:
            continue
        lines += [
            f"Период: {row['target_period']}; охват: `{row['claim_scope']}`.",
            "",
            "### Сильные стороны",
            "",
        ]
        for item in row["literary_review"]["strengths"]:
            lines.append(f"- «{' '.join(item['quote'].split())}» — {item['reason']}")
        lines += ["", "### Замечания к тексту", ""]
        for item in row["literary_review"]["findings"]:
            lines.append(
                f"- **{item['severity']} / {item['category']}**: «{' '.join(item['quote'].split())}». "
                f"{item['reason']} Предложение: {item['suggestion']}"
            )
        lines += ["", "### Исходные утверждения", ""]
        for item in row["factual_claims"]:
            lines.append(
                f"- **{labels[item['status']]}**: «{' '.join(item['quote'].split())}». {item['reason']}"
            )
            for evidence in item["evidence"]:
                lines.append(
                    f"  - [Источник]({evidence['url']}), snapshot `{evidence['snapshot_path']}`."
                )
        lines += ["", "Ограничения: " + " ".join(row["limitations"]), ""]
    lines += [
        "## Очередь поиска",
        "",
        f"Неподтверждённых тезисов для адресного поиска: {len(report['search_queue'])}.",
        "Точные тезисы, периоды и уже опробованные запросы сохранены в report.json.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "summarize"))
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--markdown", type=Path, help="New private Markdown report path")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare_reviews(args.corpus, args.output)
        else:
            if args.reviews is None or args.evidence_root is None:
                parser.error("summarize requires --reviews and --evidence-root")
            if args.markdown and (
                args.markdown.exists() or args.markdown.resolve() == args.output.resolve()
            ):
                parser.error("Markdown report requires a separate new path")
            result = audit_summary(
                args.corpus,
                json.loads(args.reviews.read_text(encoding="utf-8")),
                args.evidence_root,
            )
            write_new(args.output, result)
            if args.markdown:
                args.markdown.parent.mkdir(parents=True, exist_ok=True)
                with args.markdown.open("x", encoding="utf-8") as handle:
                    handle.write(markdown_report(result))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "cases": result["cases"]
                if isinstance(result["cases"], int)
                else len(result["cases"]),
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
