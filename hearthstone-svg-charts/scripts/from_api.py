#!/usr/bin/env python3
"""Готовые графики из живых данных api.kolodahearthstone.com и hs-manacost.ru.

Команды (все пишут chart-*.svg в --out, с --png ещё и PNG):
    meta         [--fmt standard|wild] [--top 10]      бары топ-архетипов по винрейту
    scatter      [--fmt] [--min-games 2000]            карта меты: винрейт × популярность
    history      --archetype "Pirate Warrior" [--fmt]  линия винрейта по дням
    arena-tiers                                         тир-лист классов Арены
    arena-donuts                                        2 donut: драфты и доля 7+ побед
    bg-tiers     [--mode solo] [--top-a 5]              тир-лист героев Полей сражений
    bg-radar     --hero "Cariel Roame" [--mode solo]    радар героя против среднего
    digest       [--days 7] [--limit 10]                дайджест статей сайта

Общие флаги: --out DIR (default .), --png, --social square|story, --theme, --title.
Пример:
    python3 scripts/from_api.py meta --png
    python3 scripts/from_api.py bg-radar --hero "Inge, the Iron Hymn" --png
"""
import argparse
import datetime
import html
import json
import pathlib
import re
import subprocess
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import make_chart

API = "https://api.kolodahearthstone.com"
WP = "https://hs-manacost.ru/wp-json/wp/v2"
FOOT = "источник: hearthpulse.net"

RU_ARCH = {
    "Quest Priest": "Квест Жрец", "Attack Druid": "Друид на атаке",
    "Rafaamlock": "Рафаам Чернокнижник", "Pirate Warrior": "Пират Воин",
    "Harold Rogue": "Разбойник на возвещении", "Thief Priest": "Жрец на воровстве",
    "Dragon Pirate Warrior": "Пират Воин (драконы)", "Quest Mage": "Квест Маг",
    "Sneaky Harold Rogue": "Скрытный разбойник", "Control Priest": "Контроль Жрец",
    "Zee Shaman": "Зи Шаман", "Harold Warlock": "Чернокнижник на возвещении",
    "Unholy DK": "Нечестивый РС", "Quest Warlock": "Квест Чернокнижник",
    "Quest Druid": "Квест Друид", "Quest Hunter": "Квест Охотник",
}
CLASS_KEYS = [("Priest", "priest"), ("Druid", "druid"), ("lock", "warlock"),
              ("Warrior", "warrior"), ("Rogue", "rogue"), ("Mage", "mage"),
              ("Shaman", "shaman"), ("DK", "deathknight"), ("Death Knight", "deathknight"),
              ("Paladin", "paladin"), ("Hunter", "hunter"), ("DH", "demonhunter"),
              ("Demon", "demonhunter")]
MON = {1: "янв", 2: "фев", 3: "мар", 4: "апр", 5: "мая", 6: "июн",
       7: "июл", 8: "авг", 9: "сен", 10: "окт", 11: "ноя", 12: "дек"}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (manacost-charts)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def api_items(path):
    d = get(API + path)
    data = d.get("data", d)
    return (data["items"] if isinstance(data, dict) and "items" in data else data), d.get("meta", {})

def ru(arch):
    return RU_ARCH.get(arch, arch)

def klass(arch):
    for key, slug in CLASS_KEYS:
        if key.lower() in arch.lower():
            return slug
    return None

def today_ru():
    d = datetime.date.today()
    return f"{d.day} {MON[d.month]} {d.year}"

def date_ru(iso):
    return f"{int(iso[8:10])} {MON[int(iso[5:7])]}"

def emit(spec, name, args):
    if args.social:
        spec["format"] = args.social
    if args.theme:
        spec["theme"] = args.theme
    if args.title:
        spec["title"] = args.title
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.date.today().strftime("%Y%m%d")
    svg_path = out / f"chart-{name}-{stamp}.svg"
    make_chart.DISPLAY_CHARS.clear()
    svg_path.write_text(make_chart.build(spec), encoding="utf-8")
    svg_path.with_suffix(".spec.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{svg_path} ({svg_path.stat().st_size // 1024} KB)")
    if args.png:
        subprocess.run([sys.executable, str(pathlib.Path(__file__).parent / "export_png.py"),
                        str(svg_path)], check=True)

# ------------------------------------------------------------------ commands

def cmd_meta(args):
    items, meta = api_items(f"/v1/hsguru/meta?format={args.fmt}")
    patch = (meta.get("current_patch_period") or "").replace("patch_", "патч ")
    top = sorted((i for i in items if (i.get("games") or 0) > 0), key=lambda i: -i["games"])[: args.top]
    spec = {"type": "bars", "title": f"Мета {'Стандарта' if args.fmt == 'standard' else 'Вольного'}: топ-{len(top)}",
            "subtitle": f"{patch} · за сутки · {today_ru()}", "theme": "arena", "vmin": 50,
            "data": [{"label": ru(i["archetype"]),
                      **({"icon": klass(i["archetype"])} if klass(i["archetype"]) else {}),
                      "value": round(i["winrate"], 1)} for i in top],
            "footer": FOOT}
    emit(spec, f"meta-{args.fmt}", args)

def cmd_scatter(args):
    items, meta = api_items(f"/v1/hsguru/meta?format={args.fmt}")
    patch = (meta.get("current_patch_period") or "").replace("patch_", "патч ")
    rows = [i for i in items if (i.get("games") or 0) >= args.min_games]
    spec = {"type": "scatter", "title": "Карта меты: сила против популярности",
            "subtitle": f"{'Стандарт' if args.fmt == 'standard' else 'Вольный'} · {patch} · {today_ru()}",
            "theme": "arena",
            "data": [{"label": ru(i["archetype"]), "x": i["winrate"], "y": i["popularity"],
                      "games": i["games"], "class": klass(i["archetype"]) or "neutral"} for i in rows],
            "footer": f"архетипы с ≥{args.min_games} игр · {FOOT}"}
    emit(spec, f"meta-scatter-{args.fmt}", args)

def cmd_history(args):
    items, _ = api_items(f"/v1/hsguru/archetypes/history?archetype={urllib.parse.quote(args.archetype)}"
                         f"&format={args.fmt}&limit=40")
    by_day = {}
    for r in items:
        if r.get("popularity_pct", 0) == 0:
            continue
        by_day.setdefault(r["recorded_at"][:10], r)
    days = sorted(by_day)[-10:]
    spec = {"type": "line", "title": f"{ru(args.archetype)}: динамика винрейта",
            "subtitle": f"{'Стандарт' if args.fmt == 'standard' else 'Вольный'} · по дням · {today_ru()}",
            "theme": "arena", "frame": "authentic",
            "data": {"xlabels": [date_ru(d) for d in days],
                     "series": [{"name": ru(args.archetype),
                                 "values": [by_day[d]["winrate"] for d in days]}]},
            "footer": FOOT}
    emit(spec, f"history-{args.archetype.lower().replace(' ', '-')}", args)

def cmd_arena_tiers(args):
    items, _ = api_items("/v1/arena/classes")
    def tier(wr): return "S" if wr >= 55 else "A" if wr >= 50 else "B" if wr >= 40 else "C" if wr >= 35 else "D"
    groups = {}
    for i in sorted(items, key=lambda x: -x["win_rate"]):
        groups.setdefault(tier(i["win_rate"]), []).append(
            {"label": i["class_ru"], "icon": i["slug"],
             "cols": [f'{i["win_rate"]:.1f}%', f'{i["pick_rate"]:.1f}%']})
    spec = {"type": "tierlist", "title": "Тир-лист классов Арены", "subtitle": f"срез {today_ru()}",
            "theme": "arena", "colheaders": ["винрейт", "выбор"],
            "data": [{"tier": t, "rows": groups[t]} for t in "SABCD" if t in groups],
            "footer": f"Тиры по винрейту: S ≥55, A ≥50, B ≥40, C ≥35 · {FOOT}"}
    emit(spec, "arena-tiers", args)

def cmd_arena_donuts(args):
    items, _ = api_items("/v1/arena/classes")
    def split(weights):
        total = sum(w for _, w in weights)
        shares = sorted(((n, w / total * 100) for n, w in weights), key=lambda x: -x[1])
        data = [{"label": n, "value": round(v, 1)} for n, v in shares[:5]]
        data.append({"label": "Прочее", "value": round(100 - sum(d["value"] for d in data), 1)})
        return data, total
    data, total = split([(i["class_ru"], i["num_drafts"]) for i in items])
    emit({"type": "donut", "title": "Кого драфтят на Арене",
          "subtitle": f"доли классов по числу драфтов · {today_ru()}", "theme": "arena",
          "center": {"big": f"{total:,}".replace(",", " "), "small": "драфтов"},
          "data": data, "footer": FOOT}, "arena-donut-picks", args)
    data, total = split([(i["class_ru"], i["num_drafts"] * i["pct_7_plus"] / 100) for i in items])
    emit({"type": "donut", "title": "Кто достигает 7+ побед",
          "subtitle": f"доли классов среди забегов 7+ · {today_ru()}", "theme": "arena",
          "center": {"big": f"≈{round(total)}", "small": "забегов 7+"},
          "data": data, "footer": f"Доля = драфты × процент 7+ побед · {FOOT}"}, "arena-donut-7plus", args)

def _bg_heroes(mode):
    items, _ = api_items(f"/v1/battlegrounds/heroes?mode={mode}&limit=300")
    return items

def cmd_bg_tiers(args):
    items = _bg_heroes(args.mode)
    s = sorted((i for i in items if i["tier"] == "S"), key=lambda i: i["avg_placement"])
    a = sorted((i for i in items if i["tier"] == "A"), key=lambda i: i["avg_placement"])[: args.top_a]
    def row(i):
        return {"label": i["hero"], "cols": [f'{i["avg_placement"]:.2f}', i["pick_rate"]]}
    spec = {"type": "tierlist", "title": "Герои Полей сражений: тир-лист",
            "subtitle": f"{args.mode} · по среднему месту · {today_ru()}", "theme": "bg",
            "colheaders": ["ср. место", "выбор"],
            "data": [{"tier": "S", "rows": [row(i) for i in s]},
                     {"tier": "A", "rows": [row(i) for i in a]}],
            "footer": f"A-тир показан не полностью (топ-{args.top_a}) · {FOOT}"}
    emit(spec, f"bg-tiers-{args.mode}", args)

def _pd(i, idx):
    return float(str(i["placement_distribution"][idx]).rstrip("%"))

def cmd_bg_radar(args):
    items = _bg_heroes(args.mode)
    hero = next((i for i in items if i["hero"].lower() == args.hero.lower()), None)
    if not hero:
        sys.exit(f"герой '{args.hero}' не найден (имена английские, как в игре)")
    # оси: сырые метрики -> min-max нормировка по всему пулу героев
    def metrics(i):
        return {"Место": -i["avg_placement"],
                "Топ-4": sum(_pd(i, k) for k in range(4)),
                "Победы": _pd(i, 0),
                "Выживание": -(_pd(i, 6) + _pd(i, 7)),
                "Выбор": i["pick_rate_value"]}
    pool = [metrics(i) for i in items]
    axes = list(pool[0])
    lo = {a: min(m[a] for m in pool) for a in axes}
    hi = {a: max(m[a] for m in pool) for a in axes}
    def norm(m):
        return [round((m[a] - lo[a]) / (hi[a] - lo[a]) * 100, 1) if hi[a] > lo[a] else 50 for a in axes]
    mid = {a: sorted(m[a] for m in pool)[len(pool) // 2] for a in axes}
    spec = {"type": "radar", "title": hero["hero"],
            "subtitle": f"{args.mode} · ср. место {hero['avg_placement']:.2f} · тир {hero['tier']} · {today_ru()}",
            "theme": "bg", "axes": axes,
            "data": [{"name": hero["hero"], "values": norm(metrics(hero)), "color": "#3d2335"},
                     {"name": "медианный герой", "values": norm(mid), "color": "#735e49", "reference": True}],
            "footer": f"Шкалы нормированы по всем {len(items)} героям · {FOOT}"}
    emit(spec, f"bg-radar-{args.hero.lower().replace(' ', '-').replace(',', '')}", args)

def cmd_arena_legendaries(args):
    d = get(API + "/datasets/hsreplay_arena_legendaries")
    groups = d["data"]["structured"]["groups"]
    rows = []
    for g in groups:
        try:
            wr = float(str(g["winrate"]).rstrip("%"))
        except (TypeError, ValueError):
            continue
        card = g["legendary_card"] or g["key_card"]
        cls = (g.get("class") or card.get("cardClass") or "").lower().replace(" ", "")
        rows.append({"label": card["name"], "value": round(wr, 1), "card_id": card.get("card_id") or card.get("id"),
                     **({"icon": cls} if cls and cls != "neutral" else {"icon": "neutral"})})
    top = sorted(rows, key=lambda r: -r["value"])[: args.top]
    if getattr(args, "cards", False):
        # рендеры карт (ruRU) с hearthstonejson, ужатые pngquant
        cdir = pathlib.Path(args.out) / ".cards"
        cdir.mkdir(parents=True, exist_ok=True)
        data = []
        for i, r in enumerate(top):
            cid = r["card_id"]
            dest = cdir / f"{cid}.png"
            if not dest.exists():
                url = f"https://art.hearthstonejson.com/v1/render/latest/ruRU/256x/{cid}.png"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                dest.write_bytes(urllib.request.urlopen(req, timeout=30).read())
                subprocess.run(["pngquant", "--force", "--quality", "70-95", "--speed", "1",
                                "--output", str(dest), str(dest)], check=False)
            data.append({"image": str(dest), "value": f'{r["value"]}%', "label": r["label"]})
        spec = {"type": "cards", "title": f"Топ-{len(top)} легендарок Арены",
                "subtitle": f"по винрейту · подземная Арена · за 4 дня · {today_ru()}", "theme": "arena",
                "data": data,
                "footer": f"винрейт колод, взявших карту · всего легендарок: {len(rows)} · источник: hearthpulse.net"}
        emit(spec, "arena-legendaries-cards", args)
        return
    spec = {"type": "bars", "title": f"Топ-{len(top)} легендарок Арены",
            "subtitle": f"подземная Арена · за 4 дня · {today_ru()}", "theme": "arena",
            "data": top,
            "footer": f"винрейт колод, взявших карту · всего легендарок: {len(rows)} · источник: hearthpulse.net"}
    emit(spec, "arena-legendaries", args)

def cmd_versus(args):
    items, meta = api_items(f"/v1/hsguru/meta?format={args.fmt}")
    patch = (meta.get("current_patch_period") or "").replace("patch_", "патч ")
    def pick(name):
        it = next((i for i in items if i["archetype"].lower() == name.lower()), None)
        if not it:
            sys.exit(f"архетип '{name}' не найден в мете (имена английские, как в hsguru)")
        return it
    l, r = pick(args.left), pick(args.right)
    def side(it, color):
        cls = klass(it["archetype"])
        return {"name": ru(it["archetype"]), "sub": "", "color": color,
                **({"avatar": cls} if cls else {})}
    spec = {"type": "versus", "title": f"{ru(l['archetype'])} против: {ru(r['archetype'])}",
            "subtitle": f"{'Стандарт' if args.fmt == 'standard' else 'Вольный'} · {patch} · за сутки · {today_ru()}",
            "theme": "arena",
            "data": {"left": side(l, "#8d171d"), "right": side(r, "#3d2335"),
                     "metrics": [
                         {"label": "винрейт", "left": l["winrate"], "right": r["winrate"], "unit": "%"},
                         {"label": "популярность", "left": l["popularity"], "right": r["popularity"], "unit": "%"},
                         {"label": "игр за сутки", "left": l["games"], "right": r["games"]},
                         {"label": "скорость набора звёзд, в час", "left": l["climbing_speed"], "right": r["climbing_speed"]},
                         {"label": "средняя длина игры, минут", "left": l["duration_minutes"], "right": r["duration_minutes"], "better": "lower"},
                     ]},
            "footer": FOOT}
    emit(spec, f"versus-{args.left.lower().replace(' ', '-')}-vs-{args.right.lower().replace(' ', '-')}", args)

def cmd_digest(args):
    posts = get(f"{WP}/posts?per_page={args.limit}&_fields=title,date,link,featured_media")
    cutoff = datetime.date.today() - datetime.timedelta(days=args.days)
    data = []
    for i, p in enumerate(posts):
        if p["date"][:10] < cutoff.isoformat():
            continue
        title = html.unescape(p["title"]["rendered"])
        item = {"title": title, "date": date_ru(p["date"]), **_digest_cat(title)}
        if p.get("link"):
            item["url"] = p["link"]
        mid = p.get("featured_media")
        if mid:
            try:
                murl = get(f"{WP}/media/{mid}?_fields=source_url")["source_url"]
                ext = re.sub(r"\?.*", "", murl).rsplit(".", 1)[-1][:4]
                dest = pathlib.Path(args.out) / f".cover-{i}.{ext}"
                req = urllib.request.Request(murl, headers={"User-Agent": "Mozilla/5.0"})
                dest.write_bytes(urllib.request.urlopen(req, timeout=20).read())
                item["image"] = str(dest)
            except Exception:
                pass
        data.append(item)
    if not data:
        sys.exit(f"за последние {args.days} дн. статей нет")
    d0, d1 = data[-1]["date"], data[0]["date"]
    spec = {"type": "digest", "title": "Вышло на Manacost",
            "subtitle": f"hs-manacost.ru · {d0} — {d1}", "theme": "arena", "data": data}
    emit(spec, "digest", args)
    for f in pathlib.Path(args.out).glob(".cover-*"):
        f.unlink()

def _digest_cat(title):
    t = title.lower()
    if "полей сражений" in t or "полях сражений" in t: return {"category": "Поля сражений", "theme": "bg"}
    if "потасовка" in t: return {"category": "Потасовка"}
    if "колод" in t: return {"category": "Колоды"}
    if "карты" in t: return {"category": "Карты"}
    if "обновление" in t or "патч" in t or "тизер" in t: return {"category": "Новости"}
    return {"category": "Hearthstone"}

# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=".")
    ap.add_argument("--png", action="store_true")
    ap.add_argument("--social", choices=["square", "story"])
    ap.add_argument("--theme", choices=["arena", "bg"])
    ap.add_argument("--title")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("meta"); p.add_argument("--fmt", default="standard", choices=["standard", "wild"]); p.add_argument("--top", type=int, default=10); p.set_defaults(fn=cmd_meta)
    p = sub.add_parser("scatter"); p.add_argument("--fmt", default="standard", choices=["standard", "wild"]); p.add_argument("--min-games", type=int, default=2000); p.set_defaults(fn=cmd_scatter)
    p = sub.add_parser("history"); p.add_argument("--archetype", required=True); p.add_argument("--fmt", default="standard", choices=["standard", "wild"]); p.set_defaults(fn=cmd_history)
    p = sub.add_parser("arena-tiers"); p.set_defaults(fn=cmd_arena_tiers)
    p = sub.add_parser("arena-donuts"); p.set_defaults(fn=cmd_arena_donuts)
    p = sub.add_parser("bg-tiers"); p.add_argument("--mode", default="solo", choices=["solo", "duos"]); p.add_argument("--top-a", type=int, default=5); p.set_defaults(fn=cmd_bg_tiers)
    p = sub.add_parser("bg-radar"); p.add_argument("--hero", required=True); p.add_argument("--mode", default="solo", choices=["solo", "duos"]); p.set_defaults(fn=cmd_bg_radar)
    p = sub.add_parser("arena-legendaries"); p.add_argument("--top", type=int, default=10); p.add_argument("--cards", action="store_true", help="рендеры карт вместо строк"); p.set_defaults(fn=cmd_arena_legendaries)
    p = sub.add_parser("versus"); p.add_argument("--left", required=True); p.add_argument("--right", required=True); p.add_argument("--fmt", default="standard", choices=["standard", "wild"]); p.set_defaults(fn=cmd_versus)
    p = sub.add_parser("digest"); p.add_argument("--days", type=int, default=7); p.add_argument("--limit", type=int, default=12); p.set_defaults(fn=cmd_digest)

    args = ap.parse_args()
    args.fn(args)

if __name__ == "__main__":
    main()
