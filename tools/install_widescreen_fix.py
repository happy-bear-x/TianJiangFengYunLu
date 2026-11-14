#!/usr/bin/env python3
"""Widescreen fixes for the 853x480 canvas.

Two classes of bug appear once the canvas is wider than the original 640x480:

1. Sprite_Picture#update resets zoom_x every frame from @picture.zoom_x,
   overwriting any scaling set in Sprite#bitmap=. Full-screen cutscene
   frames (Graphics/KC, Endflash, TrueEnd -- all 640x480) therefore still
   occupy only 640 of the 853 columns and leave a black band on the right.
   Scale those sprites horizontally, and map their x into the wider frame.

2. Camera bounds are hard-coded for a 20x15 tile view. With a 26.7-tile
   wide view the player can scroll past the right map edge and expose empty
   space. Game_Player#center and Game_Map#scroll_* must derive their limits
   from Graphics.width/height instead.

Works line-by-line (prefix match) so CRLF is preserved. Idempotent.
"""
import shutil
import zlib

from rubymarshal.reader import loads
from rubymarshal.writer import writes

from paths import GAME

SCRIPTS = GAME / "Data" / "Scripts.rxdata"

# (script name fragment, list of (line prefix, replacement lines))
PATCHES = [
    (
        "Sprite_Picture",
        [
            (
                "self.tone = @picture.tone",
                [
                    "    self.tone = @picture.tone",
                    "    # Widescreen: update() resets zoom_x every frame, so",
                    "    # full-screen artwork must be scaled here, not in bitmap=.",
                    "    if self.bitmap != nil and self.bitmap.width == 640 and",
                    "       self.bitmap.height == 480 and Graphics.width != 640",
                    "      factor = Graphics.width.to_f / 640.0",
                    "      self.zoom_x *= factor",
                    "      self.x = (self.x * factor).to_i",
                    "    end",
                ],
            ),
        ],
    ),
    (
        "Game_Player",
        [
            (
                "CENTER_X = (320 - 16) * 4",
                ["  CENTER_X = (Graphics.width / 2 - 16) * 4   # widescreen"],
            ),
            (
                "CENTER_Y = (240 - 16) * 4",
                ["  CENTER_Y = (Graphics.height / 2 - 16) * 4   # widescreen"],
            ),
            (
                "max_x = ($game_map.width - 20) * 128",
                [
                    "    # Camera clamp: never scroll past a map edge.",
                    "    # 4 display units per pixel, 32 pixels per tile.",
                    "    max_x = ($game_map.width * 32 - Graphics.width) * 4",
                ],
            ),
            (
                "max_y = ($game_map.height - 15) * 128",
                ["    max_y = ($game_map.height * 32 - Graphics.height) * 4"],
            ),
        ],
    ),
    (
        "Game_Map",
        [
            (
                "@display_y = [@display_y + distance, (self.height - 15) * 128].min",
                [
                    "    @display_y = [@display_y + distance,",
                    "                  (self.height * 32 - Graphics.height) * 4].min",
                ],
            ),
            (
                "@display_x = [@display_x + distance, (self.width - 20) * 128].min",
                [
                    "    @display_x = [@display_x + distance,",
                    "                  (self.width * 32 - Graphics.width) * 4].min",
                ],
            ),
        ],
    ),
]


def main():
    data = loads(SCRIPTS.read_bytes())
    gp = next(e for e in data if "Game_Player" in e[1].decode("utf-8", "replace"))
    if b"Camera clamp" in zlib.decompress(gp[2]):
        print("already patched, nothing to do")
    else:
        total = 0
        for frag, rules in PATCHES:
            matches = [e for e in data if frag in e[1].decode("utf-8", "replace")]
            assert len(matches) == 1, f"{frag}: expected 1 script, got {len(matches)}"
            e = matches[0]
            code = zlib.decompress(e[2])
            eol = b"\r\n" if b"\r\n" in code else b"\n"
            lines = code.split(eol)
            hits = {prefix: 0 for prefix, _ in rules}
            out = []
            for line in lines:
                key = line.strip().decode("utf-8", "replace")
                matched = None
                for prefix, new_lines in rules:
                    if key.startswith(prefix):
                        matched = (prefix, new_lines)
                        break
                if matched:
                    prefix, new_lines = matched
                    out.extend(n.encode("utf-8") for n in new_lines)
                    hits[prefix] += 1
                else:
                    out.append(line)
            for prefix, n in hits.items():
                assert n == 1, f"{frag}: {prefix!r} matched {n} times"
            e[2] = zlib.compress(eol.join(out), 9)
            total += sum(hits.values())
            print(f"  patched {frag}: {len(rules)} sites")
        backup = SCRIPTS.with_suffix(".rxdata.bak-widescreen2")
        if not backup.exists():
            shutil.copy2(SCRIPTS, backup)
        SCRIPTS.write_bytes(writes(data))
        print("total patched sites:", total)

    check = loads(SCRIPTS.read_bytes())
    assert len(check) == 209
    for frag, _ in PATCHES:
        e = next(x for x in check if frag in x[1].decode("utf-8", "replace"))
        src = zlib.decompress(e[2]).decode("utf-8", "replace")
        assert "Graphics.width" in src or "Graphics.height" in src, frag
        print("  verify OK:", frag)
    print("size:", SCRIPTS.stat().st_size)


if __name__ == "__main__":
    main()
