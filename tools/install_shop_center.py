#!/usr/bin/env python3
"""Fit the shop's buy-confirm backdrop to the wide canvas.

The buy dialog is not a Window: Scene_Shop shows a 364x230 sprite
`@backbuy` (Graphics/Pictures/输入.png) as the backdrop art, with the
number and yes/no windows painted on top of it.

Two problems, in order of discovery:

1. Position. It was hard-coded at `320 - 364/2` = 138, i.e. centred on
   the old 640 canvas. Nothing moved it, so the backdrop stayed left
   while the text (which does get the 1.333 remap) centred on 426.

2. Width. mkxp_compat only stretches full-screen 640x480 art, and this
   picture is smaller than a screen, so it kept its original 364px width
   while the windows above it were rescaled to 490px. The text spread
   wider than the frame around it.

So the sprite must be *scaled* horizontally exactly like the background
art (zoom_x = Graphics.width / 640) and then centred on its scaled
width. Vertical stays 1:1 because the canvas height is still 480.

Idempotent: recognises both the original expression and the
x-only-centring version written by the previous revision.
"""
import zlib
from pathlib import Path

from rubymarshal.reader import loads
from rubymarshal.writer import writes

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "tianjiang_game" / "Data" / "Scripts.rxdata"

MARK = b"@backbuy.zoom_x = Graphics.width / 640.0"

_CENTER = (b"@backbuy.zoom_x = Graphics.width / 640.0\n"
           b"    @backbuy.x = (Graphics.width - 364 * @backbuy.zoom_x) / 2")

# (old, replacement) — several spellings appear across the shop variants
REWRITES = [
    # v1 of this patch: centred but not scaled
    (b"@backbuy.x = (Graphics.width - 364) / 2", _CENTER),
    # original 640-canvas centring
    (b"@backbuy.x = 320-364 / 2", _CENTER),
    (b"@backbuy.x=320-364 / 2",
     b"@backbuy.zoom_x = Graphics.width / 640.0\n"
     b"    @backbuy.x=(Graphics.width - 364 * @backbuy.zoom_x) / 2"),
    (b"@backbuy.x = 320 - 364 / 2", _CENTER),
    (b"@backbuy.x=320 - 364 / 2",
     b"@backbuy.zoom_x = Graphics.width / 640.0\n"
     b"    @backbuy.x=(Graphics.width - 364 * @backbuy.zoom_x) / 2"),
]


def _name(entry):
    n = entry[1]
    if isinstance(n, bytes):
        return n.decode("utf-8", "replace")
    return getattr(n, "text", None) or str(n)


def patch(data):
    changed = 0
    for entry in data:
        name = _name(entry)
        if "Shop" not in name and "shop" not in name:
            continue
        body = zlib.decompress(entry[2])
        new = body
        for old, rep in REWRITES:
            if old in new:
                new = new.replace(old, rep)
        if new != body:
            entry[2] = zlib.compress(new, 9)
            changed += 1
            print(f"  patched {name} ({len(body)} -> {len(new)} bytes)")
    return changed


def main():
    data = loads(SCRIPTS.read_bytes())
    n = patch(data)
    if n == 0:
        print("  nothing to patch (already scaled?)")
        return
    SCRIPTS.write_bytes(writes(data))

    check = loads(SCRIPTS.read_bytes())
    hits = 0
    for entry in check:
        body = zlib.decompress(entry[2])
        if MARK in body:
            hits += 1
        assert b"@backbuy.x = 320-364 / 2" not in body, "old expression survived"
        assert b"@backbuy.x = (Graphics.width - 364) / 2" not in body, \
            "x-only centring survived"
    assert hits >= 1, "scaled expression not found after write"
    print(f"  verify OK: {hits} shop script(s) scaled, {SCRIPTS.stat().st_size} bytes")


if __name__ == "__main__":
    main()
