#!/usr/bin/env python3
"""Fix the "主角残影" left behind by the party-follow (Train_Actor) script.

DYGS 的 moveto_party_actors 在传送时把 **所有** 跟随者 moveto 到主角同一格：

    for character in @characters
      character.moveto( x, y )
    end

于是 3 个跟随角色精确重叠在主角脚下。跟随角色的 sprite 用 screen_z 压在
主角之下，主角一停住，叠在一起的那几个人就变成一团"重影"；队伍里有人
和主角同形象时，看起来就是"主角残影"。

改成按当前朝向把跟随者依次排到主角身后一格、两格、三格，并夹在地图
范围内。这样传送落地时队列已经是散开的。

Idempotent：已打过的跳过。
"""
import shutil
import zlib

from rubymarshal.reader import loads
from rubymarshal.writer import writes

from paths import GAME

SCRIPTS = GAME / "Data" / "Scripts.rxdata"
TARGET = "DYGS"
MARK = "tj_dx"

OLD = "character.moveto( x, y )"

NEW = """tj_d = $game_player.direction
tj_dx = tj_d == 6 ? -1 : tj_d == 4 ? 1 : 0
tj_dy = tj_d == 2 ? -1 : tj_d == 8 ? 1 : 0
tj_i = 1
for character in @characters
tj_nx = x + tj_dx * tj_i
tj_ny = y + tj_dy * tj_i
tj_nx = 0 if tj_nx < 0
tj_ny = 0 if tj_ny < 0
tj_nx = $game_map.width - 1 if $game_map.width > 0 and tj_nx > $game_map.width - 1
tj_ny = $game_map.height - 1 if $game_map.height > 0 and tj_ny > $game_map.height - 1
character.moveto( tj_nx, tj_ny )
tj_i += 1
end"""


def main():
    data = loads(SCRIPTS.read_bytes())
    e = next(x for x in data if x[1].decode("utf-8", "replace") == TARGET)
    code = zlib.decompress(e[2])

    if MARK.encode() in code:
        print("already patched, nothing to do")
        return

    eol = b"\r\n" if b"\r\n" in code else b"\n"
    lines = code.split(eol)
    out, hits = [], 0
    for line in lines:
        if line.strip() == OLD.encode():
            out.extend(n.encode("utf-8") for n in NEW.split("\n"))
            hits += 1
        else:
            out.append(line)
    assert hits == 1, f"expected 1 moveto line, matched {hits}"

    e[2] = zlib.compress(eol.join(out), 9)
    backup = SCRIPTS.with_suffix(".rxdata.bak-trainactor")
    if not backup.exists():
        shutil.copy2(SCRIPTS, backup)
    SCRIPTS.write_bytes(writes(data))

    check = loads(SCRIPTS.read_bytes())
    ce = next(x for x in check if x[1].decode("utf-8", "replace") == TARGET)
    cs = zlib.decompress(ce[2]).decode("utf-8", "replace")
    assert "tj_dx" in cs and "tj_i += 1" in cs
    assert "character.moveto( tj_nx, tj_ny )" in cs
    print(f"patched; scripts={len(check)} size={SCRIPTS.stat().st_size}")


if __name__ == "__main__":
    main()
