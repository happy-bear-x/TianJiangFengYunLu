#!/usr/bin/env python3
import shutil
import zlib
from pathlib import Path

from rubymarshal.reader import loads
from rubymarshal.writer import writes

from paths import GAME
SCRIPTS = GAME / "Data" / "Scripts.rxdata"
SOURCE = Path(__file__).with_name("tianjiang_visible_enemies.rb")
NAME = b"TianJiangVisibleEnemies"
MAGIC = 99000003


def _name(entry):
    n = entry[1]
    if isinstance(n, bytes):
        return n.decode("utf-8", "replace")
    return str(getattr(n, "text", n))


def main():
    source = SOURCE.read_text(encoding="utf-8")
    data = loads(SCRIPTS.read_bytes())
    # 以前这里直接比较 x[1] != b"...": rubymarshal 读回来的名字是 RubyString
    # 对象时比较不可靠，会把 TJ_TouchLayer / TJ_UIAlign 一起过滤掉。统一走
    # 字符串比较。
    data = [x for x in data if _name(x) != NAME.decode("utf-8")]
    main_index = next(i for i, x in enumerate(data) if _name(x) == "Main")
    data.insert(main_index, [MAGIC, NAME, zlib.compress(source.encode("utf-8"), 9)])
    backup = SCRIPTS.with_suffix(".rxdata.bak-visible-enemies")
    if not backup.exists():
        shutil.copy2(SCRIPTS, backup)
    SCRIPTS.write_bytes(writes(data))
    check = loads(SCRIPTS.read_bytes())
    names = [_name(x) for x in check]
    assert names[-1] == "Main"
    assert names[-2] == NAME.decode()
    code = zlib.decompress(check[-2][2]).decode("utf-8")
    assert "VisibleEnemyManager" in code
    print("scripts:", len(check), "main_index:", main_index, "inserted:", NAME.decode())
    print("last:", names[-3:])
    print("verified; size:", SCRIPTS.stat().st_size)


if __name__ == "__main__":
    main()
