#!/usr/bin/env python3
"""Validate a persistent deep-research bundle and its ID references."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from search_support import (
    CANDIDATE_DECISIONS,
    CANDIDATE_REJECT_REASONS,
    MIN_EXCERPT_WORDS,
    QUERY_FAMILIES,
    QUERY_PASSES,
    quote_in_text,
)
from urllib.parse import unquote_plus, urlsplit, urlunsplit

from validate_editor_output import (
    WORD_RE,
    is_safe_external_url,
    mask_fenced_code,
    mask_hidden_html_elements,
    mask_html_comments,
    mask_indented_code,
    mask_inline_code_spans,
    mask_inline_html_tags,
    mask_raw_html_blocks,
    rendered_lines,
    strip_link_destinations,
    validate_markdown as validate_editor_markdown,
    visible_external_links,
)


REQUIRED_FILES = (
    "manifest.json",
    "queries.jsonl",
    "sources.jsonl",
    "evidence.jsonl",
    "claims.jsonl",
    "community.jsonl",
    "contradictions.jsonl",
    "checkpoints.jsonl",
    "audit.json",
    "report.md",
    "handoff.md",
)

STATUS_VALUES = {
    "planned",
    "discovering",
    "collecting",
    "validating",
    "auditing",
    "complete",
    "incomplete",
    "blocked",
}
CLAIM_STATUSES = {
    "supported",
    "supported_with_conditions",
    "contested",
    "unsupported",
    "unresolved",
    "rejected",
}
IMPORTANCE_VALUES = {"critical", "material", "supporting", "contextual"}
CONFIDENCE_VALUES = {"VERY_HIGH", "HIGH", "MEDIUM", "LOW", "SPECULATIVE"}
SCHEMA_VALUES = {"1.0", "1.1", "1.2"}
# Schema versions that carry the 1.1 provenance contract (1.2 adds search integrity).
PROVENANCE_SCHEMAS = {"1.1", "1.2"}
CHALLENGE_RESULT_VALUES = {"none_found", "found_weak", "found"}
OUTPUT_PROFILE_VALUES = {"editor-ready", "research-report", "raw-research"}
COVERAGE_CONTRACT_VALUES = {"1.0"}
SECTION_STATUS_VALUES = {"planned", "researching", "covered", "excluded", "unresolved"}
FINAL_SECTION_STATUS_VALUES = {"covered", "excluded", "unresolved"}
OUTPUT_DISPOSITION_VALUES = {"main", "useful_data", "appendix", "omit"}
USEFUL_DATA_TYPE_VALUES = {
    "number",
    "comparison",
    "advice",
    "sequence",
    "example",
    "mistake",
    "exception",
    "deck_code",
    "x_insight",
    "youtube_segment",
}
FINGERPRINT_STATUSES = {"verified", "unavailable", "exempt"}
FINGERPRINT_POLICIES = {"required", "when-permitted", "off"}
SEMANTIC_SUPPORT_VALUES = {"exact", "partial", "none", "contradicted"}
SEMANTIC_REVIEW_VALUES = {"pass", "warning", "fail"}
CLARITY_PRESERVATION_FIELDS = (
    "claims_preserved",
    "numbers_preserved",
    "scope_preserved",
    "citations_preserved",
    "limitations_preserved",
    "contradictions_preserved",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SECTION_ID_RE = re.compile(r"^SEC-[0-9]{4}$")
UNFILLED_ARTIFACT_PLACEHOLDER_RE = re.compile(
    r"\[(?:"
    r"название (?:основного|editor-ready) документа|"
    r"название раздела|название первоисточника|"
    r"дата и важная версия|дата, версия|"
    r"напишите здесь|дайте обычным содержательным абзацем|"
    r"короткое понятное название|краткая ограниченная формулировка|"
    r"точный раздел|когда материал применим|что мешает обобщить|"
    r"пройдено \||опционально, если существует|"
    r"подтвержд[её]н \|"
    r")[^\]]*\]",
    re.IGNORECASE,
)
YOUTUBE_TRANSIENT_CITATION_QUERY_KEYS = {
    "t",
    "start",
    "time_continue",
    "si",
    "feature",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="Research-run directory")
    parser.add_argument("--stage", choices=("working", "final"), default="working")
    return parser.parse_args()


def load_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"{path.name}: invalid JSON: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path.name}: root must be an object")
        return {}
    return value


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validated_file_sha256(
    path: Path, label: str, errors: list[str]
) -> str | None:
    try:
        return file_sha256(path)
    except (OSError, ValueError) as exc:
        errors.append(f"{label}: cannot hash file: {exc}")
        return None


def load_text(path: Path, errors: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"{path.name}: cannot read UTF-8 text: {exc}")
        return ""


def handoff_values(markdown: str, field: str) -> list[str]:
    visible = re.sub(r"<!--.*?(?:-->|$)", "", markdown, flags=re.DOTALL)
    label = "[_ ]".join(re.escape(part) for part in field.split("_"))
    return [
        match.group(1).casefold()
        for match in re.finditer(
            rf"(?im)^\s*(?:[-*]\s*)?{label}\s*:\s*`?"
            rf"([a-z][a-z0-9_-]*)`?\s*$",
            visible,
        )
    ]


def handoff_value(markdown: str, field: str) -> str | None:
    values = handoff_values(markdown, field)
    return values[0] if len(values) == 1 else None


def citation_identity(url: str) -> str | None:
    """Normalize a citation URL without erasing source-defining query values."""

    if not is_safe_external_url(url):
        return None
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    host = parsed.hostname.lower()
    rendered_host = f"[{host}]" if ":" in host else host
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    netloc = (
        rendered_host
        if port in {None, default_port}
        else f"{rendered_host}:{port}"
    )
    is_youtube = host in {"youtube.com", "youtu.be"} or host.endswith(
        ".youtube.com"
    )
    query_parts: list[str] = []
    for part in parsed.query.split("&") if parsed.query else ():
        raw_key = part.split("=", 1)[0]
        normalized_key = unquote_plus(raw_key).casefold()
        if normalized_key.startswith("utm_"):
            continue
        if is_youtube and normalized_key in YOUTUBE_TRANSIENT_CITATION_QUERY_KEYS:
            continue
        query_parts.append(part)
    path = parsed.path or "/"
    return urlunsplit(
        (
            parsed.scheme.lower(),
            netloc,
            path,
            "&".join(query_parts),
            "",
        )
    )


def validate_artifact_source_links(
    markdown: str,
    artifact_name: str,
    recorded_source_urls: set[str],
    errors: list[str],
) -> None:
    link_identities: dict[str, str] = {}
    for link in set(visible_external_links(markdown)):
        identity = citation_identity(link)
        if identity is None:
            errors.append(f"{artifact_name}: invalid source URL: {link}")
        else:
            link_identities[link] = identity
    unrecorded = sorted(
        link
        for link, identity in link_identities.items()
        if identity not in recorded_source_urls
    )
    if unrecorded:
        errors.append(
            f"{artifact_name}: source links missing from sources.jsonl: "
            + ", ".join(unrecorded)
        )


def load_jsonl(path: Path, errors: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        errors.append(f"{path.name}: cannot read: {exc}")
        return records
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name}:{line_number}: invalid JSON: {exc}")
            continue
        if not isinstance(value, dict):
            errors.append(f"{path.name}:{line_number}: record must be an object")
            continue
        value["__line__"] = line_number
        records.append(value)
    return records


def require_fields(
    record: dict[str, Any], fields: tuple[str, ...], label: str, errors: list[str]
) -> None:
    for field in fields:
        if field not in record or record[field] in (None, ""):
            errors.append(f"{label}: missing {field}")


def collect_ids(
    records: list[dict[str, Any]], field: str, prefix: str, ledger: str, errors: list[str]
) -> set[str]:
    values: set[str] = set()
    for record in records:
        line = record.get("__line__", "?")
        value = record.get(field)
        label = f"{ledger}:{line}"
        if not isinstance(value, str) or not value:
            errors.append(f"{label}: missing {field}")
            continue
        if not value.startswith(prefix):
            errors.append(f"{label}: {field} must start with {prefix}")
        if value in values:
            errors.append(f"{label}: duplicate ID {value}")
        values.add(value)
    return values


def require_list(record: dict[str, Any], field: str, label: str, errors: list[str]) -> list[Any]:
    value = record.get(field)
    if not isinstance(value, list):
        errors.append(f"{label}: {field} must be a list")
        return []
    return value


def list_or_empty(record: dict[str, Any], field: str) -> list[Any]:
    value = record.get(field)
    return value if isinstance(value, list) else []


def string_in(value: Any, allowed: set[str]) -> bool:
    return isinstance(value, str) and value in allowed


def validate_timestamp(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, str):
        errors.append(f"{label}: timestamp must be a string")
        return
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{label}: invalid ISO-8601 timestamp")


def validate_section_links(
    record: dict[str, Any],
    label: str,
    section_ids: set[str],
    errors: list[str],
) -> list[str]:
    values = require_list(record, "deliverable_section_ids", label, errors)
    valid: list[str] = []
    if not values:
        errors.append(f"{label}: deliverable_section_ids must not be empty")
        return valid
    for value in values:
        if not isinstance(value, str):
            errors.append(f"{label}: deliverable_section_ids must contain strings")
            continue
        if value not in section_ids:
            errors.append(f"{label}: unknown deliverable section {value}")
            continue
        if value not in valid:
            valid.append(value)
    return valid


def validate_output_disposition(
    record: dict[str, Any], label: str, errors: list[str]
) -> str | None:
    value = record.get("output_disposition")
    if not string_in(value, OUTPUT_DISPOSITION_VALUES):
        errors.append(f"{label}: invalid output_disposition")
        return None
    if value == "omit" and not isinstance(record.get("output_omit_reason"), str):
        errors.append(f"{label}: omit requires output_omit_reason")
    elif value == "omit" and not record.get("output_omit_reason", "").strip():
        errors.append(f"{label}: omit requires output_omit_reason")
    if value == "useful_data":
        types = require_list(record, "useful_data_types", label, errors)
        if not types:
            errors.append(f"{label}: useful_data requires useful_data_types")
        for item in types:
            if not string_in(item, USEFUL_DATA_TYPE_VALUES):
                errors.append(f"{label}: invalid useful_data_type {item}")
    return value if isinstance(value, str) else None


def output_record_source_identities(
    record_id: str,
    evidence_by_id: dict[str, dict[str, Any]],
    claims_by_id: dict[str, dict[str, Any]],
    community_by_id: dict[str, dict[str, Any]],
    source_url_identities_by_id: dict[str, set[str]],
) -> set[str]:
    source_ids: set[str] = set()
    evidence_record = evidence_by_id.get(record_id)
    if evidence_record is not None:
        source_id = evidence_record.get("source_id")
        if isinstance(source_id, str):
            source_ids.add(source_id)

    claim_record = claims_by_id.get(record_id)
    if claim_record is not None:
        for field in ("supporting_evidence_ids", "challenging_evidence_ids"):
            for evidence_id in list_or_empty(claim_record, field):
                if not isinstance(evidence_id, str):
                    continue
                linked_evidence = evidence_by_id.get(evidence_id)
                source_id = (
                    linked_evidence.get("source_id") if linked_evidence else None
                )
                if isinstance(source_id, str):
                    source_ids.add(source_id)

    community_record = community_by_id.get(record_id)
    if community_record is not None:
        for evidence_id in list_or_empty(
            community_record, "supporting_evidence_ids"
        ):
            if not isinstance(evidence_id, str):
                continue
            linked_evidence = evidence_by_id.get(evidence_id)
            source_id = linked_evidence.get("source_id") if linked_evidence else None
            if isinstance(source_id, str):
                source_ids.add(source_id)

    identities: set[str] = set()
    for source_id in source_ids:
        identities.update(source_url_identities_by_id.get(source_id, set()))
    return identities


def routed_artifact_visible_lines(markdown: str) -> list[str]:
    """Keep reader-visible Markdown while excluding code and hidden HTML."""

    lines = mask_raw_html_blocks(
        mask_indented_code(mask_fenced_code(rendered_lines(markdown)))
    )
    visible = mask_hidden_html_elements("\n".join(lines))
    visible = mask_inline_html_tags(visible)
    return mask_html_comments(visible.split("\n"))


def markdown_record_blocks(markdown: str, record_id: str) -> list[str]:
    visible_lines = routed_artifact_visible_lines(markdown)
    id_lines = [strip_link_destinations(line) for line in visible_lines]
    record_pattern = re.compile(
        rf"(?<![A-Z0-9-]){re.escape(record_id)}(?![A-Z0-9-])"
    )
    heading_indexes = [
        index
        for index, line in enumerate(id_lines)
        if re.match(r"^#{2,6}\s+.+$", line)
    ]
    blocks: list[str] = []
    if not heading_indexes:
        id_text = "\n".join(id_lines)
        return ["\n".join(visible_lines)] if record_pattern.search(id_text) else []
    for index, start in enumerate(heading_indexes):
        end = (
            heading_indexes[index + 1]
            if index + 1 < len(heading_indexes)
            else len(visible_lines)
        )
        id_block = "\n".join(id_lines[start:end])
        if record_pattern.search(id_block):
            blocks.append("\n".join(visible_lines[start:end]))
    return blocks


def block_has_substantive_material(block: str) -> bool:
    without_code = mask_inline_code_spans(
        "\n".join(routed_artifact_visible_lines(block))
    )
    body_lines = []
    metadata_prefixes = (
        "связанные записи:",
        "раздел:",
        "назначение записи:",
        "прямой проверенный источник:",
        "прямое основание:",
        "актуальность:",
        "условия:",
        "ограничения:",
        "уверенность:",
        "статус:",
        "повторяйте ",
        "повторите ",
        "linked records:",
        "section:",
        "output disposition:",
        "source:",
        "as of:",
        "conditions:",
        "limitations:",
        "confidence:",
        "status:",
        "repeat ",
    )
    for line in without_code.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "-", "*", "|", ">")):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            continue
        if re.match(r"^\[[^\]]+\]:", stripped):
            continue
        if stripped.casefold().startswith(metadata_prefixes):
            continue
        rendered = re.sub(r"!?\[[^\]]*\]\([^)]+\)", "", stripped)
        rendered = re.sub(r"\[[^\]]+\]\[[^\]]*\]", "", rendered)
        rendered = re.sub(r"https?://\S+", "", rendered)
        rendered = re.sub(r"[`*_~]", "", rendered).strip()
        if rendered:
            body_lines.append(rendered)
    substantive_text = re.sub(r"\s+", " ", " ".join(body_lines)).strip()
    return (
        len(substantive_text) >= 60
        and len(WORD_RE.findall(substantive_text)) >= 8
    )


def validate_routed_record_artifact(
    markdown: str,
    artifact_name: str,
    route_name: str,
    record_ids: set[str],
    evidence_by_id: dict[str, dict[str, Any]],
    claims_by_id: dict[str, dict[str, Any]],
    community_by_id: dict[str, dict[str, Any]],
    source_url_identities_by_id: dict[str, set[str]],
    errors: list[str],
) -> None:
    for record_id in sorted(record_ids):
        blocks = markdown_record_blocks(markdown, record_id)
        if not blocks:
            errors.append(
                f"{artifact_name}: missing {route_name} record {record_id}"
            )
            continue
        substantive_blocks = [block for block in blocks if block_has_substantive_material(block)]
        if not substantive_blocks:
            errors.append(
                f"{artifact_name}: {route_name} record {record_id} has no "
                "substantive material"
            )
            continue
        expected_identities = output_record_source_identities(
            record_id,
            evidence_by_id,
            claims_by_id,
            community_by_id,
            source_url_identities_by_id,
        )
        if not expected_identities:
            errors.append(
                f"{artifact_name}: {route_name} record {record_id} has no "
                "linked source evidence"
            )
            continue
        matching_link = False
        for block in substantive_blocks:
            block_identities = {
                identity
                for link in visible_external_links(block)
                if (identity := citation_identity(link)) is not None
            }
            if expected_identities.intersection(block_identities):
                matching_link = True
                break
        if not matching_link:
            errors.append(
                f"{artifact_name}: {route_name} record {record_id} requires a "
                "visible inspected source link matching its evidence"
            )


def validate_candidates(
    root: Path, query_ids: set[str], source_ids: set[str], errors: list[str]
) -> None:
    """Validate the optional candidates.jsonl ledger of seen search results."""

    path = root / "candidates.jsonl"
    if not path.is_file():
        return
    candidates = load_jsonl(path, errors)
    collect_ids(candidates, "candidate_id", "CAN-", "candidates.jsonl", errors)
    for record in candidates:
        label = f"candidates.jsonl:{record['__line__']}"
        require_fields(record, ("query_id", "url", "decision"), label, errors)
        query_id = record.get("query_id")
        if isinstance(query_id, str) and query_id and query_id not in query_ids:
            errors.append(f"{label}: unknown query {query_id}")
        decision = record.get("decision")
        if not string_in(decision, CANDIDATE_DECISIONS):
            errors.append(f"{label}: invalid decision")
            continue
        if decision == "rejected" and not string_in(
            record.get("reason"), CANDIDATE_REJECT_REASONS
        ):
            errors.append(f"{label}: rejected candidate needs a canonical reason")
        if decision == "opened":
            source_id = record.get("source_id")
            if not string_in(source_id, source_ids):
                errors.append(f"{label}: opened candidate must reference a known source_id")


def main() -> int:
    args = parse_args()
    root = Path(args.directory).expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []

    if not root.is_dir():
        print(f"Research bundle: FAIL\n- not a directory: {root}")
        return 1
    for name in REQUIRED_FILES:
        if not (root / name).is_file():
            errors.append(f"missing required file: {name}")
    if errors:
        print("Research bundle: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    manifest = load_json(root / "manifest.json", errors)
    schema_hint = manifest.get("schema_version")
    audit = load_json(root / "audit.json", errors)
    queries = load_jsonl(root / "queries.jsonl", errors)
    sources = load_jsonl(root / "sources.jsonl", errors)
    evidence = load_jsonl(root / "evidence.jsonl", errors)
    claims = load_jsonl(root / "claims.jsonl", errors)
    community = load_jsonl(root / "community.jsonl", errors)
    contradictions = load_jsonl(root / "contradictions.jsonl", errors)
    checkpoints = load_jsonl(root / "checkpoints.jsonl", errors)
    semantic_audit: list[dict[str, Any]] = []
    if schema_hint in PROVENANCE_SCHEMAS:
        semantic_path = root / "semantic-audit.jsonl"
        if not semantic_path.is_file():
            errors.append("missing required file: semantic-audit.jsonl")
        else:
            semantic_audit = load_jsonl(semantic_path, errors)

    require_fields(
        manifest,
        (
            "schema_version",
            "research_id",
            "main_question",
            "created_at",
            "updated_at",
            "as_of",
            "depth",
            "modifiers",
            "domain_adapters",
            "status",
            "current_context",
            "prior_research_ids",
        ),
        "manifest.json",
        errors,
    )
    schema_version = manifest.get("schema_version")
    if not string_in(schema_version, SCHEMA_VALUES):
        errors.append("manifest.json: unsupported schema_version")
    if not str(manifest.get("research_id", "")).startswith("RES-"):
        errors.append("manifest.json: research_id must start with RES-")
    if not string_in(manifest.get("depth"), {"quick", "deep", "exhaustive"}):
        errors.append("manifest.json: invalid depth")
    effective_output_profile = manifest.get("output_profile")
    modifiers = manifest.get("modifiers")
    modifier_values = modifiers if isinstance(modifiers, list) else []
    if manifest:
        if "output_profile" not in manifest:
            if schema_version == "1.2":
                errors.append("manifest.json: schema 1.2 requires output_profile")
            elif schema_version == "1.1":
                effective_output_profile = (
                    "raw-research"
                    if "raw-research" in modifier_values
                    else "research-report"
                )
                message = (
                    "manifest.json: legacy schema 1.1 is missing output_profile; "
                    f"inferred {effective_output_profile}"
                )
                if args.stage == "final":
                    errors.append(message + "; explicit backfill is required for final")
                else:
                    warnings.append(message)
            else:
                effective_output_profile = (
                    "raw-research"
                    if "raw-research" in modifier_values
                    else "research-report"
                )
                warnings.append(
                    "manifest.json: legacy schema without output_profile; "
                    f"assuming {effective_output_profile}"
                )
        elif not string_in(manifest.get("output_profile"), OUTPUT_PROFILE_VALUES):
            errors.append("manifest.json: invalid output_profile")
        if "raw-research" in modifier_values and "output_profile" in manifest:
            errors.append(
                "manifest.json: raw-research must be output_profile, not a modifier"
            )
    if not string_in(manifest.get("status"), STATUS_VALUES):
        errors.append("manifest.json: invalid status")
    for field in ("modifiers", "domain_adapters", "prior_research_ids"):
        if not isinstance(manifest.get(field), list):
            errors.append(f"manifest.json: {field} must be a list")
    if not isinstance(manifest.get("current_context"), dict):
        errors.append("manifest.json: current_context must be an object")
    fingerprint_policy = "off"
    if schema_version in PROVENANCE_SCHEMAS:
        provenance = manifest.get("provenance")
        if not isinstance(provenance, dict):
            errors.append("manifest.json: schema 1.1 requires provenance object")
        else:
            require_fields(
                provenance,
                ("fingerprint_policy", "snapshot_policy", "hash_algorithm"),
                "manifest.json:provenance",
                errors,
            )
            fingerprint_policy = str(provenance.get("fingerprint_policy", ""))
            if not string_in(fingerprint_policy, FINGERPRINT_POLICIES):
                errors.append("manifest.json: invalid provenance fingerprint_policy")
            if provenance.get("hash_algorithm") != "sha256":
                errors.append("manifest.json: provenance hash_algorithm must be sha256")
    for field in ("created_at", "updated_at"):
        validate_timestamp(manifest.get(field), f"manifest.json:{field}", errors)
    try:
        date.fromisoformat(str(manifest.get("as_of", "")))
    except ValueError:
        errors.append("manifest.json: as_of must use YYYY-MM-DD")

    coverage_contract_version = manifest.get("coverage_contract_version")
    coverage_enabled = coverage_contract_version == "1.0"
    if coverage_contract_version is not None and not string_in(
        coverage_contract_version, COVERAGE_CONTRACT_VALUES
    ):
        errors.append("manifest.json: unsupported coverage_contract_version")
    if coverage_enabled and effective_output_profile != "editor-ready":
        errors.append(
            "manifest.json: coverage contract is only valid for editor-ready output"
        )
    if coverage_enabled and schema_version not in PROVENANCE_SCHEMAS:
        errors.append("manifest.json: coverage contract requires schema_version 1.1 or 1.2")
    if effective_output_profile == "editor-ready" and coverage_contract_version is None:
        warnings.append(
            "manifest.json: legacy editor-ready bundle without coverage contract"
        )

    plan: dict[str, Any] = {}
    section_ids: set[str] = set()
    section_status_by_id: dict[str, str] = {}
    useful_data_required = (
        coverage_enabled
        and string_in(manifest.get("depth"), {"deep", "exhaustive"})
    )
    if coverage_enabled:
        plan_path = root / "plan.json"
        if not plan_path.is_file():
            errors.append("missing coverage contract file: plan.json")
        else:
            plan = load_json(plan_path, errors)
        if plan:
            require_fields(
                plan,
                (
                    "coverage_contract_version",
                    "research_id",
                    "updated_at",
                    "deliverable_outline",
                ),
                "plan.json",
                errors,
            )
            if plan.get("coverage_contract_version") != coverage_contract_version:
                errors.append(
                    "plan.json: coverage_contract_version must match manifest.json"
                )
            if plan.get("research_id") != manifest.get("research_id"):
                errors.append("plan.json: research_id must match manifest.json")
            validate_timestamp(plan.get("updated_at"), "plan.json:updated_at", errors)
            outline = plan.get("deliverable_outline")
            if not isinstance(outline, list):
                errors.append("plan.json: deliverable_outline must be a list")
                outline = []
            if args.stage == "final" and not outline:
                errors.append("plan.json: final stage requires deliverable sections")
            for index, section in enumerate(outline, start=1):
                label = f"plan.json:deliverable_outline:{index}"
                if not isinstance(section, dict):
                    errors.append(f"{label}: section must be an object")
                    continue
                require_fields(
                    section,
                    (
                        "section_id",
                        "working_title",
                        "reader_question",
                        "readiness_condition",
                        "status",
                    ),
                    label,
                    errors,
                )
                for field in (
                    "working_title",
                    "reader_question",
                    "readiness_condition",
                ):
                    value = section.get(field)
                    if not isinstance(value, str) or not value.strip():
                        errors.append(f"{label}: {field} must be a non-empty string")
                section_id = section.get("section_id")
                if not isinstance(section_id, str) or not SECTION_ID_RE.fullmatch(
                    section_id
                ):
                    errors.append(f"{label}: section_id must use SEC-0001 format")
                    continue
                if section_id in section_ids:
                    errors.append(f"{label}: duplicate section_id {section_id}")
                section_ids.add(section_id)
                status = section.get("status")
                if not string_in(status, SECTION_STATUS_VALUES):
                    errors.append(f"{label}: invalid section status")
                    continue
                section_status_by_id[section_id] = status
                if args.stage == "final" and not string_in(
                    status, FINAL_SECTION_STATUS_VALUES
                ):
                    errors.append(
                        f"{label}: section {section_id} final section status must be "
                        "covered, excluded, or unresolved"
                    )
                if (
                    args.stage == "final"
                    and string_in(status, {"excluded", "unresolved"})
                    and (
                        not isinstance(section.get("coverage_note"), str)
                        or not section.get("coverage_note", "").strip()
                    )
                ):
                    errors.append(
                        f"{label}: {status} section requires coverage_note"
                    )
        if not isinstance(audit.get("coverage_review"), dict):
            errors.append("audit.json: coverage contract requires coverage_review")
        if useful_data_required and not (root / "useful-data.md").is_file():
            errors.append(
                "missing coverage contract file: useful-data.md is required for "
                "deep or exhaustive editor-ready research"
            )

    query_ids = collect_ids(queries, "query_id", "QRY-", "queries.jsonl", errors)
    source_ids = collect_ids(sources, "source_id", "SRC-", "sources.jsonl", errors)
    evidence_ids = collect_ids(evidence, "evidence_id", "EVD-", "evidence.jsonl", errors)
    claim_ids = collect_ids(claims, "claim_id", "CLM-", "claims.jsonl", errors)
    community_ids = collect_ids(
        community, "community_claim_id", "COM-", "community.jsonl", errors
    )
    collect_ids(contradictions, "contradiction_id", "CTR-", "contradictions.jsonl", errors)
    collect_ids(checkpoints, "checkpoint_id", "CHK-", "checkpoints.jsonl", errors)
    collect_ids(
        semantic_audit,
        "semantic_audit_id",
        "SEM-",
        "semantic-audit.jsonl",
        errors,
    )

    query_sections_by_id: dict[str, set[str]] = {}
    record_sections_by_id: dict[str, set[str]] = {}
    record_disposition_by_id: dict[str, str] = {}

    for record in queries:
        label = f"queries.jsonl:{record['__line__']}"
        require_fields(
            record, ("pass", "family", "query", "executed_at", "status"), label, errors
        )
        if record.get("executed_at"):
            validate_timestamp(record.get("executed_at"), f"{label}:executed_at", errors)
        if "result_source_ids" in record:
            for source_id in require_list(record, "result_source_ids", label, errors):
                if not string_in(source_id, source_ids):
                    errors.append(f"{label}: unknown result source {source_id}")
        if coverage_enabled:
            linked_sections = validate_section_links(
                record, label, section_ids, errors
            )
            query_id = record.get("query_id")
            if isinstance(query_id, str):
                query_sections_by_id[query_id] = set(linked_sections)
        family = record.get("family")
        if isinstance(family, str) and family and family not in QUERY_FAMILIES:
            message = (
                f"{label}: non-canonical query family {family!r}; "
                "search coverage cannot count it toward a branch"
            )
            (errors if schema_version == "1.2" else warnings).append(message)
        pass_value = record.get("pass")
        if isinstance(pass_value, str) and pass_value and pass_value not in QUERY_PASSES:
            message = f"{label}: non-canonical query pass {pass_value!r}"
            (errors if schema_version == "1.2" else warnings).append(message)
        if schema_version == "1.2" and not record.get("language"):
            warnings.append(f"{label}: schema 1.2 query should record a language")

    validate_candidates(root, query_ids, source_ids, errors)

    for record in sources:
        label = f"sources.jsonl:{record['__line__']}"
        source_fields = (
            "title",
            "accessed_at",
            "access_integrity",
            "source_type",
            "lineage_id",
        )
        if schema_version in PROVENANCE_SCHEMAS:
            source_fields += (
                "requested_url",
                "final_url",
                "mutable",
                "fingerprint_status",
            )
        else:
            source_fields += ("url",)
        require_fields(record, source_fields, label, errors)
        urls = (
            (
                ("requested_url", record.get("requested_url")),
                ("final_url", record.get("final_url")),
            )
            if schema_version in PROVENANCE_SCHEMAS
            else (("url", record.get("url")),)
        )
        for field, url in urls:
            url_text = str(url or "")
            if schema_version in PROVENANCE_SCHEMAS and url_text and citation_identity(url_text) is None:
                errors.append(f"{label}: invalid {field}")
            elif url_text.startswith(("https://", "http://")):
                if citation_identity(url_text) is None:
                    errors.append(f"{label}: invalid {field}")
            elif url_text:
                warnings.append(f"{label}: URL is not HTTP(S)")
        if record.get("accessed_at"):
            validate_timestamp(record.get("accessed_at"), f"{label}:accessed_at", errors)
        if schema_version in PROVENANCE_SCHEMAS:
            if not isinstance(record.get("mutable"), bool):
                errors.append(f"{label}: mutable must be boolean")
            status = record.get("fingerprint_status")
            if not string_in(status, FINGERPRINT_STATUSES):
                errors.append(f"{label}: invalid fingerprint_status")
            if status == "verified":
                require_fields(
                    record,
                    (
                        "content_sha256",
                        "content_bytes",
                        "fingerprinted_at",
                        "snapshot_path",
                    ),
                    label,
                    errors,
                )
                digest = str(record.get("content_sha256", ""))
                if not re.fullmatch(r"[0-9a-f]{64}", digest):
                    errors.append(f"{label}: invalid content_sha256")
                if not isinstance(record.get("content_bytes"), int) or record.get(
                    "content_bytes", -1
                ) < 0:
                    errors.append(f"{label}: content_bytes must be a non-negative integer")
                if record.get("fingerprinted_at"):
                    validate_timestamp(
                        record.get("fingerprinted_at"), f"{label}:fingerprinted_at", errors
                    )
                snapshot_value = record.get("snapshot_path")
                if isinstance(snapshot_value, str) and snapshot_value:
                    try:
                        snapshot = (root / snapshot_value).resolve()
                        if not snapshot.is_relative_to(root):
                            errors.append(f"{label}: snapshot_path escapes bundle")
                        elif not snapshot.is_file():
                            errors.append(f"{label}: snapshot_path does not exist")
                        else:
                            actual = hashlib.sha256(snapshot.read_bytes()).hexdigest()
                            if digest and actual != digest:
                                errors.append(
                                    f"{label}: snapshot hash does not match "
                                    "content_sha256"
                                )
                    except (OSError, RuntimeError, ValueError) as exc:
                        errors.append(f"{label}: invalid snapshot_path: {exc}")
            elif string_in(status, {"unavailable", "exempt"}):
                require_fields(record, ("fingerprint_reason",), label, errors)

    snapshot_by_source: dict[str, Path] = {}
    if schema_version == "1.2":
        for record in sources:
            source_id = record.get("source_id")
            snapshot_value = record.get("snapshot_path")
            if (
                record.get("fingerprint_status") == "verified"
                and isinstance(source_id, str)
                and isinstance(snapshot_value, str)
                and snapshot_value
            ):
                try:
                    candidate = (root / snapshot_value).resolve()
                    usable = candidate.is_relative_to(root) and candidate.is_file()
                except (OSError, ValueError):
                    usable = False
                if usable:
                    snapshot_by_source[source_id] = candidate
    snapshot_text_cache: dict[str, str] = {}
    anchored_evidence_ids: set[str] = set()

    for record in evidence:
        label = f"evidence.jsonl:{record['__line__']}"
        require_fields(
            record,
            ("source_id", "claim_ids", "relationship", "locator", "evidence_type"),
            label,
            errors,
        )
        if not record.get("faithful_paraphrase") and not record.get("exact_excerpt"):
            errors.append(f"{label}: needs faithful_paraphrase or exact_excerpt")
        if schema_version == "1.2":
            excerpt = record.get("exact_excerpt")
            evidence_source = record.get("source_id")
            if excerpt is not None and not isinstance(excerpt, str):
                errors.append(f"{label}: exact_excerpt must be a string")
            elif isinstance(excerpt, str) and excerpt.strip():
                if len(excerpt.split()) < MIN_EXCERPT_WORDS:
                    errors.append(
                        f"{label}: exact_excerpt needs at least {MIN_EXCERPT_WORDS} words "
                        "to be verifiable"
                    )
                elif isinstance(evidence_source, str) and evidence_source in snapshot_by_source:
                    if evidence_source not in snapshot_text_cache:
                        snapshot_text_cache[evidence_source] = snapshot_by_source[
                            evidence_source
                        ].read_text(encoding="utf-8", errors="replace")
                    if quote_in_text(snapshot_text_cache[evidence_source], excerpt):
                        evidence_id = record.get("evidence_id")
                        if isinstance(evidence_id, str):
                            anchored_evidence_ids.add(evidence_id)
                    else:
                        errors.append(
                            f"{label}: exact_excerpt not found in snapshot of {evidence_source}"
                        )
        if not string_in(record.get("source_id"), source_ids):
            errors.append(f"{label}: unknown source {record.get('source_id')}")
        linked_claim_ids = require_list(record, "claim_ids", label, errors)
        for claim_id in linked_claim_ids:
            if not string_in(claim_id, claim_ids):
                errors.append(f"{label}: unknown claim {claim_id}")
        if coverage_enabled:
            linked_sections = validate_section_links(
                record, label, section_ids, errors
            )
            disposition = validate_output_disposition(record, label, errors)
            evidence_id = record.get("evidence_id")
            if isinstance(evidence_id, str):
                record_sections_by_id[evidence_id] = set(linked_sections)
                if disposition is not None:
                    record_disposition_by_id[evidence_id] = disposition
            if (
                args.stage == "final"
                and disposition != "omit"
                and not linked_claim_ids
            ):
                errors.append(f"{label}: retained evidence must link to a claim")

    evidence_by_source_snapshot_ids = {
        record["evidence_id"]
        for record in evidence
        if isinstance(record.get("evidence_id"), str)
        and isinstance(record.get("source_id"), str)
        and record.get("source_id") in snapshot_by_source
    }

    for record in claims:
        label = f"claims.jsonl:{record['__line__']}"
        require_fields(
            record,
            (
                "claim",
                "importance",
                "status",
                "confidence",
                "supporting_evidence_ids",
                "challenging_evidence_ids",
            ),
            label,
            errors,
        )
        if not string_in(record.get("status"), CLAIM_STATUSES):
            errors.append(f"{label}: invalid claim status")
        if not string_in(record.get("importance"), IMPORTANCE_VALUES):
            errors.append(f"{label}: invalid importance")
        if not string_in(record.get("confidence"), CONFIDENCE_VALUES):
            errors.append(f"{label}: invalid confidence")
        linked = []
        for field in ("supporting_evidence_ids", "challenging_evidence_ids"):
            for evidence_id in require_list(record, field, label, errors):
                linked.append(evidence_id)
                if not string_in(evidence_id, evidence_ids):
                    errors.append(f"{label}: unknown evidence {evidence_id}")
        if coverage_enabled:
            linked_sections = validate_section_links(
                record, label, section_ids, errors
            )
            disposition = validate_output_disposition(record, label, errors)
            claim_id = record.get("claim_id")
            if isinstance(claim_id, str):
                record_sections_by_id[claim_id] = set(linked_sections)
                if disposition is not None:
                    record_disposition_by_id[claim_id] = disposition
            if record.get("status") == "rejected" and disposition != "omit":
                errors.append(f"{label}: rejected claim must use output_disposition omit")
            if (
                record.get("status") != "rejected"
                and string_in(
                    record.get("importance"), {"critical", "material"}
                )
                and disposition != "main"
            ):
                errors.append(
                    f"{label}: critical or material claim must use "
                    "output_disposition main"
                )
            if (
                args.stage == "final"
                and record.get("status") != "rejected"
                and disposition != "omit"
                and not linked
            ):
                errors.append(f"{label}: retained claim must link to evidence")
        if (
            schema_version == "1.2"
            and record.get("status") != "rejected"
            and string_in(record.get("importance"), {"critical", "material"})
        ):
            importance = str(record.get("importance"))
            challenge_search = record.get("challenge_search")
            challenge_recorded = False
            if challenge_search is not None:
                if not isinstance(challenge_search, dict):
                    errors.append(f"{label}: challenge_search must be an object")
                else:
                    search_query_ids = require_list(
                        challenge_search, "query_ids", f"{label}:challenge_search", errors
                    )
                    for query_id in search_query_ids:
                        if not string_in(query_id, query_ids):
                            errors.append(
                                f"{label}: challenge_search references unknown query {query_id}"
                            )
                    if not string_in(challenge_search.get("result"), CHALLENGE_RESULT_VALUES):
                        errors.append(f"{label}: challenge_search result is invalid")
                    challenge_recorded = bool(search_query_ids)
            if not list_or_empty(record, "challenging_evidence_ids") and not challenge_recorded:
                message = (
                    f"{label}: {importance} claim has no challenging evidence and no "
                    "recorded challenge_search"
                )
                if args.stage == "final" and importance == "critical":
                    errors.append(message)
                else:
                    warnings.append(message)
            unanchored = [
                evidence_id
                for evidence_id in list_or_empty(record, "supporting_evidence_ids")
                if isinstance(evidence_id, str)
                and evidence_id in evidence_by_source_snapshot_ids
                and evidence_id not in anchored_evidence_ids
            ]
            if unanchored:
                message = (
                    f"{label}: supporting evidence without a verified exact_excerpt "
                    f"although its source has a snapshot: {', '.join(unanchored)}"
                )
                if args.stage == "final":
                    errors.append(message)
                else:
                    warnings.append(message)
        if (
            args.stage == "final"
            and isinstance(record.get("importance"), str)
            and record.get("importance") in {"critical", "material"}
        ):
            if record.get("status") == "unsupported" and record.get("importance") == "critical":
                errors.append(f"{label}: critical claim is unsupported")
            if record.get("status") != "rejected" and not linked:
                errors.append(f"{label}: decision-relevant claim has no linked evidence")
            if record.get("status") == "unresolved" and not record.get("impact_on_main_answer"):
                errors.append(f"{label}: unresolved claim needs impact_on_main_answer")

    evidence_by_id = {
        record["evidence_id"]: record
        for record in evidence
        if isinstance(record.get("evidence_id"), str)
    }
    claims_by_id = {
        record["claim_id"]: record
        for record in claims
        if isinstance(record.get("claim_id"), str)
    }
    community_by_id = {
        record["community_claim_id"]: record
        for record in community
        if isinstance(record.get("community_claim_id"), str)
    }
    for evidence_id, record in evidence_by_id.items():
        for claim_id in list_or_empty(record, "claim_ids"):
            if not isinstance(claim_id, str):
                continue
            claim = claims_by_id.get(claim_id)
            if not claim:
                continue
            reverse_links = list_or_empty(
                claim, "supporting_evidence_ids"
            ) + list_or_empty(
                claim, "challenging_evidence_ids"
            )
            if evidence_id not in reverse_links:
                errors.append(
                    f"evidence {evidence_id}: claim {claim_id} lacks reciprocal evidence link"
                )
    for claim_id, record in claims_by_id.items():
        for evidence_id in list_or_empty(
            record, "supporting_evidence_ids"
        ) + list_or_empty(
            record, "challenging_evidence_ids"
        ):
            if not isinstance(evidence_id, str):
                continue
            item = evidence_by_id.get(evidence_id)
            if item and claim_id not in list_or_empty(item, "claim_ids"):
                errors.append(
                    f"claim {claim_id}: evidence {evidence_id} lacks reciprocal claim link"
                )
    if coverage_enabled:
        for evidence_id, record in evidence_by_id.items():
            evidence_sections = record_sections_by_id.get(evidence_id, set())
            for claim_id in list_or_empty(record, "claim_ids"):
                if not isinstance(claim_id, str):
                    continue
                claim_sections = record_sections_by_id.get(str(claim_id), set())
                if claim_sections and evidence_sections.isdisjoint(claim_sections):
                    errors.append(
                        f"evidence {evidence_id}: linked claim {claim_id} has no "
                        "shared deliverable section"
                    )

    semantic_by_claim: dict[str, list[dict[str, Any]]] = {}
    for record in semantic_audit:
        label = f"semantic-audit.jsonl:{record['__line__']}"
        require_fields(
            record,
            (
                "claim_id",
                "evidence_id",
                "source_id",
                "semantic_support",
                "scope_match",
                "authority_match",
                "freshness_match",
                "evidence_type_match",
                "reviewer_status",
                "reviewer_basis",
                "audited_at",
            ),
            label,
            errors,
        )
        claim_id = record.get("claim_id")
        evidence_id = record.get("evidence_id")
        source_id = record.get("source_id")
        if not string_in(claim_id, claim_ids):
            errors.append(f"{label}: unknown claim {claim_id}")
        if not string_in(evidence_id, evidence_ids):
            errors.append(f"{label}: unknown evidence {evidence_id}")
        if not string_in(source_id, source_ids):
            errors.append(f"{label}: unknown source {source_id}")
        evidence_record = evidence_by_id.get(str(evidence_id))
        if evidence_record:
            if evidence_record.get("source_id") != source_id:
                errors.append(f"{label}: source_id does not match evidence source")
            if claim_id not in list_or_empty(evidence_record, "claim_ids"):
                errors.append(f"{label}: evidence is not linked to claim")
        if not string_in(record.get("semantic_support"), SEMANTIC_SUPPORT_VALUES):
            errors.append(f"{label}: invalid semantic_support")
        if not string_in(record.get("reviewer_status"), SEMANTIC_REVIEW_VALUES):
            errors.append(f"{label}: invalid reviewer_status")
        for field in (
            "scope_match",
            "authority_match",
            "freshness_match",
            "evidence_type_match",
        ):
            if not isinstance(record.get(field), bool):
                errors.append(f"{label}: {field} must be boolean")
        if record.get("audited_at"):
            validate_timestamp(record.get("audited_at"), f"{label}:audited_at", errors)
        if string_in(record.get("semantic_support"), {"none", "contradicted"}) and record.get(
            "reviewer_status"
        ) == "pass":
            errors.append(f"{label}: unsupported evidence cannot have reviewer_status pass")
        semantic_by_claim.setdefault(str(claim_id), []).append(record)

    for record in community:
        label = f"community.jsonl:{record['__line__']}"
        require_fields(record, ("community_claim", "consensus_strength"), label, errors)
        supporting_evidence = list_or_empty(record, "supporting_evidence_ids")
        if coverage_enabled:
            require_fields(
                record,
                ("claim_ids", "supporting_evidence_ids"),
                label,
                errors,
            )
            claim_links = require_list(record, "claim_ids", label, errors)
            supporting_evidence = require_list(
                record, "supporting_evidence_ids", label, errors
            )
            linked_sections = validate_section_links(
                record, label, section_ids, errors
            )
            disposition = validate_output_disposition(record, label, errors)
            community_id = record.get("community_claim_id")
            if isinstance(community_id, str):
                record_sections_by_id[community_id] = set(linked_sections)
                if disposition is not None:
                    record_disposition_by_id[community_id] = disposition
            for claim_id in claim_links:
                if not string_in(claim_id, claim_ids):
                    errors.append(f"{label}: unknown claim {claim_id}")
                    continue
                claim_sections = record_sections_by_id.get(str(claim_id), set())
                if claim_sections and set(linked_sections).isdisjoint(claim_sections):
                    errors.append(
                        f"{label}: linked claim {claim_id} has no shared "
                        "deliverable section"
                    )
            if (
                args.stage == "final"
                and disposition != "omit"
                and not supporting_evidence
            ):
                errors.append(
                    f"{label}: retained community record must link to evidence"
                )
            if (
                args.stage == "final"
                and disposition != "omit"
                and not claim_links
            ):
                errors.append(
                    f"{label}: retained community record must link to a claim"
                )
        for evidence_id in supporting_evidence:
            if not string_in(evidence_id, evidence_ids):
                errors.append(f"{label}: unknown evidence {evidence_id}")
            elif coverage_enabled:
                evidence_sections = record_sections_by_id.get(str(evidence_id), set())
                community_sections = set(linked_sections)
                if evidence_sections and community_sections.isdisjoint(
                    evidence_sections
                ):
                    errors.append(
                        f"{label}: supporting evidence {evidence_id} has no shared "
                        "deliverable section"
                    )

    for record in contradictions:
        label = f"contradictions.jsonl:{record['__line__']}"
        require_fields(record, ("claim_id", "outcome"), label, errors)
        if not string_in(record.get("claim_id"), claim_ids):
            errors.append(f"{label}: unknown claim {record.get('claim_id')}")
        for evidence_id in list_or_empty(record, "counter_evidence_ids"):
            if not string_in(evidence_id, evidence_ids):
                errors.append(f"{label}: unknown evidence {evidence_id}")

    for record in checkpoints:
        label = f"checkpoints.jsonl:{record['__line__']}"
        require_fields(
            record,
            (
                "pass",
                "created_at",
                "what_we_know",
                "missing_data",
                "underrepresented_source_types",
                "unsupported_decision_relevant_claims",
                "unresolved_contradictions",
                "freshness_risks",
                "saturated_branches",
                "unsaturated_branches",
                "next_actions",
            ),
            label,
            errors,
        )
        if record.get("created_at"):
            validate_timestamp(record.get("created_at"), f"{label}:created_at", errors)
        for field in (
            "what_we_know",
            "missing_data",
            "underrepresented_source_types",
            "unsupported_decision_relevant_claims",
            "unresolved_contradictions",
            "freshness_risks",
            "saturated_branches",
            "unsaturated_branches",
            "next_actions",
        ):
            require_list(record, field, label, errors)

    all_output_record_ids = evidence_ids | claim_ids | community_ids
    useful_data_record_ids: set[str] = set()
    appendix_record_ids: set[str] = set()
    omitted_record_ids: set[str] = set()
    non_omitted_record_ids: set[str] = set()
    if coverage_enabled:
        missing_section_links = sorted(
            all_output_record_ids - set(record_sections_by_id)
        )
        if missing_section_links:
            errors.append(
                "coverage contract: records missing deliverable sections: "
                + ", ".join(missing_section_links)
            )
        missing_dispositions = sorted(
            all_output_record_ids - set(record_disposition_by_id)
        )
        if missing_dispositions:
            errors.append(
                "coverage contract: records missing valid output dispositions: "
                + ", ".join(missing_dispositions)
            )
        useful_data_record_ids = {
            record_id
            for record_id, disposition in record_disposition_by_id.items()
            if disposition == "useful_data"
        }
        appendix_record_ids = {
            record_id
            for record_id, disposition in record_disposition_by_id.items()
            if disposition == "appendix"
        }
        omitted_record_ids = {
            record_id
            for record_id, disposition in record_disposition_by_id.items()
            if disposition == "omit"
        }
        non_omitted_record_ids = all_output_record_ids - omitted_record_ids
        if useful_data_record_ids and not (root / "useful-data.md").is_file():
            errors.append(
                "coverage contract: useful_data records require useful-data.md"
            )

    audit_status = audit.get("audit_status")
    if args.stage == "final":
        if not string_in(manifest.get("status"), {"complete", "incomplete"}):
            errors.append("manifest.json: final stage requires complete or incomplete status")
        if not string_in(audit_status, {"pass", "pass_with_warnings"}):
            errors.append("audit.json: final stage requires pass or pass_with_warnings")
        report_path = root / "report.md"
        handoff_path = root / "handoff.md"
        report_text = load_text(report_path, errors)
        handoff_text = load_text(handoff_path, errors)
        for name, marker, content in (
            ("report.md", "not-yet-synthesized", report_text),
            ("handoff.md", "not-yet-audited", handoff_text),
        ):
            if marker in content or len(content.strip()) < 80:
                errors.append(f"{name}: final content is missing")
        handoff_fields: dict[str, str | None] = {}
        for field in (
            "delivery_status",
            "output_profile",
            "audit_status",
            "clarity_preservation",
            "coverage_preservation",
            "bundle_validation",
        ):
            values = handoff_values(handoff_text, field)
            if len(values) > 1:
                errors.append(f"handoff.md: {field} appears more than once")
            handoff_fields[field] = values[0] if len(values) == 1 else None
        handoff_profile = handoff_fields["output_profile"]
        if handoff_profile != effective_output_profile:
            errors.append(
                "handoff.md: output_profile must match manifest.json"
            )
        handoff_audit = handoff_fields["audit_status"]
        if handoff_audit != audit_status:
            errors.append("handoff.md: audit_status must match audit.json")
        delivery_status = handoff_fields["delivery_status"]
        if not string_in(
            delivery_status, {"ready", "ready_with_warnings", "not_ready"}
        ):
            errors.append("handoff.md: missing or invalid delivery_status")
        if manifest.get("status") == "incomplete" and delivery_status != "not_ready":
            errors.append(
                "handoff.md: incomplete research requires delivery_status: not_ready"
            )
        if audit_status == "pass_with_warnings" and delivery_status == "ready":
            errors.append(
                "handoff.md: pass_with_warnings cannot use delivery_status: ready"
            )
        if handoff_fields["bundle_validation"] != "pass":
            errors.append("handoff.md: final stage requires bundle_validation: pass")

        if effective_output_profile == "editor-ready":
            clarity_errors, clarity_warnings = validate_editor_markdown(report_text)
            for finding in clarity_errors:
                errors.append(
                    f"report.md: editor-ready [{finding.code}] {finding.message}"
                )
            for finding in clarity_warnings:
                warnings.append(
                    f"report.md: editor-ready [{finding.code}] {finding.message}"
                )

            if handoff_fields["clarity_preservation"] != "pass":
                errors.append(
                    "handoff.md: editor-ready final stage requires "
                    "clarity_preservation: pass"
                )

            if not claims:
                errors.append(
                    "editor-ready final bundle requires at least one claim record"
                )
            if not sources:
                errors.append(
                    "editor-ready final bundle requires at least one source record"
                )

            report_links = set(visible_external_links(report_text))
            recorded_source_urls: set[str] = set()
            source_url_identities_by_id: dict[str, set[str]] = {}
            for record in sources:
                source_id = record.get("source_id")
                for field in ("requested_url", "final_url"):
                    value = record.get(field)
                    if not isinstance(value, str) or not value:
                        continue
                    identity = citation_identity(value)
                    if identity is None:
                        errors.append(
                            f"sources.jsonl: invalid {field} for "
                            f"{record.get('source_id', 'unknown')}"
                        )
                    else:
                        recorded_source_urls.add(identity)
                        if isinstance(source_id, str):
                            source_url_identities_by_id.setdefault(
                                source_id, set()
                            ).add(identity)
            report_link_identities: dict[str, str] = {}
            for link in report_links:
                identity = citation_identity(link)
                if identity is None:
                    errors.append(f"report.md: invalid source URL: {link}")
                else:
                    report_link_identities[link] = identity
            unrecorded_links = sorted(
                link
                for link, identity in report_link_identities.items()
                if identity not in recorded_source_urls
            )
            if unrecorded_links:
                errors.append(
                    "report.md: source links missing from sources.jsonl: "
                    + ", ".join(unrecorded_links)
                )
            if report_links and not set(report_link_identities.values()).intersection(
                recorded_source_urls
            ):
                errors.append(
                    "report.md: no visible source link matches sources.jsonl"
                )

            clarity_review = audit.get("clarity_review")
            if not isinstance(clarity_review, dict):
                errors.append(
                    "audit.json: editor-ready final stage requires clarity_review"
                )
            else:
                if clarity_review.get("status") != "pass":
                    errors.append(
                        "audit.json: editor-ready final stage requires "
                        "clarity_review.status=pass"
                    )
                for field in CLARITY_PRESERVATION_FIELDS:
                    if clarity_review.get(field) is not True:
                        errors.append(
                            "audit.json: clarity_review requires " + field + "=true"
                        )
                validate_timestamp(
                    clarity_review.get("reviewed_at"),
                    "audit.json:clarity_review:reviewed_at",
                    errors,
                )
                required_reviewed_claim_ids = {
                    str(record.get("claim_id"))
                    for record in claims
                    if isinstance(record.get("importance"), str)
                    and record.get("importance") in {"critical", "material"}
                    and record.get("status") != "rejected"
                }
                reviewed_claim_ids = clarity_review.get("reviewed_claim_ids")
                if not isinstance(reviewed_claim_ids, list) or not all(
                    isinstance(item, str) for item in reviewed_claim_ids
                ):
                    errors.append(
                        "audit.json: clarity_review.reviewed_claim_ids must be a list"
                    )
                    reviewed_claim_id_set: set[str] = set()
                else:
                    reviewed_claim_id_set = set(reviewed_claim_ids)
                missing_reviewed = sorted(
                    required_reviewed_claim_ids - reviewed_claim_id_set
                )
                unknown_reviewed = sorted(reviewed_claim_id_set - claim_ids)
                if not required_reviewed_claim_ids:
                    errors.append(
                        "editor-ready final bundle requires a critical or material claim"
                    )
                if missing_reviewed:
                    errors.append(
                        "audit.json: clarity_review missing reviewed claims: "
                        + ", ".join(missing_reviewed)
                    )
                if unknown_reviewed:
                    errors.append(
                        "audit.json: clarity_review has unknown claim IDs: "
                        + ", ".join(unknown_reviewed)
                    )

                for field, path in (
                    ("report_sha256", report_path),
                    ("claims_sha256", root / "claims.jsonl"),
                    ("sources_sha256", root / "sources.jsonl"),
                ):
                    expected_hash = clarity_review.get(field)
                    if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(
                        expected_hash
                    ):
                        errors.append(
                            f"audit.json: clarity_review.{field} must be SHA-256"
                        )
                    else:
                        actual_hash = validated_file_sha256(
                            path, f"audit.json: clarity_review.{field}", errors
                        )
                        if actual_hash is not None and expected_hash != actual_hash:
                            errors.append(
                                f"audit.json: clarity_review.{field} does not match "
                                f"the reviewed file"
                            )

            if coverage_enabled:
                if handoff_fields["coverage_preservation"] != "pass":
                    errors.append(
                        "handoff.md: coverage contract requires "
                        "coverage_preservation: pass"
                    )

                coverage_review = audit.get("coverage_review")
                if not isinstance(coverage_review, dict):
                    errors.append(
                        "audit.json: coverage contract final stage requires "
                        "coverage_review"
                    )
                else:
                    if coverage_review.get("status") != "pass":
                        errors.append(
                            "audit.json: coverage_review.status must be pass"
                        )
                    for field in ("sections_covered", "dispositions_preserved"):
                        if coverage_review.get(field) is not True:
                            errors.append(
                                f"audit.json: coverage_review requires {field}=true"
                            )
                    validate_timestamp(
                        coverage_review.get("reviewed_at"),
                        "audit.json:coverage_review:reviewed_at",
                        errors,
                    )

                    reviewed_values = coverage_review.get("reviewed_record_ids")
                    if not isinstance(reviewed_values, list) or not all(
                        isinstance(item, str) for item in reviewed_values
                    ):
                        errors.append(
                            "audit.json: coverage_review.reviewed_record_ids "
                            "must be a list of strings"
                        )
                        reviewed_set: set[str] = set()
                    else:
                        reviewed_set = set(reviewed_values)
                        if len(reviewed_set) != len(reviewed_values):
                            errors.append(
                                "audit.json: coverage_review.reviewed_record_ids "
                                "contains duplicates"
                            )

                    omitted_values = coverage_review.get("omitted_record_ids")
                    if not isinstance(omitted_values, list) or not all(
                        isinstance(item, str) for item in omitted_values
                    ):
                        errors.append(
                            "audit.json: coverage_review.omitted_record_ids "
                            "must be a list of strings"
                        )
                        reviewed_omitted_set: set[str] = set()
                    else:
                        reviewed_omitted_set = set(omitted_values)
                        if len(reviewed_omitted_set) != len(omitted_values):
                            errors.append(
                                "audit.json: coverage_review.omitted_record_ids "
                                "contains duplicates"
                            )

                    missing_reviewed_records = sorted(
                        non_omitted_record_ids - reviewed_set
                    )
                    unexpected_reviewed_records = sorted(
                        reviewed_set - non_omitted_record_ids
                    )
                    if missing_reviewed_records:
                        errors.append(
                            "audit.json: coverage_review missing reviewed records "
                            "in reviewed_record_ids: "
                            + ", ".join(missing_reviewed_records)
                        )
                    if unexpected_reviewed_records:
                        errors.append(
                            "audit.json: coverage_review has unexpected reviewed records: "
                            + ", ".join(unexpected_reviewed_records)
                        )
                    if reviewed_omitted_set != omitted_record_ids:
                        missing_omitted = sorted(
                            omitted_record_ids - reviewed_omitted_set
                        )
                        unexpected_omitted = sorted(
                            reviewed_omitted_set - omitted_record_ids
                        )
                        if missing_omitted:
                            errors.append(
                                "audit.json: coverage_review missing omitted records: "
                                + ", ".join(missing_omitted)
                            )
                        if unexpected_omitted:
                            errors.append(
                                "audit.json: coverage_review has unexpected omitted records: "
                                + ", ".join(unexpected_omitted)
                            )

                    raw_section_results = coverage_review.get("section_results")
                    seen_result_sections: set[str] = set()
                    if not isinstance(raw_section_results, list):
                        errors.append(
                            "audit.json: coverage_review.section_results must be a list"
                        )
                        raw_section_results = []
                    for index, result in enumerate(raw_section_results, start=1):
                        label = f"audit.json:coverage_review:section_results:{index}"
                        if not isinstance(result, dict):
                            errors.append(f"{label}: result must be an object")
                            continue
                        require_fields(
                            result,
                            ("section_id", "status", "record_ids"),
                            label,
                            errors,
                        )
                        section_id = result.get("section_id")
                        if not string_in(section_id, section_ids):
                            errors.append(f"{label}: unknown section_id {section_id}")
                            continue
                        if section_id in seen_result_sections:
                            errors.append(
                                f"{label}: duplicate section result {section_id}"
                            )
                        seen_result_sections.add(section_id)
                        expected_status = section_status_by_id.get(section_id)
                        if result.get("status") != expected_status:
                            errors.append(
                                f"{label}: status must match plan.json ({expected_status})"
                            )
                        result_record_values = require_list(
                            result, "record_ids", label, errors
                        )
                        if not all(
                            isinstance(item, str) for item in result_record_values
                        ):
                            errors.append(f"{label}: record_ids must contain strings")
                            result_record_set: set[str] = set()
                        else:
                            result_record_set = set(result_record_values)
                            if len(result_record_set) != len(result_record_values):
                                errors.append(f"{label}: record_ids contains duplicates")
                        expected_section_records = {
                            record_id
                            for record_id in non_omitted_record_ids
                            if section_id
                            in record_sections_by_id.get(record_id, set())
                        }
                        if result_record_set != expected_section_records:
                            missing = sorted(
                                expected_section_records - result_record_set
                            )
                            unexpected = sorted(
                                result_record_set - expected_section_records
                            )
                            if missing:
                                errors.append(
                                    f"{label}: missing section records: "
                                    + ", ".join(missing)
                                )
                            if unexpected:
                                errors.append(
                                    f"{label}: unexpected section records: "
                                    + ", ".join(unexpected)
                                )
                        if expected_status == "covered":
                            has_query = any(
                                section_id in linked_sections
                                for linked_sections in query_sections_by_id.values()
                            )
                            main_claim_ids = {
                                claim_id
                                for claim_id, claim in claims_by_id.items()
                                if record_disposition_by_id.get(claim_id) == "main"
                                and string_in(
                                    claim.get("status"),
                                    {
                                        "supported",
                                        "supported_with_conditions",
                                        "contested",
                                    },
                                )
                                and section_id
                                in record_sections_by_id.get(claim_id, set())
                            }
                            if not has_query:
                                errors.append(
                                    f"{label}: covered section has no linked query"
                                )
                            if not expected_section_records:
                                errors.append(
                                    f"{label}: covered section has no retained records"
                                )
                            if not main_claim_ids:
                                errors.append(
                                    f"{label}: covered section has no claim routed "
                                    "to output_disposition main"
                                )
                        result_note = result.get("note")
                        if expected_status in {"excluded", "unresolved"} and (
                            not isinstance(result_note, str)
                            or not result_note.strip()
                        ):
                            errors.append(
                                f"{label}: {expected_status} section requires note"
                            )

                    missing_section_results = sorted(
                        section_ids - seen_result_sections
                    )
                    if missing_section_results:
                        errors.append(
                            "audit.json: coverage_review missing section results: "
                            + ", ".join(missing_section_results)
                        )
                    extra_section_results = sorted(
                        seen_result_sections - section_ids
                    )
                    if extra_section_results:
                        errors.append(
                            "audit.json: coverage_review has unknown section results: "
                            + ", ".join(extra_section_results)
                        )

                    bank_path = root / "useful-data.md"
                    bank_present = bank_path.is_file()
                    bank_applicable = (
                        useful_data_required
                        or bool(useful_data_record_ids)
                        or bank_present
                    )
                    if bank_applicable and bank_present:
                        bank_text = load_text(bank_path, errors)
                        if (
                            "not-yet-populated" in bank_text
                            or len(bank_text.strip()) < 80
                            or UNFILLED_ARTIFACT_PLACEHOLDER_RE.search(bank_text)
                        ):
                            errors.append("useful-data.md: final content is missing")
                        validate_routed_record_artifact(
                            bank_text,
                            "useful-data.md",
                            "useful_data",
                            useful_data_record_ids,
                            evidence_by_id,
                            claims_by_id,
                            community_by_id,
                            source_url_identities_by_id,
                            errors,
                        )
                        validate_artifact_source_links(
                            bank_text,
                            "useful-data.md",
                            recorded_source_urls,
                            errors,
                        )

                    appendix_path = root / "evidence-appendix.md"
                    if appendix_record_ids:
                        if not appendix_path.is_file():
                            errors.append(
                                "coverage contract: appendix records require "
                                "evidence-appendix.md"
                            )
                        else:
                            appendix_text = load_text(appendix_path, errors)
                            if (
                                "not-yet-populated" in appendix_text
                                or len(appendix_text.strip()) < 80
                                or UNFILLED_ARTIFACT_PLACEHOLDER_RE.search(
                                    appendix_text
                                )
                            ):
                                errors.append(
                                    "evidence-appendix.md: final content is missing"
                                )
                            validate_routed_record_artifact(
                                appendix_text,
                                "evidence-appendix.md",
                                "appendix",
                                appendix_record_ids,
                                evidence_by_id,
                                claims_by_id,
                                community_by_id,
                                source_url_identities_by_id,
                                errors,
                            )
                            validate_artifact_source_links(
                                appendix_text,
                                "evidence-appendix.md",
                                recorded_source_urls,
                                errors,
                            )

                    reviewed_files: list[tuple[str, Path]] = [
                        ("manifest_sha256", root / "manifest.json"),
                        ("plan_sha256", root / "plan.json"),
                        ("queries_sha256", root / "queries.jsonl"),
                        ("sources_sha256", root / "sources.jsonl"),
                        ("evidence_sha256", root / "evidence.jsonl"),
                        ("claims_sha256", root / "claims.jsonl"),
                        ("community_sha256", root / "community.jsonl"),
                        ("contradictions_sha256", root / "contradictions.jsonl"),
                        ("checkpoints_sha256", root / "checkpoints.jsonl"),
                        ("semantic_audit_sha256", root / "semantic-audit.jsonl"),
                        ("report_sha256", report_path),
                    ]
                    if bank_applicable:
                        reviewed_files.append(("useful_data_sha256", bank_path))
                    if appendix_record_ids:
                        reviewed_files.append(("appendix_sha256", appendix_path))
                    for field, path in reviewed_files:
                        expected_hash = coverage_review.get(field)
                        if not isinstance(
                            expected_hash, str
                        ) or not SHA256_RE.fullmatch(expected_hash):
                            errors.append(
                                f"audit.json: coverage_review.{field} must be SHA-256"
                            )
                        else:
                            actual_hash = validated_file_sha256(
                                path,
                                f"audit.json: coverage_review.{field}",
                                errors,
                            )
                            if (
                                actual_hash is not None
                                and expected_hash != actual_hash
                            ):
                                errors.append(
                                    f"audit.json: coverage_review.{field} does not "
                                    "match the reviewed file"
                                )

                if (
                    "unresolved" in section_status_by_id.values()
                    and delivery_status == "ready"
                ):
                    errors.append(
                        "handoff.md: unresolved coverage sections cannot use "
                        "delivery_status: ready"
                    )
        if not claims:
            warnings.append("final bundle contains no claim records")
        if not sources:
            warnings.append("final bundle contains no source records")
        if schema_version == "1.0":
            warnings.append("legacy schema 1.0 bundle; migrate to 1.1 for reproducible sources")
        if schema_version in PROVENANCE_SCHEMAS:
            mutable_unverified = [
                record.get("source_id", "unknown")
                for record in sources
                if record.get("mutable") is True
                and record.get("fingerprint_status") != "verified"
            ]
            if mutable_unverified and fingerprint_policy == "required":
                errors.append(
                    "mutable sources lack verified fingerprints: "
                    + ", ".join(str(item) for item in mutable_unverified)
                )
            elif mutable_unverified and fingerprint_policy == "when-permitted":
                warnings.append(
                    "mutable sources without verified fingerprints: "
                    + ", ".join(str(item) for item in mutable_unverified)
                )
            for claim_id, claim in claims_by_id.items():
                importance = claim.get("importance")
                if not isinstance(importance, str) or importance not in {
                    "critical",
                    "material",
                }:
                    continue
                if claim.get("status") == "rejected":
                    continue
                reviews = semantic_by_claim.get(claim_id, [])
                if importance == "critical":
                    acceptable = any(
                        item.get("semantic_support") == "exact"
                        and item.get("reviewer_status") == "pass"
                        and all(
                            item.get(field) is True
                            for field in (
                                "scope_match",
                                "authority_match",
                                "freshness_match",
                                "evidence_type_match",
                            )
                        )
                        for item in reviews
                    )
                else:
                    acceptable = any(
                        string_in(item.get("semantic_support"), {"exact", "partial"})
                        and string_in(item.get("reviewer_status"), {"pass", "warning"})
                        and item.get("scope_match") is True
                        and item.get("freshness_match") is True
                        for item in reviews
                    )
                if not acceptable:
                    errors.append(
                        f"claim {claim_id}: missing acceptable semantic audit for "
                        f"{importance} claim"
                    )
    elif audit_status == "not_run":
        warnings.append("research audit has not run yet")

    if errors:
        print("Research bundle: FAIL")
        for error in errors:
            print(f"- {error}")
        for warning in warnings:
            print(f"- warning: {warning}")
        return 1

    print(
        "Research bundle: PASS "
        f"({len(query_ids)} queries, {len(source_ids)} sources, "
        f"{len(evidence_ids)} evidence items, {len(claim_ids)} claims)"
    )
    for warning in warnings:
        print(f"- warning: {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
