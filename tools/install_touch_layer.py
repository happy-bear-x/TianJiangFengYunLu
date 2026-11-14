#!/usr/bin/env python3
"""Install the unified touch layer into Data/Scripts.rxdata.

Two idempotent changes:

1. Insert a "TJ_TouchLayer" script immediately BEFORE "Main". It translates
   SDL mouse taps into RGSS virtual keys and hit-tests selectable windows.
   Two ordering constraints apply: the game-defined Window_Base does not
   exist during preload, and Main contains the blocking `while $scene != nil`
   loop, so anything after Main is dead code.

2. Patch Game_Player#update to read Input.dir8 instead of Input.dir4 and
   dispatch the four diagonals to tj_slide_move (defined in the injected
   touch layer). Input.dir4 only ever returns ONE orthogonal direction when
   two adjacent arrow keys are held; Input.dir8 returns 1/3/7/9. The native
   diagonal methods refuse to move unless BOTH components are passable, so
   tj_slide_move falls back to a wall-slide (horizontal first, then
   vertical) when the true diagonal is blocked.
"""
import shutil
import zlib
from pathlib import Path

from rubymarshal.reader import loads
from rubymarshal.writer import writes

from paths import GAME

SCRIPTS = GAME / "Data" / "Scripts.rxdata"
SOURCE = Path(__file__).with_name("tianjiang_touch_layer.rb")
SCRIPT_NAME = "TJ_TouchLayer"

# Replacement for the single "case Input.dir4" line in 023_Game_Player.rb.
# The existing when 2/4/6/8 branches stay in place; case order is irrelevant.
DIAG_LINES = [
    "      case Input.dir8",
    "      when 1",
    "        tj_slide_move(1, 4, 2)",
    "      when 3",
    "        tj_slide_move(3, 6, 2)",
    "      when 7",
    "        tj_slide_move(7, 4, 8)",
    "      when 9",
    "        tj_slide_move(9, 6, 8)",
]


def _script_name(entry):
    # rubymarshal returns bytes for the original entries and a RubyString
    # (proxying .text) for entries we wrote ourselves as a Python str.
    n = entry[1]
    if isinstance(n, bytes):
        return n.decode("utf-8", "replace")
    if hasattr(n, "text"):
        return str(n.text)
    return str(n)


def patch_diagonal(data):
    matches = [e for e in data if "Game_Player" in _script_name(e)]
    assert len(matches) == 1, f"Game_Player: expected 1 script, got {len(matches)}"
    e = matches[0]
    code = zlib.decompress(e[2])
    eol = b"\r\n" if b"\r\n" in code else b"\n"
    lines = code.split(eol)
    if any(b"case Input.dir8" in line for line in lines):
        print("  diagonal: already patched")
        return False

    out, hits = [], 0
    for line in lines:
        if line.strip() == b"case Input.dir4":
            out.extend(x.encode("utf-8") for x in DIAG_LINES)
            hits += 1
        else:
            out.append(line)
    assert hits == 1, f"case Input.dir4 matched {hits} times"
    e[2] = zlib.compress(eol.join(out), 9)
    print("  diagonal: Game_Player now reads Input.dir8 with 4-way diagonals")
    return True


def inject_layer(data):
    src = SOURCE.read_bytes().replace(b"\r\n", b"\n")

    # Remove any previous copy first, keeping the install idempotent.
    script_id = None
    for i, e in enumerate(data):
        if _script_name(e) == SCRIPT_NAME:
            script_id = e[0]
            del data[i]
            break
    if script_id is None:
        script_id = max(e[0] for e in data) + 1

    # Main contains `while $scene != nil; $scene.main; end` and blocks
    # forever. mkxp-z evals scripts in order, so anything after Main is
    # dead code. The touch layer MUST be inserted before it.
    main_idx = next((i for i, e in enumerate(data)
                     if _script_name(e) == "Main"), None)
    assert main_idx is not None, "could not find the Main script"
    data.insert(main_idx, [script_id, SCRIPT_NAME, zlib.compress(src, 9)])
    print(f"  touch layer: installed at #{main_idx + 1} "
          f"(before Main, id {script_id})")
    return True


def main():
    data = loads(SCRIPTS.read_bytes())
    before = len(data)
    backup = SCRIPTS.with_suffix(".rxdata.bak-touch")
    if not backup.exists():
        shutil.copy2(SCRIPTS, backup)

    changed = patch_diagonal(data) | inject_layer(data)
    if changed:
        SCRIPTS.write_bytes(writes(data))

    check = loads(SCRIPTS.read_bytes())
    hits = [i for i, x in enumerate(check) if _script_name(x) == SCRIPT_NAME]
    assert len(hits) == 1, f"expected one touch layer, got {len(hits)}"
    main_idx = next(i for i, x in enumerate(check) if _script_name(x) == "Main")
    assert hits[0] < main_idx, "touch layer must run BEFORE Main"
    body = zlib.decompress(check[hits[0]][2])
    assert b"module TJTouch" in body and b"Input.mouse_x" in body
    assert b"tj_slide_move" in body, "touch layer must define tj_slide_move"
    gp = next(x for x in check if "Game_Player" in _script_name(x))
    gp_src = zlib.decompress(gp[2])
    assert b"case Input.dir8" in gp_src
    assert b"tj_slide_move" in gp_src
    print(f"  verify OK: {before} -> {len(check)} scripts, "
          f"touch layer #{hits[0] + 1} < Main #{main_idx + 1}, "
          f"{SCRIPTS.stat().st_size} bytes")


if __name__ == "__main__":
    main()
