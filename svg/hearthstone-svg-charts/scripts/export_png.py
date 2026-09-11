#!/usr/bin/env python3
"""Export chart SVG to PNG (transparent background preserved) via resvg.

Usage:
    python3 scripts/export_png.py chart.svg            # chart.png, 2x
    python3 scripts/export_png.py chart.svg -z 3       # 3x for retina/print

Needs resvg (brew install resvg). Renders with system fonts: Cinzel falls back
to Georgia — check the PNG before publishing.
"""
import argparse
import pathlib
import shutil
import subprocess
import sys
import tempfile

DU = pathlib.Path(__file__).resolve().parent.parent / "assets" / "datauri"

def webp_to_png_twins(svg_text):
    """resvg can't decode webp — swap known webp data-URIs for their PNG twins."""
    for twin in DU.glob("*.webp.pngtwin.txt"):
        orig = DU / twin.name.replace(".pngtwin", "")
        if not orig.exists():
            continue
        webp_uri = orig.read_text().strip()
        if webp_uri in svg_text:
            svg_text = svg_text.replace(webp_uri, twin.read_text().strip())
    return svg_text

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("svg", nargs="+")
    ap.add_argument("-z", "--zoom", type=float, default=2.0)
    ap.add_argument("--no-quant", action="store_true", help="не сжимать pngquant")
    a = ap.parse_args()
    if not shutil.which("resvg"):
        sys.exit("resvg не найден: brew install resvg")
    for s in a.svg:
        src = pathlib.Path(s)
        out = src.with_suffix(".png")
        text = src.read_text(encoding="utf-8")
        swapped = webp_to_png_twins(text)
        render_src = src
        if swapped != text:
            tmp = pathlib.Path(tempfile.mkstemp(suffix=".svg")[1])
            tmp.write_text(swapped, encoding="utf-8")
            render_src = tmp
        cmd = ["resvg", "--zoom", str(a.zoom)]
        hs_font = DU.parent / "fonts" / "HSDisplay.otf"
        if hs_font.exists():
            cmd += ["--use-font-file", str(hs_font)]
        subprocess.run(cmd + [str(render_src), str(out)], check=True)
        if not a.no_quant and shutil.which("pngquant"):
            # палитра 256 цветов на пергаменте не видна, а вес падает в 3-4 раза
            subprocess.run(["pngquant", "--force", "--quality", "70-92", "--speed", "1",
                            "--output", str(out), str(out)], check=False)
        print(f"{out} ({out.stat().st_size/1024:.0f} KB)")

if __name__ == "__main__":
    main()
