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
      col_w = w.width / col_max
      return nil if col_w < 1
      oy = begin
        w.oy.to_i
      rescue Exception
        0
      end
      col = lx / col_w
      row = (ly + oy) / 32
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
          next if x < w.x || x >= w.x + w.width
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

      hit = hit_test(x, y)
      if hit
        w = hit[1]
        idx = hit[2]
        w.index = idx if w.index != idx
        press(Input::C)
      elsif $game_temp != nil && $game_temp.message_window_showing
        # 对话框没有可选窗口，点击等价于推进
        press(Input::C)
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
