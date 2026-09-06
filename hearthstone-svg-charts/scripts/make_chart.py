#!/usr/bin/env python3
"""Generate a Hearthstone-style SVG chart from a JSON spec.

Usage:
    python3 scripts/make_chart.py spec.json -o chart.svg

Spec (common fields):
{
  "type":     "bars|line|donut|tierlist|beforeafter|matchup|badge|timeline|digest",
  "title":    "Заголовок",
  "subtitle": "патч 33.4 · источник",          // optional
  "footer":   "текст сноски",                   // optional, auto-added scale note
  "theme":    "arena" | "bg",                   // plaque color, default arena
  "frame":    "vector" | "authentic",           // default vector; badge always deck-border
  "data":     ...                               // per-type, see references/generator.md
}

Icons: any "icon" value resolves to assets/datauri/<match>.txt:
  class slug ("mage"), "tribe-murlocs", "bg-tier3", "rarity-epic", "mana",
  "bg-hero-Alexstrasza", or a local image file path (inlined, webp converted).
"""
import argparse
import base64
import json
import math
import pathlib
import re
import struct
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DU = ROOT / "assets" / "datauri"

SANS = "Inter, -apple-system, 'Segoe UI', sans-serif"
SERIF = "HSDisplay, Georgia, serif"
DISPLAY_CHARS: set = set()   # chars rendered with SERIF -> font subset

def serif_text(s):
    DISPLAY_CHARS.update(str(s))
    return esc(s)

DEFINED: set = set()   # id уже вшитых symbol/image — повторные вставки идут через <use>
DEDUPE = False         # spec "dedupe": true — только для страниц, где <use> точно не режется

def img_ref(name, x, y, w, h, photo=False):
    """Картинка по имени: первый раз — <symbol> с data-URI, дальше — <use>.
    Экономит десятки КБ, когда одна иконка повторяется в каждой строке."""
    if not DEDUPE:
        # WordPress/TinyMCE вырезает <symbol>/<use> внутри инлайн-SVG —
        # по умолчанию картинки вставляются напрямую, надёжно везде
        return f'<image href="{icon_uri(name, photo=photo)}" x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}"/>'
    sid = "im-" + re.sub(r"[^A-Za-z0-9_-]", "_", str(name))[-40:]
    out = ""
    if sid not in DEFINED:
        DEFINED.add(sid)
        out = (f'<symbol id="{sid}" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">'
               f'<image href="{icon_uri(name, photo=photo)}" width="100" height="100"/></symbol>')
    return out + f'<use href="#{sid}" x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}"/>'
INK, MUTED = "#30251c", "#735e49"
CREAM = "#f7e8bf"
SERIES = ["#8d171d", "#8f536d", "#2f7a3e", "#b98a2f", "#735e49", "#3f6f6a"]
POS, NEG = "#2f7a3e", "#a33a3a"
GOLD = "#d9ab49"
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
CLASS_COLORS = {  # стандартные цвета классов, затемнённые под пергамент
    "druid": "#a05a10", "hunter": "#5e7a2f", "mage": "#2a7fa5", "paladin": "#c9722f",
    "priest": "#8a8578", "rogue": "#b0a231", "shaman": "#1e4e8c", "warlock": "#6a4a8c",
    "warrior": "#8c3a2a", "deathknight": "#3f6f6a", "demonhunter": "#2f7a5c",
    "neutral": "#735e49"}

# ---------------------------------------------------------------- helpers

def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))

def die(msg):
    sys.exit(f"make_chart: {msg}")

def text_w(s, size, serif=False):
    """Rough text width; cyrillic-friendly overestimate."""
    return len(str(s)) * size * (0.64 if serif else 0.60)

def wrap(s, size, max_w, max_lines=2):
    words, lines, cur = str(s).split(), [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if text_w(cand, size) <= max_w or not cur:
            cur = cand
        else:
            lines.append(cur); cur = w
        if len(lines) == max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines and words and " ".join(lines).split() != words:
        lines[-1] = lines[-1][: max(1, int(max_w / (size * 0.6)) - 1)].rstrip() + "…"
    return lines

def icon_tag(name, x, y, size=26, ring=True):
    """Game icon with a subtle gold ring (never tint the icon itself)."""
    tag = img_ref(name, x, y, size, size)
    if ring:
        tag += (f'<rect x="{x-1.2:g}" y="{y-1.2:g}" width="{size+2.4}" height="{size+2.4}" rx="{size*0.24:g}" '
                f'fill="none" stroke="url(#goldEdge)" stroke-width="1" opacity="0.55"/>')
    return tag

def icon_uri(name, photo=False):
    # PNG-двойники первыми: санитайзеры SVG (WordPress Safe SVG) режут data:image/webp
    for cand in (f"class-{name}.webp.pngtwin.txt", f"{name}.webp.pngtwin.txt",
                 f"class-{name}.webp.txt", f"{name}.webp.txt", f"{name}.png.txt",
                 f"{name}.jpg.txt", f"{name}.txt"):
        p = DU / cand
        if p.exists():
            return p.read_text().strip()
    p = pathlib.Path(name).expanduser()
    if p.exists():
        return inline_image(p, force_jpeg=photo)
    die(f"иконка/картинка не найдена: {name} (см. assets/datauri или укажи путь к файлу)")

def inline_image(path, max_kb=100, thumb_w=480, force_jpeg=False):
    """Inline a local image; big ones are downscaled via sips first.

    Photos stay JPEG (a PNG re-encode of a photo is ~10x heavier);
    webp always becomes PNG so resvg can render the PNG export.
    """
    if path.suffix.lower() not in MIME:
        die(f"неподдерживаемый формат картинки: {path}")
    src = path
    ext = path.suffix.lower()
    if path.stat().st_size > max_kb * 1024 or ext == ".webp" or (force_jpeg and ext != ".jpg"):
        fmt = "png" if ext == ".webp" else "jpeg"
        if ext == ".png" and not force_jpeg:
            ctype = path.read_bytes()[25]        # PNG colour type: 4/6 carry alpha
            fmt = "png" if ctype in (4, 6) else "jpeg"
        tmp = pathlib.Path(tempfile.mkstemp(suffix="." + ("png" if fmt == "png" else "jpg"))[1])
        if ext == ".png":
            thumb_w = min(thumb_w, png_size(path)[0])   # не растягивать маленькие PNG
        cmd = ["sips", "-s", "format", fmt, "--resampleWidth", str(thumb_w)]
        if fmt == "jpeg":
            cmd += ["-s", "formatOptions", "65"]
        subprocess.run(cmd + [str(path), "--out", str(tmp)], check=True, capture_output=True)
        src = tmp
    data = src.read_bytes()
    return f"data:{MIME[src.suffix.lower()]};base64,{base64.b64encode(data).decode()}"

def lerp_color(c1, c2, t):
    a = [int(c1[i:i+2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i+2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))

def nice_ticks(vmin, vmax, n=4):
    span = vmax - vmin
    step = 10 ** math.floor(math.log10(span / n))
    for m in (1, 2, 2.5, 5, 10):
        if span / (step * m) <= n + 1:
            step *= m
            break
    start = math.ceil(vmin / step) * step
    ticks, v = [], start
    while v <= vmax + 1e-9:
        ticks.append(round(v, 6)); v += step
    return ticks

# ---------------------------------------------------------------- chrome

def _cloth_uri():
    p = DU / "arena-rail-red.jpg.txt"
    if p.exists():
        return p.read_text().strip()
    src = ROOT / "assets" / "arena-rail-red.jpg"
    if src.exists():
        uri = "data:image/jpeg;base64," + base64.b64encode(src.read_bytes()).decode()
        p.write_text(uri)
        return uri
    return None

def make_defs():
    cloth = _cloth_uri()
    cloth_pat = (f'<pattern id="cloth" patternUnits="userSpaceOnUse" width="375" height="172">'
                 f'<image href="{cloth}" width="375" height="172"/></pattern>') if cloth else ""
    return f'''<defs>
  <linearGradient id="wood" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#6b3f21"/><stop offset="0.35" stop-color="#5f371d"/>
    <stop offset="0.65" stop-color="#472712"/><stop offset="1" stop-color="#2e160b"/>
  </linearGradient>
  <linearGradient id="parchment" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#f7e8bf"/><stop offset="1" stop-color="#ead6a7"/>
  </linearGradient>
  <linearGradient id="goldEdge" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#efc96f"/><stop offset="0.5" stop-color="#d9ab49"/>
    <stop offset="1" stop-color="#a67c2e"/>
  </linearGradient>
  <linearGradient id="bevelTop" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#ffe4aa" stop-opacity="0.55"/>
    <stop offset="0.5" stop-color="#ffe4aa" stop-opacity="0.10"/>
    <stop offset="1" stop-color="#000000" stop-opacity="0.28"/>
  </linearGradient>
  <linearGradient id="bevelBot" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#000000" stop-opacity="0.38"/>
    <stop offset="0.55" stop-color="#000000" stop-opacity="0.08"/>
    <stop offset="1" stop-color="#ffdf9e" stop-opacity="0.30"/>
  </linearGradient>
  <radialGradient id="vignette" cx="0.5" cy="0.5" r="0.75">
    <stop offset="0.70" stop-color="#30251c" stop-opacity="0"/>
    <stop offset="0.92" stop-color="#30251c" stop-opacity="0.10"/>
    <stop offset="1" stop-color="#241a12" stop-opacity="0.28"/>
  </radialGradient>
  <filter id="grain" x="0" y="0" width="100%" height="100%">
    <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" result="n"/>
    <feColorMatrix in="n" type="matrix"
      values="0 0 0 0 0.45  0 0 0 0 0.36  0 0 0 0 0.26  0 0 0 0.06 0"/>
    <feComposite operator="in" in2="SourceGraphic"/>
  </filter>
  <filter id="blotch" x="0" y="0" width="100%" height="100%">
    <feTurbulence type="fractalNoise" baseFrequency="0.011 0.017" numOctaves="3" seed="7" result="n"/>
    <feColorMatrix in="n" type="matrix"
      values="0 0 0 0 0.42  0 0 0 0 0.31  0 0 0 0 0.18  0 0 0 0.10 0"/>
    <feComposite operator="in" in2="SourceGraphic"/>
  </filter>
  <filter id="soft" x="-8%" y="-8%" width="116%" height="116%">
    <feGaussianBlur stdDeviation="3.2"/>
  </filter>
  <path id="cornerCap" d="M 3 30 L 3 13 Q 3 3 13 3 L 30 3 L 30 11.5 L 15 11.5
    Q 11.5 11.5 11.5 15 L 11.5 30 Z"/>
  {cloth_pat}
</defs>'''

def png_size(path):
    d = path.read_bytes()
    return struct.unpack(">II", d[16:24])

def nine_slice(asset, x, y, w, h, c, uid=""):
    uri = (DU / (asset + ".txt")).read_text().strip()
    iw, ih = png_size(ROOT / "assets" / asset)
    img_id = "f9-" + asset.split(".")[0]
    regions = [
        (x, y, c, c, 0, 0, c, c), (x + c, y, w - 2*c, c, c, 0, iw - 2*c, c),
        (x + w - c, y, c, c, iw - c, 0, c, c),
        (x, y + c, c, h - 2*c, 0, c, c, ih - 2*c),
        (x + w - c, y + c, c, h - 2*c, iw - c, c, c, ih - 2*c),
        (x, y + h - c, c, c, 0, ih - c, c, c),
        (x + c, y + h - c, w - 2*c, c, c, ih - c, iw - 2*c, c),
        (x + w - c, y + h - c, c, c, iw - c, ih - c, c, c),
    ]
    out = ["<g>"]
    if img_id not in DEFINED:
        DEFINED.add(img_id)
        out.append(f'<defs><image id="{img_id}" href="{uri}" width="{iw}" height="{ih}"/></defs>')
    for dx, dy, dw, dh, sx, sy, sw, sh in regions:
        out.append(f'<svg x="{dx:g}" y="{dy:g}" width="{dw:g}" height="{dh:g}" '
                   f'viewBox="{sx:g} {sy:g} {sw:g} {sh:g}" preserveAspectRatio="none" '
                   f'overflow="hidden"><use href="#{img_id}"/></svg>')
    out.append("</g>")
    return "".join(out)

def frame(H, mode="vector", finish="parade"):
    shadow = (f'<rect x="12" y="17" width="776" height="{H-25}" rx="16" '
              f'fill="#1a120b" opacity="0.30" filter="url(#soft)"/>')
    blotch = (f'<rect x="14" y="14" width="772" height="{H-28}" rx="10" filter="url(#blotch)" fill="#fff"/>'
              if finish == "parade" else "")
    if mode == "authentic":
        return (f'{make_defs()}\n{shadow}'
                f'<rect x="18" y="18" width="764" height="{H-36}" rx="6" fill="url(#parchment)"/>'
                + (f'<rect x="18" y="18" width="764" height="{H-36}" rx="6" filter="url(#blotch)" fill="#fff"/>' if finish == "parade" else "")
                + f'<rect x="18" y="18" width="764" height="{H-36}" rx="6" fill="url(#vignette)"/>'
                + nine_slice("main-page-rail-border.png", 6, 6, 788, H - 12, 45))
    corners = "".join(
        f'<use href="#cornerCap" transform="{t}" fill="url(#goldEdge)" stroke="#5d3f12" stroke-width="0.9"/>'
        for t in ("translate(0 0)", f"translate(800 0) scale(-1 1)",
                  f"translate(0 {H}) scale(1 -1)", f"translate(800 {H}) scale(-1 -1)"))
    return f'''{make_defs()}
{shadow}
<rect x="14" y="14" width="772" height="{H-28}" rx="10" fill="url(#parchment)"/>
{blotch}
<rect x="14" y="14" width="772" height="{H-28}" rx="10" fill="url(#vignette)"/>
<rect x="14" y="14" width="772" height="{H-28}" rx="10" filter="url(#grain)" fill="#fff"/>
<rect x="9" y="9" width="782" height="{H-18}" rx="14" fill="none" stroke="#1c0d06" stroke-width="2"/>
<rect x="10" y="10" width="780" height="{H-20}" rx="13" fill="none" stroke="url(#wood)" stroke-width="12"/>
<rect x="4.75" y="4.75" width="790.5" height="{H-9.5}" rx="16" fill="none" stroke="url(#bevelTop)" stroke-width="1.5"/>
<rect x="15.4" y="15.4" width="769.2" height="{H-30.8}" rx="9" fill="none" stroke="url(#bevelBot)" stroke-width="1.4"/>
<rect x="17.5" y="17.5" width="765" height="{H-35}" rx="8" fill="none" stroke="url(#goldEdge)" stroke-width="1.6"/>
{corners}'''

def title_block(spec):
    if not spec.get("title"):
        return "", 96
    t = serif_text(spec.get("title", ""))
    sub = esc(spec.get("subtitle", ""))
    arena = spec.get("theme", "arena") == "arena"
    edge, tail, outline = (("#5d0d13", "#4a0a0f", "#3a080c") if arena
                           else ("#2a1725", "#221022", "#1a0c18"))
    tint, tint_op = ("#8d171d", 0.30) if arena else ("#3d2335", 0.62)
    size = 26 if text_w(t, 26, serif=True) <= 660 else 21
    cloth = _cloth_uri()
    plaque_fill = 'url(#cloth)' if cloth else tint
    return f'''<g>
  <polygon points="46,38 24,38 34,56 24,74 46,74" fill="{tail}" stroke="#1c0d06" stroke-width="1"/>
  <polygon points="754,38 776,38 766,56 776,74 754,74" fill="{tail}" stroke="#1c0d06" stroke-width="1"/>
  <rect x="40" y="32" width="720" height="46" rx="6" fill="{plaque_fill}"/>
  <rect x="40" y="32" width="720" height="46" rx="6" fill="{tint}" opacity="{tint_op}"/>
  <rect x="40" y="32" width="720" height="46" rx="6" fill="url(#bevelTop)" opacity="0.55"/>
  <rect x="40" y="32" width="720" height="46" rx="6" fill="none" stroke="{edge}" stroke-width="1.6"/>
  <rect x="42" y="34" width="716" height="42" rx="5" fill="none" stroke="url(#goldEdge)" stroke-width="0.8" opacity="0.45"/>
  <text x="400" y="{64 if size == 26 else 62}" text-anchor="middle" font-family="{SERIF}"
        font-size="{size}" font-weight="700" fill="#f9ead0" letter-spacing="0.5"
        stroke="{outline}" stroke-width="3" paint-order="stroke" stroke-linejoin="round">{t}</text>
</g>''' + (f'\n<text x="400" y="101" text-anchor="middle" font-family="Georgia, serif" '
           f'font-style="italic" font-size="14" fill="{MUTED}">{sub}</text>' if sub else ""), (112 if sub else 96)

def footer(spec, H, extra=""):
    parts = [p for p in (extra, spec.get("footer", "")) if p]
    if not parts:
        return ""
    lines = wrap(" · ".join(parts), 12, 560, 2)   # 560: не заезжаем под логотип
    out = []
    for i, ln in enumerate(lines):
        y = H - 34 - (len(lines) - 1 - i) * 16
        out.append(f'<text x="40" y="{y}" font-family="{SANS}" font-size="12" fill="{MUTED}">{esc(ln)}</text>')
    return "\n".join(out)

def doc(W, H, label, body):
    # картинки через xlink:href: его понимают все браузеры, вьюеры и санитайзеры
    # (дублировать href нельзя — data-URI удвоили бы вес файла)
    body = re.sub(r'<image href="', '<image xlink:href="', body)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'viewBox="0 0 {W} {H}" role="img"\n'
            f'     aria-label="{esc(label)}">\n{body}\n</svg>\n')

# ---------------------------------------------------------------- renderers

def r_bars(spec):
    rows = spec["data"]
    vals = [r["value"] for r in rows]
    vmin = spec.get("vmin", math.floor(min(vals) - 2))
    vmax = spec.get("vmax", math.ceil(max(vals) + 1))
    unit = spec.get("unit", "%")
    extra_header = spec.get("extra_header")   # optional 2nd text column (e.g. popularity)
    H = 118 + len(rows) * 38 + 76 + (24 if extra_header else 0)
    # label column adapts to the longest name (up to 320), rest is truncated
    max_lab = max(len(str(r["label"])) * 9.0 for r in rows)
    X0 = min(380, max(230, int(82 + max_lab + 12)))
    track_end = 656 if extra_header else 710
    TRACK = track_end - X0
    lab_chars = int((X0 - 82 - 12) / 8.3)   # looser than sizing: truncate only real overflow
    y0 = 118
    body = []
    if extra_header:
        body.append(f'<text x="754" y="{y0+6}" text-anchor="end" font-family="{SANS}" '
                    f'font-size="13" font-weight="600" fill="{MUTED}">{esc(extra_header)}</text>')
        y0 += 24
    show_avg = spec.get("average", True) and len(rows) > 2
    if show_avg:
        avg = sum(vals) / len(vals)
        ax = X0 + TRACK * (avg - vmin) / (vmax - vmin)
        body.append(f'<line x1="{ax:.1f}" y1="{y0-6}" x2="{ax:.1f}" y2="{y0+len(rows)*38-8}" '
                    f'stroke="{MUTED}" stroke-width="1" stroke-dasharray="4 3"/>'
                    f'<text x="{ax:.1f}" y="{y0+len(rows)*38+8}" text-anchor="middle" '
                    f'font-family="{SANS}" font-size="12" fill="{MUTED}">среднее {avg:.1f}{unit}</text>')
    for i, r in enumerate(sorted(rows, key=lambda r: -r["value"])):
        y = y0 + i * 38
        w = TRACK * (r["value"] - vmin) / (vmax - vmin)
        leader = r.get("leader", i == 0 and spec.get("highlight_leader", True))
        stroke = f'stroke="{GOLD}" stroke-width="1.5"' if leader else 'stroke="#5d0d13" stroke-width="1"'
        color = r.get("color", "#8d171d" if spec.get("theme", "arena") == "arena" else "#8f536d")
        raw = str(r["label"])
        label = serif_text(raw if len(raw) <= lab_chars else raw[:lab_chars - 1].rstrip() + "…")
        icon = icon_tag(r["icon"], 46, y) if r.get("icon") else ""
        star = f'<text x="78" y="{y+18}" font-size="12" fill="{GOLD}">★</text>' if leader else ""
        tx = 92 if leader else 82
        # bar with inner bevel: light crest on top, shade below
        bar = f'''<rect x="{X0}" y="{y+1}" width="{TRACK}" height="24" rx="3" fill="{INK}" opacity="0.08"/>
  <rect class="a-grow" x="{X0}" y="{y+1}" width="{w:.1f}" height="24" rx="3" fill="{color}" {stroke}/>
  <rect x="{X0+1}" y="{y+2}" width="{max(w-2,0):.1f}" height="8" rx="2" fill="#ffffff" opacity="0.20"/>
  <rect x="{X0+1}" y="{y+17}" width="{max(w-2,0):.1f}" height="7" rx="2" fill="#000000" opacity="0.14"/>'''
        val = f'{r["value"]}{unit}'
        DISPLAY_CHARS.update(val + str(r.get("extra") or ""))
        if leader:
            bar += (f'\n  <circle cx="{X0+w:.1f}" cy="{y+13}" r="6.5" fill="url(#goldEdge)" '
                    f'stroke="#5d3f12" stroke-width="1"/>')
            mw = text_w(val, 14) + 18
            mx = X0 + w + 12
            if mx + mw > (676 if extra_header else 754):
                mx = X0 + w - mw - 14
            bar += (f'\n  <rect x="{mx:.1f}" y="{y+2}" width="{mw:.1f}" height="22" rx="11" '
                    f'fill="#5d0d13" stroke="url(#goldEdge)" stroke-width="1.2"/>'
                    f'\n  <text x="{mx+mw/2:.1f}" y="{y+18}" text-anchor="middle" font-family="{SERIF}" '
                    f'font-size="14.5" font-weight="700" fill="{CREAM}">{val}</text>')
        else:
            vx = X0 + w + 8
            vattr = f'x="{vx:.1f}" fill="{INK}"'
            if w > TRACK - 64:
                vattr = f'x="{X0+w-8:.1f}" text-anchor="end" fill="{CREAM}"'
            bar += f'\n  <text {vattr} y="{y+18}" font-family="{SERIF}" font-size="14.5">{val}</text>'
        if extra_header and r.get("extra") is not None:
            bar += (f'\n  <text x="754" y="{y+18}" text-anchor="end" font-family="{SERIF}" font-size="14" '
                    f'fill="{MUTED}">{esc(r["extra"])}</text>')
        body.append(f'''<g font-family="{SANS}">{icon}
  <text x="{tx}" y="{y+18}" font-family="{SERIF}" font-size="15" fill="{INK}">{label}</text>{star}
  {bar}
</g>''')
    return 800, H, "\n".join(body), f"Шкала от {vmin}{unit}"

def r_line(spec):
    d = spec["data"]
    xlabels, series = d["xlabels"], d["series"]
    allv = [v for s in series for v in s["values"]]
    vmin = spec.get("vmin", round(min(allv) - (max(allv) - min(allv)) * 0.15, 1))
    vmax = spec.get("vmax", round(max(allv) + (max(allv) - min(allv)) * 0.2, 1))
    unit = spec.get("unit", "%")
    H = 450
    PX0, PX1, PY0, PY1 = 100, 740, H - 80, 150
    def xy(i, v):
        x = PX0 + (PX1 - PX0) * (i / max(len(xlabels) - 1, 1))
        y = PY0 + (PY1 - PY0) * (v - vmin) / (vmax - vmin)
        return x, y
    body = []
    for gv in nice_ticks(vmin, vmax):
        _, gy = xy(0, gv)
        body.append(f'<line x1="{PX0}" y1="{gy:.1f}" x2="{PX1}" y2="{gy:.1f}" stroke="{MUTED}" stroke-width="1" opacity="0.3"/>'
                    f'<text x="{PX0-10}" y="{gy+4:.1f}" text-anchor="end" font-family="{SANS}" font-size="13" fill="{MUTED}">{gv:g}{unit}</text>')
    step = max(1, math.ceil(len(xlabels) / 7))
    for i, lab in enumerate(xlabels):
        if i % step and i != len(xlabels) - 1:
            continue
        x, _ = xy(i, vmin)
        body.append(f'<text x="{x:.1f}" y="{PY0+24}" text-anchor="middle" font-family="{SANS}" font-size="13" fill="{INK}">{esc(lab)}</text>')
    if len(series) > 1:
        lx = 100
        for si, s in enumerate(series):
            col = s.get("color", SERIES[si % len(SERIES)])
            name = esc(s["name"])
            body.append(f'<line x1="{lx}" y1="124" x2="{lx+24}" y2="124" stroke="{col}" stroke-width="3" stroke-linecap="round"/>'
                        f'<text x="{lx+32}" y="128" font-family="{SANS}" font-size="13" fill="{INK}">{name}</text>')
            lx += 32 + text_w(name, 13) + 28
    for si, s in enumerate(series):
        col = s.get("color", SERIES[si % len(SERIES)])
        pts = [xy(i, v) for i, v in enumerate(s["values"])]
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        if len(series) == 1:
            body.append(f'<defs><linearGradient id="la{si}" x1="0" y1="0" x2="0" y2="1">'
                        f'<stop offset="0" stop-color="{col}" stop-opacity="0.22"/>'
                        f'<stop offset="1" stop-color="{col}" stop-opacity="0"/></linearGradient></defs>'
                        f'<polygon points="{pts[0][0]:.1f},{PY0} {poly} {pts[-1][0]:.1f},{PY0}" fill="url(#la{si})"/>')
        body.append(f'<polyline points="{poly}" fill="none" stroke="{col}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
        for i, (x, y) in enumerate(pts):
            last = i == len(pts) - 1
            body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{col}" stroke="{GOLD if last else CREAM}" stroke-width="{2 if last else 1.5}"/>')
            if last:
                body.append(f'<text x="{x:.1f}" y="{y-14:.1f}" text-anchor="middle" font-family="{SANS}" font-size="15" font-weight="700" fill="{col}">{s["values"][-1]:g}{unit}</text>')
    return 800, H, "\n".join(body), f"Шкала от {vmin:g}{unit}"

def r_donut(spec):
    rows = spec["data"]
    total = sum(r["value"] for r in rows)
    if abs(total - 100) > 0.5:
        die(f"donut: сумма долей {total}, должна быть 100")
    H = 450
    CX, CY, R, RIN = 250, 268, 128, 77
    def pt(r, a): return CX + r * math.cos(a), CY + r * math.sin(a)
    body, a0 = [], -math.pi / 2
    # legend column on the right: immune to overlaps at any share skew
    ly0 = CY - (len(rows) * 36 - 10) / 2
    for i, r in enumerate(rows):
        col = r.get("color", "#a89274" if r["label"].strip().lower() == "прочее"
                    else SERIES[i % len(SERIES)])
        a1 = a0 + 2 * math.pi * r["value"] / total
        large = 1 if (a1 - a0) > math.pi else 0
        x0o, y0o = pt(R, a0); x1o, y1o = pt(R, a1)
        x1i, y1i = pt(RIN, a1); x0i, y0i = pt(RIN, a0)
        body.append(f'<path d="M {x0o:.1f} {y0o:.1f} A {R} {R} 0 {large} 1 {x1o:.1f} {y1o:.1f} '
                    f'L {x1i:.1f} {y1i:.1f} A {RIN} {RIN} 0 {large} 0 {x0i:.1f} {y0i:.1f} Z" '
                    f'fill="{col}" stroke="#ead6a7" stroke-width="3"/>')
        ly = ly0 + i * 36
        body.append(f'<rect x="446" y="{ly:.1f}" width="15" height="15" rx="4" fill="{col}" stroke="#5d3f12" stroke-width="0.7"/>'
                    f'<text x="470" y="{ly+12.5:.1f}" font-family="{SERIF}" font-size="15" fill="{INK}">{serif_text(r["label"])}</text>'
                    f'<text x="754" y="{ly+12.5:.1f}" text-anchor="end" font-family="{SERIF}" font-size="15" fill="{INK}">{serif_text(f"{r['value']:g}%")}</text>')
        a0 = a1
    # carved-ring shading so the donut reads as an inset, not a flat disc
    body.append(f'<circle cx="{CX}" cy="{CY}" r="{R}" fill="none" stroke="#30251c" stroke-width="2.5" opacity="0.15"/>'
                f'<circle cx="{CX}" cy="{CY}" r="{RIN}" fill="none" stroke="#30251c" stroke-width="2.5" opacity="0.20"/>'
                f'<circle cx="{CX}" cy="{CY}" r="{RIN-2.5}" fill="none" stroke="#fff6dd" stroke-width="1.5" opacity="0.5"/>')
    c = spec.get("center", {})
    if c:
        body.append(f'<text x="{CX}" y="{CY-2}" text-anchor="middle" font-family="{SERIF}" font-size="30" font-weight="700" fill="{INK}">{serif_text(c.get("big",""))}</text>'
                    f'<text x="{CX}" y="{CY+22}" text-anchor="middle" font-family="{SANS}" font-size="13" fill="{MUTED}">{esc(c.get("small",""))}</text>')
    return 800, H, "\n".join(body), "Сегменты по убыванию с 12 часов"

def r_tierlist(spec):
    tiers = spec["data"]
    plq = {"S": (GOLD, INK), "A": ("#8d171d", CREAM), "B": (MUTED, CREAM),
           "C": ("#5f371d", CREAM), "D": ("#443021", CREAM)}
    heads = spec.get("colheaders", [])
    y, ROW, GAP = 152, 34, 16
    body = []
    for ci, h in enumerate(heads):
        body.append(f'<text x="{600 + ci*130}" y="140" text-anchor="end" font-family="{SERIF}" font-size="14" '
                    f'letter-spacing="1" fill="{MUTED}">{serif_text(str(h).upper())}</text>')
    for ti, tier in enumerate(tiers):
        letter = tier["tier"]
        fill, tcol = plq.get(letter, (MUTED, CREAM))
        gh = len(tier["rows"]) * ROW
        body.append(f'<rect x="46" y="{y}" width="40" height="{gh-6}" rx="6" fill="{fill}" stroke="#2e160b" stroke-width="1"/>'
                    f'<rect x="46" y="{y}" width="40" height="{gh-6}" rx="6" fill="url(#bevelTop)" opacity="0.5"/>'
                    f'<text x="66" y="{y+(gh-6)/2+8}" text-anchor="middle" font-family="{SERIF}" font-size="22" font-weight="700" fill="{tcol}">{serif_text(letter)}</text>')
        for i, r in enumerate(tier["rows"]):
            ry = y + i * ROW
            icon = icon_tag(r["icon"], 100, ry, 24) if r.get("icon") else ""
            cols = "".join(
                f'<text x="{600 + ci*130}" y="{ry+17}" text-anchor="end" font-size="14.5" fill="{INK if ci == 0 else MUTED}">{serif_text(v)}</text>'
                for ci, v in enumerate(r.get("cols", [])))
            body.append(f'<g font-family="{SERIF}" font-size="15" fill="{INK}">{icon}'
                        f'<text x="134" y="{ry+17}">{serif_text(r["label"])}</text>{cols}</g>')
        y += gh + GAP
        if ti != len(tiers) - 1:
            dy = y - 10
            body.append(f'<rect x="46" y="{dy}" width="708" height="2" fill="#5f371d" opacity="0.6"/>'
                        f'<rect x="{400-4.5}" y="{dy-3.5}" width="9" height="9" rx="1.5" fill="url(#goldEdge)" '
                        f'stroke="#5d3f12" stroke-width="0.8" transform="rotate(45 400 {dy+1})"/>')
    return 800, y + 44, "\n".join(body), ""

def r_beforeafter(spec):
    rows = spec["data"]
    allv = [v for r in rows for v in (r["before"], r["after"])]
    vmin = spec.get("vmin", math.floor(min(allv) - 2))
    vmax = spec.get("vmax", math.ceil(max(allv) + 1))
    unit = spec.get("unit", "%")
    labels = spec.get("labels", ["до патча", "после патча"])
    # колонка подписей растёт под самое длинное имя (Belwe ~9 ед./символ), до 340
    max_lab = max(len(str(r["label"])) * 9.0 for r in rows)
    X0 = min(340, max(230, int(46 + max_lab + 14)))
    TRACK = 640 - X0
    def bw(v): return TRACK * (v - vmin) / (vmax - vmin)
    y = 152
    body = [f'''<g font-family="{SANS}" font-size="13">
  <rect x="270" y="118" width="22" height="12" rx="3" fill="{MUTED}" opacity="0.55"/>
  <text x="298" y="128" fill="{INK}">{esc(labels[0])}</text>
  <rect x="410" y="118" width="22" height="12" rx="3" fill="#8d171d"/>
  <text x="438" y="128" fill="{INK}">{esc(labels[1])}</text></g>''']
    for r in rows:
        d = r["after"] - r["before"]
        dcol, arrow, sign = (POS, "▲", "+") if d >= 0 else (NEG, "▼", "−")
        body.append(f'''<g font-family="{SANS}">
  <text x="46" y="{y+22}" font-family="{SERIF}" font-size="15" fill="{INK}">{serif_text(r["label"])}</text>
  <rect x="{X0}" y="{y}" width="{TRACK}" height="14" rx="3" fill="{INK}" opacity="0.06"/>
  <rect x="{X0}" y="{y}" width="{bw(r["before"]):.1f}" height="14" rx="3" fill="{MUTED}" opacity="0.55"/>
  <text x="{X0+bw(r["before"])+8:.1f}" y="{y+11}" font-size="13" fill="{MUTED}">{r["before"]}{unit}</text>
  <rect x="{X0}" y="{y+18}" width="{TRACK}" height="14" rx="3" fill="{INK}" opacity="0.06"/>
  <rect x="{X0}" y="{y+18}" width="{bw(r["after"]):.1f}" height="14" rx="3" fill="#8d171d" stroke="#5d0d13" stroke-width="1"/>
  <text x="{X0+bw(r["after"])+8:.1f}" y="{y+30}" font-size="13" font-weight="600" fill="{INK}">{r["after"]}{unit}</text>
  <text x="754" y="{y+22}" text-anchor="end" font-size="15" font-weight="700" fill="{dcol}">{sign}{abs(d):.1f}{unit} {arrow}</text>
</g>''')
        y += 56
    return 800, y + 60, "\n".join(body), f"Шкала от {vmin}{unit}"

def r_matchup(spec):
    d = spec["data"]
    rows, cols, vals = d["rows"], d["cols"], d["values"]
    n, m = len(rows), len(cols)
    if len(vals) != n or any(len(v) != m for v in vals):
        die("matchup: values должен быть матрицей rows×cols")
    LX, TY = 200, 158            # grid origin
    CW = min(80, (754 - LX) // m)
    CH = 38
    H = TY + n * CH + 84
    lo, hi = spec.get("vmin", 40), spec.get("vmax", 60)
    neutral = "#e6d2a1"
    def cell_color(v):
        if v is None: return "none"
        t = max(-1, min(1, (v - 50) / ((hi - lo) / 2)))
        return lerp_color(neutral, POS, t) if t >= 0 else lerp_color(neutral, NEG, -t)
    body = [f'<text x="{LX-8}" y="{TY-30}" text-anchor="end" font-family="{SANS}" font-size="12" fill="{MUTED}">строка против столбца →</text>']
    for j, c in enumerate(cols):
        x = LX + j * CW + CW / 2
        body.append(icon_tag(c["icon"], x - 12, TY - 28, 24)
                    if c.get("icon") else
                    f'<text x="{x:.1f}" y="{TY-12}" text-anchor="middle" font-family="{SANS}" font-size="12" fill="{INK}">{esc(c["label"])[:4]}</text>')
    for i, r in enumerate(rows):
        yv = TY + i * CH
        icon = icon_tag(r["icon"], 46, yv + 7, 24) if r.get("icon") else ""
        body.append(f'{icon}<text x="78" y="{yv+24}" font-family="{SERIF}" font-size="14" fill="{INK}">{serif_text(r["label"])}</text>')
        for j in range(m):
            v = vals[i][j]
            x = LX + j * CW
            if v is None:
                body.append(f'<rect x="{x+2}" y="{yv+2}" width="{CW-4}" height="{CH-4}" rx="3" fill="{INK}" opacity="0.06"/>'
                            f'<text x="{x+CW/2:.1f}" y="{yv+24}" text-anchor="middle" font-family="{SANS}" font-size="13" fill="{MUTED}">—</text>')
            else:
                tcol = CREAM if abs(v - 50) > (hi - lo) * 0.30 else INK
                body.append(f'<rect x="{x+2}" y="{yv+2}" width="{CW-4}" height="{CH-4}" rx="3" fill="{cell_color(v)}"/>'
                            f'<text x="{x+CW/2:.1f}" y="{yv+24}" text-anchor="middle" font-family="{SANS}" font-size="13" font-weight="600" fill="{tcol}">{v:g}</text>')
    # legend gradient
    gy = TY + n * CH + 22
    body.append(f'<defs><linearGradient id="mgrad" x1="0" y1="0" x2="1" y2="0">'
                f'<stop offset="0" stop-color="{NEG}"/><stop offset="0.5" stop-color="{neutral}"/>'
                f'<stop offset="1" stop-color="{POS}"/></linearGradient></defs>'
                f'<rect x="{LX}" y="{gy}" width="180" height="10" rx="3" fill="url(#mgrad)"/>'
                f'<text x="{LX-8}" y="{gy+10}" text-anchor="end" font-family="{SANS}" font-size="12" fill="{MUTED}">{lo}%</text>'
                f'<text x="{LX+188}" y="{gy+10}" font-family="{SANS}" font-size="12" fill="{MUTED}">{hi}%</text>')
    return 800, H, "\n".join(body), "Числа — винрейт строки против столбца"

def r_badge(spec):
    d = spec["data"]
    W, H = 320, 132
    body = [nine_slice("deck-border.png", 4, 4, W - 8, H - 8, 16)]
    icon = d.get("icon")
    tx = W / 2
    if icon:
        body.append(f'<image href="{icon_uri(icon)}" x="34" y="{H/2-24}" width="48" height="48"/>')
        tx = (W + 82) / 2
    body.append(f'<text x="{tx:.0f}" y="{H/2+2:.0f}" text-anchor="middle" font-family="{SERIF}" font-size="38" font-weight="700" fill="{INK}">{serif_text(d["value"])}</text>')
    if d.get("label"):
        body.append(f'<text x="{tx:.0f}" y="{H/2+30:.0f}" text-anchor="middle" font-family="{SANS}" font-size="14" fill="{MUTED}">{esc(d["label"])}</text>')
    # parchment under the transparent center + soft object shadow
    body.insert(0, f'{make_defs()}'
                   f'<rect x="8" y="13" width="{W-16}" height="{H-19}" rx="10" fill="#1a120b" opacity="0.28" filter="url(#soft)"/>'
                   f'<rect x="14" y="14" width="{W-28}" height="{H-28}" rx="6" fill="url(#parchment)"/>'
                   f'<rect x="14" y="14" width="{W-28}" height="{H-28}" rx="6" fill="url(#vignette)"/>')
    return W, H, "\n".join(body), None   # no footer, no title chrome

def r_timeline(spec):
    events = spec["data"]
    n = len(events)
    if n < 2: die("timeline: нужно минимум 2 события")
    H = 340
    LX, RX, CY_ = 80, 720, 210
    scol = {"done": POS, "now": GOLD, "major": "#8d171d", "planned": MUTED}
    body = [f'<line x1="{LX-14}" y1="{CY_}" x2="{RX+20}" y2="{CY_}" stroke="url(#wood)" stroke-width="4" stroke-linecap="round"/>'
            f'<path d="M {RX+34} {CY_} l -14 -7 v 14 Z" fill="#5f371d"/>']
    for i, e in enumerate(events):
        x = LX + (RX - LX) * i / (n - 1)
        st = e.get("status", "planned")
        col = scol.get(st, MUTED)
        above = i % 2 == 0
        if st == "now":
            body.append(f'<rect x="{x-8:.1f}" y="{CY_-8}" width="16" height="16" rx="3" fill="url(#goldEdge)" stroke="#5d3f12" stroke-width="1" transform="rotate(45 {x:.1f} {CY_})"/>')
        elif st == "planned":
            body.append(f'<circle cx="{x:.1f}" cy="{CY_}" r="7" fill="url(#parchment)" stroke="{col}" stroke-width="2.5"/>')
        else:
            body.append(f'<circle cx="{x:.1f}" cy="{CY_}" r="7.5" fill="{col}" stroke="{CREAM}" stroke-width="2"/>')
        ly = CY_ - 26 if above else CY_ + 40
        stem_y1, stem_y2 = (CY_ - 12, ly + 6) if above else (CY_ + 12, ly - 16)
        body.append(f'<line x1="{x:.1f}" y1="{stem_y1}" x2="{x:.1f}" y2="{stem_y2}" stroke="{MUTED}" stroke-width="1" opacity="0.6"/>')
        date = esc(e.get("date", ""))
        lines = wrap(e["label"], 13, 120, 2)
        block = [f'<text x="{x:.1f}" y="{ly}" text-anchor="middle" font-family="{SANS}" font-size="13" font-weight="700" fill="{col if st != "planned" else INK}">{date}</text>']
        for li, ln in enumerate(lines):
            block.append(f'<text x="{x:.1f}" y="{ly + 17 + li*16 if not above else ly - 34 + (li - len(lines) + 1)*16 - 2}" text-anchor="middle" font-family="{SANS}" font-size="13" fill="{INK}">{esc(ln)}</text>')
        if above:
            # date closest to axis, label lines above it
            block = [f'<text x="{x:.1f}" y="{ly}" text-anchor="middle" font-family="{SANS}" font-size="13" font-weight="700" fill="{col if st != "planned" else INK}">{date}</text>']
            for li, ln in enumerate(reversed(lines)):
                block.append(f'<text x="{x:.1f}" y="{ly - 18 - li*16}" text-anchor="middle" font-family="{SANS}" font-size="13" fill="{INK}">{esc(ln)}</text>')
        body.extend(block)
    if spec.get("legend", True):
        items = [("done", "вышло"), ("now", "сейчас"), ("planned", "план")]
        lx = 270
        for st, name in items:
            body.append(f'<circle cx="{lx}" cy="{H-52}" r="6" fill="{scol[st] if st != "planned" else "url(#parchment)"}" stroke="{scol[st]}" stroke-width="2"/>'
                        f'<text x="{lx+13}" y="{H-47}" font-family="{SANS}" font-size="13" fill="{INK}">{name}</text>')
            lx += 13 + text_w(name, 13) + 34
    return 800, H, "\n".join(body), ""

def r_digest(spec):
    items = spec["data"]
    if spec.get("compact", len(items) > 6):
        return r_digest_compact(spec)
    IH, PAD = 104, 118
    H = 128 + len(items) * PAD + 44
    body = []
    y = 128
    for i, it in enumerate(items):
        # thumb 168x94 in deck-border mini frame
        if it.get("url"):
            body.append(f'<a href="{esc(it["url"])}">')
        if it.get("image"):
            uri = icon_uri(it["image"], photo=True)
            body.append(f'<defs><clipPath id="dg{i}"><rect x="52" y="{y+6}" width="156" height="{IH-22}" rx="4"/></clipPath></defs>'
                        f'<image href="{uri}" x="52" y="{y+6}" width="156" height="{IH-22}" preserveAspectRatio="xMidYMid slice" clip-path="url(#dg{i})"/>')
        else:
            body.append(f'<rect x="52" y="{y+6}" width="156" height="{IH-22}" rx="4" fill="{INK}" opacity="0.08"/>'
                        f'<image href="{icon_uri("mana")}" x="112" y="{y+24}" width="36" height="46" opacity="0.7"/>')
        body.append(nine_slice("deck-border.png", 44, y - 2, 172, IH - 6, 14, uid=f"-{i}"))
        cat = it.get("category", "")
        catw = text_w(cat, 12) + 20
        if cat:
            ccol = "#8d171d" if it.get("theme", spec.get("theme", "arena")) == "arena" else "#3d2335"
            body.append(f'<rect x="238" y="{y+2}" width="{catw:.0f}" height="20" rx="10" fill="{ccol}"/>'
                        f'<text x="{238+catw/2:.0f}" y="{y+16}" text-anchor="middle" font-family="{SANS}" font-size="12" fill="{CREAM}">{esc(cat)}</text>')
        if it.get("date"):
            body.append(f'<text x="754" y="{y+17}" text-anchor="end" font-family="{SANS}" font-size="13" fill="{MUTED}">{esc(it["date"])}</text>')
        for li, ln in enumerate(wrap(it["title"], 17, 500, 2)):
            body.append(f'<text x="238" y="{y+48+li*24}" font-family="{SANS}" font-size="17" font-weight="600" fill="{INK}">{esc(ln)}</text>')
        if it.get("url"):
            body.append('</a>')
        if i != len(items) - 1:
            body.append(f'<rect x="44" y="{y+PAD-11}" width="712" height="1.5" fill="#5f371d" opacity="0.35"/>')
        y += PAD
    return 800, H, "\n".join(body), ""

def r_digest_compact(spec):
    """Dense digest for 7+ items: one-line titles, small thumbs."""
    items = spec["data"]
    PAD = 84
    H = 128 + len(items) * PAD + 36
    body = []
    y = 128
    for i, it in enumerate(items):
        if it.get("url"):
            body.append(f'<a href="{esc(it["url"])}">')
        if it.get("image"):
            uri = icon_uri(it["image"], photo=True)
            body.append(f'<defs><clipPath id="dgc{i}"><rect x="52" y="{y+7}" width="108" height="56" rx="3"/></clipPath></defs>'
                        f'<image href="{uri}" x="52" y="{y+7}" width="108" height="56" preserveAspectRatio="xMidYMid slice" clip-path="url(#dgc{i})"/>')
        else:
            body.append(f'<rect x="52" y="{y+7}" width="108" height="56" rx="3" fill="{INK}" opacity="0.08"/>'
                        f'<image href="{icon_uri("mana")}" x="92" y="{y+13}" width="28" height="36" opacity="0.7"/>')
        body.append(nine_slice("deck-border.png", 45, y, 122, 70, 12, uid=f"c{i}"))
        cat = it.get("category", "")
        if cat:
            catw = text_w(cat, 12) + 18
            ccol = "#8d171d" if it.get("theme", spec.get("theme", "arena")) == "arena" else "#3d2335"
            body.append(f'<rect x="186" y="{y+6}" width="{catw:.0f}" height="19" rx="9.5" fill="{ccol}"/>'
                        f'<text x="{186+catw/2:.0f}" y="{y+19.5}" text-anchor="middle" font-family="{SANS}" font-size="12" fill="{CREAM}">{esc(cat)}</text>')
        if it.get("date"):
            body.append(f'<text x="754" y="{y+20}" text-anchor="end" font-family="{SANS}" font-size="13" fill="{MUTED}">{esc(it["date"])}</text>')
        title = str(it["title"])
        if len(title) > 56:
            title = title[:55].rstrip() + "…"
        body.append(f'<text x="186" y="{y+50}" font-family="{SANS}" font-size="15" font-weight="600" fill="{INK}">{esc(title)}</text>')
        if it.get("url"):
            body.append('</a>')
        if i != len(items) - 1:
            body.append(f'<rect x="44" y="{y+PAD-8}" width="712" height="1.5" fill="#5f371d" opacity="0.3"/>')
        y += PAD
    return 800, H, "\n".join(body), ""


def r_scatter(spec):
    """Карта меты: X — винрейт, Y — популярность (методология hearthpulse)."""
    rows = spec["data"]
    H = 560
    PX0, PX1, PY1, PY0 = 96, 736, 138, H - 96          # PY0 низ (y=0 популярности)
    xs = [r["x"] for r in rows]
    xmin = spec.get("vmin", math.floor(min(xs) - 2))
    xmax = spec.get("vmax", math.ceil(max(xs) + 2))
    ymax = spec.get("ymax", math.ceil(max(r["y"] for r in rows) / 5) * 5)
    def XY(r):
        x = PX0 + (PX1 - PX0) * (r["x"] - xmin) / (xmax - xmin)
        y = PY0 - (PY0 - PY1) * r["y"] / ymax
        return x, y
    body = []
    for gv in nice_ticks(xmin, xmax):
        gx = PX0 + (PX1 - PX0) * (gv - xmin) / (xmax - xmin)
        body.append(f'<line x1="{gx:.1f}" y1="{PY1}" x2="{gx:.1f}" y2="{PY0}" stroke="{MUTED}" stroke-width="1" opacity="0.22"/>'
                    f'<text x="{gx:.1f}" y="{PY0+22}" text-anchor="middle" font-family="{SANS}" font-size="13" fill="{MUTED}">{gv:g}%</text>')
    for gv in nice_ticks(0, ymax):
        gy = PY0 - (PY0 - PY1) * gv / ymax
        body.append(f'<line x1="{PX0}" y1="{gy:.1f}" x2="{PX1}" y2="{gy:.1f}" stroke="{MUTED}" stroke-width="1" opacity="0.22"/>'
                    f'<text x="{PX0-10}" y="{gy+4:.1f}" text-anchor="end" font-family="{SANS}" font-size="13" fill="{MUTED}">{gv:g}%</text>')
    if xmin < 50 < xmax:
        g50 = PX0 + (PX1 - PX0) * (50 - xmin) / (xmax - xmin)
        body.append(f'<line x1="{g50:.1f}" y1="{PY1}" x2="{g50:.1f}" y2="{PY0}" stroke="{NEG}" stroke-width="1.5" stroke-dasharray="5 4" opacity="0.55"/>'
                    f'<text x="{g50:.1f}" y="{PY1-8}" text-anchor="middle" font-family="{SANS}" font-size="12" fill="{NEG}">50%</text>')
    body.append(f'<text x="{(PX0+PX1)/2}" y="{PY0+44}" text-anchor="middle" font-family="{SANS}" font-size="13" fill="{INK}">винрейт →</text>'
                f'<text x="{PX0-56}" y="{PY1-14}" font-family="{SANS}" font-size="13" fill="{INK}">популярность ↑</text>')
    gmax = max((r.get("games") or 0) for r in rows) or 1
    labeled = sorted(rows, key=lambda r: -(r.get("games") or r["y"]))[: spec.get("label_top", 8)]
    placed = []          # (x0, x1, y) уже поставленных подписей — для разруливания коллизий
    for r in sorted(rows, key=lambda r: -(r.get("games") or 0)):
        x, y = XY(r)
        rad = 6 + 8 * math.sqrt((r.get("games") or 0) / gmax)
        col = r.get("color") or CLASS_COLORS.get(r.get("class", ""), MUTED)
        body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rad:.1f}" fill="{col}" fill-opacity="0.82" stroke="{CREAM}" stroke-width="1.6"/>')
        if r in labeled:
            lab = serif_text(r["label"])
            w = text_w(r["label"], 13.5, serif=True)
            anchor, lx = ("start", x + rad + 6) if x < 600 else ("end", x - rad - 6)
            x0, x1 = (lx, lx + w) if anchor == "start" else (lx - w, lx)
            ly = y + 4
            for dy in (0, -19, 19, -38, 38, -57, 57):
                cand = ly + dy
                if all(x1 < px0 - 6 or x0 > px1 + 6 or abs(cand - py) >= 17
                       for px0, px1, py in placed):
                    ly = cand
                    break
            placed.append((x0, x1, ly))
            body.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" font-family="{SERIF}" '
                        f'font-size="13.5" fill="{INK}" stroke="#f7e8bf" stroke-width="3" paint-order="stroke" stroke-linejoin="round">{lab}</text>')
    return 800, H, "\n".join(body), f"Размер точки — число игр · подписаны топ-{len(labeled)}"

def r_radar(spec):
    """Паутинка 3–8 осей, до 2 серий, значения 0–100 (нормировка на вызывающей стороне)."""
    axes = spec["axes"]
    series = spec["data"]
    n = len(axes)
    if not 3 <= n <= 8: die("radar: нужно 3–8 осей")
    H = 560
    CX, CY, R = 400, 320, 168
    def pt(frac, i):
        a = -math.pi / 2 + 2 * math.pi * i / n
        return CX + R * frac * math.cos(a), CY + R * frac * math.sin(a)
    body = []
    for ring in (0.2, 0.4, 0.6, 0.8, 1.0):
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (pt(ring, i) for i in range(n)))
        body.append(f'<polygon points="{pts}" fill="none" stroke="{MUTED}" stroke-width="1" opacity="{0.42 if ring == 1.0 else 0.25}"/>')
    for i, ax in enumerate(axes):
        x1, y1 = pt(1.0, i)
        body.append(f'<line x1="{CX}" y1="{CY}" x2="{x1:.1f}" y2="{y1:.1f}" stroke="{MUTED}" stroke-width="1" opacity="0.3"/>')
        lx, ly = pt(1.16, i)
        anchor = "middle" if abs(lx - CX) < 30 else ("start" if lx > CX else "end")
        body.append(f'<text x="{lx:.1f}" y="{ly+5:.1f}" text-anchor="{anchor}" font-family="{SERIF}" font-size="15" fill="{INK}">{serif_text(ax)}</text>')
    for si, s in enumerate(series[:2]):
        col = s.get("color", SERIES[si % len(SERIES)])
        pts = [pt(max(0, min(100, v)) / 100, i) for i, v in enumerate(s["values"])]
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        ref = s.get("reference")
        if ref:
            body.append(f'<polygon points="{poly}" fill="none" stroke="{col}" stroke-width="2" stroke-dasharray="5 4" opacity="0.7"/>')
        else:
            body.append(f'<polygon points="{poly}" fill="{col}" fill-opacity="0.22" stroke="{col}" stroke-width="3" stroke-linejoin="round"/>')
            for x, y in pts:
                body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{col}" stroke="{CREAM}" stroke-width="1.5"/>')
    if len(series) > 1:
        lx = 270
        for si, s in enumerate(series[:2]):
            col = s.get("color", SERIES[si % len(SERIES)])
            dash = ' stroke-dasharray="5 4"' if s.get("reference") else ""
            body.append(f'<line x1="{lx}" y1="{H-52}" x2="{lx+26}" y2="{H-52}" stroke="{col}" stroke-width="3"{dash}/>'
                        f'<text x="{lx+34}" y="{H-47}" font-family="{SANS}" font-size="13" fill="{INK}">{esc(s["name"])}</text>')
            lx += 34 + text_w(s["name"], 13) + 30
    return 800, H, "\n".join(body), ""


def r_stackbars(spec):
    """100%-стек с лентами перетекания между строками (мини-санкей).

    Ленты показывают, как доля темы меняется от строки к строке —
    главный сюжет такого графика виден без арифметики в уме.
    """
    rows = spec["data"]
    names = []
    for r in rows:
        for s in r["segments"]:
            if s["name"] not in names:
                names.append(s["name"])
    colors = {n: ("#a89274" if n.strip().lower() == "прочее" else SERIES[i % len(SERIES)])
              for i, n in enumerate(names)}
    colors.update(spec.get("colors", {}))
    X0, TRACK, BH, GAP = 214, 540, 40, 44
    STEP = BH + GAP
    y0 = 128
    # легенда с переносом
    body, lx, lrow = [], 46, 0
    for n in names:
        w = 20 + text_w(n, 13) + 22
        if lx + w > 754:
            lx, lrow = 46, lrow + 1
        ly = y0 - 14 + lrow * 24
        body.append(f'<rect x="{lx}" y="{ly}" width="14" height="14" rx="4" fill="{colors[n]}" stroke="#5d3f12" stroke-width="0.6"/>'
                    f'<text x="{lx+20}" y="{ly+12}" font-family="{SANS}" font-size="13" fill="{INK}">{esc(n)}</text>')
        lx += w
    y_first = y0 + 26 + lrow * 24
    # границы сегментов по строкам: bounds[i][name] = (x_start, x_end)
    bounds = []
    for r in rows:
        total = sum(s["value"] for s in r["segments"]) or 1
        b, x = {}, X0
        for s in r["segments"]:
            w = TRACK * s["value"] / total
            b[s["name"]] = (x, x + w)
            x += w
        bounds.append(b)
    # ленты перетекания — рисуются ПОД полосами
    for i in range(len(rows) - 1):
        ya = y_first + i * STEP + BH
        yb = y_first + (i + 1) * STEP
        mid = (ya + yb) / 2
        for n in names:
            if n not in bounds[i] or n not in bounds[i + 1]:
                continue
            a0, a1 = bounds[i][n]
            b0, b1 = bounds[i + 1][n]
            if a1 - a0 < 0.5 and b1 - b0 < 0.5:
                continue
            body.append(f'<path d="M {a0:.1f} {ya} C {a0:.1f} {mid} {b0:.1f} {mid} {b0:.1f} {yb} '
                        f'L {b1:.1f} {yb} C {b1:.1f} {mid} {a1:.1f} {mid} {a1:.1f} {ya} Z" '
                        f'fill="{colors[n]}" opacity="0.17"/>')
    # полосы
    for i, r in enumerate(rows):
        y = y_first + i * STEP
        total = sum(s["value"] for s in r["segments"]) or 1
        body.append(f'<defs><clipPath id="sb{i}"><rect x="{X0}" y="{y}" width="{TRACK}" height="{BH}" rx="6"/></clipPath></defs>')
        body.append(f'<text x="{X0-16}" y="{y+18}" text-anchor="end" font-family="{SERIF}" font-size="16" fill="{INK}">{serif_text(r["label"])}</text>')
        if r.get("sub"):
            body.append(f'<text x="{X0-16}" y="{y+35}" text-anchor="end" font-family="{SANS}" font-size="12" fill="{MUTED}">{esc(r["sub"])}</text>')
        seg_tags = []
        x = X0
        for s in r["segments"]:
            w = TRACK * s["value"] / total
            if w <= 0:
                continue
            seg_tags.append(f'<rect class="a-grow" x="{x:.1f}" y="{y}" width="{w:.1f}" height="{BH}" fill="{colors[s["name"]]}"/>'
                            f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="12" fill="#ffffff" opacity="0.18"/>'
                            f'<rect x="{x:.1f}" y="{y+BH-9}" width="{w:.1f}" height="9" fill="#000000" opacity="0.12"/>')
            if x > X0:
                seg_tags.append(f'<line x1="{x:.1f}" y1="{y}" x2="{x:.1f}" y2="{y+BH}" stroke="#ead6a7" stroke-width="1.6"/>')
            pct = s["value"] / total * 100
            if w >= 42:
                seg_tags.append(f'<text x="{x+w/2:.1f}" y="{y+BH/2+5.5}" text-anchor="middle" font-family="{SERIF}" '
                                f'font-size="14.5" fill="{CREAM}">{serif_text(f"{pct:.0f}%")}</text>')
            x += w
        body.append(f'<g clip-path="url(#sb{i})">{"".join(seg_tags)}</g>')
        body.append(f'<rect x="{X0}" y="{y}" width="{TRACK}" height="{BH}" rx="6" fill="none" stroke="#5d0d13" stroke-width="1.2" opacity="0.45"/>'
                    f'<rect x="{X0+1}" y="{y+1}" width="{TRACK-2}" height="{BH-2}" rx="5" fill="none" stroke="url(#goldEdge)" stroke-width="0.8" opacity="0.35"/>')
    return 800, y_first + len(rows) * STEP - GAP + 78, "\n".join(body), "Каждая строка = 100%"


def r_author(spec):
    """Карточка автора для подписи статей: аватар, имя, роль, статы-пилюли."""
    d = spec["data"]
    H = 236
    body = []
    # аватар в двойном золотом кольце
    ax, ay, r = 118, H / 2, 58
    uri = icon_uri(d["avatar"], photo=True) if d.get("avatar") else None
    if uri:
        body.append(f'<defs><clipPath id="avclip"><circle cx="{ax}" cy="{ay}" r="{r}"/></clipPath></defs>'
                    f'<circle cx="{ax}" cy="{ay}" r="{r+7}" fill="#5d0d13" opacity="0.25"/>'
                    f'<image href="{uri}" x="{ax-r}" y="{ay-r}" width="{2*r}" height="{2*r}" '
                    f'preserveAspectRatio="xMidYMid slice" clip-path="url(#avclip)"/>')
    body.append(f'<circle cx="{ax}" cy="{ay}" r="{r+2}" fill="none" stroke="url(#goldEdge)" stroke-width="4"/>'
                f'<circle cx="{ax}" cy="{ay}" r="{r+5.5}" fill="none" stroke="#5d3f12" stroke-width="1.2"/>')
    tx = 214
    icon = f' {icon_tag(d["icon"], tx + text_w(d["name"], 26, serif=True) + 10, 52, 28)}' if d.get("icon") else ""
    body.append(f'<text x="{tx}" y="76" font-family="{SERIF}" font-size="26" fill="{INK}" '
                f'letter-spacing="0.4">{serif_text(d["name"])}</text>{icon}')
    if d.get("role"):
        body.append(f'<text x="{tx}" y="100" font-family="Georgia, serif" font-style="italic" '
                    f'font-size="14.5" fill="#8d171d">{esc(d["role"])}</text>')
    if d.get("tagline"):
        for i, ln in enumerate(wrap(d["tagline"], 14, 520, 2)):
            body.append(f'<text x="{tx}" y="{126 + i*19}" font-family="{SANS}" font-size="14" '
                        f'fill="{INK}">{esc(ln)}</text>')
    x = tx
    for st in (d.get("stats") or [])[:3]:
        vw = max(text_w(st["value"], 15, serif=True), text_w(st["label"], 11)) + 26
        body.append(f'<rect x="{x}" y="164" width="{vw:.0f}" height="42" rx="9" fill="#5d0d13" opacity="0.92"/>'
                    f'<rect x="{x}" y="164" width="{vw:.0f}" height="42" rx="9" fill="url(#bevelTop)" opacity="0.5"/>'
                    f'<rect x="{x}" y="164" width="{vw:.0f}" height="42" rx="9" fill="none" stroke="url(#goldEdge)" stroke-width="1"/>'
                    f'<text x="{x+vw/2:.0f}" y="{164+19}" text-anchor="middle" font-family="{SERIF}" font-size="15" fill="{CREAM}">{serif_text(st["value"])}</text>'
                    f'<text x="{x+vw/2:.0f}" y="{164+34}" text-anchor="middle" font-family="{SANS}" font-size="11" fill="#d9ab49">{esc(st["label"])}</text>')
        x += vw + 14
    return 800, H, "\n".join(body), None


def _fighter(side, cx, cy, r):
    body = []
    if side.get("avatar"):
        uri = icon_uri(side["avatar"], photo=str(side["avatar"]).startswith("/"))
        body.append(f'<defs><clipPath id="vs-{cx}"><circle cx="{cx}" cy="{cy}" r="{r}"/></clipPath></defs>'
                    f'<image href="{uri}" x="{cx-r}" y="{cy-r}" width="{2*r}" height="{2*r}" '
                    f'preserveAspectRatio="xMidYMid slice" clip-path="url(#vs-{cx})"/>')
    body.append(f'<circle cx="{cx}" cy="{cy}" r="{r+2}" fill="none" stroke="url(#goldEdge)" stroke-width="4"/>'
                f'<circle cx="{cx}" cy="{cy}" r="{r+5.5}" fill="none" stroke="#5d3f12" stroke-width="1.2"/>')
    body.append(f'<text x="{cx}" y="{cy+r+34}" text-anchor="middle" font-family="{SERIF}" '
                f'font-size="20" fill="{INK}">{serif_text(side["name"])}</text>')
    if side.get("sub"):
        body.append(f'<text x="{cx}" y="{cy+r+54}" text-anchor="middle" font-family="{SANS}" '
                    f'font-size="13" fill="{MUTED}">{esc(side["sub"])}</text>')
    return "\n".join(body)

def r_versus(spec):
    """Афиша «кто кого»: два портрета, VS-медальон, встречные бары по метрикам."""
    d = spec["data"]
    left, right, metrics = d["left"], d["right"], d["metrics"]
    lc = left.get("color", "#8d171d")
    rc = right.get("color", "#3d2335")
    cy, r = 196, 62
    rows_y0 = cy + r + 84
    H = rows_y0 + len(metrics) * 56 + 58
    body = [_fighter(left, 168, cy, r), _fighter(right, 632, cy, r)]
    # VS-медальон
    body.append(f'<circle cx="400" cy="{cy}" r="34" fill="url(#goldEdge)" stroke="#5d3f12" stroke-width="1.6"/>'
                f'<circle cx="400" cy="{cy}" r="28" fill="none" stroke="#5d3f12" stroke-width="1" opacity="0.5"/>'
                f'<text x="400" y="{cy+9}" text-anchor="middle" font-family="{SERIF}" font-size="26" '
                f'fill="#3a2408" stroke="#f9ead0" stroke-width="0.6">{serif_text("VS")}</text>')
    HALF, CXL, CXR = 168, 388, 412   # встречные дорожки от центра
    for i, m in enumerate(metrics):
        y = rows_y0 + i * 56
        body.append(f'<text x="400" y="{y-8}" text-anchor="middle" font-family="{SERIF}" '
                    f'font-size="14" letter-spacing="0.4" fill="{MUTED}">{serif_text(m["label"])}</text>')
        try:
            lv, rv = float(m["left"]), float(m["right"])
            numeric = True
        except (TypeError, ValueError):
            numeric = False
        if numeric and (lv or rv):
            better = m.get("better", "higher")
            lwin = (lv > rv) if better == "higher" else (lv < rv)
            rwin = (rv > lv) if better == "higher" else (rv < lv)
            mx = max(abs(lv), abs(rv)) or 1
            lw, rw = HALF * abs(lv) / mx, HALF * abs(rv) / mx
            for (x0, w, col, win) in ((CXL - lw, lw, lc, lwin), (CXR, rw, rc, rwin)):
                body.append(f'<rect x="{x0:.1f}" y="{y}" width="{w:.1f}" height="20" rx="3" fill="{col}" '
                            f'opacity="{1 if win else 0.45}"'
                            + (f' stroke="{GOLD}" stroke-width="1.5"' if win else "") + '/>'
                            f'<rect x="{x0:.1f}" y="{y+1}" width="{w:.1f}" height="7" rx="2" fill="#ffffff" opacity="0.18"/>')
            body.append(f'<text x="{CXL-HALF-12}" y="{y+16}" text-anchor="end" font-family="{SERIF}" font-size="15.5" '
                        f'fill="{INK if lwin else MUTED}">{serif_text(m["left"])}{esc(m.get("unit", ""))}</text>'
                        f'<text x="{CXR+HALF+12}" y="{y+16}" font-family="{SERIF}" font-size="15.5" '
                        f'fill="{INK if rwin else MUTED}">{serif_text(m["right"])}{esc(m.get("unit", ""))}</text>')
            if lwin or rwin:
                sx = CXL - HALF - 12 - text_w(f'{m["left"]}{m.get("unit","")}', 15.5, serif=True) - 16 if lwin \
                     else CXR + HALF + 12 + text_w(f'{m["right"]}{m.get("unit","")}', 15.5, serif=True) + 8
                body.append(f'<text x="{sx:.0f}" y="{y+15}" font-size="12" fill="{GOLD}">★</text>')
        else:
            body.append(f'<text x="{CXL-40}" y="{y+16}" text-anchor="end" font-family="{SERIF}" font-size="15.5" fill="{INK}">{serif_text(m["left"])}</text>'
                        f'<text x="{CXR+40}" y="{y+16}" font-family="{SERIF}" font-size="15.5" fill="{INK}">{serif_text(m["right"])}</text>')
        if i != len(metrics) - 1:
            body.append(f'<line x1="120" y1="{y+38}" x2="680" y2="{y+38}" stroke="#5f371d" stroke-width="1" opacity="0.25"/>')
    return 800, H, "\n".join(body), "★ — лучший по метрике"

def r_quote(spec):
    """Цитата-карточка: золотые кавычки, текст Belwe, автор с аватаром."""
    d = spec["data"]
    lines = wrap(d["text"], 21, 560, 5)
    qy0 = 118
    ay = qy0 + len(lines) * 32 + 34
    H = ay + 96
    body = [f'<text x="52" y="{qy0+52}" font-family="{SERIF}" font-size="110" '
            f'fill="url(#goldEdge)" opacity="0.75">{serif_text("«")}</text>']
    for i, ln in enumerate(lines):
        body.append(f'<text x="150" y="{qy0 + i*32}" font-family="{SERIF}" font-size="21" '
                    f'fill="{INK}">{serif_text(ln)}</text>')
    body.append(f'<line x1="150" y1="{ay-26}" x2="330" y2="{ay-26}" stroke="url(#goldEdge)" stroke-width="2" opacity="0.7"/>')
    ax = 150
    if d.get("avatar"):
        uri = icon_uri(d["avatar"], photo=str(d["avatar"]).startswith("/"))
        body.append(f'<defs><clipPath id="qav"><circle cx="{ax+24}" cy="{ay+10}" r="24"/></clipPath></defs>'
                    f'<image href="{uri}" x="{ax}" y="{ay-14}" width="48" height="48" '
                    f'preserveAspectRatio="xMidYMid slice" clip-path="url(#qav)"/>'
                    f'<circle cx="{ax+24}" cy="{ay+10}" r="25" fill="none" stroke="url(#goldEdge)" stroke-width="2.5"/>')
        ax += 64
    body.append(f'<text x="{ax}" y="{ay+8}" font-family="{SERIF}" font-size="17" fill="{INK}">{serif_text(d["author"])}</text>')
    if d.get("role"):
        body.append(f'<text x="{ax}" y="{ay+28}" font-family="{SANS}" font-size="13" fill="{MUTED}">{esc(d["role"])}</text>')
    return 800, H, "\n".join(body), None


def _mana_crystal(x, y, cost, scale=1.0):
    """Векторный кристалл маны с цифрой — чётче, чем растровая иконка в 24px."""
    s = scale
    return (f'<g transform="translate({x} {y}) scale({s})">'
            f'<path d="M 13 0 L 24 9 L 20.5 26 L 5.5 26 L 2 9 Z" fill="url(#manaG)" stroke="#0a2c50" stroke-width="1.6"/>'
            f'<path d="M 13 2.5 L 21.5 9.5 L 13 7 L 4.5 9.5 Z" fill="#bfe3ff" opacity="0.5"/>'
            f'<text x="13" y="19.5" text-anchor="middle" font-family="{SERIF}" font-size="14" '
            f'fill="#ffffff" stroke="#0a2c50" stroke-width="2.6" paint-order="stroke">{serif_text(cost)}</text>'
            f'</g>')

def r_mulligan(spec):
    """Мулиган-гайд: карты × классы-оппоненты, вердикты держать/по ситуации/кидать."""
    d = spec["data"]
    opps, rows = d["opponents"], d["rows"]
    if len(opps) > 7: die("mulligan: максимум 7 оппонентов")
    LX = 320
    CW = min(74, (752 - LX) // len(opps))
    TY = 168
    RH = 46
    H = TY + len(rows) * RH + 64
    VER = {"keep": ("#2f7a3e", "#1d5229", "✓"), "if": ("#b98a2f", "#7d5a1a", "?"),
           "toss": ("#a33a3a", "#6e2222", "✗")}
    body = []
    # легенда — внизу, под таблицей; верх остаётся чистым
    ly = TY + len(rows) * RH + 8
    lx = 46
    for k, label in (("keep", "держать"), ("if", "по ситуации"), ("toss", "кидать")):
        col, edge, sym = VER[k]
        body.append(f'<rect x="{lx}" y="{ly}" width="24" height="24" rx="7" fill="{col}" stroke="{edge}" stroke-width="1.4"/>'
                    f'<rect x="{lx}" y="{ly}" width="24" height="10" rx="5" fill="#ffffff" opacity="0.22"/>'
                    f'<text x="{lx+12}" y="{ly+17}" text-anchor="middle" font-family="{SANS}" font-size="13" font-weight="700" fill="{CREAM}">{sym}</text>'
                    f'<text x="{lx+32}" y="{ly+17}" font-family="{SANS}" font-size="13.5" fill="{INK}">{label}</text>')
        lx += 32 + text_w(label, 13.5) + 24
    body.append(f'<text x="{320-14}" y="{TY-28}" text-anchor="end" font-family="Georgia, serif" font-style="italic" font-size="13" fill="{MUTED}">против →</text>')
    # дорожки колонок (чётные тонированы) + иконки оппонентов в кольцах
    bot = TY + len(rows) * RH - 6
    for j, o in enumerate(opps):
        x0 = LX + j * CW
        if j % 2 == 0:
            body.append(f'<rect x="{x0+3}" y="{TY-52}" width="{CW-6}" height="{bot-(TY-52)}" rx="9" fill="{INK}" opacity="0.05"/>')
        body.append(icon_tag(o, x0 + CW / 2 - 15, TY - 48, 30))
    # деревянный разделитель под шапкой
    body.append(f'<rect x="44" y="{TY-10}" width="712" height="2" fill="#5f371d" opacity="0.5"/>'
                f'<rect x="395.5" y="{TY-14.5}" width="9" height="9" rx="1.5" fill="url(#goldEdge)" stroke="#5d3f12" stroke-width="0.8" transform="rotate(45 400 {TY-10+1})"/>')
    for i, r in enumerate(rows):
        y = TY + i * RH
        body.append(img_ref("mana", 46, y + 1, 30, 30) +
                    f'<text x="61" y="{y+22}" text-anchor="middle" font-family="{SERIF}" font-size="14.5" '
                    f'fill="#ffffff" stroke="#0a2c50" stroke-width="2.6" paint-order="stroke">{serif_text(r.get("cost", ""))}</text>')
        name = str(r["card"])
        if len(name) > 22: name = name[:21].rstrip() + "…"
        body.append(f'<text x="84" y="{y+23}" font-family="{SERIF}" font-size="15.5" fill="{INK}">{serif_text(name)}</text>')
        if r.get("count") == 2:
            nx = min(84 + text_w(name, 15.5, serif=True) + 6, LX - 34)
            body.append(f'<text x="{nx:.0f}" y="{y+23}" font-family="{SANS}" font-size="12" font-weight="700" fill="#b98a2f">×2</text>')
        for j, v in enumerate(r["verdicts"][:len(opps)]):
            col, edge, sym = VER.get(v, (MUTED, MUTED, "—"))
            cx = LX + j * CW + CW / 2
            body.append(f'<rect x="{cx-14:.0f}" y="{y+2}" width="28" height="28" rx="8" fill="{col}" stroke="{edge}" stroke-width="1.5"/>'
                        f'<rect x="{cx-14:.0f}" y="{y+2}" width="28" height="12" rx="6" fill="#ffffff" opacity="0.22"/>'
                        f'<text x="{cx:.0f}" y="{y+22}" text-anchor="middle" font-family="{SANS}" font-size="14.5" font-weight="700" fill="{CREAM}">{sym}</text>')
        if i != len(rows) - 1:
            body.append(f'<line x1="44" y1="{y+RH-6}" x2="756" y2="{y+RH-6}" stroke="{MUTED}" stroke-width="1" opacity="0.18"/>')
    return 800, H, "\n".join(body), None


def r_facts(spec):
    """Полоса «факты»: 2–4 медальона с крупным числом и подписью."""
    items = spec["data"][:4]
    n = len(items)
    H = 340
    GAP = 22
    PW = min(250, int((700 - (n - 1) * GAP) / n))   # 4 медальона → 158, 3 → 218
    PH = 136
    total = n * PW + (n - 1) * GAP
    x = 400 - total / 2
    y = 140
    body = []
    for i, it in enumerate(items):
        tone = it.get("tone", "neutral")
        vcol = {"pos": "#9fd39a", "neg": "#f0a0a0"}.get(tone, CREAM)
        body.append(f'<rect x="{x:.0f}" y="{y}" width="{PW}" height="{PH}" rx="14" fill="#5d0d13"/>'
                    f'<rect x="{x:.0f}" y="{y}" width="{PW}" height="{PH}" rx="14" fill="url(#bevelTop)" opacity="0.55"/>'
                    f'<rect x="{x+1:.0f}" y="{y+1}" width="{PW-2}" height="{PH-2}" rx="13" fill="none" stroke="url(#goldEdge)" stroke-width="1.6"/>')
        if it.get("icon"):
            body.append(icon_tag(it["icon"], x + 12, y + 12, 26))
        val = str(it["value"])
        vsize = 34 if len(val) <= 6 else 26 if len(val) <= 10 else 20
        body.append(f'<text x="{x+PW/2:.0f}" y="{y+60}" text-anchor="middle" font-family="{SERIF}" '
                    f'font-size="{vsize}" fill="{vcol}">{serif_text(val)}</text>')
        for li, ln in enumerate(wrap(it["label"], 12, PW - 22, 3)):
            body.append(f'<text x="{x+PW/2:.0f}" y="{y+84+li*15}" text-anchor="middle" font-family="{SANS}" '
                        f'font-size="12" fill="#d9ab49">{esc(ln)}</text>')
        x += PW + GAP
    if spec.get("note"):
        for li, ln in enumerate(wrap(spec["note"], 14, 660, 2)):
            body.append(f'<text x="400" y="{y+PH+40+li*20}" text-anchor="middle" font-family="{SANS}" '
                        f'font-size="14" fill="{INK}">{esc(ln)}</text>')
    return 800, H, "\n".join(body), None


def r_cards(spec):
    """Галерея рендеров карт: до 10 карт в 2 ряда, ранг-гемма и медальон со значением."""
    items = spec["data"][:10]
    n = len(items)
    cols = min(5, n)
    CW, CH = 120, 182
    gap = (720 - cols * CW) / (cols - 1) if cols > 1 else 0
    PITCH = CH + 58
    rows = (n + cols - 1) // cols
    y0 = 118
    H = y0 + rows * PITCH + 30
    body = []
    for i, it in enumerate(items):
        r, c = divmod(i, cols)
        x = 40 + c * (CW + gap)
        y = y0 + r * PITCH
        uri = icon_uri(it["image"])
        body.append(f'<rect x="{x+6:.0f}" y="{y+10}" width="{CW-12}" height="{CH-12}" rx="12" fill="#1a120b" opacity="0.28" filter="url(#soft)"/>'
                    f'<image href="{uri}" x="{x:.0f}" y="{y}" width="{CW}" height="{CH}" preserveAspectRatio="xMidYMid meet"/>')
        rank = it.get("rank", i + 1)
        # ранг — справа сверху (слева на карте кристалл маны); по умолчанию выключен
        rx = x + CW - 14
        if spec.get("ranks", False):
          body.append(f'<circle cx="{rx:.0f}" cy="{y+16}" r="15" fill="url(#goldEdge)" stroke="#5d3f12" stroke-width="1.4"/>'
                    f'<text x="{rx:.0f}" y="{y+21.5}" text-anchor="middle" font-family="{SERIF}" font-size="15" fill="#3a2408">{serif_text(rank)}</text>')
        val = str(it["value"])
        mw = max(text_w(val, 16, serif=True) + 26, 74)
        mx = x + CW / 2 - mw / 2
        my = y + CH + 8
        body.append(f'<rect x="{mx:.0f}" y="{my}" width="{mw:.0f}" height="30" rx="15" fill="#5d0d13" stroke="url(#goldEdge)" stroke-width="1.4"/>'
                    f'<rect x="{mx:.0f}" y="{my}" width="{mw:.0f}" height="12" rx="6" fill="#ffffff" opacity="0.14"/>'
                    f'<text x="{x+CW/2:.0f}" y="{my+21}" text-anchor="middle" font-family="{SERIF}" font-size="16" fill="{CREAM}">{serif_text(val)}</text>')
        if it.get("sub"):
            body.append(f'<text x="{x+CW/2:.0f}" y="{my+46}" text-anchor="middle" font-family="{SANS}" font-size="11.5" fill="{MUTED}">{esc(it["sub"])}</text>')
    return 800, H, "\n".join(body), None


def r_bump(spec):
    """Смена рейтинга: две колонки рангов (было/стало), линии соединяют один объект."""
    d = spec["data"]
    before, after = d["before"], d["after"]     # списки {label, value, icon?} в порядке рангов
    hb, ha = d.get("labels", ["было", "стало"])
    n = max(len(before), len(after))
    y0, STEP = 150, 44
    H = y0 + n * STEP + 40
    LX, RX = 46, 468          # левые края колонок
    LW = 290                  # ширина колонки
    body = [f'<text x="{LX+LW/2:.0f}" y="{y0-26}" text-anchor="middle" font-family="{SERIF}" font-size="15" letter-spacing="1" fill="{MUTED}">{serif_text(str(hb).upper())}</text>',
            f'<text x="{RX+LW/2:.0f}" y="{y0-26}" text-anchor="middle" font-family="{SERIF}" font-size="15" letter-spacing="1" fill="{MUTED}">{serif_text(str(ha).upper())}</text>']
    pos_b = {r["label"]: i for i, r in enumerate(before)}
    pos_a = {r["label"]: i for i, r in enumerate(after)}
    # линии — под строками
    for lab, ib in pos_b.items():
        if lab not in pos_a:
            continue
        ia = pos_a[lab]
        y1, y2 = y0 + ib * STEP + 14, y0 + ia * STEP + 14
        col = POS if ia < ib else NEG if ia > ib else MUTED
        x1, x2 = LX + LW + 6, RX - 6
        mx = (x1 + x2) / 2
        body.append(f'<path d="M {x1} {y1} C {mx} {y1} {mx} {y2} {x2} {y2}" fill="none" stroke="{col}" '
                    f'stroke-width="{3 if ia != ib else 1.5}" opacity="{0.75 if ia != ib else 0.35}" stroke-linecap="round"/>')
    def column(rows, x, other_pos, mine_pos, right=False):
        for i, r in enumerate(rows):
            y = y0 + i * STEP
            moved = other_pos.get(r["label"])
            delta = (moved - i) if moved is not None else 0      # >0 поднялся (в правой колонке)
            body.append(f'<rect x="{x}" y="{y-6}" width="{LW}" height="{STEP-4}" rx="8" fill="{INK}" opacity="0.045"/>'
                        f'<text x="{x+22}" y="{y+20}" text-anchor="middle" font-family="{SERIF}" font-size="16" fill="{MUTED}">{serif_text(i+1)}</text>')
            if r.get("icon"):
                body.append(icon_tag(r["icon"], x + 42, y + 1, 26))
            # имя сверху, значение под ним — длинные названия не спорят со стрелкой
            body.append(f'<text x="{x+78}" y="{y+15}" font-family="{SERIF}" font-size="14.5" fill="{INK}">{serif_text(r["label"])}</text>')
            val = str(r.get("value", ""))
            if val:
                body.append(f'<text x="{x+78}" y="{y+31}" font-family="{SANS}" font-size="12" fill="{MUTED}">{esc(val)}</text>')
            if right and moved is not None and delta:
                arrow = "▲" if delta > 0 else "▼"
                acol = POS if delta > 0 else NEG
                body.append(f'<text x="{x+LW-12}" y="{y+22}" text-anchor="end" font-family="{SANS}" font-size="14" font-weight="700" fill="{acol}">{arrow}{abs(delta)}</text>')
    column(before, LX, pos_a, pos_b)
    column(after, RX, pos_b, pos_a, right=True)
    return 800, H, "\n".join(body), "▲▼ — на сколько мест изменился ранг"


def r_notice(spec):
    """Объявление/вакансия: оффер, 1–2 колонки буллетов, плашка-призыв."""
    d = spec["data"]
    cols = d.get("columns", [])[:2]
    # в квадрате/сторис без колонок текста мало — крупнее типографика, чтобы заполнить формат
    big = spec.get("format") in ("square", "story") and not cols
    hs, hl = (27, 36) if big else (22, 30)          # кегль/интерлиньяж оффера
    ls, ll = (17.5, 27) if big else (15, 23)         # кегль/интерлиньяж лида
    y = 160 if big else 144
    body = []
    if d.get("headline"):
        h_lines = wrap(d["headline"], hs, 640, 3)
        for i, ln in enumerate(h_lines):
            body.append(f'<text x="400" y="{y+i*hl}" text-anchor="middle" font-family="{SERIF}" '
                        f'font-size="{hs}" fill="{INK}">{serif_text(ln)}</text>')
        y += hl * len(h_lines) + (26 if big else 18)
    if d.get("lead"):
        lead_lines = wrap(d["lead"], ls, 600 if big else 620, 6)
        for i, ln in enumerate(lead_lines):
            body.append(f'<text x="400" y="{y+i*ll}" text-anchor="middle" font-family="{SANS}" '
                        f'font-size="{ls}" fill="{INK}">{esc(ln)}</text>')
        y += ll * len(lead_lines) + (34 if big else 22)
    # колонки
    n = len(cols)
    colw = 330 if n == 2 else 680
    xs = [60, 410] if n == 2 else [60]
    ymax = y
    for ci, col in enumerate(cols):
        x = xs[ci]
        cy = y
        body.append(f'<text x="{x}" y="{cy}" font-family="{SERIF}" font-size="14" letter-spacing="1.2" '
                    f'fill="#8d171d">{serif_text(str(col.get("title", "")).upper())}</text>'
                    f'<rect x="{x}" y="{cy+8}" width="{colw}" height="2" fill="#5f371d" opacity="0.45"/>')
        cy += 34
        for item in col.get("items", []):
            lines = wrap(item, 14.5, colw - 26, 3)
            body.append(f'<rect x="{x+2}" y="{cy-9}" width="9" height="9" rx="1.5" fill="url(#goldEdge)" '
                        f'stroke="#5d3f12" stroke-width="0.8" transform="rotate(45 {x+6.5} {cy-4.5})"/>')
            for li, ln in enumerate(lines):
                body.append(f'<text x="{x+24}" y="{cy+li*20}" font-family="{SANS}" font-size="14.5" '
                            f'fill="{INK}">{esc(ln)}</text>')
            cy += 20 * len(lines) + 10
        ymax = max(ymax, cy)
    y = ymax + 16
    cta = d.get("cta")
    if cta:
        txt = str(cta.get("text", ""))
        contact = str(cta.get("contact", ""))
        w = 700
        ch = 72 if big else 58
        body.append(f'<rect x="50" y="{y}" width="{w}" height="{ch}" rx="12" fill="#5d0d13"/>'
                    f'<rect x="50" y="{y}" width="{w}" height="{ch}" rx="12" fill="url(#bevelTop)" opacity="0.5"/>'
                    f'<rect x="51" y="{y+1}" width="{w-2}" height="{ch-2}" rx="11" fill="none" stroke="url(#goldEdge)" stroke-width="1.6"/>'
                    f'<text x="400" y="{y+(31 if big else 25)}" text-anchor="middle" font-family="{SERIF}" font-size="{20 if big else 17}" fill="{CREAM}">{serif_text(txt)}</text>'
                    f'<text x="400" y="{y+(56 if big else 46)}" text-anchor="middle" font-family="{SANS}" font-size="{16 if big else 14}" font-weight="700" fill="#d9ab49">{esc(contact)}</text>')
        y += ch
    return 800, y + 40, "\n".join(body), None

RENDERERS = {"bars": r_bars, "facts": r_facts, "cards": r_cards, "bump": r_bump, "notice": r_notice, "scatter": r_scatter, "radar": r_radar, "stackbars": r_stackbars, "author": r_author, "versus": r_versus, "quote": r_quote, "mulligan": r_mulligan, "line": r_line, "donut": r_donut, "tierlist": r_tierlist,
             "beforeafter": r_beforeafter, "matchup": r_matchup, "badge": r_badge,
             "timeline": r_timeline, "digest": r_digest}

# ---------------------------------------------------------------- main

def font_face_style():
    """Subset HSDisplay (Belwe cyr) to the chars actually used and embed it.

    Works even when the SVG is placed via <img> — data-URI needs no network.
    Silently skipped if fontTools/brotli or the font file are missing.
    """
    if not DISPLAY_CHARS:
        return ""
    fpath = ROOT / "assets" / "fonts" / "HSDisplay.otf"
    if not fpath.exists():
        return ""
    try:
        import io
        from fontTools import subset
    except ImportError:
        return ""
    opts = subset.Options(flavor="woff2")
    font = subset.load_font(str(fpath), opts)
    sub = subset.Subsetter(opts)
    sub.populate(text="".join(DISPLAY_CHARS) + " 0123456789%.,-—")
    sub.subset(font)
    buf = io.BytesIO()
    font.save(buf)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return (f'<style>@font-face{{font-family:"HSDisplay";'
            f'src:url(data:font/woff2;base64,{b64}) format("woff2");}}</style>')

def logo_tag(H):
    p = DU / "site-logo.png.txt"
    png = ROOT / "assets" / "site-logo.png"
    if not p.exists() or not png.exists():
        return ""
    iw, ih = png_size(png)
    lw = min(132, 58 * iw / ih)      # fit the 52-unit bottom band, keep aspect
    lh = lw * ih / iw
    return (f'<image href="{p.read_text().strip()}" x="{754-lw:.0f}" y="{H-26-lh:.0f}" '
            f'width="{lw:.1f}" height="{lh:.1f}"/>')

def anim_style():
    """CSS-анимация появления. Только opacity/transform через animation —
    рендеры без поддержки CSS-анимаций (resvg и т.п.) показывают конечный кадр."""
    delays = "\n".join(f".anim>*:nth-child({i}){{animation-delay:{0.06*i:.2f}s}}"
                        for i in range(2, 41))
    return f"""<style>
@keyframes hs-rise {{from{{opacity:0;transform:translateY(14px)}}to{{opacity:1;transform:none}}}}
@keyframes hs-grow {{from{{transform:scaleX(0)}}to{{transform:none}}}}
.anim>*{{animation:hs-rise .55s cubic-bezier(.2,.7,.3,1) both}}
{delays}
.anim .a-grow{{transform-box:fill-box;transform-origin:left center;animation:hs-grow .9s .25s cubic-bezier(.2,.7,.3,1) both}}
</style>"""

def build(spec):
    global DEDUPE
    DISPLAY_CHARS.clear()
    DEFINED.clear()
    DEDUPE = bool(spec.get("dedupe", False))
    t = spec.get("type")
    if t not in RENDERERS:
        die(f"неизвестный type '{t}'; доступны: {', '.join(RENDERERS)}")
    finish = spec.get("finish", "quiet" if t in ("badge", "digest", "author", "quote", "facts", "notice") else "parade")
    W, H, content, scale_note = RENDERERS[t](spec)
    if t == "badge":
        return doc(W, H, spec.get("title", "Бейдж"), font_face_style() + "\n" + content)
    logo = ""
    if spec.get("logo", t != "author"):
        H += 52                     # bottom band for the site logo
        logo = logo_tag(H)
    if spec.get("animate"):
        content = f'<g class="anim">{content}</g>'
    fmt = spec.get("format", "wide")
    if fmt in ("square", "story"):
        target = 800 if fmt == "square" else 1422      # 1:1 / 9:16 при ширине 800
        pad = target - H
        if pad < 0:
            die(f"{fmt}: контент выше формата ({H} > {target}) — сократи данные")
        if pad > H * 0.6:
            die(f"{fmt}: контент слишком низкий для формата (пустых полей {pad}) — возьми больше строк или другой тип")
        content = f'<g transform="translate(0 {pad/2:.0f})">{content}</g>'
        H = target
        logo = logo_tag(H) if logo else ""
    tb, _ = ("", 96) if t in ("author", "quote") else title_block(spec)
    body = "\n".join([font_face_style(), frame(H, spec.get("frame", "vector"), finish),
                      tb, content, footer(spec, H, scale_note or ""), logo,
                      anim_style() if spec.get("animate") else ""])
    return doc(W, H, spec.get("title", "График"), body)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", help="path to JSON spec, or '-' to read the spec from stdin")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    raw = sys.stdin.read() if a.spec == "-" else pathlib.Path(a.spec).read_text(encoding="utf-8")
    spec = json.loads(raw)
    svg = build(spec)
    pathlib.Path(a.out).write_text(svg, encoding="utf-8")
    print(f"{a.out}: {len(svg.encode())/1024:.0f} KB")

if __name__ == "__main__":
    main()
