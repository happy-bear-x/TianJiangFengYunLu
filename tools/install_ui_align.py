#!/usr/bin/env python3
"""Install the UI align layer into Data/Scripts.rxdata.

One idempotent change: insert a "TJ_UIAlign" script immediately BEFORE
"Main" (same ordering constraints as the touch layer: game-defined
classes exist by then, and anything after Main is dead code).

Why: mkxp_compat.rb stretches every exact-640x480 full-screen picture
(zoom_x = 853/640) to cover the 16:9 canvas. Scenes that compose such a
picture with windows authored in 640-space (status, item, skill, shop,
equip-exchange) end up with text sitting 106 px LEFT of its art slots —
the art slots moved to 1.333*x while the text stayed at x.

Window_Base#initialize calls super() with NO arguments and then assigns
self.x / self.width directly, so the Window#initialize hook in
mkxp_compat.rb never fires for game windows. This layer therefore hooks
Window_Base#initialize (defined by the game scripts, so it must be
injected after them) and applies the same affine transform the
background picture gets:

  window.x    *= F
  window.width *= F          (windowskin border stretches with it)
  draw_text/blt/fill_rect/stretch_blt x and width *= F (+ a 16*(F-1)
              contents-inset compensation)
  cursor_rect x, width *= F  (no inset compensation: cursor coords are
              window-space, not contents-space)

`Window_Base#width` is overridden to keep returning the AUTHORED width
so that layout math derived from self.width (help-window centring,
column spacing) is not scaled twice. The real scaled width is exposed
as Window_Base#tj_real_w for hit-testing.

Scene scope is explicit (SCENES below): scenes whose background picture
is stretched. Scene_Menu/Scene_End use small un-stretched art and stay
untouched; Scene_Title was already fixed separately.
"""
import shutil
import zlib
from pathlib import Path

from rubymarshal.reader import loads
from rubymarshal.writer import writes

from paths import GAME

SCRIPTS = GAME / "Data" / "Scripts.rxdata"
SOURCE = Path(__file__).with_name("tianjiang_ui_align.rb")
SCRIPT_NAME = "TJ_UIAlign"


def _script_name(entry):
    n = entry[1]
    if isinstance(n, bytes):
        return n.decode("utf-8", "replace")
    if hasattr(n, "text"):
        return str(n.text)
    return str(n)


def inject_layer(data):
    src = SOURCE.read_bytes().replace(b"\r\n", b"\n")

    script_id = None
    for i, e in enumerate(data):
        if _script_name(e) == SCRIPT_NAME:
            script_id = e[0]
            del data[i]
            break
    if script_id is None:
        script_id = max(e[0] for e in data) + 1

    main_idx = next((i for i, e in enumerate(data)
                     if _script_name(e) == "Main"), None)
    assert main_idx is not None, "could not find the Main script"
    data.insert(main_idx, [script_id, SCRIPT_NAME, zlib.compress(src, 9)])
    print(f"  ui align: installed at #{main_idx + 1} "
          f"(before Main, id {script_id})")
    return True


def main():
    data = loads(SCRIPTS.read_bytes())
    before = len(data)
    backup = SCRIPTS.with_suffix(".rxdata.bak-uialign")
    if not backup.exists():
        shutil.copy2(SCRIPTS, backup)

    changed = inject_layer(data)
    if changed:
        SCRIPTS.write_bytes(writes(data))

    check = loads(SCRIPTS.read_bytes())
    hits = [i for i, x in enumerate(check) if _script_name(x) == SCRIPT_NAME]
    assert len(hits) == 1, f"expected one ui align layer, got {len(hits)}"
    main_idx = next(i for i, x in enumerate(check) if _script_name(x) == "Main")
    assert hits[0] < main_idx, "ui align layer must run BEFORE Main"
    body = zlib.decompress(check[hits[0]][2])
    assert b"module TJUIAlign" in body
    assert b"cursor_rect=" in body
    assert b"Scene_Status" in body
    print(f"  verify OK: {before} -> {len(check)} scripts, "
          f"ui align #{hits[0] + 1} < Main #{main_idx + 1}, "
          f"{SCRIPTS.stat().st_size} bytes")


if __name__ == "__main__":
    main()
