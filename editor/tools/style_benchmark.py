#!/usr/bin/env python3
"""Заготовка бенчмарка стиля write-like-me (подготовка чистого BG-корпуса и dry-run смета).

Использование:
  python editor/tools/style_benchmark.py prepare --out build/style-benchmark
  python editor/tools/style_benchmark.py eval --manifest build/style-benchmark/manifest.json --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EDITOR = ROOT / "editor"
if str(EDITOR / "src") not in sys.path:
    sys.path.insert(0, str(EDITOR / "src"))


def _split_for(doc_id: str, holdout_share: float = 0.4) -> str:
    bucket = int(hashlib.sha256(doc_id.encode("utf-8")).hexdigest()[:8], 16) % 100
    return "holdout" if bucket < int(holdout_share * 100) else "train"


def collect_human_bg_benchmark(repo_root: Path = ROOT, *, limit: int | None = None) -> list[dict]:
    """Собрать подтверждённые human BG-гайды: до-2023 + 2024–2025 Alexey/Zulutan + gold/."""
    rows: list[dict] = []
    manifest_path = repo_root / "editor" / "corpus-bg" / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for g in manifest.get("guides", []):
            pub = str(g.get("published_at", ""))
            is_pre = pub < "2023-01-01"
            is_human_author = pub[:4] in {"2024", "2025"} and g.get("author") in {"Alexey", "Zulutan"}
            if not (is_pre or is_human_author):
                continue
            path = repo_root / "editor" / g["path"]
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            rows.append(
                {
                    "id": g["id"],
                    "title": g.get("title", g["id"]),
                    "source_group": "corpus-bg-pre2023" if is_pre else f"corpus-bg-{g.get('author')}",
                    "published_at": pub,
                    "path": str(path.relative_to(repo_root)).replace("\\", "/"),
                    "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "words": len(text.split()),
                    "split": _split_for(g["id"]),
                }
            )

    gold_dir = repo_root / "build" / "owner-rejections" / "apm-2026-11-09" / "gold"
    if gold_dir.is_dir():
        for p in sorted(gold_dir.glob("*")):
            if not p.is_file() or p.suffix not in {".md", ".txt"}:
                continue
            text = p.read_text(encoding="utf-8")
            doc_id = f"gold-{p.stem}"
            rows.append(
                {
                    "id": doc_id,
                    "title": p.stem,
                    "source_group": "owner-gold",
                    "published_at": "owner-approved",
                    "path": str(p.relative_to(repo_root)).replace("\\", "/"),
                    "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "words": len(text.split()),
                    "split": _split_for(doc_id),
                }
            )

    rows.sort(key=lambda r: (r["split"], r["id"]))
    if limit is not None:
        rows = rows[: max(1, limit)]
    return rows


def prepare_cmd(args) -> int:
    rows = collect_human_bg_benchmark(ROOT, limit=args.limit)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    train = [r for r in rows if r["split"] == "train"]
    holdout = [r for r in rows if r["split"] == "holdout"]
    payload = {
        "schema_version": 1,
        "arms": ["no_guide", "current_manacost", "optimized_compact"],
        "counts": {"total": len(rows), "train": len(train), "holdout": len(holdout)},
        "documents": rows,
    }
    manifest_file = out_dir / "manifest.json"
    manifest_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"style-benchmark: {len(rows)} human BG гайдов "
        f"(train={len(train)}, holdout={len(holdout)}) -> {manifest_file}"
    )
    return 0


def eval_cmd(args) -> int:
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    holdout = [d for d in manifest.get("documents", []) if d.get("split") == "holdout"]
    arms = manifest.get("arms", ["no_guide", "current_manacost", "optimized_compact"])
    brief_calls = len(holdout)  # извлечение нейтрального фактового брифа из эталона
    gen_calls = len(holdout) * len(arms)
    # 3 попарных сравнения (A vs B, B vs C, A vs C) x 2 перестановки позиций против эталона
    pair_calls = len(holdout) * 3 * 2
    total = brief_calls + gen_calls + pair_calls
    summary = {
        "holdout_docs": len(holdout),
        "arms": arms,
        "calls": {
            "brief_extraction": brief_calls,
            "draft_generation": gen_calls,
            "pairwise_judging": pair_calls,
            "total_claude_p_calls": total,
        },
        "dry_run": not args.execute,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not args.execute:
        print("style-benchmark: dry-run завершён; живой прогон claude -p не запускался (нужен --execute).")
        return 0
    print("style-benchmark: живой запуск будет подключён при явном старте эксперимента.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Подготовка и смета эксперимента write-like-me для BG")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_prep = sub.add_parser("prepare", help="собрать manifest чистого human BG корпуса")
    p_prep.add_argument("--out", default=str(ROOT / "build" / "style-benchmark"))
    p_prep.add_argument("--limit", type=int, default=None)
    p_prep.set_defaults(func=prepare_cmd)

    p_eval = sub.add_parser("eval", help="считать смету или запустить A/B/C оценку")
    p_eval.add_argument("--manifest", default=str(ROOT / "build" / "style-benchmark" / "manifest.json"))
    p_eval.add_argument("--dry-run", action="store_true", default=True)
    p_eval.add_argument("--execute", action="store_true", help="разрешить вызовы claude -p")
    p_eval.set_defaults(func=eval_cmd)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
