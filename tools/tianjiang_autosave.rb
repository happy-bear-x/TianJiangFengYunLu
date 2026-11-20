# =====================================================================
# ★ TJ_AutoSave — 自动存档（5 份轮换）+ 读档界面入口
# ---------------------------------------------------------------------
# 注入位置：Main 之前（依赖 Scene_File / Scene_Map / Window_Base 已定义）。
#
# 配套改动由 tools/install_autosave.py 直接写进原脚本（类重开在设备上
# 不生效，这是踩过的坑）：
#   Window_SaveFile  —— 槽高 104 -> 88，为底部「自动存档」入口腾 64px
#   Scene_File       —— 创建入口窗口、方向键 5 项循环、确认键分流
#   Scene_Map        —— 进图/传送后置 pending，在安全点写盘
#
# 存档格式与手动存档完全一致（11 个 Marshal 对象，顺序同
# Scene_Save#write_save_data），所以读档逻辑可以直接复用。
#
# 文件名 SaveAuto1..5.rxdata 都以 "Save" 开头，
# BootstrapActivity.backupSaves() 的前缀匹配能覆盖到，升级资源不会丢。
# =====================================================================

module TJAutoSave
  COUNT        = 5
  INTERVAL_SEC = 90     # 同一张地图里，最多这么久补一份
  DEBOUNCE_SEC = 45     # 同一张图、同一格，45 秒内不重复写

  module_function

  def filename(index)
    "SaveAuto#{index}.rxdata"
  end

  def exist?(index)
    FileTest.exist?(filename(index))
  rescue Exception
    false
  end

  # 最新一份的编号（没有则 nil）
  def latest_index
    best = nil
    best_t = nil
    (1..COUNT).each do |i|
      next unless exist?(i)
      t = begin; File.mtime(filename(i)); rescue Exception; nil; end
      next if t.nil?
      if best_t.nil? || t > best_t
        best_t = t
        best = i
      end
    end
    best
  end

  def latest_time
    i = latest_index
    return nil if i.nil?
    begin; File.mtime(filename(i)); rescue Exception; nil; end
  end

  # 有空位先用空位，否则覆盖最老的一份 —— 5 份始终保有历史，
  # 写坏一份也不会把仅有的进度冲掉。
  def next_index
    (1..COUNT).each { |i| return i unless exist?(i) }
    best = 1
    best_t = nil
    (1..COUNT).each do |i|
      t = begin; File.mtime(filename(i)); rescue Exception; nil; end
      next if t.nil?
      if best_t.nil? || t < best_t
        best_t = t
        best = i
      end
    end
    best
  end

  # -------------------------------------------------------------------
  # 安全点：只在这些条件全部成立时落盘。
  #
  # 关键的一条是解释器空闲 —— 传送往往由事件里的「场所移动」触发，
  # 那一刻 map_interpreter 还在跑后续指令，存档里已经写进了新位置和
  # 半途改过的 self_switch，读回来就是半个演出，最容易卡剧情。
  # -------------------------------------------------------------------
  def safe_now?
    return false if $game_system.nil? || $game_map.nil? || $game_player.nil?
    return false if $game_system.save_disabled
    interpreter = $game_system.map_interpreter
    return false if interpreter && interpreter.running?
    return false if $game_temp.nil?
    return false if $game_temp.message_window_showing
    return false if $game_temp.player_transferring
    return false if $game_temp.transition_processing
    return false if $game_temp.battle_calling || $game_temp.in_battle
    return false if $game_temp.shop_calling
    return false if $game_temp.name_calling
    return false if $game_temp.menu_calling
    return false if $game_temp.gameover || $game_temp.to_title
    return false if $game_player.moving?
    true
  rescue Exception
    false
  end

  # 上次落盘的位置与时间。刻意用全局变量而不是 @ivar：
  # module_function 下模块方法的实例变量作用域在设备上不可靠
  # （实测 progressed? 一直返回 true，挂机会每 90 秒刷一份存档）。
  def mark_position(map_id, x, y)
    $tj_as_map = map_id
    $tj_as_x = x
    $tj_as_y = y
  end

  # 同一张图、同一格、间隔太短就不写：反复开关菜单不该把 5 份历史刷掉。
  # 另外无论位置如何，20 秒内不重复落盘 —— 门口来回走两步不该连写五份。
  def too_soon?
    return false if $tj_as_at.nil?
    gap = Time.now - $tj_as_at
    return true if gap < 20
    return false if $game_map.nil? || $game_player.nil?
    return false if $tj_as_map != $game_map.map_id
    return false if $tj_as_x != $game_player.x || $tj_as_y != $game_player.y
    gap < DEBOUNCE_SEC
  rescue Exception
    false
  end

  # -------------------------------------------------------------------
  # 「有进展」才值得存。
  #
  # 玩家挂机（切出去吃饭、手机放下）时位置一动没动，如果照样按定时器
  # 落盘，5 份全会被"同一格、同一时间之前"的存档占满，真正有进度的
  # 历史反而被挤掉。所以定时的前提是：地图换了，或者人挪过位置。
  # -------------------------------------------------------------------
  def progressed?
    return false if $game_map.nil? || $game_player.nil?
    return true if $tj_as_map.nil?
    return true if $tj_as_map != $game_map.map_id
    $tj_as_x != $game_player.x || $tj_as_y != $game_player.y
  rescue Exception
    false
  end

  def note_saved
    return if $game_map.nil? || $game_player.nil?
    mark_position($game_map.map_id, $game_player.x, $game_player.y)
    $tj_as_at = Time.now
  end

  # 读档之后立刻又自动存一次没有意义，还会挤掉刚读到的那份
  def note_loaded
    note_saved
  end

  def write
    index = next_index
    path  = filename(index)
    tmp   = path + ".tmp"
    begin
      characters = []
      $game_party.actors.each do |actor|
        characters.push([actor.character_name, actor.character_hue])
      end
      $game_system.magic_number = $data_system.magic_number
      # 先写临时文件再改名：写到一半被系统杀掉时，原存档仍然完整，
      # 不会出现"半截 Marshal 文件"让读档界面直接崩。
      File.open(tmp, "wb") do |file|
        Marshal.dump(characters, file)
        Marshal.dump(Graphics.frame_count, file)
        Marshal.dump($game_system, file)
        Marshal.dump($game_switches, file)
        Marshal.dump($game_variables, file)
        Marshal.dump($game_self_switches, file)
        Marshal.dump($game_screen, file)
        Marshal.dump($game_actors, file)
        Marshal.dump($game_party, file)
        Marshal.dump($game_troop, file)
        Marshal.dump($game_map, file)
        Marshal.dump($game_player, file)
      end
      File.delete(path) if FileTest.exist?(path)
      File.rename(tmp, path)
      note_saved
      true
    rescue Exception
      begin
        File.delete(tmp) if FileTest.exist?(tmp)
      rescue Exception
      end
      false
    end
  end

  def load_file(path)
    return false unless FileTest.exist?(path)
    begin
      File.open(path, "rb") do |file|
        Marshal.load(file)                  # 角色显示用数据
        Graphics.frame_count = Marshal.load(file)
        $game_system        = Marshal.load(file)
        $game_switches      = Marshal.load(file)
        $game_variables     = Marshal.load(file)
        $game_self_switches = Marshal.load(file)
        $game_screen        = Marshal.load(file)
        $game_actors        = Marshal.load(file)
        $game_party         = Marshal.load(file)
        $game_troop         = Marshal.load(file)
        $game_map           = Marshal.load(file)
        $game_player        = Marshal.load(file)
      end
      if $game_system.magic_number != $data_system.magic_number
        $game_map.setup($game_map.map_id)
        $game_player.center($game_player.x, $game_player.y)
      end
      $game_party.refresh
      $game_system.bgm_play($game_system.playing_bgm)
      $game_system.bgs_play($game_system.playing_bgs)
      $game_map.update
      note_loaded
      true
    rescue Exception
      false
    end
  end

  # 存档/读档界面把底部整行做成了「自动存档」入口，而这块区域和
  # 摇杆的跟手范围重叠，点击会被摇杆吃掉。用标记文件让 Java 层在
  # 这些界面停用摇杆；Scene_Map 每次进图都会清掉，异常残留也能自愈。
  JOY_MARKER = "tj_joy_off"

  def set_joystick(enabled)
    if enabled
      File.delete(JOY_MARKER) if FileTest.exist?(JOY_MARKER)
    else
      File.open(JOY_MARKER, "wb") { |f| f.write("1") }
    end
    true
  rescue Exception
    false
  end

  def time_text(time)
    return "--" if time.nil?
    time.strftime("%m/%d %H:%M")
  end

  def play_text(total_sec)
    total_sec = total_sec.to_i
    sprintf("%02d:%02d:%02d", total_sec / 3600, total_sec / 60 % 60, total_sec % 60)
  end
end


# =====================================================================
# 读档界面底部的「自动存档」入口条
# =====================================================================
class Window_AutoSaveEntry < Window_Base
  attr_reader :selected

  def initialize(y, height)
    super(0, y, 640, height)
    self.contents = Bitmap.new(width - 32, height - 32)
    @selected = false
    refresh
  end

  def refresh
    self.contents.clear
    self.contents.font.color = normal_color
    self.contents.draw_text(4, 0, 240, 32, "自动存档")
    time = TJAutoSave.latest_time
    if time.nil?
      self.contents.font.color = disabled_color
      self.contents.draw_text(4, 0, 600, 32, "暂无", 2)
    else
      self.contents.font.color = normal_color
      self.contents.draw_text(4, 0, 600, 32, TJAutoSave.time_text(time), 2)
      self.contents.font.color = disabled_color
      self.contents.draw_text(244, 0, 300, 32, "(#{TJAutoSave::COUNT} 份轮换)")
    end
  end

  def selected=(value)
    @selected = value
    update_cursor_rect
  end

  def update_cursor_rect
    if @selected
      self.cursor_rect.set(0, 0, 150, 32)
    else
      self.cursor_rect.empty
    end
  end
end


# =====================================================================
# 自动存档列表里的单行（和 Window_SaveFile 用同样的 @file_exist 名字，
# 这样 TJ_TouchLayer 的存档格点击逻辑可以原样复用）
# =====================================================================
class Window_AutoSaveFile < Window_Base
  attr_reader :index
  attr_reader :selected
  attr_reader :filename

  def initialize(index, y, height)
    super(0, y, 640, height)
    @index = index
    @filename = TJAutoSave.filename(index)
    @file_exist = FileTest.exist?(@filename)
    @time_stamp = nil
    @total_sec = 0
    if @file_exist
      begin
        File.open(@filename, "rb") do |file|
          Marshal.load(file)                       # 角色数据，不画
          frame_count = Marshal.load(file)
          @total_sec = frame_count.to_i / Graphics.frame_rate
        end
        @time_stamp = File.mtime(@filename)
      rescue Exception
        # 文件损坏：显示成空槽，绝不让读档界面崩掉
        @file_exist = false
      end
    end
    self.contents = Bitmap.new(width - 32, height - 32)
    @selected = false
    refresh
  end

  def refresh
    self.contents.clear
    self.contents.font.color = normal_color
    self.contents.draw_text(4, 0, 260, 26, "自动 #{@index}")
    if @file_exist
      self.contents.draw_text(4, 0, 600, 26, TJAutoSave.play_text(@total_sec), 2)
      self.contents.font.color = disabled_color
      self.contents.draw_text(4, 24, 600, 26, TJAutoSave.time_text(@time_stamp), 2)
    else
      self.contents.font.color = disabled_color
      self.contents.draw_text(4, 24, 600, 26, "空", 2)
    end
  end

  def selected=(value)
    @selected = value
    update_cursor_rect
  end

  def update_cursor_rect
    if @selected
      self.cursor_rect.set(0, 0, 150, 32)
    else
      self.cursor_rect.empty
    end
  end
end


# =====================================================================
# 二级界面：5 份自动存档
# ---------------------------------------------------------------------
# 刻意继承 Scene_File：TJ_TouchLayer 的 savefile_windows 只认
# Scene_File 子类的 @savefile_windows，继承以后 5 个格子的点击直接
# 复用，不用再给触摸层加一条分支。
# =====================================================================
class Scene_AutoSave < Scene_File
  TOP   = 64
  ROW_H = 82

  def initialize
    @help_text = "要载入哪一份自动存档？"
  end

  def main
    TJAutoSave.set_joystick(false)
    @help_window = Window_Help.new
    @help_window.set_text(@help_text)

    @savefile_windows = []
    TJAutoSave::COUNT.times do |i|
      @savefile_windows.push(
        Window_AutoSaveFile.new(i + 1, TOP + i * ROW_H, ROW_H))
    end

    @file_index = 0
    latest = TJAutoSave.latest_index
    @file_index = latest - 1 if latest && latest >= 1 && latest <= TJAutoSave::COUNT
    @savefile_windows[@file_index].selected = true

    Graphics.transition
    loop do
      Graphics.update
      Input.update
      update
      break if $scene != self
    end
    Graphics.freeze

    @help_window.dispose
    @savefile_windows.each { |w| w.dispose }
    TJAutoSave.set_joystick(true)
  end

  def update
    @help_window.update
    @savefile_windows.each { |w| w.update }

    if Input.trigger?(Input::C)
      on_decision(@file_index)
      return
    end

    if Input.trigger?(Input::B)
      on_cancel
      return
    end

    if Input.repeat?(Input::DOWN)
      if Input.trigger?(Input::DOWN) || @file_index < TJAutoSave::COUNT - 1
        $game_system.se_play($data_system.cursor_se)
        @savefile_windows[@file_index].selected = false
        @file_index = (@file_index + 1) % TJAutoSave::COUNT
        @savefile_windows[@file_index].selected = true
        return
      end
    end

    if Input.repeat?(Input::UP)
      if Input.trigger?(Input::UP) || @file_index > 0
        $game_system.se_play($data_system.cursor_se)
        @savefile_windows[@file_index].selected = false
        @file_index = (@file_index + TJAutoSave::COUNT - 1) % TJAutoSave::COUNT
        @savefile_windows[@file_index].selected = true
        return
      end
    end
  end

  # index 是数组下标（0 起），文件名编号是下标 + 1
  def on_decision(array_index)
    window = @savefile_windows[array_index]
    unless window && window.instance_variable_get(:@file_exist)
      $game_system.se_play($data_system.buzzer_se)
      return
    end
    path = TJAutoSave.filename(array_index + 1)
    $game_system.se_play($data_system.load_se)
    if TJAutoSave.load_file(path)
      $scene = Scene_Map.new
    else
      $game_system.se_play($data_system.buzzer_se)
    end
  end

  def on_cancel
    $game_system.se_play($data_system.cancel_se)
    # 原路返回：从菜单「读入」进来就回 Scene_Load2，标题进来就回 Scene_Load
    if defined?(Scene_Load2) && $tj_autosave_from == 2
      $scene = Scene_Load2.new
    else
      $scene = Scene_Load.new
    end
  end
end
