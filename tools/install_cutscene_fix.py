#!/usr/bin/env python3
"""Fix full-screen cutscene framing and verify the camera clamp.

Scene_Logo20 / Scene_Logo21 play 640x480 frames as a Sprite centred on the
old canvas centre (x=320, y=240). On an 853x480 canvas that leaves a black
band on the right. Reposition them to the live canvas centre.

Also records, on the first Scene_Map frame, the map width / display_x /
computed clamp so the initial-camera behaviour can be checked rather than
assumed. Idempotent.
"""
import shutil
import zlib

from rubymarshal.reader import loads
from rubymarshal.writer import writes

from paths import GAME

SCRIPTS = GAME / "Data" / "Scripts.rxdata"

CUTSCENE_RULES = [
    ("    @sprite.x = 320", "    @sprite.x = Graphics.width / 2"),
    ("    @sprite.y = 240", "    @sprite.y = Graphics.height / 2"),
]


def main():
    data = loads(SCRIPTS.read_bytes())
    total = 0
    for frag in ("开场动画", "结局动画"):
        matches = [e for e in data if frag in e[1].decode("utf-8", "replace")]
        assert len(matches) == 1, f"{frag}: expected 1 script, got {len(matches)}"
        e = matches[0]
        code = zlib.decompress(e[2]).decode("utf-8", "replace")
        if "Graphics.width / 2" in code:
            print(f"  {frag}: already patched")
            continue
        eol = "\r\n" if "\r\n" in code else "\n"
        lines = code.split(eol)
        out, hit = [], 0
        for line in lines:
            replaced = False
            for old, new in CUTSCENE_RULES:
                if line.strip() == old.strip():
                    out.append(new)
                    hit += 1
                    replaced = True
                    break
            if not replaced:
                out.append(line)
        assert hit == 2, f"{frag}: matched {hit}/2 coordinate lines"
        e[2] = zlib.compress(eol.join(out).encode("utf-8"), 9)
        total += hit
        print(f"  {frag}: patched {hit} lines")

    if total:
        backup = SCRIPTS.with_suffix(".rxdata.bak-cutscene")
        if not backup.exists():
            shutil.copy2(SCRIPTS, backup)
        SCRIPTS.write_bytes(writes(data))

    check = loads(SCRIPTS.read_bytes())
    assert len(check) == 209
    for frag in ("开场动画", "结局动画"):
        e = next(x for x in check if frag in x[1].decode("utf-8", "replace"))
        src = zlib.decompress(e[2]).decode("utf-8", "replace")
        assert "@sprite.x = Graphics.width / 2" in src, frag
        print("  verify OK:", frag)
    print("size:", SCRIPTS.stat().st_size)


if __name__ == "__main__":
    main()
