#!/usr/bin/env python3
"""Install the auto-save feature into Data/Scripts.rxdata.

Two kinds of change:

1. Inject the "TJ_AutoSave" script immediately BEFORE "Main" — it defines
   TJAutoSave, Window_AutoSaveEntry, Window_AutoSaveFile and Scene_AutoSave.

2. Rewrite three existing scripts IN PLACE. Reopening a game class from a
   standalone injected script does NOT take effect on device (proven: even a
   `raise` probe inside the reopened method never fired), so the original
   method bodies are edited directly:

   Window_SaveFile#initialize   slot height 104 -> 88, stride 104 -> 88
   Window_SaveFile#refresh      redraw for the shorter slot
   Scene_File#main              add the bottom "自动存档" entry window
   Scene_File#update            cursor walks 5 entries; C on the entry opens
                                Scene_AutoSave
   Scene_Map#main / #update     schedule an auto-save once the map is idle
   Scene_Map#transfer_player    re-arm the schedule after every transfer

Save file format is unchanged (same 11 Marshal objects in the same order),
so auto-saves are readable by the normal load path and vice versa.
"""
import zlib
from pathlib import Path

from rubymarshal.reader import loads
from rubymarshal.writer import writes

from paths import GAME

SCRIPTS = GAME / "Data" / "Scripts.rxdata"
SOURCE = Path(__file__).with_name("tianjiang_autosave.rb")
SCRIPT_NAME = "TJ_AutoSave"

STALE_SCRIPTS = ("TJ_AutoSave",)


def script_name(entry):
    n = entry[1]
    if isinstance(n, bytes):
        return n.decode("utf-8", "replace")
    if hasattr(n, "text"):
        return str(n.text)
    return str(n)


def source_of(data, name):
    for entry in data:
        if script_name(entry) == name:
            return zlib.decompress(entry[2]).decode("utf-8", "replace")
    raise KeyError(name)


def replace_once(text, old, new, what):
    assert old in text, "anchor not found: " + what
    assert text.count(old) == 1, "anchor not unique: " + what
    return text.replace(old, new)


# ---------------------------------------------------------------------------
# 1. Window_SaveFile — 4 slots shrink from 104 to 88 so the bottom 64px can
#    hold the auto-save entry.
# ---------------------------------------------------------------------------
def patch_savefile(text):
    old = """  def initialize(file_index, filename)
    super(0, 64 + file_index % 4 * 104, 640, 104)"""
    new = """  def initialize(file_index, filename)
    # 槽高 104 -> 88：底部 64px 留给「自动存档」入口条。
    # （TJ_AutoSave）
    super(0, 64 + file_index * 88, 640, 88)"""
    text = replace_once(text, old, new, "Window_SaveFile#initialize")

    old = """    self.contents.font.color = normal_color
    name = "文件 #{@file_index + 1}"
    self.contents.draw_text(4, 0, 600, 32, name)
    @name_width = contents.text_size(name).width"""
    new = """    self.contents.font.color = normal_color
    name = "文件 #{@file_index + 1}"
    self.contents.draw_text(4, 0, 600, 26, name)
    @name_width = contents.text_size(name).width"""
    text = replace_once(text, old, new, "Window_SaveFile#refresh name")

    old = """        x = 300 - @characters.size * 32 + i * 64 - cw / 2
        self.contents.blt(x, 68 - ch, bitmap, src_rect)"""
    new = """        x = 300 - @characters.size * 32 + i * 64 - cw / 2
        # 内容高 56（88 - 32），立绘贴底而不是贴 68
        self.contents.blt(x, 56 - ch, bitmap, src_rect)"""
    text = replace_once(text, old, new, "Window_SaveFile#refresh blt")

    old = """      self.contents.draw_text(4, 8, 600, 32, time_string, 2)"""
    new = """      self.contents.draw_text(4, 0, 600, 26, time_string, 2)"""
    text = replace_once(text, old, new, "Window_SaveFile#refresh playtime")

    old = """      time_string = @time_stamp.strftime("%Y/%m/%d %H:%M")
      self.contents.draw_text(4, 40, 600, 32, time_string, 2)"""
    new = """      time_string = @time_stamp.strftime("%Y/%m/%d %H:%M")
      self.contents.draw_text(4, 26, 600, 26, time_string, 2)"""
    text = replace_once(text, old, new, "Window_SaveFile#refresh timestamp")
    return text


# ---------------------------------------------------------------------------
# 2. Scene_File — entry window + 5-way cursor.
# ---------------------------------------------------------------------------
def patch_scene_file(text):
    old = """    @savefile_windows = []
    for i in 0..3
      @savefile_windows.push(Window_SaveFile.new(i, make_filename(i)))
    end
    # 选择最后操作的文件"""
    new = """    # 底部整行是「自动存档」入口，和摇杆跟手范围重叠：先停用摇杆
    TJAutoSave.set_joystick(false)
    @savefile_windows = []
    for i in 0..3
      @savefile_windows.push(Window_SaveFile.new(i, make_filename(i)))
    end
    # 底部「自动存档」入口：只在读档界面出现，存档界面点了没有意义
    @autosave_window = nil
    if self.is_a?(Scene_Load) ||
       (defined?(Scene_Load2) && self.is_a?(Scene_Load2))
      @autosave_window = Window_AutoSaveEntry.new(416, 64)
    end
    # 选择最后操作的文件"""
    text = replace_once(text, old, new, "Scene_File#main windows")

    old = """    @help_window.dispose
    for i in @savefile_windows
      i.dispose
    end"""
    new = """    @help_window.dispose
    for i in @savefile_windows
      i.dispose
    end
    @autosave_window.dispose if @autosave_window
    TJAutoSave.set_joystick(true)"""
    text = replace_once(text, old, new, "Scene_File#main dispose")

    # --- update: C 键 ---
    old = """    if Input.trigger?(Input::C)
      # 调用过程 on_decision (定义继承目标)
      on_decision(make_filename(@file_index))
      $game_temp.last_file_index = @file_index
      return
    end"""
    new = """    if Input.trigger?(Input::C)
      # 光标停在「自动存档」上：进入二级界面
      if @autosave_window && @file_index == 4
        $game_system.se_play($data_system.decision_se)
        # 记住来源，二级界面按 B 能原路返回
        $tj_autosave_from = (defined?(Scene_Load2) && self.is_a?(Scene_Load2)) ? 2 : 1
        $scene = Scene_AutoSave.new
        return
      end
      # 调用过程 on_decision (定义继承目标)
      on_decision(make_filename(@file_index))
      $game_temp.last_file_index = @file_index
      return
    end"""
    text = replace_once(text, old, new, "Scene_File#update confirm")

    # --- update: 下方向键 ---
    old = """    if Input.repeat?(Input::DOWN)
      # 方向键下的按下状态不是重复的情况下、
      # 并且光标的位置在 3 以前的情况下
      if Input.trigger?(Input::DOWN) or @file_index < 3
        # 演奏光标 SE
        $game_system.se_play($data_system.cursor_se)
        # 光标向下移动
        @savefile_windows[@file_index].selected = false
        @file_index = (@file_index + 1) % 4
        @savefile_windows[@file_index].selected = true
        return
      end
    end"""
    new = """    if Input.repeat?(Input::DOWN)
      # 方向键下的按下状态不是重复的情况下、
      # 并且光标的位置在最后一项以前的情况下
      if Input.trigger?(Input::DOWN) or @file_index < tj_last_index
        # 演奏光标 SE
        $game_system.se_play($data_system.cursor_se)
        # 光标向下移动
        tj_clear_selection
        @file_index = (@file_index + 1) % (tj_last_index + 1)
        tj_apply_selection
        return
      end
    end"""
    text = replace_once(text, old, new, "Scene_File#update down")

    # --- update: 上方向键 ---
    old = """    if Input.repeat?(Input::UP)
      # 方向键上的按下状态不是重复的情况下、
      # 并且光标的位置在 0 以后的情况下
      if Input.trigger?(Input::UP) or @file_index > 0
        # 演奏光标 SE
        $game_system.se_play($data_system.cursor_se)
        # 光标向上移动
        @savefile_windows[@file_index].selected = false
        @file_index = (@file_index + 3) % 4
        @savefile_windows[@file_index].selected = true
        return
      end
    end"""
    new = """    if Input.repeat?(Input::UP)
      # 方向键上的按下状态不是重复的情况下、
      # 并且光标的位置在 0 以后的情况下
      if Input.trigger?(Input::UP) or @file_index > 0
        # 演奏光标 SE
        $game_system.se_play($data_system.cursor_se)
        # 光标向上移动
        tj_clear_selection
        @file_index = (@file_index + tj_last_index) % (tj_last_index + 1)
        tj_apply_selection
        return
      end
    end"""
    text = replace_once(text, old, new, "Scene_File#update up")

    # --- 追加三个辅助方法（放在 make_filename 之前） ---
    old = """  #--------------------------------------------------------------------------
  # ● 生成文件名
  #     file_index : 文件名的索引 (0～3)
  #--------------------------------------------------------------------------
  def make_filename(file_index)"""
    new = """  #--------------------------------------------------------------------------
  # ● 光标可停留的最后一项（3 = 第 4 个手动槽，4 = 自动存档入口）
  #--------------------------------------------------------------------------
  def tj_last_index
    @autosave_window ? 4 : 3
  end
  #--------------------------------------------------------------------------
  # ● 清除当前高亮
  #--------------------------------------------------------------------------
  def tj_clear_selection
    if @file_index < 4
      @savefile_windows[@file_index].selected = false
    elsif @autosave_window
      @autosave_window.selected = false
    end
  end
  #--------------------------------------------------------------------------
  # ● 高亮当前项
  #--------------------------------------------------------------------------
  def tj_apply_selection
    if @file_index < 4
      @savefile_windows[@file_index].selected = true
    elsif @autosave_window
      @autosave_window.selected = true
    end
  end
  #--------------------------------------------------------------------------
  # ● 生成文件名
  #     file_index : 文件名的索引 (0～3)
  #--------------------------------------------------------------------------
  def make_filename(file_index)"""
    text = replace_once(text, old, new, "Scene_File#make_filename helpers")
    return text


# ---------------------------------------------------------------------------
# 3. Scene_Map — schedule + fire the auto-save.
# ---------------------------------------------------------------------------
def patch_scene_map(text):
    old = """  def main
    # 生成活动块
    # TJ: 读档会带回旧的 display_x，进地图时先校正一次"""
    new = """  def main
    # 自动存档的节流状态：进地图先把当前位置记为"基准点"，之后只有
    # 换图或 player 真的挪过位置才算有进展 —— 挂机不会刷档。
    @tj_autosave_forced = false
    @tj_autosave_tick = 0
    # 回到地图一定放开摇杆：存档界面的标记即使异常残留也在这里清掉
    TJAutoSave.set_joystick(true)
    TJAutoSave.mark_position($game_map.map_id, $game_player.x, $game_player.y) if $game_map && $game_player
    # 生成活动块
    # TJ: 读档会带回旧的 display_x，进地图时先校正一次"""
    text = replace_once(text, old, new, "Scene_Map#main state")

    old = """  def update
    # 循环
    loop do"""
    new = """  def update
    # 自动存档节流。
    #   换图（transfer_player 置 forced）-> 落地后补一份，记录新场景；
    #   同一张图待满 INTERVAL_SEC 且 player 真的挪过位置 -> 补一份。
    # 挂机时玩家一动不动，progressed? 为 false，绝不会把 5 份历史
    # 刷成同一格 —— 这是"挂在那里不能一直覆盖存档"的那条约束。
    @tj_autosave_tick = (@tj_autosave_tick || 0) + 1
    tj_autosave_due = @tj_autosave_forced
    if !tj_autosave_due &&
       @tj_autosave_tick >= Graphics.frame_rate * TJAutoSave::INTERVAL_SEC
      tj_autosave_due = TJAutoSave.progressed?
    end
    if tj_autosave_due && TJAutoSave.safe_now?
      if TJAutoSave.progressed? && !TJAutoSave.too_soon?
        TJAutoSave.write
      end
      @tj_autosave_forced = false
      @tj_autosave_tick = 0
    end
    # 循环
    loop do"""
    text = replace_once(text, old, new, "Scene_Map#update pending")

    old = """    # 设置画面
    Graphics.frame_reset
    # 刷新输入信息
    Input.update
  end
end"""
    new = """    # 设置画面
    Graphics.frame_reset
    # 刷新输入信息
    Input.update
    # 换了地图：落地后的下一个安全点补一份自动存档
    @tj_autosave_forced = true
  end
end"""
    text = replace_once(text, old, new, "Scene_Map#transfer_player pending")
    return text


PATCHERS = {
    "Window_SaveFile": patch_savefile,
    "Scene_File": patch_scene_file,
    "Scene_Map": patch_scene_map,
}


def main():
    data = loads(SCRIPTS.read_bytes())

    # 移除旧版本（按字符串名比较，rubymarshal 的 RubyString 直接 == bytes 不可靠）
    before = len(data)
    data = [e for e in data if script_name(e) not in STALE_SCRIPTS]
    if len(data) != before:
        print("  autosave: replaced existing script")

    for name, patcher in PATCHERS.items():
        for entry in data:
            if script_name(entry) == name:
                raw = zlib.decompress(entry[2]).decode("utf-8", "replace")
                # 原脚本是 CRLF，锚点按 LF 写；统一后再还原
                crlf = "\r\n" in raw
                src = raw.replace("\r\n", "\n")
                patched = patcher(src)
                if crlf:
                    patched = patched.replace("\n", "\r\n")
                entry[2] = zlib.compress(patched.encode("utf-8"), 9)
                print("  patched:", name)
                break
        else:
            raise SystemExit("missing script: " + name)

    script_id = max(e[0] for e in data) + 1
    main_index = next(i for i, e in enumerate(data) if script_name(e) == "Main")
    src = SOURCE.read_bytes().replace(b"\r\n", b"\n")
    data.insert(main_index, [script_id, SCRIPT_NAME, zlib.compress(src, 9)])
    print("  autosave: installed at #%d (before Main, id %d)"
          % (main_index + 1, script_id))

    SCRIPTS.write_bytes(writes(data))

    # 校验
    check = loads(SCRIPTS.read_bytes())
    names = [script_name(e) for e in check]
    assert SCRIPT_NAME in names, "injection lost"
    assert names.index(SCRIPT_NAME) < names.index("Main"), "order wrong"
    sf = source_of(check, "Scene_File")
    assert "@autosave_window" in sf and "tj_last_index" in sf
    sm = source_of(check, "Scene_Map")
    assert "@tj_autosave_forced" in sm and "TJAutoSave.safe_now?" in sm
    ws = source_of(check, "Window_SaveFile")
    assert "640, 88" in ws
    print("  verify: OK (%d scripts)" % len(names))


if __name__ == "__main__":
    main()
