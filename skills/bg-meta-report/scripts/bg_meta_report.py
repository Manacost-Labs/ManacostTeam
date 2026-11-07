"""Helper for the Battlegrounds meta-report workflow.

It plans the search matrix, audits recorded coverage, lints the finished
article against the owner's live-story format and builds transparent card
strips. It never searches the web or writes prose.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCHEMA_VERSION = 1
RACES = (
    "Механизмы", "Нежить", "Свинобразы", "Пираты", "Демоны", "Элементали",
    "Мурлоки", "Звери", "Аберрации", "Драконы", "Наги",
)
GLOBAL_LANES = (
    "official", "statistics", "manacost_archive", "owner_sources", "youtube",
    "twitch", "reddit", "x", "web", "international",
)
RACE_LANES = ("statistics", "manacost_archive", "youtube", "twitch", "reddit", "x", "web")
COMMUNITY_LANES = {"youtube", "twitch", "reddit", "x"}
DATA_LANES = {"official", "statistics", "manacost_archive", "web"}
STATUSES = {"pending", "inspected", "no_relevant_results", "blocked", "excluded"}
READER_QUESTIONS = (
    "Что изменил патч для расы и ее соседей по пулу?",
    "Какие 1–3 сборки реально играются и через какие кор-карты?",
    "Когда переходить и чего это стоит по темпу?",
    "Порядок действий в ходу и главная механическая ловушка.",
    "Сцена или ошибка со стрима для истории.",
    "Контрпример: где сборка проигрывает и кто ее держит.",
)
REQUIRED_SECTIONS = {
    "meta": ("характеристика меты",),
    "patch": ("как патч повлиял", "изменения патча", "что изменил патч"),
    "race_tiers": ("тир-лист рас",),
    "balance": ("баланс рас и стратегий", "баланс рас"),
    "tips": ("повторяющиеся советы", "советы сильных игроков"),
    "heroes": ("тир-лист героев",),
}
FORBIDDEN = (
    (r"\d+(?:[.,]\d+)?\s?%", "процент"),
    (r"средн\w*\s+мест", "среднее место"),
    (r"\bвыборк\w*", "выборка"),
    (r"\bсрез(?:е|а|ы|ов|ам|ах)?\b", "срез данных"),
    (r"(?<![\wЁё])N\s?=\s?\d", "размер выборки"),
    (r"винрейт\w*", "винрейт"),
    (r"по данным\b", "ссылка на данные вместо вывода"),
    (r"оговор(?:имся|ка)", "исследовательская оговорка"),
    (r"следует отметить", "канцелярит"),
    (r"корреляци\w*", "исследовательский термин"),
)
WARN_WORDS = ((r"HSReplay|Firestone", "название статистического сервиса в тексте"),)
CHECKLIST_HEADINGS = re.compile(
    r"^#{2,6}\s*(когда переходить|как играть|чего не делать|плюсы|минусы|"
    r"сильные стороны|слабые стороны|итог по расе)\b", re.IGNORECASE | re.MULTILINE)
SHORTCODE = re.compile(r"\[/?hs_(?:bg|card)\b[^\]]*\]")
IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _cell() -> dict:
    return {"status": "pending", "queries": [], "urls": [], "reason": "", "findings": []}


def initialize(run: Path, as_of: str, patch: str | None = None, issue: int | None = None,
               races: tuple[str, ...] = RACES, mode: str = "solo") -> Path:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
        raise ValueError("as_of must be YYYY-MM-DD")
    if not races or len(set(races)) != len(races):
        raise ValueError("races must be a non-empty list without duplicates")
    run.mkdir(parents=True, exist_ok=True)
    brief = run / "brief.json"
    if brief.exists():
        raise FileExistsError(f"{brief} already exists; start a new run directory")
    _write_json(brief, {
        "schema_version": SCHEMA_VERSION, "as_of": as_of, "patch": patch, "issue": issue,
        "mode": mode, "races": list(races),
        "research": {"depth": "exhaustive", "profile": "editor-ready",
                     "global_lanes": list(GLOBAL_LANES), "race_lanes": list(RACE_LANES)},
        "reader_questions": list(READER_QUESTIONS),
        "style": "skills/bg-meta-report/references/writing-style.md",
        "status": "planned",
    })
    _write_json(run / "search-matrix.json", {
        "schema_version": SCHEMA_VERSION,
        "global": {lane: _cell() for lane in GLOBAL_LANES},
        "races": {race: {"lanes": {lane: _cell() for lane in RACE_LANES}, "saturation": ""}
                  for race in races},
    })
    return brief


def _cell_problems(where: str, cell: object) -> list[str]:
    if not isinstance(cell, dict):
        return [f"{where}: cell must be an object"]
    status = cell.get("status")
    if status not in STATUSES:
        return [f"{where}: unknown status {status!r}"]
    if status == "pending":
        return [f"{where}: still pending"]
    problems = []
    if status == "inspected":
        if not cell.get("urls"):
            problems.append(f"{where}: inspected without urls")
        if not cell.get("queries"):
            problems.append(f"{where}: inspected without recorded queries")
    elif not str(cell.get("reason", "")).strip():
        problems.append(f"{where}: {status} without reason")
    return problems


def audit_coverage(run: Path) -> dict:
    matrix = json.loads((run / "search-matrix.json").read_text(encoding="utf-8"))
    errors: list[str] = []
    warnings: list[str] = []
    global_cells = matrix.get("global", {})
    for lane in GLOBAL_LANES:
        if lane not in global_cells:
            errors.append(f"global.{lane}: missing")
            continue
        errors += _cell_problems(f"global.{lane}", global_cells[lane])
        if lane in ("official", "statistics") and global_cells[lane].get("status") != "inspected":
            warnings.append(f"global.{lane}: not inspected; disclose the limit")
    for race, entry in matrix.get("races", {}).items():
        lanes = entry.get("lanes", {})
        for lane in RACE_LANES:
            if lane not in lanes:
                errors.append(f"{race}.{lane}: missing")
            else:
                errors += _cell_problems(f"{race}.{lane}", lanes[lane])
        inspected = {lane for lane, cell in lanes.items()
                     if isinstance(cell, dict) and cell.get("status") == "inspected"}
        if not inspected & COMMUNITY_LANES:
            errors.append(f"{race}: no inspected community lane (youtube/twitch/reddit/x)")
        if not inspected & DATA_LANES:
            errors.append(f"{race}: no inspected data lane (statistics/archive/web)")
        if not str(entry.get("saturation", "")).strip():
            errors.append(f"{race}: saturation not recorded")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def _sections(text: str, level: int) -> list[tuple[str, str]]:
    pattern = re.compile(rf"^{'#' * level} (.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    out = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        if level > 1:
            higher = re.compile(rf"^#{{1,{level - 1}}} ", re.MULTILINE).search(text, match.end(), end)
            if higher:
                end = higher.start()
        out.append((match.group(1).strip(), text[match.end():end]))
    return out


def check_article(article: Path, races: tuple[str, ...] | None = None) -> dict:
    raw = article.read_bytes().decode("utf-8")
    text = SHORTCODE.sub("", raw.replace("\r\n", "\n"))
    errors: list[str] = []
    warnings: list[str] = []

    if not re.search(r"^# \S", text, re.MULTILINE):
        errors.append("нет заголовка H1")
    first_h2 = text.find("\n## ")
    intro = text if first_h2 < 0 else text[:first_h2]
    if "Приятного чтения" not in intro:
        errors.append("вступление не заканчивается «Приятного чтения!»")

    h2 = _sections(text, 2)
    found: dict[str, str] = {}
    for key, variants in REQUIRED_SECTIONS.items():
        for title, body in h2:
            if any(title.casefold().startswith(v) for v in variants):
                found[key] = body
                break
        else:
            errors.append(f"нет раздела «{variants[0]}»")

    balance = found.get("balance", "")
    race_sections = dict(_sections(balance, 3))
    for race in races or ():
        if race not in race_sections:
            errors.append(f"нет раздела расы «### {race}»")
    for race, body in race_sections.items():
        builds = _sections(body, 4)
        if not builds:
            errors.append(f"{race}: нет ни одной сборки «#### Через …»")
        for title, build in builds:
            images = IMAGE.findall(build)
            if not images:
                errors.append(f"{race} / {title}: нет ленты карт")
            for target in images:
                if not re.match(r"[a-z]+://", target):
                    path = Path(target) if Path(target).is_absolute() else article.parent / target
                    if not path.is_file():
                        errors.append(f"{race} / {title}: файл картинки не найден: {target}")
            if not title.startswith("Через"):
                warnings.append(f"{race} / {title}: заголовок сборки не в форме «Через …»")

    tables = len(re.findall(r"^\|\s*:?-{3,}", text, re.MULTILINE))
    if tables > 1:
        errors.append(f"таблиц {tables}; допустима одна — тир-лист рас")
    for match in CHECKLIST_HEADINGS.finditer(text):
        errors.append(f"чек-листовый подзаголовок: {match.group(0).strip()}")
    body_text = IMAGE.sub("", text)
    for pattern, label in FORBIDDEN:
        hits = re.findall(pattern, body_text, re.IGNORECASE)
        if hits:
            errors.append(f"{label}: {', '.join(sorted(set(hits))[:5])}")
    for pattern, label in WARN_WORDS:
        if re.search(pattern, body_text):
            warnings.append(label)

    heroes = found.get("heroes", "")
    for line in heroes.splitlines():
        if line.startswith("**Тир"):
            rest = re.sub(r"^\*\*Тир[-\s]?\w+:?\*\*:?", "", line)
            if re.search(r"\d", rest):
                errors.append(f"числа в тир-листе героев: {line[:60]}")
    if "Удачи в таверне" not in text[-400:]:
        warnings.append("нет финального «Удачи в таверне!»")
    stories = sum(1 for p in text.split("\n\n") if re.search(r"\bстрим", p, re.IGNORECASE))
    if stories < 3:
        warnings.append(f"историй со стримов {stories}; ориентир — 3–5")
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "races": sorted(race_sections)}


def build_strips(selection: Path, cards_dir: Path, out_dir: Path,
                 height: int = 520, gap: int = 60, pad: int = 40) -> list[dict]:
    from PIL import Image  # optional dependency, needed only for this command

    data = json.loads(selection.read_text(encoding="utf-8"))
    base = (512, 776)
    loaded: dict[str, Image.Image] = {}
    box = None
    for strategy in data["strategies"]:
        for card_id in strategy["cards"]:
            if card_id in loaded:
                continue
            image = Image.open(cards_dir / f"{card_id}.png").convert("RGBA")
            if image.size != base:
                image = image.resize(base, Image.LANCZOS)
            loaded[card_id] = image
            bbox = image.getchannel("A").getbbox()
            if bbox:
                box = bbox if box is None else (min(box[0], bbox[0]), min(box[1], bbox[1]),
                                                max(box[2], bbox[2]), max(box[3], bbox[3]))
    if box is None:
        raise ValueError("no visible card pixels")
    width = round((box[2] - box[0]) * height / (box[3] - box[1]))
    out_dir.mkdir(parents=True, exist_ok=True)
    report = []
    for strategy in data["strategies"]:
        ids = list(strategy["cards"])
        canvas = Image.new("RGBA", (2 * pad + len(ids) * width + (len(ids) - 1) * gap,
                                    2 * pad + height), (0, 0, 0, 0))
        for index, card_id in enumerate(ids):
            card = loaded[card_id].crop(box).resize((width, height), Image.LANCZOS)
            canvas.alpha_composite(card, (pad + index * (width + gap), pad))
        target = out_dir / f"{strategy['slug']}.png"
        canvas.save(target, optimize=True)
        w, h = canvas.size
        corners = [canvas.getpixel(point)[3] for point in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
        report.append({"slug": strategy["slug"], "cards": len(ids), "size": [w, h],
                       "transparent_corners": all(alpha == 0 for alpha in corners)})
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create brief.json and search-matrix.json")
    init.add_argument("run", type=Path)
    init.add_argument("--as-of", required=True)
    init.add_argument("--patch")
    init.add_argument("--issue", type=int)
    init.add_argument("--mode", default="solo", choices=("solo", "duos"))
    init.add_argument("--races", help="comma-separated Russian race names in rotation")
    coverage = sub.add_parser("coverage", help="audit the recorded search matrix")
    coverage.add_argument("run", type=Path)
    check = sub.add_parser("check", help="lint the article against the live format")
    check.add_argument("article", type=Path)
    check.add_argument("--brief", type=Path)
    strips = sub.add_parser("strips", help="build transparent card strips")
    strips.add_argument("selection", type=Path)
    strips.add_argument("cards_dir", type=Path)
    strips.add_argument("out_dir", type=Path)
    args = parser.parse_args(argv)

    if args.command == "init":
        races = tuple(r.strip() for r in args.races.split(",") if r.strip()) if args.races else RACES
        brief = initialize(args.run, args.as_of, args.patch, args.issue, races, args.mode)
        print(json.dumps({"brief": str(brief), "matrix": str(args.run / "search-matrix.json"),
                          "next": "run ResearchTeam exhaustive search and fill the matrix"},
                         ensure_ascii=False))
        return 0
    if args.command == "coverage":
        result = audit_coverage(args.run)
    elif args.command == "check":
        races = None
        if args.brief:
            races = tuple(json.loads(args.brief.read_text(encoding="utf-8"))["races"])
        result = check_article(args.article, races)
    else:
        report = build_strips(args.selection, args.cards_dir, args.out_dir)
        result = {"ok": all(item["transparent_corners"] for item in report), "strips": report}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
