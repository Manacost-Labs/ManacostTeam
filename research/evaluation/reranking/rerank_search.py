#!/usr/bin/env python3
"""Optionally rerank saved source_access search results without changing ledgers."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

MODEL = "BAAI/bge-reranker-v2-m3"
REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
MAX_LENGTH = 512


def validate(payload: Any, max_candidates: int) -> list[tuple[str, str]]:
    if not 1 <= max_candidates <= 100:
        raise ValueError("max_candidates must be between 1 and 100")
    if not isinstance(payload, dict):
        raise TypeError("input must be a source_access search JSON object")
    if (
        payload.get("provider") != "scrape.do"
        or payload.get("operation") != "google-search"
    ):
        raise ValueError(
            "expected source_access search output (scrape.do/google-search)"
        )
    if "reranking" in payload:
        raise ValueError("use the original search output, not a reranked report")
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("input query must be a non-empty string")
    rows = payload.get("results")
    if not isinstance(rows, list):
        raise TypeError("results must be a list")
    pairs = []
    for index, row in enumerate(rows):
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("url"), str)
            or not row["url"].strip()
        ):
            raise ValueError(f"results[{index}] must have a URL")
        if row.get("evidence_status") != "discovery_only":
            raise ValueError(f"results[{index}] must remain discovery_only")
        if any(key in row for key in ("rerank_score", "reranked_position")):
            raise ValueError("results already contain reranking fields")
        # source_access preserves a missing provider field as JSON null.
        parts = [row.get("title"), row.get("snippet")]
        parts = ["" if part is None else part for part in parts]
        if not all(isinstance(part, str) for part in parts):
            raise ValueError(f"results[{index}] title/snippet must be strings")
        passage = "\n".join(part.strip() for part in parts if part.strip())
        if index < max_candidates:
            if not passage:
                raise ValueError(f"results[{index}] has no title/snippet to rank")
            pairs.append((query, passage))
    return pairs


def score_bge(
    pairs: list[tuple[str, str]], *, allow_download: bool, batch_size: int
) -> list[float]:
    # Heavy dependencies and model loading stay outside the default research runtime.
    from sentence_transformers import CrossEncoder
    from torch.nn import Identity

    model = CrossEncoder(
        MODEL,
        revision=REVISION,
        local_files_only=not allow_download,
        trust_remote_code=False,
        device="cpu",
        max_length=MAX_LENGTH,
        activation_fn=Identity(),
        model_kwargs={"use_safetensors": True},
    )
    scores = model.predict(pairs, batch_size=batch_size, show_progress_bar=False)
    return [float(score) for score in scores]


def rerank(
    raw: bytes,
    scorer: Callable[[list[tuple[str, str]]], list[float]],
    *,
    max_candidates: int = 50,
) -> dict[str, Any]:
    payload = json.loads(raw)
    pairs = validate(payload, max_candidates)
    started = time.monotonic()
    scores = list(scorer(pairs)) if pairs else []
    if len(scores) != len(pairs):
        raise ValueError("model returned a different number of scores than candidates")
    if any(
        isinstance(s, bool) or not isinstance(s, (float, int)) or not math.isfinite(s)
        for s in scores
    ):
        raise ValueError("model scores must be finite numbers")
    output = copy.deepcopy(payload)
    order = sorted(range(len(pairs)), key=lambda index: -scores[index])
    ranked = []
    for rank, index in enumerate(order, start=1):
        row = output["results"][index]
        # Original SERP position and all provenance stay intact. Equal scores are stable.
        row["rerank_score"] = float(scores[index])
        row["reranked_position"] = rank
        ranked.append(row)
    output["results"] = ranked + output["results"][len(pairs) :]
    output["reranking"] = {
        "schema_version": 1,
        "model": MODEL,
        "revision": REVISION,
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "created_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "max_length_tokens": MAX_LENGTH,
        "max_candidates": max_candidates,
        "scored_count": len(pairs),
        "unscored_count": len(output["results"]) - len(pairs),
        "score_semantics": "relevance_logit_not_evidence_or_probability",
        "text_fields": ["title", "snippet"],
    }
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, required=True, help="New report; never overwrites a file"
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=50,
        help="Rerank the first N results, 1..100",
    )
    parser.add_argument(
        "--batch-size", type=int, default=4, help="CPU inference batch, 1..16"
    )
    parser.add_argument(
        "--allow-download",
        action="store_true",
        help="Allow downloading pinned model weights",
    )
    args = parser.parse_args(argv)
    try:
        if args.input.resolve() == args.output.resolve() or args.output.exists():
            raise ValueError("output must be a new path, distinct from input")
        if not 1 <= args.batch_size <= 16:
            raise ValueError("batch-size must be between 1 and 16")
        raw = args.input.read_bytes()
        report = rerank(
            raw,
            lambda pairs: score_bge(
                pairs, allow_download=args.allow_download, batch_size=args.batch_size
            ),
            max_candidates=args.max_candidates,
        )
        report["reranking"]["runtime"] = {
            "device": "cpu",
            "batch_size": args.batch_size,
            "allow_download": args.allow_download,
            "model_loaded": bool(report["reranking"]["scored_count"]),
        }
        if report["reranking"]["scored_count"]:
            report["reranking"]["runtime"].update(
                {
                    "sentence_transformers": version("sentence-transformers"),
                    "torch": version("torch"),
                    "transformers": version("transformers"),
                }
            )
        serialized = (
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        )
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(serialized)
        print(
            json.dumps(
                {
                    "saved": str(args.output),
                    "scored": report["reranking"]["scored_count"],
                }
            )
        )
        return 0
    except (OSError, ValueError, TypeError, ImportError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(
            "Use the optional reranking requirements; cached weights are required unless --allow-download is set.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
