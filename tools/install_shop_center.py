#!/usr/bin/env python3
"""Centre the shop's buy-confirm backdrop on the 853-wide canvas.

The buy dialog is not a Window at all: Scene_Shop shows a 364x230 sprite
`@backbuy` (Graphics/Pictures/输入.png) as the backdrop, with the number
and yes/no windows drawn on top of it. The sprite is positioned with

    @backbuy.x = 320 - 364 / 2      # = 138, centre 320

which is hard-coded to the original 640-wide canvas. Nothing rescales it,
because the picture is smaller than a full screen and mkxp_compat only
stretches 640x480 art. Meanwhile the number / command windows DO get the
1.333 horizontal remap, so their text ends up centred on 426 while the
backdrop stays at 138..502 -- the dialog looks shifted left by ~106px.

Rewrite that one expression to centre on Graphics.width instead. The y
coordinate needs no change (the vertical canvas is still 480).

Idempotent: the replacement marker is checked before writing.
"""
import zlib
from pathlib import Path

from rubymarshal.reader import loads
from rubymarshal.writer import writes

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "tianjiang_game" / "Data" / "Scripts.rxdata"

OLD = b"@backbuy.x = 320-364 / 2"
NEW = b"@backbuy.x = (Graphics.width - 364) / 2"

# 360 is a second copy of the same layout in some shop variants
OLD_VARIANTS = [
    (b"@backbuy.x = 320-364 / 2", b"@backbuy.x = (Graphics.width - 364) / 2"),
    (b"@backbuy.x=320-364 / 2", b"@backbuy.x=(Graphics.width - 364) / 2"),
    (b"@backbuy.x = 320 - 364 / 2", b"@backbuy.x = (Graphics.width - 364) / 2"),
    (b"@backbuy.x=320 - 364 / 2", b"@backbuy.x=(Graphics.width - 364) / 2"),
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
        for old, rep in OLD_VARIANTS:
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
        print("  nothing to patch (already centred?)")
        return
    SCRIPTS.write_bytes(writes(data))

    # 验证：重新读一遍，确认表达式已写入且旧写法消失
    check = loads(SCRIPTS.read_bytes())
    hits = 0
    for entry in check:
        body = zlib.decompress(entry[2])
        if b"(Graphics.width - 364) / 2" in body:
            hits += 1
        assert b"@backbuy.x = 320-364 / 2" not in body, "old expression survived"
    assert hits >= 1, "centred expression not found after write"
    print(f"  verify OK: {hits} shop script(s) centred, {SCRIPTS.stat().st_size} bytes")


if __name__ == "__main__":
    main()
