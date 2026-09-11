#!/usr/bin/env python3
"""Build an HTML page that shows chart SVGs on light/dark checkerboards.

Usage: python3 scripts/checkerboard.py out.html chart1.svg [chart2.svg ...]

Open out.html in a browser and screenshot it. Verify:
  1. checkerboard is visible OUTSIDE the frame on both backgrounds (transparency),
  2. no text overlaps or clipping,
  3. the 360px column stays readable (article mobile width).
"""
import pathlib
import sys

TPL = """<!doctype html><meta charset="utf-8">
<style>
body {{ margin:0; font:13px sans-serif; }}
.board {{ padding:24px; display:flex; gap:24px; align-items:flex-start; flex-wrap:wrap; }}
.light {{ background:
  repeating-conic-gradient(#e8e8e8 0% 25%, #ffffff 0% 50%) 0 0/24px 24px; }}
.dark {{ background:
  repeating-conic-gradient(#20242c 0% 25%, #2c313b 0% 50%) 0 0/24px 24px; }}
.dark h2 {{ color:#eee; }}
figure {{ margin:0; }}
figcaption {{ margin:4px 0; opacity:0.7; }}
.dark figcaption {{ color:#eee; }}
.w720 svg {{ width:720px; }}
.w360 svg {{ width:360px; }}
</style>
{sections}
"""

SECTION = """<div class="board {cls}"><h2 style="width:100%;margin:0">{label}</h2>
{figures}</div>
"""

FIG = """<figure class="{wcls}"><figcaption>{name} @ {wpx}px</figcaption>{svg}</figure>
"""


def main() -> None:
    out, svgs = sys.argv[1], sys.argv[2:]
    sections = []
    for cls, label in (("light", "Светлая статья"), ("dark", "Тёмная статья")):
        figs = []
        for s in svgs:
            code = pathlib.Path(s).read_text(encoding="utf-8")
            name = pathlib.Path(s).name
            figs.append(FIG.format(wcls="w720", name=name, wpx=720, svg=code))
            figs.append(FIG.format(wcls="w360", name=name, wpx=360, svg=code))
        sections.append(SECTION.format(cls=cls, label=label, figures="".join(figs)))
    pathlib.Path(out).write_text(TPL.format(sections="".join(sections)), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
