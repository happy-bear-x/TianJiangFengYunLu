# =====================================================================
# ★ TJ_UIAlign — 组合界面横向重映射（注入脚本，必须位于 Main 之前）
# ---------------------------------------------------------------------
# 背景：mkxp_compat.rb 把所有恰好 640x480 的整屏背景图横向拉伸到
# 853 宽（zoom_x = 853/640 ≈ 1.333）。状态 / 物品 / 技能 / 商店 / 穿戴
# 等界面的窗口文字按 640 坐标系绘制，背景的砖块槽位却已按 1.333 平移
# 到 1.333*x 处，于是文字整体向左错位 106px（属性页文字压在砖块上）。
#
# 原 Window#initialize 钩子对游戏窗口无效：Window_Base#initialize 调
# super() 不带参数，随后直接 self.x = x / self.width = width，钩子
# 收不到坐标。本脚本 hook Window_Base#initialize（游戏脚本已定义完，
# 注入顺序保证在它们之后），对窗口施加与背景一致的仿射变换：
#
#   窗口 x、宽度 *= F（窗口边框随 windowskin 一起拉伸，风格统一）
#   contents 位图宽度 *= F（窗口矩形会裁剪 contents，必须加宽）
#   draw_text / blt / fill_rect / stretch_blt 的 x、宽度 *= F，
#     并补偿 contents 固定 16px 内缩：+ 16*(F-1)
#   cursor_rect 的 x、宽度 *= F（窗口坐标系，无内缩补偿）
#
# Window_Base#width 保持返回"原始设计宽度"，使所有以 self.width 推导
# 的布局（居中、列距）只被缩放一次；真实宽度经 tj_real_w 暴露。
#
# 适用场景（SCENES）是显式清单：背景图确实被拉伸的组合界面。
# 菜单/结束画面用的是小尺寸未拉伸素材，不在此列；标题画面已单独修过。
# =====================================================================

module TJUIAlign
  F = defined?($tj_canvas_w) ? $tj_canvas_w.to_f / $tj_orig_w : 1.0
  # contents 绘制原点固定在窗口 (16,16)：缩放后要补偿 16*(F-1)
  B = 16 * (F - 1)

  SCENES = []
  [:Scene_Status, :Scene_chuandai, :Scene_Item, :Scene_Item2,
   :Scene_Skill, :Scene_Shop, :Scene_Shopvip].each do |sym|
    begin
      k = Object.const_get(sym)
      SCENES << k if k.is_a?(Class)
    rescue Exception
      # 场景类不存在时跳过
    end
  end

  def self.active?
    !SCENES.empty? && SCENES.any? { |k| $scene.is_a?(k) }
  rescue Exception
    false
  end
end

if defined?(Window_Base)
  class Window_Base
    # 真实（缩放后）宽度，供触摸层命中测试等需要屏幕坐标的代码使用
    def tj_real_w
      @tj_real_w || self.width
    end

    alias_method :tj_align_initialize, :initialize
    def initialize(x, y, width, height)
      @tj_align = TJUIAlign.active?
      @tj_authored_w = width
      if @tj_align && TJUIAlign::F != 1.0
        @tj_real_w = (width * TJUIAlign::F).round
        # 原来的 Window_Base#initialize 内部还会执行 self.x = x，
        # 而 Window#x= 也挂了缩放钩子 —— 不设这个标志的话 x 会被
        # 缩放两次（F² = 1.78）。属性页的窗口 x 多为 0 所以没暴露，
        # 商店（x=192）会整块飞出屏幕右侧。
        nx = (x * TJUIAlign::F).round
        # 原版就贴右边缘的窗口（如商店列表 192+448=640），缩放到
        # 853 画布后右边界会超出，这里把它推回可见区域。
        if nx + @tj_real_w > Graphics.width
          nx = [Graphics.width - @tj_real_w, 0].max
        end
        @tj_initing = true
        begin
          tj_align_initialize(nx, y, @tj_real_w, height)
        ensure
          @tj_initing = false
        end
      else
        @tj_real_w = width
        # 存档/读档界面没有整屏背景，640 宽的窗口贴左会留 213px 黑边，
        # 顺手把它水平居中（窗口内容相对窗口绘制，整体平移即视觉居中）。
        nx = x
        if width == 640 && defined?(Scene_File) && $scene.is_a?(Scene_File)
          nx = x + (Graphics.width - 640) / 2
        end
        tj_align_initialize(nx, y, width, height)
      end
    end

    # 布局推导一律看"设计宽度"，避免与绘制坐标缩放叠加成双重缩放
    def width
      @tj_authored_w || super
    end
  end
end

if defined?(Window)
  # RGSS 移动光标用的是 self.cursor_rect.set(x, y, w, h)：拿到 Rect 之后就
  # 地修改，不会走 cursor_rect= 的钩子。所以文字被放大 1.333 倍、光标却
  # 还是原尺寸原间距，商店「是/否」两个选项就对不上了。
  #
  # 这里让 getter 返回一个代理：写入时乘 F，读出时除回 F，调用方看到的
  # 仍然是设计坐标系。
  class TJCursorProxy
    def initialize(rect, f)
      @rect = rect
      @f = f
    end

    def set(x, y, w, h)
      @rect.set((x * @f).round, y, (w * @f).round, h)
    end

    def empty
      @rect.empty
    end

    def x
      (@rect.x / @f).round
    end

    def width
      (@rect.width / @f).round
    end

    def y
      @rect.y
    end

    def height
      @rect.height
    end

    def method_missing(name, *args, &blk)
      @rect.send(name, *args, &blk)
    end

    def respond_to_missing?(name, include_private = false)
      @rect.respond_to?(name, include_private)
    end
  end

  class Window
    alias_method :tj_align_cursor_get, :cursor_rect
    def cursor_rect
      r = tj_align_cursor_get
      return r if r.nil?
      return r unless @tj_align && TJUIAlign::F != 1.0
      TJCursorProxy.new(r, TJUIAlign::F)
    end

    # 场景代码在窗口创建后重定位（@win.x = ...）同样要映射
    alias_method :tj_align_x_eq, :x=
    def x=(v)
      if @tj_align && !@tj_initing && v.is_a?(Numeric)
        v = (v * TJUIAlign::F).round
        w = @tj_real_w || self.width
        v = [Graphics.width - w, 0].max if v + w > Graphics.width
      end
      tj_align_x_eq(v)
    end

    # 子类在 super 之后才创建 contents，这里统一加宽并打标记
    alias_method :tj_align_contents_eq, :contents=
    def contents=(bmp)
      if @tj_align && bmp.is_a?(Bitmap) && TJUIAlign::F != 1.0
        w2 = (bmp.width * TJUIAlign::F).round
        if w2 > bmp.width
          nb = Bitmap.new(w2, bmp.height)
          nb.instance_variable_set(:@tj_f, TJUIAlign::F)
          bmp = nb
        else
          bmp.instance_variable_set(:@tj_f, TJUIAlign::F)
        end
      end
      tj_align_contents_eq(bmp)
    end

    # cursor_rect 是窗口坐标系：x 与背景变换一致地乘 F，无内缩补偿。
    # 部分脚本用缩放后的 contents.width 直接当光标宽（>400），
    # 这类已是真实坐标，不再放大。
    alias_method :tj_align_cursor_eq, :cursor_rect=
    def cursor_rect=(r)
      if @tj_align && r.is_a?(Rect) && TJUIAlign::F != 1.0
        nw = r.width.to_i > 400 ? r.width : (r.width * TJUIAlign::F).round
        r2 = Rect.new((r.x * TJUIAlign::F).round, r.y, nw, r.height)
        tj_align_cursor_eq(r2)
      else
        tj_align_cursor_eq(r)
      end
    end
  end
end

if defined?(Bitmap)
  class Bitmap
    alias_method :tj_align_draw_text, :draw_text
    def draw_text(*args)
      f = @tj_f
      if f && TJUIAlign::F != 1.0
        b = TJUIAlign::B
        a = args.dup
        if a[0].is_a?(Rect)
          r = a[0]
          a[0] = Rect.new((r.x * f + b).round, r.y,
                          (r.width * f).round, r.height)
        elsif a.size >= 5
          a[0] = (a[0] * f + b).round
          a[2] = (a[2] * f).round
        end
        return tj_align_draw_text(*a)
      end
      tj_align_draw_text(*args)
    end

    alias_method :tj_align_blt, :blt
    def blt(x, y, src_bitmap, src_rect, opacity = 255)
      if @tj_f && TJUIAlign::F != 1.0
        x = (x * @tj_f + TJUIAlign::B).round
      end
      tj_align_blt(x, y, src_bitmap, src_rect, opacity)
    end

    alias_method :tj_align_fill_rect, :fill_rect
    def fill_rect(*args)
      f = @tj_f
      if f && TJUIAlign::F != 1.0
        b = TJUIAlign::B
        a = args.dup
        if a[0].is_a?(Rect)
          r = a[0]
          a[0] = Rect.new((r.x * f + b).round, r.y,
                          (r.width * f).round, r.height)
        elsif a.size >= 5
          a[0] = (a[0] * f + b).round
          a[2] = (a[2] * f).round
        end
        return tj_align_fill_rect(*a)
      end
      tj_align_fill_rect(*args)
    end

    alias_method :tj_align_stretch_blt, :stretch_blt
    def stretch_blt(dest_rect, src_bitmap, src_rect)
      if @tj_f && dest_rect.is_a?(Rect) && TJUIAlign::F != 1.0
        dest_rect = Rect.new((dest_rect.x * @tj_f + TJUIAlign::B).round,
                             dest_rect.y,
                             (dest_rect.width * @tj_f).round,
                             dest_rect.height)
      end
      tj_align_stretch_blt(dest_rect, src_bitmap, src_rect)
    end
  end
end
