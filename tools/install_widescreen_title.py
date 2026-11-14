#!/usr/bin/env python3
"""Replace the two hard-coded 320 (old 4:3 canvas centre) in Scene_Title
with Graphics.width / 2, so the title menu stays centred on a wider canvas."""
import shutil
import zlib
from pathlib import Path

from rubymarshal.reader import loads
from rubymarshal.writer import writes

from paths import GAME

SCRIPTS = GAME / "Data" / "Scripts.rxdata"
OLD = b"320 - @command_window.width / 2"
NEW = b"Graphics.width / 2 - @command_window.width / 2"


def main():
    data = loads(SCRIPTS.read_bytes())
    hit = 0
    for entry in data:
        name = entry[1].decode("utf-8", "replace")
        if "Scene_Title" not in name:
            continue
        code = zlib.decompress(entry[2])
        count = code.count(OLD)
        if count == 0 and code.count(NEW) == 2:
            print("already patched")
            return
        assert count == 2, f"expected 2 occurrences, got {count}"
        entry[2] = zlib.compress(code.replace(OLD, NEW), 9)
        hit += count
        print(f"patched [{name}] x{hit}")

    assert hit == 2
    backup = SCRIPTS.with_suffix(".rxdata.bak-widescreen")
    if not backup.exists():
        shutil.copy2(SCRIPTS, backup)
    SCRIPTS.write_bytes(writes(data))

    check = loads(SCRIPTS.read_bytes())
    title = next(e for e in check if "Scene_Title" in e[1].decode("utf-8", "replace"))
    src = zlib.decompress(title[2]).decode("utf-8", "replace")
    assert src.count("Graphics.width / 2 - @command_window.width / 2") == 2
    print("verified; scripts:", len(check), "size:", SCRIPTS.stat().st_size)


if __name__ == "__main__":
    main()
