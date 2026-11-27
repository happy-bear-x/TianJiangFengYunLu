#!/usr/bin/env python3
"""让跟随队列贴住主角轨迹，修掉「身边多出一个分身」。

XRXS 列车跟随（DYGS）是「主角走一步 → 下一帧跟随者补一步」的队列重放：
队列只记录**方向**，跟随者从自己当前位置重放同样的方向。于是：

  * 起点只要不在主角走过的轨迹上，那个偏移就会**永远保留**；
  * 主角转向时，队列会把偏移原样平移过去，永远不会自我修正。

偏移从哪来：

  1. `moveto` 传送落地时按**朝向**把跟随者摆成一排。这只是「看起来在身后」，
     主角下一步只要不是朝这个方向走，队列就把这一排整体平移，
     从此永久错开一格 —— 表现就是一个一模一样的分身贴着身边走。
  2. 跟随者 `@through = true`，唯一走不动的情况是**地图边界**（valid? 判定），
     少走一步后同样永久错开。

这里给 Game_Party 加一份「主角最近走过的格子」轨迹表（tj_trail），
每帧检查跟随者 i 是否还在 trail[i+1] 上，不在就 moveto 拉回来。
正常行走时两者恒等，不会产生多余校正。

Idempotent：已打过（含 tj_sync_followers 标记）直接跳过。
"""
import re
import shutil
import zlib

from rubymarshal.reader import loads
from rubymarshal.writer import writes

from paths import GAME

SCRIPTS = GAME / "Data" / "Scripts.rxdata"
TARGET = "DYGS"
MARK = b"tj_sync_followers"

HELPERS = """#--------------------------------------------------------------------------
# ● 跟随轨迹 / 自愈（tj_）
# 队伍跟随是队列重放：只记方向，不记格子。起点一旦不在主角轨迹上，
# 偏移就会永久保留（转向也不会修正），看起来就是身边多一个分身。
# 这里记下主角最近走过的格子，每帧把掉队的跟随者拉回轨迹。
#--------------------------------------------------------------------------
TJ_TRAIL_MAX = 8

def tj_trail
@tj_trail = [] if @tj_trail == nil
return @tj_trail
end

def tj_clamp_tile(x, y)
x = 0 if x < 0
y = 0 if y < 0
x = $game_map.width - 1 if $game_map.width > 0 and x > $game_map.width - 1
y = $game_map.height - 1 if $game_map.height > 0 and y > $game_map.height - 1
return [x, y]
end

# 把整队按当前朝向摆到 (x, y) 身后，并重建轨迹
def tj_realign_party(x, y)
if @characters == nil
@tj_trail = [[x, y]]
return
end
d = $game_player.direction
dx = (d == 6 ? 1 : d == 4 ? -1 : 0)
dy = (d == 2 ? 1 : d == 8 ? -1 : 0)
if dx == 0 and dy == 0
dx = 0
dy = 1
end
# 主角贴着地图边界、身后出界时，改成摆在身前，避免全挤在脚下
bx, by = tj_clamp_tile(x - dx, y - dy)
if bx == x and by == y
dx = -dx
dy = -dy
end
trail = [[x, y]]
i = 1
for character in @characters
nx, ny = tj_clamp_tile(x - dx * i, y - dy * i)
character.moveto(nx, ny) if character != nil
trail.push([nx, ny])
i += 1
end
@tj_trail = trail
end

def tj_trail_track
trail = tj_trail
px = $game_player.x
py = $game_player.y
if trail.empty?
trail.push([px, py])
return
end
hx, hy = trail[0]
return if hx == px and hy == py
if (hx - px).abs + (hy - py).abs > 1
# 不是走过来的（脚本直接改坐标 / 跳跃），整队按朝向重排
tj_realign_party(px, py)
return
end
trail.unshift([px, py])
trail.slice!(TJ_TRAIL_MAX, trail.size) if trail.size > TJ_TRAIL_MAX
end

# moveto 时朝向还没定（transfer_player 是 moveto 之后才 turn_*），
# 所以落地那一刻先按旧朝向摆一次，等下一帧朝向定了再按新朝向摆一次。
def tj_realign_pending_one
return if @tj_realign_pending == nil
x, y = @tj_realign_pending
@tj_realign_pending = nil
return if $game_player.x != x or $game_player.y != y
tj_realign_party(x, y)
end

def tj_sync_followers
return if @characters == nil
trail = tj_trail
i = 1
for character in @characters
if character != nil and character.character_name.to_s != ""
spot = trail[i]
if spot != nil and (character.x != spot[0] or character.y != spot[1])
tj_sync_log("snap #{i} #{character.x},#{character.y} -> #{spot[0]},#{spot[1]}")
character.moveto(spot[0], spot[1])
end
end
i += 1
end
end

def tj_sync_log(msg)
begin
@tj_sync_logs = 0 if @tj_sync_logs == nil
return if @tj_sync_logs >= 200
@tj_sync_logs += 1
File.open("tj_party.log", "a") { |f| f.puts "#{Graphics.frame_count} #{msg}" }
rescue Exception
nil
end
end
"""

NEW_MOVETO = """def moveto_party_actors( x, y )
setup_actor_character_sprites
@move_list = [] if @move_list == nil
@tj_realign_pending = [ x, y ]
tj_realign_party( x, y )
move_list_setup
end
"""


def script_name(entry):
    n = entry[1]
    if isinstance(n, bytes):
        return n.decode("utf-8", "replace")
    if hasattr(n, "text"):
        return str(n.text)
    return str(n)


def main():
    data = loads(SCRIPTS.read_bytes())
    e = next(x for x in data if script_name(x) == TARGET)
    code = zlib.decompress(e[2])
    if MARK in code:
        print("already patched, nothing to do")
        return

    eol = b"\r\n" if b"\r\n" in code else b"\n"
    lines = code.split(eol)
    s = [ln.strip() for ln in lines]

    # 1) 在 update_party_actors 前面插入辅助方法
    idx = s.index(b"def update_party_actors")
    helpers = [x.encode("utf-8") for x in HELPERS.split("\n")]
    lines[idx:idx] = helpers
    s[idx:idx] = [b""] * len(helpers)
    idx += len(helpers)

    # 2) update_party_actors 第一行后挂轨迹记录 + 校正
    j = idx + 1
    while s[j] != b"setup_actor_character_sprites":
        j += 1
    assert j - idx < 5, "update_party_actors body changed"
    calls = [b"tj_trail_track", b"tj_realign_pending_one", b"tj_sync_followers"]
    lines[j + 1:j + 1] = calls
    s[j + 1:j + 1] = calls

    # 3) moveto_party_actors 整体换成 朝向前摆 + 清空移动队列
    start = s.index(b"def moveto_party_actors( x, y )")
    k = start + 1
    while s[k] != b"move_list_setup":
        k += 1
    assert s[k + 1] == b"end", "moveto_party_actors tail changed"
    lines[start:k + 2] = [x.encode("utf-8") for x in NEW_MOVETO.split("\n")[:-1]]

    e[2] = zlib.compress(eol.join(lines), 9)
    backup = SCRIPTS.with_suffix(".rxdata.bak-partysync")
    if not backup.exists():
        shutil.copy2(SCRIPTS, backup)
    SCRIPTS.write_bytes(writes(data))

    # 复核
    check = loads(SCRIPTS.read_bytes())
    ce = next(x for x in check if script_name(x) == TARGET)
    cs = zlib.decompress(ce[2]).decode("utf-8", "replace").replace("\r\n", "\n")
    m = re.search(r"def update_party_actors\n(.*?)\ndef ", cs, re.S)
    assert m and "tj_trail_track" in m.group(1) and "tj_sync_followers" in m.group(1)
    assert "tj_realign_pending_one" in m.group(1)
    assert "def tj_realign_party(x, y)" in cs
    assert "tj_realign_party( x, y )" in cs
    assert cs.count("def moveto_party_actors( x, y )") == 1
    print(f"patched; scripts={len(check)} size={SCRIPTS.stat().st_size}")
    print("--- update_party_actors ---")
    print(m.group(0)[:400])


if __name__ == "__main__":
    main()
