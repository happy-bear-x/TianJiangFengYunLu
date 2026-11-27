#!/usr/bin/env python3
"""Centre the battle scene on the widened canvas.

The canvas is widened to the panel width (853 on 16:9, up to 1066 on 20:9)
and mkxp_compat already stretches every full-screen battleback across it.
What it cannot fix is everything that still uses the authored 640-space
coordinate system:

  * enemy / actor sprites          (Sprite_Battler#update -> screen_x)
  * target selection arrows         (Arrow_Enemy / Arrow_Actor -> screen_x)
  * the battle timer                (Sprite_Timer -> 640 - width)
  * the sub-screen backdrop arts    (Scene_Battle @back.x = 0 / 89)
  * every window                    (Window_Base#initialize, handled in
                                     TJ_UIAlign because super() there takes
                                     no arguments, so the Window hook never
                                     fires)

They all end up pinned to the left edge with 213 px of dead space on the
right. This installer shifts exactly those, by $tj_ui_shift =
(canvas_w - 640) / 2, which mkxp_compat already computes.

Deliberately NOT shifted: the battleback sprite and any other 640x480
full-screen art, because mkxp_compat zooms those to fill the canvas.
"""
import zlib
from pathlib import Path

from rubymarshal.reader import loads
from rubymarshal.writer import writes

from paths import GAME

SCRIPTS = GAME / "Data" / "Scripts.rxdata"

SHIFT = "($tj_ui_shift || 0)"


def script_name(entry):
    n = entry[1]
    if isinstance(n, bytes):
        return n.decode("utf-8", "replace")
    if hasattr(n, "text"):
        return str(n.text)
    return str(n)


def replace_once(text, old, new, what):
    assert old in text, "anchor not found: " + what
    assert text.count(old) == 1, "anchor not unique: " + what
    return text.replace(old, new)


def patch_sprite_battler(text):
    old = """    # 设置活动块的坐标
    self.x = @battler.screen_x
    self.y = @battler.screen_y"""
    new = """    # 设置活动块的坐标
    # 战斗者站位按 640 设计坐标排布，宽屏画布下要整体右移居中
    self.x = @battler.screen_x + """ + SHIFT + """
    self.y = @battler.screen_y"""
    return replace_once(text, old, new, "Sprite_Battler#update x")


def patch_sprite_timer(text):
    old = """    self.x = 640 - self.bitmap.width"""
    new = """    # 计时器贴在 640 画布右上角，宽屏下同样要跟着右移
    self.x = 640 - self.bitmap.width + """ + SHIFT + """ """
    return replace_once(text, old, new, "Sprite_Timer#initialize x")


def patch_battle_backdrops(text):
    """把战斗里几张局部背景图的 x 加上偏移。

    这些是「物品菜单 / 状态 / 物品」等子界面的底板图（RPG::Cache.picture），
    尺寸不是 640x480，所以 mkxp_compat 不会拉伸它们，只能自己挪。
    """
    changed = 0
    for old, new in (
        ("    @back.x = 0\n", "    @back.x = 0 + " + SHIFT + "\n"),
        ("    @back.x = 89\n", "    @back.x = 89 + " + SHIFT + "\n"),
    ):
        count = text.count(old)
        if count:
            text = text.replace(old, new)
            changed += count
    assert changed >= 3, "battle backdrop anchors not found (got %d)" % changed
    return text


def patch_arrow_enemy(text):
    """选敌指针（红三角）。

    Arrow_Enemy#update 直接 self.x = enemy.screen_x，和 Sprite_Battler 用的是
    同一套 640 坐标。Sprite_Battler 加了偏移、指针没加，箭头就会停在敌人
    左边 $tj_ui_shift 的位置 —— 玩家会以为"点在空地上了"。
    """
    old = """    # 设置活动块坐标
    if self.enemy != nil
      self.x = self.enemy.screen_x
      self.y = self.enemy.screen_y
    end"""
    new = """    # 设置活动块坐标
    # 敌人站位在宽屏下整体右移，指针必须跟着走，否则会停在旧的左侧位置
    if self.enemy != nil
      self.x = self.enemy.screen_x + """ + SHIFT + """
      self.y = self.enemy.screen_y
    end"""
    return replace_once(text, old, new, "Arrow_Enemy#update x")


def patch_arrow_actor(text):
    """选我方角色的指针，道理同 Arrow_Enemy。"""
    old = """    # 设置活动块坐标
    if self.actor != nil
      self.x = self.actor.screen_x
      self.y = self.actor.screen_y
    end"""
    new = """    # 设置活动块坐标
    # 与 Arrow_Enemy 同理：角色站位右移了，指针要跟
    if self.actor != nil
      self.x = self.actor.screen_x + """ + SHIFT + """
      self.y = self.actor.screen_y
    end"""
    return replace_once(text, old, new, "Arrow_Actor#update x")


PATCHERS = {
    "Sprite_Battler": patch_sprite_battler,
    "Sprite_Timer": patch_sprite_timer,
    "Scene_Battle 3新": patch_battle_backdrops,
    "Arrow_Enemy": patch_arrow_enemy,
    "Arrow_Actor": patch_arrow_actor,
}


def main():
    data = loads(SCRIPTS.read_bytes())
    for name, patcher in PATCHERS.items():
        for entry in data:
            if script_name(entry) == name:
                raw = zlib.decompress(entry[2]).decode("utf-8", "replace")
                crlf = "\r\n" in raw
                src = raw.replace("\r\n", "\n")
                if "tj_ui_shift" in src:
                    print("  already patched:", name)
                    break
                patched = patcher(src)
                if crlf:
                    patched = patched.replace("\n", "\r\n")
                entry[2] = zlib.compress(patched.encode("utf-8"), 9)
                print("  patched:", name)
                break
        else:
            raise SystemExit("missing script: " + name)

    SCRIPTS.write_bytes(writes(data))

    check = loads(SCRIPTS.read_bytes())
    for name in PATCHERS:
        src = zlib.decompress(
            next(e for e in check if script_name(e) == name)[2]
        ).decode("utf-8", "replace")
        assert "tj_ui_shift" in src, name + " patch lost"
    print("  verify: OK")


if __name__ == "__main__":
    main()
