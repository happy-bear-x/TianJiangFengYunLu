#!/usr/bin/env python3
"""Fix the small-map camera jump by rewriting the scripts in place.

Why not reopen the classes in a separate script? A class reopen placed just
before Main did not take effect on device -- the game kept the original
scroll_* behaviour. Editing the original method bodies is unambiguous, so
that is what this script does.

Problem: the widescreen canvas is 853x480, but 85 of 183 maps are the stock
20x15 (640px wide). Game_Map#scroll_right clamps with
`(width * 32 - Graphics.width) * 4`, which is NEGATIVE for such maps, so
@display_x is pushed to -852 and the whole picture shifts right with a black
band on the left; scroll_left then drags it back to 0. Walking across a room
makes the view jump between those two positions.

Fix: every scroll_* and Game_Player#center now go through tj_clamp_x/y,
which pins a too-small map at dead centre (never scrolls) and keeps the
original [0, free] clamp for maps wider than the screen.

Idempotent: skips when `tj_clamp_x` is already present, and removes the
earlier TJ_MapCamera entry if one was installed.
"""
import shutil
import zlib
from pathlib import Path

from rubymarshal.reader import loads
from rubymarshal.writer import writes

from paths import GAME

SCRIPTS = GAME / "Data" / "Scripts.rxdata"
STALE_SCRIPT = "TJ_MapCamera"

HELPERS = [
    "  # TJ: 窄地图摄像机居中锁定（画布比地图宽时不再乱滚）",
    "  def tj_free_w",
    "    (width * 32 - Graphics.width) * 4",
    "  end",
    "",
    "  def tj_free_h",
    "    (height * 32 - Graphics.height) * 4",
    "  end",
    "",
    "  def tj_clamp_x(value)",
    "    fw = tj_free_w",
    "    return fw / 2 if fw <= 0",
    "    return 0 if value < 0",
    "    return fw if value > fw",
    "    value",
    "  end",
    "",
    "  def tj_clamp_y(value)",
    "    fh = tj_free_h",
    "    return fh / 2 if fh <= 0",
    "    return 0 if value < 0",
    "    return fh if value > fh",
    "    value",
    "  end",
]


def _script_name(entry):
    n = entry[1]
    if isinstance(n, bytes):
        return n.decode("utf-8", "replace")
    if hasattr(n, "text"):
        return str(n.text)
    return str(n)


def _entry(data, name):
    m = [e for e in data if _script_name(e).strip() == name]
    assert len(m) == 1, f"{name}: expected 1 script, got {len(m)}"
    return m[0]


def patch_map(data):
    e = _entry(data, "Game_Map")
    code = zlib.decompress(e[2])
    if b"tj_clamp_x" in code:
        print("  Game_Map: already patched")
        return False

    eol = b"\r\n" if b"\r\n" in code else b"\n"
    lines = code.split(eol)
    out, done, i = [], set(), 0

    while i < len(lines):
        s = lines[i].strip().decode("utf-8", "replace")
        indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())].decode("utf-8", "replace")

        if s == "def scroll_down(distance)":
            out.extend(h.encode("utf-8") for h in HELPERS)
            out.append(lines[i])
            done.add("helpers")
            i += 1
            continue
        if s == "@display_y = [@display_y + distance,":
            out.append(f"{indent}@display_y = tj_clamp_y(@display_y + distance)".encode("utf-8"))
            done.add("down")
            i += 2          # the wrapped `(self.height * 32 ... ) * 4].min` line
            continue
        if s == "@display_x = [@display_x - distance, 0].max":
            out.append(f"{indent}@display_x = tj_clamp_x(@display_x - distance)".encode("utf-8"))
            done.add("left")
            i += 1
            continue
        if s == "@display_x = [@display_x + distance,":
            out.append(f"{indent}@display_x = tj_clamp_x(@display_x + distance)".encode("utf-8"))
            done.add("right")
            i += 2
            continue
        if s == "@display_y = [@display_y - distance, 0].max":
            out.append(f"{indent}@display_y = tj_clamp_y(@display_y - distance)".encode("utf-8"))
            done.add("up")
            i += 1
            continue
        out.append(lines[i])
        i += 1

    missing = {"helpers", "down", "left", "right", "up"} - done
    assert not missing, f"Game_Map: failed to patch {missing}"
    e[2] = zlib.compress(eol.join(out), 9)
    print("  Game_Map: scroll_left/right/up/down now clamp through tj_clamp_x/y")
    return True


def patch_player(data):
    e = _entry(data, "Game_Player")
    code = zlib.decompress(e[2])
    if b"tj_clamp_x" in code:
        print("  Game_Player: already patched")
        return False

    eol = b"\r\n" if b"\r\n" in code else b"\n"
    lines = code.split(eol)
    out, hits = [], 0
    for line in lines:
        s = line.strip().decode("utf-8", "replace")
        indent = line[:len(line) - len(line.lstrip())].decode("utf-8", "replace")
        if s == "$game_map.display_x = [0, [x * 128 - CENTER_X, max_x].min].max":
            out.append(f"{indent}$game_map.display_x = $game_map.tj_clamp_x(x * 128 - CENTER_X)".encode("utf-8"))
            hits += 1
        elif s == "$game_map.display_y = [0, [y * 128 - CENTER_Y, max_y].min].max":
            out.append(f"{indent}$game_map.display_y = $game_map.tj_clamp_y(y * 128 - CENTER_Y)".encode("utf-8"))
            hits += 1
        else:
            out.append(line)
    assert hits == 2, f"Game_Player: expected 2 center lines, matched {hits}"
    e[2] = zlib.compress(eol.join(out), 9)
    print("  Game_Player: center() now uses the same clamp")
    return True


def drop_stale(data):
    for i, e in enumerate(data):
        if _script_name(e) == STALE_SCRIPT:
            del data[i]
            print(f"  removed stale {STALE_SCRIPT}")
            return True
    return False


def patch_scene_map(data):
    """Re-centre on map entry.

    Loading a save restores @display_x straight from the save file, so the
    first frame of a small room is still offset until the player happens to
    walk. Recentring once in Scene_Map#main fixes it before the spriteset is
    built.
    """
    e = _entry(data, "Scene_Map")
    code = zlib.decompress(e[2])
    if b"$game_player.center" in code:
        print("  Scene_Map: already patched")
        return False

    eol = b"\r\n" if b"\r\n" in code else b"\n"
    lines = code.split(eol)
    out, hits = [], 0
    for line in lines:
        s = line.strip().decode("utf-8", "replace")
        if s == "@spriteset = Spriteset_Map.new" and hits == 0:
            indent = line[:len(line) - len(line.lstrip())].decode("utf-8", "replace")
            out.append(f"{indent}# TJ: 读档会带回旧的 display_x，进地图时先校正一次".encode("utf-8"))
            out.append(f"{indent}$game_player.center($game_player.x, $game_player.y)".encode("utf-8"))
            hits += 1
        out.append(line)
    assert hits == 1, f"Scene_Map: expected 1 spriteset line, matched {hits}"
    e[2] = zlib.compress(eol.join(out), 9)
    print("  Scene_Map: recenters the camera on map entry")
    return True


def main():
    data = loads(SCRIPTS.read_bytes())
    backup = SCRIPTS.with_suffix(".rxdata.bak-mapcam2")
    if not backup.exists():
        shutil.copy2(SCRIPTS, backup)

    drop_stale(data)
    patch_map(data)
    patch_player(data)
    patch_scene_map(data)
    SCRIPTS.write_bytes(writes(data))

    check = loads(SCRIPTS.read_bytes())
    gm = zlib.decompress(_entry(check, "Game_Map")[2])
    gp = zlib.decompress(_entry(check, "Game_Player")[2])
    for needle in (b"def tj_clamp_x", b"def tj_clamp_y",
                   b"@display_x = tj_clamp_x", b"@display_y = tj_clamp_y"):
        assert needle in gm, f"Game_Map missing {needle!r}"
    assert b"$game_map.tj_clamp_x" in gp
    assert b"$game_map.tj_clamp_y" in gp
    sm = zlib.decompress(_entry(check, "Scene_Map")[2])
    assert b"$game_player.center($game_player.x" in sm
    assert not any(_script_name(e) == STALE_SCRIPT for e in check)
    print(f"  verify OK: {len(check)} scripts, {SCRIPTS.stat().st_size} bytes")


if __name__ == "__main__":
    main()
