"""Inspect connector snapshots and bind numeric claims to original JSON cells."""

import json
import math
import re


def need(condition, message):
    if not condition:
        raise ValueError(message)


def resolve(document, pointer):
    need(isinstance(pointer, str) and (pointer == "" or pointer.startswith("/")), "invalid JSON pointer")
    node = document
    for token in pointer.split("/")[1:]:
        need(re.search(r"~(?:[^01]|$)", token) is None, "invalid JSON pointer escape")
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            need(token.isdigit() and str(int(token)) == token and int(token) < len(node), "JSON pointer array index absent")
            node = node[int(token)]
        else:
            need(isinstance(node, dict) and token in node, "JSON pointer cell absent")
            node = node[token]
    return node


def label(value):
    return value.get("id") if isinstance(value, dict) else value


def inspect_payload(payload):
    """Recognize Manacost connector and endpoint shapes; never certify research."""
    root, prefix, envelope = payload, "", {}
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict) and "sourceUrl" in payload["data"]:
        envelope = payload["data"]
        root, prefix = envelope.get("data"), "/data/data"
    recognized = isinstance(root, dict) and isinstance(root.get("data"), list) and isinstance(root.get("meta"), dict)
    if not recognized:
        return {"recognized": False, "research_ready": False, "warnings": ["unrecognized-statistics-shape"], "rows": []}
    meta = root["meta"]
    period = label(meta.get("period"))
    patch = meta.get("patch") or (meta.get("period", {}).get("patch") if isinstance(meta.get("period"), dict) else None)
    context = {"rank": label(meta.get("rank")), "format": meta.get("format"), "patch": patch,
               "period": period, "data_status": meta.get("dataStatus"), "dataset_version": meta.get("datasetVersion"),
               "dataset_updated_at": meta.get("updatedAt"), "retrieved_at": envelope.get("retrievedAt") or payload.get("retrievedAt"),
               "source_url": envelope.get("sourceUrl")}
    warnings = []
    if context["data_status"] != "fresh":
        warnings.append(context["data_status"] or "freshness-unspecified")
    if not patch:
        warnings.append("patch-unspecified")
    warnings.append("period-bounds-unverified")
    has_more = root.get("pagination", {}).get("hasMore") is True
    if has_more:
        warnings.append("partial-pagination")
    rows = []
    for index, record in enumerate(root["data"]):
        if not isinstance(record, dict):
            continue
        sample = record.get("sample") or {}
        need(isinstance(sample, dict), "invalid JSON sample metadata")
        rank = label(sample.get("rank")) or context["rank"]
        raw_period = label(sample.get("period")) or period
        archetype = record.get("archetype") or {}
        need(isinstance(archetype, dict), "invalid JSON archetype metadata")
        rows.append({"pointer": f"{prefix}/data/{index}", "rank": "all-ranks" if rank == "all" else rank,
                     "period": raw_period, "patch": patch, "format": record.get("format") or context["format"],
                     "updated_at": record.get("updatedAt"), "deck_id": record.get("deckId"), "deck_code": record.get("deckCode"),
                     "archetype_id": archetype.get("slug"), "class": archetype.get("classId"),
                     "metrics": record.get("metrics", {}), "opponent": sample.get("opponent")})
    return {"recognized": True, "research_ready": False, "source_context": context, "rows": rows,
            "warnings": warnings, "has_more": has_more}


def validate_numeric(row, source_text, quote, subject=None):
    document = json.loads(source_text)
    pointer, quote_pointer = row.get("value_pointer"), row.get("quote_pointer", "")
    subtree = resolve(document, quote_pointer)
    need(json.loads(quote) == subtree, "JSON evidence quote does not match original subtree")
    need(pointer == quote_pointer or pointer.startswith(quote_pointer + "/"), "value outside evidence quote")
    number = resolve(document, pointer)
    need(type(number) in {int, float} and math.isfinite(number), "JSON metric must be a finite number")
    unit = row.get("value_unit")
    need(unit in {"percent", "fraction"}, "explicit JSON value_unit percent/fraction required")
    value = number * (100 if unit == "fraction" else 1)
    need(math.isclose(value, row["value"], rel_tol=0, abs_tol=1e-9), "JSON value mismatch")
    if row["sample_games"] is not None:
        sample_pointer = row.get("sample_games_pointer")
        need(isinstance(sample_pointer, str) and sample_pointer.startswith(quote_pointer + "/"), "sample outside evidence quote")
        count = resolve(document, sample_pointer)
        need(type(count) is int and count == row["sample_games"], "JSON sample mismatch")
    inspected = inspect_payload(document)
    if inspected["recognized"]:
        records = [record for record in inspected["rows"] if pointer.startswith(record["pointer"] + "/")]
        need(len(records) == 1, "JSON metric outside a statistics row")
        record = records[0]
        grain = "deck" if record["deck_id"] or record["deck_code"] else "archetype"
        need(row["grain"] == grain, "original JSON grain mismatch")
        source_identity = record["deck_id"] if grain == "deck" else record["archetype_id"]
        if source_identity:
            need(row.get("source_subject_id") == source_identity, "original JSON source_subject_id required/mismatch")
        need(row.get("opponent") == record["opponent"], "original JSON opponent mismatch; overall result is not a matchup")
        if subject and record["class"]:
            need(record["class"].replace("deathknight", "death-knight").replace("demonhunter", "demon-hunter") == subject["class"], "original JSON class mismatch")
        expected = "winratePercent" if row["metric"] == "winrate" else "popularityPercent"
        need(pointer == record["pointer"] + "/metrics/" + expected and unit == "percent", "JSON metric/unit does not match statistic kind")
        for key in ("rank", "format", "patch"):
            if record[key] is not None:
                need(record[key] == row[key], f"original JSON {key} mismatch")
        if record["period"]:
            need(row.get("source_period") == record["period"], "original JSON source_period required/mismatch")
        need(isinstance(row.get("period_note"), str) and row["period_note"].strip(), "JSON period_note must explain unverified period bounds")
        if row["sample_games"] is not None:
            need(sample_pointer == record["pointer"] + "/metrics/games", "sample belongs to another JSON row or cell")
        if subject and grain == "deck" and record["deck_code"]:
            need(record["deck_code"] == subject["code"], "JSON statistic belongs to another deck code")
    return inspected
