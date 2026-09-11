#!/usr/bin/env python3
"""Generate a 9-slice SVG <g> block for a frame asset with transparent center.

Corners stay undistorted, edges stretch. Output goes to stdout — paste it
into the SVG after the parchment rect.

Usage:
    python3 scripts/frame9.py main-page-rail-border.png --x 6 --y 6 --w 788 --h 438 --corner 45
    python3 scripts/frame9.py deck-border.png --x 40 --y 30 --w 720 --h 60 --corner 16
"""
import argparse
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def png_size(path: pathlib.Path) -> tuple[int, int]:
    d = path.read_bytes()
    if d[:8] != b"\x89PNG\r\n\x1a\n":
        sys.exit(f"{path} is not a PNG (9-slice needs PNG frames)")
    return struct.unpack(">II", d[16:24])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("asset", help="file name inside assets/, e.g. main-page-rail-border.png")
    p.add_argument("--x", type=float, required=True, help="frame left in viewBox units")
    p.add_argument("--y", type=float, required=True)
    p.add_argument("--w", type=float, required=True, help="frame width in viewBox units")
    p.add_argument("--h", type=float, required=True)
    p.add_argument("--corner", type=float, required=True,
                   help="corner size in SOURCE pixels (also used as output corner size)")
    a = p.parse_args()

    asset = ROOT / "assets" / a.asset
    uri_file = ROOT / "assets" / "datauri" / (a.asset + ".txt")
    if not uri_file.exists():
        sys.exit(f"{uri_file} missing — run scripts/fetch_assets.py first")
    uri = uri_file.read_text().strip()
    iw, ih = png_size(asset)
    c = a.corner
    if c * 2 >= min(iw, ih) or c * 2 >= min(a.w, a.h):
        sys.exit("corner too large for asset or target size")

    # (dest x, y, w, h, src x, y, w, h)
    regions = [
        (a.x,               a.y,               c,             c,             0,      0,      c,          c),
        (a.x + c,           a.y,               a.w - 2 * c,   c,             c,      0,      iw - 2 * c, c),
        (a.x + a.w - c,     a.y,               c,             c,             iw - c, 0,      c,          c),
        (a.x,               a.y + c,           c,             a.h - 2 * c,   0,      c,      c,          ih - 2 * c),
        (a.x + a.w - c,     a.y + c,           c,             a.h - 2 * c,   iw - c, c,      c,          ih - 2 * c),
        (a.x,               a.y + a.h - c,     c,             c,             0,      ih - c, c,          c),
        (a.x + c,           a.y + a.h - c,     a.w - 2 * c,   c,             c,      ih - c, iw - 2 * c, c),
        (a.x + a.w - c,     a.y + a.h - c,     c,             c,             iw - c, ih - c, c,          c),
    ]

    img_id = "f9-" + a.asset.split(".")[0]
    print(f'<g><!-- 9-slice {a.asset} -->')
    print(f'<defs><image id="{img_id}" href="{uri}" width="{iw}" height="{ih}"/></defs>')
    for dx, dy, dw, dh, sx, sy, sw, sh in regions:
        print(f'<svg x="{dx:g}" y="{dy:g}" width="{dw:g}" height="{dh:g}" '
              f'viewBox="{sx:g} {sy:g} {sw:g} {sh:g}" preserveAspectRatio="none" '
              f'overflow="hidden"><use href="#{img_id}"/></svg>')
    print('</g>')


if __name__ == "__main__":
    main()
