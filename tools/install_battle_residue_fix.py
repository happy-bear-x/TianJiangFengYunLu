#!/usr/bin/env python3
"""在 Scripts.rxdata 里安装战斗残留文字修复脚本（放在 Main 之前）。

三个分支共用同一份安装器：脚本本身只做运行时钩子，不依赖分支特性，
main / optimized / hd-remaster 都可以直接跑。
"""
import shutil
import zlib
from pathlib import Path

from rubymarshal.reader import loads
from rubymarshal.writer import writes

from paths import GAME

SCRIPTS = GAME / "Data" / "Scripts.rxdata"
SOURCE = Path(__file__).with_name("tianjiang_battle_residue.rb")
NAME = "TianJiangBattleResidueFix"
MAGIC = 99000008


def _name(entry):
    n = entry[1]
    if isinstance(n, bytes):
        return n.decode("utf-8", "replace")
    return str(getattr(n, "text", n))


def main():
    source = SOURCE.read_text(encoding="utf-8").replace("\r\n", "\n")
    data = loads(SCRIPTS.read_bytes())

    # 按脚本名过滤（rubymarshal 读回的 RubyString 直接比较不可靠）
    data = [x for x in data if _name(x) != NAME]
    main_index = next(i for i, x in enumerate(data) if _name(x) == "Main")
    entry = [MAGIC, NAME.encode("utf-8"), zlib.compress(source.encode("utf-8"), 9)]
    data.insert(main_index, entry)

    backup = SCRIPTS.with_suffix(".rxdata.bak-battle-residue")
    if not backup.exists():
        shutil.copy2(SCRIPTS, backup)
    SCRIPTS.write_bytes(writes(data))

    check = loads(SCRIPTS.read_bytes())
    names = [_name(x) for x in check]
    assert names[-1] == "Main", names[-3:]
    assert names[-2] == NAME, names[-3:]
    code = zlib.decompress(check[-2][2]).decode("utf-8")
    assert "TJ_BattleResidue" in code
    print("scripts:", len(check), "main_index:", main_index, "inserted:", NAME)
    print("last:", names[-3:])
    print("verified; size:", SCRIPTS.stat().st_size)


if __name__ == "__main__":
    main()
