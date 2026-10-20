"""Import actual MCP catalog captures; catalog leads never count as verified decks."""

import copy
import hashlib
import json
import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from deck_code import decode, normalize_deck
from quality import CLASS_NAMES, require, text

MCP_CLASSES = {name.replace(" ", ""): key for key, (_, name) in CLASS_NAMES.items()}


def timestamp(value, label):
    require(isinstance(value, str), f"{label}: ISO timestamp required")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise ValueError(f"{label}: invalid ISO timestamp") from exc


def public_url(value):
    require(text(value), "catalog: source URL required")
    parsed = urlsplit(value)
    require(parsed.scheme in ("https", "http") and parsed.hostname
            and not parsed.username and not parsed.password, "catalog: invalid public source URL")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), parsed.query, ""))


def unpack(capture):
    require(isinstance(capture, dict) and isinstance(capture.get("request"), dict),
            "catalog: request and response capture required")
    request = capture["request"]
    require(set(request) == {"className", "format", "limit", "offset"},
            "catalog: record the exact broad request without a title/author query")
    require(isinstance(request["className"], str) and request["className"] in MCP_CLASSES,
            "catalog: canonical className required")
    require(request["format"] in ("standard", "wild"), "catalog: unsupported format")
    require(type(request["limit"]) is int and 1 <= request["limit"] <= 200
            and type(request["offset"]) is int and request["offset"] >= 0,
            "catalog: invalid requested page")
    response = capture.get("response")
    require(isinstance(response, dict) and not response.get("isError"), "catalog: unsuccessful response")
    if "content" in response:
        blocks = response["content"]
        require(isinstance(blocks, list), "catalog: invalid MCP content")
        payloads = [block.get("text") for block in blocks if isinstance(block, dict) and block.get("type") == "text"]
        require(len(payloads) == 1 and text(payloads[0]), "catalog: one JSON text block required")
        response = json.loads(payloads[0])
    require(isinstance(response, dict) and isinstance(response.get("data"), dict),
            "catalog: response data envelope required")
    page = response["data"]
    rows, meta = page.get("data"), page.get("meta")
    require(isinstance(rows, list) and isinstance(meta, dict), "catalog: rows and metadata required")
    require(type(meta.get("count")) is int and meta["count"] >= 0
            and type(meta.get("limit")) is int and meta["limit"] == request["limit"]
            and type(meta.get("offset")) is int and meta["offset"] == request["offset"],
            "catalog: response page does not match request")
    require(type(meta.get("stale")) is bool, "catalog: explicit stale metadata required")
    expected = min(request["limit"], max(0, meta["count"] - request["offset"]))
    require(len(rows) == expected, "catalog: incomplete page; do not skip unseen rows")
    return request, response, rows, meta


def prepare(data, capture, raw, relative):
    """Prepare in memory. No existing records or caller objects are mutated."""
    require(isinstance(data, dict) and data.get("schema_version") == 2, "catalog requires a v2 run")
    request, response, rows, meta = unpack(capture)
    require(request["format"] == data.get("format"), "catalog: run format mismatch")
    require(text(data.get("as_of")), "catalog: run date required")
    as_of = date.fromisoformat(data["as_of"])
    require(timestamp(response.get("retrievedAt"), "retrievedAt") <= as_of,
            "catalog: response retrieved after run date; start a new run")
    timestamp(meta.get("fetched_at"), "fetched_at")
    digest = hashlib.sha256(raw).hexdigest()
    captures = data.get("catalog_captures", [])
    require(isinstance(captures, list) and all(isinstance(row, dict) for row in captures),
            "catalog_captures: record array required")
    if any(row.get("sha256") == digest for row in captures):
        return None, {"status": "already_imported", "sha256": digest}
    class_name = MCP_CLASSES[request["className"]]
    require(not any(row.get("class") == class_name and row.get("offset") == request["offset"]
                    for row in captures), "catalog: page already imported; preserve it and use a new run for refresh")
    prior = [row for row in captures if row.get("class") == class_name]
    expected_offset = prior[-1].get("next_offset") if prior else 0
    require(expected_offset is not None and request["offset"] == expected_offset,
            "catalog: page out of sequence")
    updated = copy.deepcopy(data)
    for field in ("sources", "search_log", "catalog_leads", "catalog_captures"):
        require(isinstance(updated.setdefault(field, []), list), f"{field}: array required")
    capture_id = "catalog-" + digest[:20]
    source_ids = []
    for index, row in enumerate(rows):
        require(isinstance(row, dict) and text(row.get("title")), "catalog: row title required")
        require(row.get("class") == request["className"] and isinstance(row.get("format"), str)
                and row["format"].lower() == request["format"], "catalog: mixed class or format in response")
        url = public_url(row.get("url"))
        code = row.get("deck_code")
        require(code is None or isinstance(code, str), "catalog: deck_code must be text or null")
        for key in ("published_at", "added_at", "updated_at"):
            if row.get(key) is not None:
                timestamp(row[key], key)
        source_id = f"{capture_id}-{index}"
        require(not any(s.get("id") == source_id for s in updated["sources"]), "catalog: source id collision")
        source_ids.append(source_id)
        updated["sources"].append({"id": source_id, "kind": "deck", "title": row["title"],
            "url": url, "publisher": urlsplit(url).hostname, "checked_on": data["as_of"],
            "format": data["format"], "access": "excerpt", "snapshot": relative, "sha256": digest,
            "scope": "Catalog record and export only; original full list not independently read."})
        updated["catalog_leads"].append({"id": source_id, "source_id": source_id, "class": class_name,
            "title": row["title"], "deck_code": code, "catalog_stale": meta["stale"],
            "fetched_at": meta["fetched_at"], "retrieved_at": response["retrievedAt"],
            "dates": {key: row[key] for key in ("published_at", "added_at", "updated_at") if row.get(key) is not None}})
    next_offset = request["offset"] + request["limit"]
    next_offset = next_offset if next_offset < meta["count"] else None
    search = {"id": capture_id, "class": class_name, "language": "en", "channel": "catalog",
              "query": "search_decks " + json.dumps(request, sort_keys=True),
              "status": "inspected" if rows else "empty", "source_ids": source_ids,
              "notes": f"Read {len(rows)} catalog records; full original lists remain unverified. stale={meta['stale']}"}
    if next_offset is not None:
        search["next_offset"] = next_offset
    require(not any(row.get("id") == capture_id for row in updated["search_log"]), "catalog: search id collision")
    updated["search_log"].append(search)
    updated["catalog_captures"].append({"id": capture_id, "class": class_name,
        "snapshot": relative, "sha256": digest, "offset": request["offset"],
        "next_offset": next_offset, "total": meta["count"], "rows": len(rows)})
    return updated, {"status": "catalog_imported", "class": class_name,
                     "new_leads": len(rows), "next_offset": next_offset,
                     "notice": "Unverified leads only; no candidates selected, independent lists or review created."}


def ingest(selection, capture_path):
    selection = Path(selection).resolve()
    original = selection.read_bytes()
    data = json.loads(original.decode("utf-8-sig"))
    from discovery import plan
    plan(data)
    audit_captures(data, selection.parent)
    raw = Path(capture_path).read_bytes()
    capture = json.loads(raw.decode("utf-8-sig"))
    relative = f"sources/catalog-{hashlib.sha256(raw).hexdigest()}.json"
    updated, result = prepare(data, capture, raw, relative)
    if updated is None:
        return result
    plan(updated)  # Catch an inconsistent journal before making any writes.
    target = selection.parent / relative
    require(target.resolve().is_relative_to(selection.parent), "catalog: snapshot escapes run directory")
    snapshot_created = False
    temporary = None
    try:
        with target.open("xb") as handle:
            snapshot_created = True
            handle.write(raw)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=selection.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(updated, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        require(selection.read_bytes() == original, "catalog: journal changed during import; retry")
        os.replace(temporary, selection)
    except BaseException:
        if snapshot_created:
            target.unlink()
        raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return result


def composition(deck, class_name):
    deck = normalize_deck(deck)
    return json.dumps([class_name, deck["format"], deck["cards"], deck["sideboards"]])


def inspection_queue(data, limit):
    leads = data.get("catalog_leads", [])
    require(isinstance(leads, list), "catalog_leads: array required")
    sources = {row["id"]: row for row in data.get("sources", [])}
    handled_sources, handled_decks = set(), set()
    candidates = data.get("candidates", [])
    for candidate in candidates:
        handled_sources.update(candidate.get("source_ids", []))
        if candidate.get("deck_list"):
            handled_decks.add(composition(candidate["deck_list"], candidate["class"]))
    # A pending candidate may not have an independent list yet. Suppress its
    # equivalent catalog exports for queueing only; this is never verification.
    for lead in leads:
        if (isinstance(lead, dict) and isinstance(lead.get("source_id"), str)
                and lead["source_id"] in handled_sources):
            try:
                handled_decks.add(composition(decode(lead.get("deck_code")), lead.get("class")))
            except ValueError:
                pass
    as_of = date.fromisoformat(data["as_of"]) if leads else None
    groups, deferred, ids = {}, [], set()
    for lead in leads:
        require(isinstance(lead, dict) and text(lead.get("id")) and lead["id"] not in ids,
                "catalog_leads: unique id required")
        ids.add(lead["id"])
        require(lead.get("class") in CLASS_NAMES and isinstance(lead.get("source_id"), str)
                and lead["source_id"] in sources and text(lead.get("title")), "catalog_leads: source/class/title required")
        warnings = []
        code = lead.get("deck_code")
        key = (lead["class"], public_url(sources[lead["source_id"]].get("url")))
        if not code:
            warnings.append("missing_code")
        else:
            try:
                decoded = decode(code)
                require(decoded["format"] == (2 if data["format"] == "standard" else 1), "format mismatch")
                key = composition(decoded, lead["class"])
            except ValueError:
                warnings.append("invalid_or_wrong_format_code")
        if lead["source_id"] in handled_sources or key in handled_decks:
            continue
        dates = lead.get("dates", {})
        require(isinstance(dates, dict), "catalog_leads: dates object required")
        if any(timestamp(dates[field], field) > as_of for field in ("published_at", "added_at") if dates.get(field)):
            deferred.append({"lead": lead["id"], "reason": "future_source_date"})
            continue
        if not dates.get("published_at"):
            warnings.append("original_publication_date_unconfirmed")
        if lead.get("catalog_stale") is not False:
            warnings.append("stale_or_unknown_catalog")
        if lead.get("fetched_at") is None or timestamp(lead["fetched_at"], "fetched_at") < as_of:
            warnings.append("catalog_not_fetched_on_run_date")
        item = {"class": lead["class"], "title": lead["title"], "lead_ids": [lead["id"]],
                "source_ids": [lead["source_id"]], "url": sources[lead["source_id"]]["url"],
                "warnings": warnings, "dates": dates,
                "instruction": "Open original source; independently read full list and verify the unusual plan, current legality and code."}
        if key in groups:
            group = groups[key]
            group["lead_ids"].extend(item["lead_ids"])
            group["source_ids"].extend(item["source_ids"])
            if len(warnings) < len(group["warnings"]):
                group.update({field: item[field] for field in ("url", "title", "warnings", "dates")})
        else:
            groups[key] = item
    # Round-robin across classes, fewer data problems first within each class.
    buckets = {name: sorted([row for row in groups.values() if row["class"] == name],
                           key=lambda row: len(row["warnings"])) for name in CLASS_NAMES}
    class_order = sorted(CLASS_NAMES, key=lambda name: any(c["class"] == name and c["decision"] != "reject" for c in candidates))
    ordered = []
    while any(buckets.values()):
        for name in class_order:
            if buckets[name]:
                ordered.append(buckets[name].pop(0))
    return {"leads_to_inspect": ordered[:limit], "remaining_catalog_leads": len(ordered),
            "deferred_catalog_leads": deferred[:limit], "deferred_catalog_lead_count": len(deferred)}


def audit_captures(data, directory):
    root = Path(directory).resolve()
    captures = data.get("catalog_captures", [])
    require(isinstance(captures, list), "catalog_captures: array required")
    for record in captures:
        require(isinstance(record, dict) and text(record.get("snapshot")), "catalog_captures: snapshot required")
        relative = Path(record["snapshot"])
        target = (root / relative).resolve()
        require(not relative.is_absolute() and target.is_relative_to(root), "catalog_captures: snapshot escapes run directory")
        require(hashlib.sha256(target.read_bytes()).hexdigest() == record.get("sha256"),
                "catalog_captures: snapshot hash mismatch")
