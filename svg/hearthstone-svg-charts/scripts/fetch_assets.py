#!/usr/bin/env python3
"""Download HS-Arena (HeartPulse) assets and build base64 data-URI versions.

Run once when installing the skill (network required):
    python3 scripts/fetch_assets.py

Download a Battlegrounds hero portrait on demand (114 exist, not bundled):
    python3 scripts/fetch_assets.py --bg-hero "Alexstrasza"
    (English name as on arena.hs-manacost.ru/bg-legacy/heroes_bg/)

Creates:
    assets/<name>             - original files
    assets/datauri/<name>.txt - ready-to-paste data URIs (webp converted to PNG
                                first via sips, so resvg PNG export works)
    assets/manifest.json      - name -> {file, datauri_file, bytes, mime}
"""
import argparse
import base64
import json
import pathlib
import subprocess
import urllib.parse
import urllib.request

BASE = "https://arena.hs-manacost.ru"
ASSETS_DIR = pathlib.Path(__file__).resolve().parent.parent / "assets"
DATAURI_DIR = ASSETS_DIR / "datauri"

FILES = {
    # frames & textures
    "deck-border.png": "/wallpaper/deck-border.png",
    "main-page-rail-border.png": "/wallpaper/main-page-rail-border.png",
    "arena-parchment.jpg": "/wallpaper/arena-parchment.jpg",
    # small game assets
    "mana.png": "/assets/mana.png",
    # rarity gems
    "rarity-common.png": "/assets/common.png",
    "rarity-rare.png": "/assets/rare.png",
    "rarity-epic.png": "/assets/epic.png",
    "rarity-legendary.png": "/assets/legendary.png",
    # class icons, 64px webp
    "class-deathknight.webp": "/class_icon/ui/deathknight-64.webp",
    "class-demonhunter.webp": "/class_icon/ui/demonhunter-64.webp",
    "class-druid.webp": "/class_icon/ui/druid-64.webp",
    "class-hunter.webp": "/class_icon/ui/hunter-64.webp",
    "class-mage.webp": "/class_icon/ui/mage-64.webp",
    "class-paladin.webp": "/class_icon/ui/paladin-64.webp",
    "class-priest.webp": "/class_icon/ui/priest-64.webp",
    "class-rogue.webp": "/class_icon/ui/rogue-64.webp",
    "class-shaman.webp": "/class_icon/ui/shaman-64.webp",
    "class-warlock.webp": "/class_icon/ui/warlock-64.webp",
    "class-warrior.webp": "/class_icon/ui/warrior-64.webp",
    # Battlegrounds tavern tier badges
    "bg-tier1.png": "/bg-legacy/assset/tier1.png",
    "bg-tier2.png": "/bg-legacy/assset/tier2.png",
    "bg-tier3.png": "/bg-legacy/assset/tier3.png",
    "bg-tier4.png": "/bg-legacy/assset/tier4.png",
    "bg-tier5.png": "/bg-legacy/assset/tier5.png",
    "bg-tier6.png": "/bg-legacy/assset/tier6.png",
    "bg-tier7.png": "/bg-legacy/assset/tier7.png",
    # Battlegrounds tribe/type icons (Cyrillic source names)
    "tribe-demons.webp": "/bg-legacy/assset/демоны.webp",
    "tribe-dragons.webp": "/bg-legacy/assset/драконы.webp",
    "tribe-duo.webp": "/bg-legacy/assset/дуо.webp",
    "tribe-beasts.webp": "/bg-legacy/assset/зверь.webp",
    "tribe-mechs.webp": "/bg-legacy/assset/механизмы.webp",
    "tribe-murlocs.webp": "/bg-legacy/assset/мурлоки.webp",
    "tribe-nagas.webp": "/bg-legacy/assset/наги.webp",
    "tribe-undead.webp": "/bg-legacy/assset/нежить.webp",
    "tribe-all.webp": "/bg-legacy/assset/общее.webp",
    "tribe-pirates.webp": "/bg-legacy/assset/пираты.webp",
    "tribe-quilboar.webp": "/bg-legacy/assset/свинобразы.webp",
    "tribe-elementals.webp": "/bg-legacy/assset/элементали.webp",
}

MIME = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp", ".svg": "image/svg+xml"}


def fetch(url: str, dest: pathlib.Path) -> None:
    url = urllib.parse.quote(url, safe=":/%")
    print(f"fetch {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        dest.write_bytes(r.read())


def webp_to_png(src: pathlib.Path) -> pathlib.Path:
    """resvg (PNG export) can't decode webp — keep a PNG twin for data URIs."""
    png = src.with_suffix(".png")
    if not png.exists():
        subprocess.run(["sips", "-s", "format", "png", str(src), "--out", str(png)],
                       check=True, capture_output=True)
    return png


def datauri_for(path: pathlib.Path) -> tuple[pathlib.Path, str]:
    data = path.read_bytes()
    uri = f"data:{MIME[path.suffix]};base64,{base64.b64encode(data).decode()}"
    uri_file = DATAURI_DIR / (path.name + ".txt")
    uri_file.write_text(uri)
    if path.suffix == ".webp":
        # PNG twin: export_png.py swaps it in — resvg can't decode webp,
        # but browsers can, so the SVG itself keeps the 4x smaller webp
        png = webp_to_png(path)
        png_uri = f"data:image/png;base64,{base64.b64encode(png.read_bytes()).decode()}"
        (DATAURI_DIR / (path.name + ".pngtwin.txt")).write_text(png_uri)
    return uri_file, MIME[path.suffix]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bg-hero", help='download one BG hero portrait by English name, e.g. "Alexstrasza"')
    args = ap.parse_args()

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    DATAURI_DIR.mkdir(parents=True, exist_ok=True)

    if args.bg_hero:
        name = args.bg_hero
        dest = ASSETS_DIR / f"bg-hero-{name.replace(' ', '_')}.png"
        if not dest.exists():
            fetch(f"{BASE}/bg-legacy/heroes_bg/{name}.png", dest)
        uri_file, _ = datauri_for(dest)
        print(f"ok: {dest.name} ({dest.stat().st_size/1024:.0f} KB) -> {uri_file}")
        return

    manifest = {}
    for name, path in FILES.items():
        dest = ASSETS_DIR / name
        if not dest.exists():
            fetch(BASE + path, dest)
        uri_file, mime = datauri_for(dest)
        manifest[name] = {
            "file": str(dest.relative_to(ASSETS_DIR.parent)),
            "datauri_file": str(uri_file.relative_to(ASSETS_DIR.parent)),
            "bytes": dest.stat().st_size,
            "mime": mime,
        }
    (ASSETS_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"done: {len(manifest)} assets -> {ASSETS_DIR}")


if __name__ == "__main__":
    main()
