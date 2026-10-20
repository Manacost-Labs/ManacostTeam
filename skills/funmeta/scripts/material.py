"""Editorial outline and structural Markdown audit, never a factual/style verdict."""

import re

from deck_code import decode
from quality import CLASS_NAMES, require, text

SECTIONS = ("Общее положение фан-колод в мете", "Какие карты самые фановые в нынешней мете",
            "Фановые колоды для каждого класса")


def clean(value):
    value = re.sub(r"\s+#+\s*$", "", value.strip()).replace("*", "")
    value = re.sub(r"(?<!\w)_|_(?!\w)", "", value)
    return " ".join(value.casefold().split())


def policy(data):
    if "material_policy" not in data:
        return False
    require(data.get("schema_version") == 2 and type(data["material_policy"]) is int
            and data["material_policy"] == 1, "material_policy: expected version 1 in a v2 run")
    return True


def selected(data):
    require(isinstance(data, dict) and data.get("schema_version") == 2, "material tools require a v2 run")
    rows = data.get("candidates")
    require(isinstance(rows, list), "candidates: array required")
    ids = set()
    for row in rows:
        require(isinstance(row, dict) and text(row.get("id")) and row["id"] not in ids,
                "candidates: unique ids required")
        ids.add(row["id"])
        require(row.get("class") in CLASS_NAMES and text(row.get("name"))
                and row.get("decision") in ("include", "pending", "reject"), "candidates: invalid record")
        if "material_heading" in row:
            require(text(row["material_heading"]) and "\n" not in row["material_heading"]
                    and "\r" not in row["material_heading"] and clean(row["material_heading"]),
                    "material_heading: one nonempty line required")
        if "code_provenance" in row:
            require(isinstance(row["code_provenance"], dict), "code_provenance: object required")
    return [row for row in rows if row["decision"] == "include"]


def outline(data):
    chosen = selected(data)
    gaps = data.get("gaps", {})
    require(isinstance(gaps, dict), "gaps: object required")
    classes = []
    for class_name, (ru, _) in CLASS_NAMES.items():
        decks = []
        for row in chosen:
            if row["class"] != class_name:
                continue
            decks.append({"candidate": row["id"], "heading": row.get("material_heading", row["name"]),
                "research": {key: row.get(key) for key in ("premise", "game_plan", "fun_moment",
                    "limitations", "closest_meta_plan", "plan_difference", "source_ids", "explanation_evidence")},
                "code_status": row.get("deck_code_status"),
                "code_origin": row.get("code_provenance", {}).get("kind"),
                "editorial_task": "Choose depth from the idea; explain its distinction, conditions and limits in connected prose."})
        duplicate_notes = {}
        for row in decks:
            difference = row["research"].get("plan_difference")
            if text(difference):
                duplicate_notes.setdefault(clean(difference), []).append(row["candidate"])
        review_tasks = [{"kind": "differentiate_game_plans", "candidates": ids,
                         "reason": "The same plan_difference note is reused; compare the actual gameplay before presenting alternatives."}
                        for ids in duplicate_notes.values() if len(ids) > 1]
        classes.append({"class": class_name, "heading": ru, "decks": decks, "review_tasks": review_tasks,
                        "gap": gaps.get(class_name),
                        "editorial_task": ("Write a current source-backed class overview, then connect the different game plans."
                                           if decks else "Explain the unresolved gap; do not invent a deck.")})
    return {"status": "editorial_outline", "selected_decks": len(chosen), "sections": list(SECTIONS),
            "classes": classes, "pending_candidates": [row["id"] for row in data["candidates"] if row["decision"] == "pending"],
            "notice": "Working research plan only. No article, approval, style score or game-fact verification is generated."}


def audit(data, material):
    chosen = selected(data)
    require(isinstance(material, str), "material: Markdown text required")
    sources = data.get("sources", [])
    require(isinstance(sources, list) and all(isinstance(s, dict) and text(s.get("id")) for s in sources),
            "sources: record array required")
    source_index = {s["id"]: s for s in sources}
    require(len(source_index) == len(sources), "sources: duplicate id")
    lines = material.splitlines()
    headings, blocks, findings = [], [], []
    fence = None

    def finding(code, message, line=None, candidate=None, severity="error"):
        findings.append({"code": code, "message": message, "line": line,
                         "candidate": candidate, "severity": severity})

    for index, line in enumerate(lines):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence is not None:
            if marker and marker[1][0] == fence["marker"][0] and len(marker[1]) >= len(fence["marker"]) and not marker[2].strip():
                fence["end"] = index
                blocks.append(fence)
                fence = None
            continue
        if marker:
            fence = {"line": index, "marker": marker[1], "language": marker[2].strip().casefold()}
            continue
        match = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*$", line)
        if match:
            headings.append({"level": len(match[1]), "title": match[2], "line": index})
    if fence is not None:
        finding("unclosed_fence", "Close the Markdown code fence.", fence["line"] + 1)

    def stop(heading, level):
        return next((h["line"] for h in headings if h["line"] > heading["line"] and h["level"] <= level), len(lines))

    def prose(start, end):
        result = []
        for index in range(start, end):
            if any(b["line"] <= index <= b["end"] for b in blocks):
                continue
            line = lines[index].strip()
            if (line.startswith("#") or clean(line).rstrip(":") in ("код колоды", "код", "состав")
                    or re.match(r"(?:источник|состав|автор|дата)\s*:", clean(line))):
                continue
            line = re.sub(r"!?\[[^\]]*\]\([^)]*\)", "", line)
            line = re.sub(r"https?://\S+", "", line)
            result.append(line)
        return "\n".join(result)

    top = [h for h in headings if h["level"] == 1]
    if len(top) != 1:
        finding("title_count", "Use one article title.")
    sections = [h for h in headings if h["level"] == 2]
    if [clean(h["title"]) for h in sections] != [clean(title) for title in SECTIONS]:
        finding("main_sections", "Keep the three requested main sections in order.")
    for h in sections:
        if clean(h["title"]) in [clean(title) for title in SECTIONS[:2]]:
            # Cards may be described under subheadings, so inspect the entire main section.
            if not any(char.isalpha() for char in prose(h["line"] + 1, stop(h, 2))):
                finding("section_text_missing", "Write the section before delivery.", h["line"] + 1)

    aliases = {clean(name): key for key, names in CLASS_NAMES.items() for name in (*names, key)}
    expected, seen, seen_classes, assigned_blocks = {}, set(), set(), set()
    for row in chosen:
        key = (row["class"], clean(row.get("material_heading", row["name"])))
        if key in expected:
            finding("ambiguous_deck_heading", "Give different selected decks distinct material_heading values.", candidate=row["id"])
        expected[key] = row
    active_section, active_class = None, None
    for h in headings:
        if h["level"] == 2:
            active_section, active_class = clean(h["title"]), None
        if active_section != clean(SECTIONS[2]):
            continue
        if h["level"] == 3:
            active_class = aliases.get(clean(h["title"]))
            if active_class is None:
                finding("unknown_class_heading", "Use a recognized class heading.", h["line"] + 1)
                continue
            if active_class in seen_classes:
                finding("duplicate_class_heading", "Group a class under one heading.", h["line"] + 1)
            seen_classes.add(active_class)
            end = next((child["line"] for child in headings if child["line"] > h["line"] and child["level"] <= 4), len(lines))
            if not any(char.isalpha() for char in prose(h["line"] + 1, end)):
                finding("class_overview_missing", "Write the class overview or explicit gap explanation.", h["line"] + 1)
        elif h["level"] == 4:
            row = expected.get((active_class, clean(h["title"])))
            if row is None:
                finding("unselected_deck_heading", "Match this deck to a selected candidate and its class.", h["line"] + 1)
                continue
            if row["id"] in seen:
                finding("duplicate_deck_section", "Print each selected deck once.", h["line"] + 1, row["id"])
            seen.add(row["id"])
            end = stop(h, 4)
            deck_blocks = [b for b in blocks if h["line"] < b["line"] < end]
            assigned_blocks.update(b["line"] for b in deck_blocks)
            try:
                require(row.get("deck_code_status") == "verified", "unverified")
                decode(row.get("deck_code"))
            except ValueError:
                finding("candidate_code_unverified", "Verify the selected deck code before delivery.", h["line"] + 1, row["id"])
            correct = (len(deck_blocks) == 1 and deck_blocks[0]["language"] in ("", "text", "plaintext")
                       and [line.strip() for line in lines[deck_blocks[0]["line"]+1:deck_blocks[0]["end"]]] == [row.get("deck_code")])
            if not correct:
                finding("deck_code_placement", "Put exactly this deck's code alone in one copyable block under its heading.", h["line"] + 1, row["id"])
            before_code = min((b["line"] for b in deck_blocks), default=end)
            if not any(char.isalpha() for char in prose(h["line"] + 1, before_code)):
                finding("deck_explanation_missing", "Explain the deck before its code.", h["line"] + 1, row["id"])
            body = "\n".join(lines[h["line"]+1:end])
            refs = row.get("source_ids", [])
            require(isinstance(refs, list) and all(isinstance(key, str) for key in refs), "candidate: source_ids array required")
            urls = [source_index[key].get("url") for key in refs if key in source_index
                    and source_index[key].get("kind") == "deck" and source_index[key].get("access") == "full"]
            if not any(text(url) and url in body for url in urls):
                finding("deck_source_missing", "Link the independently read full deck source under this deck.", h["line"] + 1, row["id"])
            if row.get("code_provenance", {}).get("kind") == "reconstructed-list":
                if "код восстановлен из опубликованного состава" not in clean(prose(h["line"] + 1, end)):
                    finding("reconstructed_code_undisclosed", "Disclose that the code was reconstructed from the published list.", h["line"] + 1, row["id"])
    for class_name in CLASS_NAMES:
        if class_name not in seen_classes:
            finding("class_missing", f"Include the class or explain its gap: {CLASS_NAMES[class_name][0]}.")
    for row in chosen:
        if row["id"] not in seen:
            finding("selected_deck_missing", "Print the selected deck under its class and material_heading.", candidate=row["id"])
    for b in blocks:
        if b["line"] not in assigned_blocks:
            finding("unassigned_code_block", "Every code block must belong to a selected deck section.", b["line"] + 1)
    for index, line in enumerate(lines):
        if "ПОЛНЫЙ_ПРОВЕРЕННЫЙ_КОД_ОДНОЙ_СТРОКОЙ" in line or re.search(r"\]\(URL\)", line):
            finding("template_placeholder", "Replace the template placeholder.", index + 1)

    # Numeric totals in the title/lead only. Per-class and vague claims still
    # need reading; explicit minimum/maximum constraints can be checked exactly.
    first_section = sections[0]["line"] if sections else len(lines)
    count_pattern = r"(?<![\w+])(\d+)(\+)?\s+(?:(?:необычн\w*|фанов\w*|интересн\w*|нов\w*|лучш\w*|разн\w*|нестандартн\w*|самых|и|фан)\s+){0,6}(?:колод(?:а|ы|у)?|сбор(?:ка|ки|ок))\b"
    for index, line in enumerate(lines[:first_section]):
        for match in re.finditer(count_pattern, line, flags=re.IGNORECASE):
            prefix, suffix = line[:match.start()].casefold(), line[match.end():].casefold()
            negative = re.search(r"(?:отсе\w*|отклон\w*|рассмотр\w*|перебрал\w*|из)\s*$", prefix)
            promise = (any(h["line"] == index for h in top) or
                       re.search(r"\b(?:выпуск\w*|подборк\w*|знакомьтесь|представляем|отобрали|собрали|нашли|предлагаем)\b", prefix))
            if negative or not promise:
                finding("count_context_review", "Check whether this number describes the delivered decks or other research context.", index + 1, severity="warning")
                continue
            qualifier = re.search(r"\b(более|свыше|около|до)\s*$", prefix)
            qualifier = qualifier[1] if qualifier else None
            if (qualifier == "около" or re.match(r"\s+(?:для|на|у)\s+(?:кажд|одн|этог)\w*\s+класс", suffix)):
                finding("scoped_count_review", "Manually verify this approximate/per-class count.", index + 1, severity="warning")
                continue
            number, actual = int(match[1]), len(chosen)
            matches = (actual > number if qualifier in ("более", "свыше") else
                       actual <= number if qualifier == "до" else
                       actual >= number if match[2] else actual == number)
            if not matches:
                finding("declared_deck_count", f"Declared {match.group(0)}; selected {actual} decks.", index + 1)
    errors = sum(f["severity"] == "error" for f in findings)
    return {"status": "material_needs_revision" if errors else "material_structure_valid",
            "errors": errors, "findings": findings, "selected_decks": len(chosen),
            "printed_selected_decks": len(seen), "classes_present": len(seen_classes),
            "mechanical_checks_only": True,
            "notice": "Structure and code placement only; source meaning, current meta, gameplay and author voice still require review."}
