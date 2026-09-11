#!/usr/bin/env python3
"""Static checks for Hearthstone-style chart SVGs.

Usage: python3 scripts/validate.py chart.svg [chart2.svg ...]
Exit code 1 if any ERROR. WARN lines are advisory.
"""
import re
import sys
import xml.etree.ElementTree as ET

SVG_NS = "http://www.w3.org/2000/svg"
GOLD = {"#d9ab49", "#efc96f"}


def check(path: str) -> list[str]:
    problems = []
    text = open(path, encoding="utf-8").read()
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        return [f"ERROR: XML не парсится: {e}"]

    # --- root svg ---
    vb = root.get("viewBox")
    if not vb:
        problems.append("ERROR: нет viewBox — график не будет масштабироваться")
        vb_w = vb_h = None
    else:
        parts = [float(x) for x in re.split(r"[ ,]+", vb.strip())]
        vb_w, vb_h = parts[2], parts[3]
    for attr in ("width", "height"):
        v = root.get(attr)
        if v and v != "100%":
            problems.append(f"WARN: атрибут {attr}='{v}' на <svg> — убери, размером управляет статья")
    style = root.get("style", "")
    if "background" in style:
        problems.append("ERROR: background на <svg> — фон должен быть прозрачным")

    all_elems = list(root.iter())

    # --- external refs ---
    for el in all_elems:
        for k, v in el.attrib.items():
            if k.endswith("href") and not (v.startswith("data:") or v.startswith("#")):
                problems.append(f"ERROR: внешняя ссылка '{v[:60]}' — в <img>-вставке не загрузится; только data-URI")

    # --- full-canvas background rect ---
    if vb_w:
        for el in all_elems:
            if el.tag == f"{{{SVG_NS}}}rect":
                try:
                    x, y = float(el.get("x", 0)), float(el.get("y", 0))
                    w, h = float(el.get("width", 0)), float(el.get("height", 0))
                except ValueError:
                    continue
                if x <= 1 and y <= 1 and w >= vb_w - 2 and h >= vb_h - 2:
                    fill = el.get("fill", "black")
                    if fill not in ("none", "transparent"):
                        problems.append("ERROR: rect на весь viewBox с заливкой — снаружи рамки должно быть прозрачно")
                # gold as large surface
                if el.get("fill", "").lower() in GOLD and w * h > 8000:
                    problems.append(f"WARN: крупная золотая заливка {w:g}x{h:g} — золото только для мелких акцентов")

    # --- text: font sizes and fallbacks ---
    for el in all_elems:
        if el.tag == f"{{{SVG_NS}}}text":
            fs = el.get("font-size")
            if fs:
                try:
                    size = float(re.sub(r"[a-z%]+$", "", fs))
                    if size < 11:
                        problems.append(f"ERROR: font-size {size:g} < 11 — нечитаемо ('{(el.text or '')[:25]}')")
                    elif size < 13:
                        problems.append(f"WARN: font-size {size:g} < 13 — допустимо только для сноски ('{(el.text or '')[:25]}')")
                except ValueError:
                    pass
    for m in re.finditer(r'font-family="([^"]+)"', text):
        fam = m.group(1)
        if "," not in fam:
            problems.append(f"WARN: font-family '{fam}' без фолбэка — через <img> шрифт не загрузится")

    # --- duplicate ids ---
    ids = [el.get("id") for el in all_elems if el.get("id")]
    dups = {i for i in ids if ids.count(i) > 1}
    for d in dups:
        problems.append(f"ERROR: дублирующийся id '{d}'")

    return problems


def main() -> None:
    fail = False
    for path in sys.argv[1:]:
        problems = check(path)
        print(f"== {path}")
        if not problems:
            print("   OK")
        for p in problems:
            print(f"   {p}")
            if p.startswith("ERROR"):
                fail = True
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
