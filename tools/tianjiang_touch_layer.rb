#==============================================================================
# ■ TJ_TouchLayer
#   统一触屏输入层。由 tools/install_touch_layer.py 注入到 Scripts.rxdata
#   的最后一个脚本条目。
#
#   依赖 mkxp-z 的 Input.mouse_x / mouse_y / Input::MOUSELEFT 扩展。
#   Java 侧 TouchLayer 把「非摇杆/非按钮」的手指转换成真实的 SDL 鼠标事件，
#   这里再把点击翻译成虚拟按键，所有 Scene 都无需改动。
#
#   ★ 必须排在 Main 之前：Main 里的 while $scene != nil 主循环会一直阻塞，
#     mkxp-z 顺序 eval 脚本，排在 Main 之后的脚本永远不会执行。
#     同时也不能放进 preload —— Window_Base 由游戏脚本定义，那时还不存在。
#==============================================================================

module TJTouch
  @windows = []
  @queue = {}
  @probe_frame = 0
  @tap_prev = false
  # 诊断探针：仅当游戏目录里放了 tj_probe 文件时启用，默认零开销。
  @probe_on = begin
    File.exist?("tj_probe")
  rescue Exception
    false
  end

  class << self
    def register(w)
      @windows << w unless @windows.include?(w)
    end

    def windows
      @windows.delete_if do |w|
        begin
          w.disposed?
        rescue Exception
          false
        end
      end
      @windows
    end

    # 虚拟按键：frames=2 表示本帧 trigger? 为真，下一帧只剩 press?。
    def press(key, frames = 2)
      @queue[key] = frames
    end

    def trigger?(key)
      @queue[key] == 2
    end

    def press?(key)
      @queue.key?(key)
    end

    def tj_probe_line(msg)
      File.open("tj_probe.log", "a") { |f| f.puts msg }
    rescue Exception
    end

    def tick
      @queue.keys.each do |k|
        @queue[k] -= 1
        @queue.delete(k) if @queue[k] <= 0
      end
    end

    # 画布坐标 → 窗口项 index。
    # 布局与 Window_Selectable#update_cursor_rect 一致：
    #   列宽 = width / column_max，行高 32，内容区从窗口左上角 (16,16) 起。
    def index_at(w, x, y)
      col_max = w.instance_variable_get(:@column_max).to_i
      item_max = w.instance_variable_get(:@item_max).to_i
      return nil if col_max < 1 || item_max < 1
      lx = x - w.x - 16
      ly = y - w.y - 16
      return nil if lx < 0 || ly < 0
      # TJ_UIAlign 会把窗口真实宽度横向放大（width 返回的是设计宽度），
      # 命中测试必须用真实宽度才能对上缩放后的列位置。
      real_w = w.respond_to?(:tj_real_w) ? w.tj_real_w.to_i : w.width
      real_w = w.width if real_w < 1
      col_w = real_w / col_max
      return nil if col_w < 1
      oy = begin
        w.oy.to_i
      rescue Exception
        0
      end
      # 行高默认 32（RGSS 标准），但商店那批窗口用 24，必须各算各的，
      # 否则点列表中间会算到别的行去。
      row_h = 32
      if w.respond_to?(:tj_row_h)
        rh = w.tj_row_h.to_i
        row_h = rh if rh > 0
      end
      col = lx / col_w
      row = (ly + oy) / row_h
      return nil if col >= col_max
      idx = row * col_max + col
      return nil if idx < 0 || idx >= item_max
      idx
    end

    def hit_test(x, y)
      hit = nil
      windows.each do |w|
        begin
          next unless w.active
          next unless w.visible
          next unless w.respond_to?(:index=)
          rw = w.respond_to?(:tj_real_w) ? w.tj_real_w.to_i : w.width
          rw = w.width if rw < 1
          next if x < w.x || x >= w.x + rw
          next if y < w.y || y >= w.y + w.height
          idx = index_at(w, x, y)
          next if idx.nil?
          z = begin
            w.z.to_i
          rescue Exception
            0
          end
          # z 越大越靠上层，多个窗口重叠时取最上面那个
          hit = [z, w, idx] if hit.nil? || z > hit[0]
        rescue Exception
          next
        end
      end
      hit
    end

    #--------------------------------------------------------------------------
    # 设置页「游戏相关」：点右侧内容区复制 Q 群号。
    # RGSS 没有剪贴板接口，这里把号码写进游戏目录下的 tj_clipboard，
    # Java 侧 TouchLayer 每 450ms 轮询一次并调用系统 ClipboardManager，
    # 复制完删除文件。不碰引擎二进制，也不用重编 .so。
    #--------------------------------------------------------------------------
    COPY_MAILBOX = "tj_clipboard"
    GROUP_TEXT = "1134180232"

    def info_page?
      return false unless defined?(Scene_Task) && $scene.is_a?(Scene_Task)
      w = $scene.instance_variable_get(:@task_info_window)
      return false if w.nil?
      tid = w.instance_variable_get(:@task_id)
      if tid.nil?
        task = begin
          $game_party.latest_task
        rescue Exception
          nil
        end
        tid = task.id if task
      end
      # @tasks_info[1] 就是「游戏相关」那一页
      tid == 1
    rescue Exception
      false
    end

    def info_window_at?(x, y)
      return false unless info_page?
      w = $scene.instance_variable_get(:@task_info_window)
      return false if w.nil?
      return false if x < w.x || x >= w.x + w.width
      return false if y < w.y || y >= w.y + w.height
      true
    rescue Exception
      false
    end

    def copy_group_number
      File.open(COPY_MAILBOX, "w") { |f| f.write(GROUP_TEXT) }
      true
    rescue Exception
      false
    end
    #--------------------------------------------------------------------------
    # 存档 / 读档界面：不是「一个可选窗口列表」，而是 4 个独立的
    # Window_SaveFile（每个高 104），选择状态由 Scene_File 的 @file_index
    # 维护。通用 hit_test 靠 index= 找目标，这批窗口没有 index=，所以
    # 以前点存档栏完全没反应。这里单独接管。
    #--------------------------------------------------------------------------
    def savefile_windows
      return nil unless defined?(Scene_File) && $scene.is_a?(Scene_File)
      wins = $scene.instance_variable_get(:@savefile_windows)
      return nil unless wins.is_a?(Array) && wins.size >= 4
      wins
    rescue Exception
      nil
    end

    def save_slot_at(x, y)
      wins = savefile_windows
      return nil unless wins
      wins.each_with_index do |w, i|
        next if w.nil?
        begin
          rect_x = w.x || 0
          rect_w = w.width || 0
          rect_y = w.y || 0
          rect_h = w.height || 0
          next if x < rect_x || x >= rect_x + rect_w
          next if y < rect_y || y >= rect_y + rect_h
        rescue Exception
          next
        end
        return i
      end
      nil
    end

    # 点哪个格子就把 @file_index 移过去并直接确认 —— 触屏上没人愿意
    # 先点选中、再跑去按「选中按钮」。
    def click_save_slot(i)
      wins = savefile_windows
      cur = $scene.instance_variable_get(:@file_index).to_i
      begin
        wins[cur].selected = false if wins[cur] && cur != i
      rescue Exception
      end
      $scene.instance_variable_set(:@file_index, i)
      begin
        wins[i].selected = true
        $game_system.se_play($data_system.cursor_se)
      rescue Exception
      end
      # 读档时点空格子只移光标，不确认 —— 否则会一直听到 buzzer
      if $scene.is_a?(Scene_Load) ||
         (defined?(Scene_Load2) && $scene.is_a?(Scene_Load2))
        exist = begin
          wins[i].instance_variable_get(:@file_exist)
        rescue Exception
          false
        end
        press(Input::C) if exist
      else
        press(Input::C)
      end
    end

    # 点击信号：Java 在 tap 时发 KEYCODE_F10，走 SDL 键盘通路。
    # 本机 SDL 的 onNativeMouse DOWN 不生效（MOTION 正常），MOUSELEFT
    # 的按键状态永远采不到；而 onNativeKeyDown 是旧版虚拟手柄验证过的
    # 可靠通路。这里读原始键盘状态（SDL_SCANCODE_F10 = 67）做上升沿。
    TAP_SCANCODE = 67

    def tap_signal?
      st = Input.raw_key_states
      cur = !st.nil? && st[TAP_SCANCODE] ? true : false
      if @probe_on && cur != @tap_prev
        pressed = []
        st.each_with_index { |v, i| pressed << i if v }
        tj_probe_line("edge cur=#{cur} scancodes=#{pressed.join(',')}")
      end
      tr = cur && !@tap_prev
      @tap_prev = cur
      tr
    rescue Exception
      false
    end

    # 画布坐标（853x480）下左上角隐藏菜单的点击区。
    # 只在 Scene_Map 生效：菜单类场景里这块会被窗口命中优先吃掉，
    # 战斗/标题等场景不会触发。
    MENU_CORNER_W = 84
    MENU_CORNER_H = 84

    # 「点窗口外面 = 返回」不适用的场景：地图上点空白发 B 会把菜单呼出来，
    # 战斗里 B 语义不同，标题画面发 B 可能触发退出。
    def outside_back_allowed?
      return false if $scene.nil?
      return false if $scene.is_a?(Scene_Map)
      return false if $scene.is_a?(Scene_Battle)
      return false if $scene.is_a?(Scene_Title)
      true
    rescue Exception
      false
    end

    def process_click
      return unless Input.respond_to?(:raw_key_states)
      tr = tap_signal?
      if tr && @probe_on
        tj_probe_line("tap_signal mx=#{Input.mouse_x} my=#{Input.mouse_y}")
      end
      return unless tr
      x = Input.mouse_x
      y = Input.mouse_y
      return if x < 0 || y < 0
      return if x >= Graphics.width || y >= Graphics.height

      # 存档/读档优先：这四个格子不是可选窗口，走不了通用命中
      slot = save_slot_at(x, y)
      if !slot.nil?
        click_save_slot(slot)
        return
      end

      # 设置页「游戏相关」：点内容区复制群号（要在「点空白=返回」之前拦）
      if info_window_at?(x, y)
        copy_group_number
        return
      end

      hit = hit_test(x, y)
      if hit
        w = hit[1]
        idx = hit[2]
        w.index = idx if w.index != idx
        press(Input::C)
      elsif $game_temp != nil && $game_temp.message_window_showing
        # 对话框没有可选窗口，点击等价于推进
        press(Input::C)
      elsif $scene.is_a?(Scene_Map) && x < MENU_CORNER_W && y < MENU_CORNER_H
        # 左上角隐藏菜单：等价于点「返回」（Scene_Map 用 Input::B 打开菜单）
        press(Input::B)
      elsif outside_back_allowed?
        # 主流触屏习惯：点开菜单后点窗口外面 = 返回
        press(Input::B)
      end
    end

    # 每 12 帧记录一次方向输入 / 鼠标坐标 / 主角地图坐标，用来验证
    # 斜向拖动时 dir8 是否为 1/3/7/9 且角色真的沿对角线移动。
    def probe
      return unless @probe_on
      @probe_frame += 1
      return if @probe_frame % 12 != 0
      begin
        info = begin
          gp = $game_player
          gp.nil? ? "gp=nil" : "px=#{gp.x} py=#{gp.y} face=#{gp.direction}"
        rescue Exception => e
          "err=#{e.class}"
        end
        sc = begin
          $scene ? $scene.class.to_s : "scene=nil"
        rescue Exception
          "scene=?"
        end
        File.open("tj_probe.log", "a") do |f|
          f.puts "f=#{@probe_frame} dir4=#{Input.dir4} dir8=#{Input.dir8} " \
                 "mx=#{Input.mouse_x} my=#{Input.mouse_y} #{info} scene=#{sc}"
        end
      rescue Exception
      end
    end
  end
end

# 登记所有窗口实例，供命中检测遍历。
# 自定义的可选窗口（Window_SelectableCaidan / cd / wupin / shop 等）
# 并不继承 Window_Selectable，而是直接继承 Window_Base，所以要 hook 基类。
class Window_Base
  alias_method :tj_touch_initialize, :initialize
  def initialize(*args)
    tj_touch_initialize(*args)
    TJTouch.register(self)
  end
end

# 商店那一批窗口用自己的排版：行高 24（top_row 里 oy/24），
# 列宽 = width/column_max。通用命中按 32 行高算会点到别的行。
[defined?(Window_Selectableshop) ? Window_Selectableshop : nil,
 defined?(Window_Selectablesell) ? Window_Selectablesell : nil].compact.each do |klass|
  klass.class_eval do
    def tj_row_h
      24
    end
  end
end

# Window_Task 只在 refresh 里用 task_id，不保存下来；触摸层要知道
# 当前展示的是哪一页（只有「游戏相关」页才复制群号），这里补一个记录。
if defined?(Window_Task)
  class Window_Task
    alias_method :tj_touch_refresh, :refresh
    def refresh(task_id)
      @task_id = task_id
      tj_touch_refresh(task_id)
    end
  end
end

# 斜向移动 + 滑墙。
# 原版 move_lower_left 等斜向方法要求「两个分量都通行」才肯挪步：
# 角色上方是房子时，拖动歪一点的「右上」会整步被拒绝，角色原地卡死。
# 这里先尝试真正的斜向；被挡时退而求其次沿墙滑动——先试水平分量，
# 再试垂直分量，哪个能走就走哪个。
class Game_Player
  def tj_slide_move(diag, hdir, vdir)
    ox = @x
    oy = @y
    case diag
    when 1 then move_lower_left
    when 3 then move_lower_right
    when 7 then move_upper_left
    when 9 then move_upper_right
    end
    return if @x != ox or @y != oy
    case hdir
    when 2 then move_down
    when 4 then move_left
    when 6 then move_right
    when 8 then move_up
    end
    return if @x != ox or @y != oy
    case vdir
    when 2 then move_down
    when 4 then move_left
    when 6 then move_right
    when 8 then move_up
    end
  end
end

# 把点击叠加到 Input 的按键查询上，键盘 / 手柄通路完全不变
module Input
  class << self
    alias_method :tj_touch_update_orig, :update
    alias_method :tj_touch_trigger_orig, :trigger?
    alias_method :tj_touch_press_orig, :press?
    alias_method :tj_touch_repeat_orig, :repeat?

    def update
      TJTouch.tick
      tj_touch_update_orig
      TJTouch.process_click
      TJTouch.probe
    end

    def trigger?(key)
      TJTouch.trigger?(key) || tj_touch_trigger_orig(key)
    end

    def press?(key)
      TJTouch.press?(key) || tj_touch_press_orig(key)
    end

    def repeat?(key)
      TJTouch.trigger?(key) || tj_touch_repeat_orig(key)
    end
  end
end
