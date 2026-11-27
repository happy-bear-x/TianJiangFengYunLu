#!/usr/bin/env python3
"""Android 双击返回键直接弹出「结束游戏」确认框，并把该确认框在宽屏居中。

两件事：

1) 双击返回键
   Java 侧（MainActivity）在 800ms 内收到两次 BACK 时写一个标记文件
   game/tj_back_exit。Ruby 侧由 TJTouch.poll_back 在 Input.update 里
   轮询（每 8 帧一次），命中就置 $tj_back_req —— 这个全局只在
   「本轮 Input.update → 本轮场景 update」之间存活，下一轮 Input.update
   开头即清空，所以不会被无关场景（标题、战斗）捡走延迟触发。

   Scene_Map#update 消费它：置 $tj_end_from_map 后切到 Scene_End。

2) 居中
   Scene_End 原来按 @command_window.x = 320 - width/2 定位，320 是
   640 画布的一半；画布扩到 853/1066 后整体偏左。现在改成以底板图
   （Pictures/标题.png，308x262）在 Graphics.width 上居中，文字窗口
   再在底板内水平居中 —— 原先贴底板左边，宽画布下看起来更偏。

只在「双击返回键进来」时把取消动作改回地图：从菜单进来的仍然回菜单。
"""
import zlib

from rubymarshal.reader import loads
from rubymarshal.writer import writes

from paths import GAME

SCRIPTS = GAME / "Data" / "Scripts.rxdata"

BACK_HOOK = """    # TJ: 双击系统返回键 → 直接弹出「结束游戏」确认框
    #     $tj_back_req 由 TJTouch.poll_back 在 Input.update 里置位，
    #     只存活一帧，这里消费掉。
    if $tj_back_req
      $tj_back_req = nil
      $tj_end_from_map = true
      $scene = Scene_End.new
      return
    end
"""

FROM_MAP = """  def main
    # TJ: 记住从哪进来的，取消时才能原路返回
    @from_map = $tj_end_from_map
    $tj_end_from_map = false
"""

CENTER = """    # TJ: 底板按画布居中（原来用 640 的 320 定基准，宽画布下偏左），
    #     文字窗口再在底板内水平居中
    tj_bw = @back.bitmap ? @back.bitmap.width : @command_window.width
    tj_bx = (Graphics.width - tj_bw) / 2
    tj_by = 240 - @command_window.height / 2
    @back.x = tj_bx
    @back.y = tj_by
    @command_window.x = tj_bx + (tj_bw - @command_window.width) / 2
    @command_window.y = tj_by
"""

CANCEL = """  #--------------------------------------------------------------------------
  # ● TJ: 取消 —— 回到来源
  #     双击返回键进来的回地图，否则会莫名其妙掉进菜单
  #--------------------------------------------------------------------------
  def tj_end_cancel
    if @from_map
      $scene = Scene_Map.new
    else
      $scene = Scene_Menu.new(3)
    end
  end
"""


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


def patch_scene_map(text):
    old = "  def update\n"
    assert text.count(old) == 1, "Scene_Map#update anchor not unique"
    return text.replace(old, "  def update\n" + BACK_HOOK, 1)


def patch_scene_end(text):
    # 主处理：记录来源
    text = replace_once(text, "  def main\n", FROM_MAP, "Scene_End#main")

    # 这两行在 @back 创建之前算，会被下面的居中逻辑覆盖，直接删掉免得误导
    text = replace_once(
        text,
        """    @command_window.x = 320 - @command_window.width / 2
    @command_window.y = 240 - @command_window.height / 2
""",
        "    # TJ: 坐标等 @back 建好之后统一算（见下方 tj_bx）\n",
        "Scene_End window x/y",
    )

    # 底板与窗口一起居中
    text = replace_once(
        text,
        """    @back.x =320 - @command_window.width / 2
    @back.y =240 - @command_window.height / 2
""",
        CENTER,
        "Scene_End backdrop x/y",
    )

    # B 键 / 双击返回 → 统一走 tj_end_cancel
    text = replace_once(
        text,
        """    if Input.trigger?(Input::B)
      # 演奏取消 SE
      $game_system.se_play($data_system.cancel_se)
      # 切换到菜单画面
      $scene = Scene_Menu.new(3)
      return
    end""",
        """    if Input.trigger?(Input::B) || $tj_back_req
      $tj_back_req = nil
      # 演奏取消 SE
      $game_system.se_play($data_system.cancel_se)
      tj_end_cancel
      return
    end""",
        "Scene_End#update B key",
    )

    # 「取消选择」也走同一套
    text = replace_once(
        text,
        """  def command_cancel
    # 演奏确定 SE
    $game_system.se_play($data_system.decision_se)
    # 切换到菜单画面
    $scene = Scene_Menu.new(3)
  end""",
        """  def command_cancel
    # 演奏确定 SE
    $game_system.se_play($data_system.decision_se)
    tj_end_cancel
  end

""" + CANCEL,
        "Scene_End#command_cancel",
    )
    return text


PATCHERS = {
    "Scene_Map": patch_scene_map,
    "Scene_End": patch_scene_end,
}


def main():
    data = loads(SCRIPTS.read_bytes())
    for name, patcher in PATCHERS.items():
        for entry in data:
            if script_name(entry) != name:
                continue
            raw = zlib.decompress(entry[2]).decode("utf-8", "replace")
            crlf = "\r\n" in raw
            src = raw.replace("\r\n", "\n")
            if "$tj_back_req" in src:
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
        assert "$tj_back_req" in src, name + " patch lost"
    print("  verify: OK")


if __name__ == "__main__":
    main()
