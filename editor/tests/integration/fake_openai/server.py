"""Deterministic OpenAI-compatible test server for the Compose E2E gate."""

from __future__ import annotations

import argparse
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

CALLS: list[dict[str, Any]] = []
LOCK = threading.Lock()
# The fake edit changes a word, not only whitespace: the pipeline accepts an
# edit only when the critic can quote a real before/after difference.
FAKE_SOURCE = "Проверьте  этот текст."
FAKE_EDIT = "Проверьте этот текст внимательно."


def _stage(system: str) -> str:
    if "QA_FINDINGS" in system:
        return "repair"
    if "Ты critic" in system:
        return "critic"
    if "Проанализируй текст" in system:
        return "analysis"
    return "rewrite"


def _scores(value: int = 8) -> dict[str, int]:
    return {
        "factual_preservation": value,
        "meaning_preservation": value,
        "clarity": value,
        "structure": value,
        "usefulness": value,
        "natural_russian": value,
        "author_voice": value,
        "terminology": value,
    }


def _payload(user: str) -> dict[str, Any]:
    """Critic and repair receive JSON data in the user message."""
    try:
        parsed = json.loads(user)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _review(payload: dict[str, Any], system: str, repair: bool) -> dict[str, Any]:
    """Supply test evidence for the actual review contract, never production judgments."""
    source, candidate = str(payload["source"]), str(payload["candidate"])
    practices = list(dict.fromkeys(re.findall(r"\[([a-z_]+)\|(?:fact|literary)_review\]", system)))
    if len(practices) != 26:
        raise ValueError("expected the complete practice catalog in the critic prompt")

    def check(identifier: str) -> dict[str, Any]:
        return {
            "id": identifier,
            "status": "clear",
            "quote": candidate,
            "reason": "Test fixture: this dimension has no unrelated defect.",
        }

    preservation = []
    for identifier in (
        "facts_numbers",
        "conditions_exceptions_negation",
        "modality",
        "entities_roles",
        "author_voice",
        "quotations_markup",
        "strengths",
    ):
        item = {**check(identifier), "original_quote": source}
        if source != candidate and identifier in {"author_voice", "strengths"}:
            item["change_evidence"] = [
                {
                    "original_quote": source,
                    "quote": candidate,
                    "disposition": "justified",
                    "reason": "Test fixture: changed passage reviewed.",
                    "benefit": "Test fixture: local readability.",
                    "meaning_risk": "Test fixture: no unrelated loss.",
                }
            ]
        preservation.append(item)
    assessments = []
    for edit in payload.get("local_edits") or []:
        assessment = {
            "edit_id": edit["id"],
            "reading_quote": edit["candidate_context"],
            "reading": "awkward" if repair else "natural",
            "scope_quote": candidate,
            "scope": "preserved",
            "decision": "repair" if repair else "keep",
            "reason": "Test fixture: local wording reviewed.",
        }
        if repair:
            assessment["finding_rule_id"] = "clarity"
        assessments.append(assessment)
    return {
        "practice_checks": [check(identifier) for identifier in practices],
        "logic_checks": [
            check(identifier)
            for identifier in (
                "coherence",
                "causal_support",
                "scope_and_conditions",
                "reference_consistency",
                "information_gain",
            )
        ],
        "preservation_checks": preservation,
        "source_checks": [],
        "original_factual_checks": {
            "whole_text_checked": True,
            "internal_consistency": "clear",
            "source_agreement": "not_performed",
            "issues": [],
        },
        "edit_assessments": assessments,
    }


def _reply(stage: str, user: str, system: str) -> str:
    if stage == "analysis":
        return json.dumps(
            {
                "thesis": "проверка",
                "audience": "игрок",
                "genre": "гайд",
                "paragraphs": [],
                "weak_spots": [],
                "repetitions": [],
                "unclear": [],
                "template_phrases": [],
                "missing_links": [],
                "factual_risks": [],
            },
            ensure_ascii=False,
        )
    if stage == "rewrite":
        # The draft payload is JSON: text plus a separate style_examples field.
        user = str(_payload(user).get("text") or user)
        if "Карта стоит 3 маны" in user:
            return "Карта стоит 4 маны."
        if "https://example.com" in user:
            return "Читайте https://evil.example."
        if "# Совет" in user:
            return "Совет\n\nНе спешите."
        return FAKE_EDIT
    if stage == "repair":
        return FAKE_EDIT
    payload = _payload(user)
    candidate = payload.get("candidate")
    improvements = [
        {
            "category": "clarity",
            "before": str(payload.get("source", ""))[:80],
            "after": str(candidate or "")[:80],
            "reason": "добавлено наречие «внимательно» как прямое указание читателю",
        }
    ]
    if candidate == FAKE_EDIT:
        with LOCK:
            repairs = sum(call["stage"] == "repair" for call in CALLS)
        findings = (
            []
            if repairs
            else [
                {
                    "rule_id": "clarity",
                    "severity": "warning",
                    "message": f"Test fixture: уточнить «{candidate}»",
                    "line": 1,
                }
            ]
        )
        return json.dumps(
            {
                "verdict": "repair" if findings else "accept",
                "no_new_facts": True,
                "unsupported_additions": [],
                "scores": _scores(),
                "improvements": improvements,
                "regressions": [],
                "findings": findings,
                "repair_required": bool(findings),
                **_review(payload, system, bool(findings)),
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "verdict": "accept",
            "no_new_facts": True,
            "unsupported_additions": [],
            "scores": _scores(),
            "improvements": improvements,
            "regressions": [],
            "findings": [],
            "repair_required": False,
            **_review(payload, system, False),
        },
        ensure_ascii=False,
    )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_: Any) -> None:
        return

    def _json(self, code: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, {"ok": True})
            return
        if self.path == "/calls":
            with LOCK:
                self._json(200, {"calls": list(CALLS)})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/reset":
            with LOCK:
                CALLS.clear()
            self._json(200, {"ok": True})
            return
        if self.path != "/v1/chat/completions":
            self._json(404, {"error": "not found"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(size))
            messages = payload["messages"]
            system = str(messages[0]["content"])
            user = str(messages[-1]["content"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            self._json(400, {"error": {"message": str(error)}})
            return
        stage = _stage(system)
        call = {"stage": stage, "system": system, "user": user, "model": payload.get("model")}
        with LOCK:
            CALLS.append(call)
        content = _reply(stage, user, system)
        self._json(200, {"choices": [{"message": {"role": "assistant", "content": content}}]})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
