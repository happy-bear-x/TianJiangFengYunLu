# Compatibility shim for the Android RGSS runtime.
# The game's optional keyboard/IME helpers use Win32-only libraries.
# Replace Win32API with a safe no-op implementation before the game
# scripts are executed. Standard RPG Maker input still works.
if defined?(Win32API)
  Object.send(:remove_const, :Win32API)
end

class Win32API
  def initialize(dll, func, *args)
    @func = func.to_s
  end

  def call(*args)
    case @func
    when 'GetPrivateProfileString', 'GetWndText',
         'MultiByteToWideChar', 'WideCharToMultiByte'
      ''
    else
      0
    end
  end
  alias Call call
end

# --- 16:9 canvas ---------------------------------------------------------
# The game is authored for a 640x480 (4:3) canvas: 20x15 tiles, with all
# windows positioned against that frame. Stretching that frame onto a 16:9
# surface distorts every tile by 33% horizontally.
#
# Widen the canvas to 853x480 instead (1.7771, i.e. 16:9 to within 0.04%).
# Filling the screen then becomes an even ~1.5x scale in both axes, so
# nothing is stretched and the vertical view keeps all 15 tile rows.
#
# The extra 213 columns have to be filled by the game itself:
#   * Viewports are widened so the tilemap draws into them. The engine's
#     tilemap repeats the border tile past the map edge (see tilemap.cpp),
#     so small maps no longer show a black band.
#   * Windows are shifted right by half the extra width to stay centred.
#   * Full-screen artwork (title, battle back) is a 640x480 bitmap on a
#     sprite; scale it horizontally so it covers the wider canvas.
$tj_orig_w   = 640
$tj_orig_h   = 480
$tj_canvas_w = 853
$tj_canvas_h = 480
$tj_ui_shift = ($tj_canvas_w - $tj_orig_w) / 2   # 106

begin
  if defined?(Graphics) && Graphics.respond_to?(:resize_screen)
    Graphics.resize_screen($tj_canvas_w, $tj_canvas_h)
  end
rescue Exception
  # never let a resize failure abort startup
end

# Every Viewport in the game is created as Viewport.new(0, 0, 640, 480).
if defined?(Viewport)
  class Viewport
    alias_method :__tj_vp_init, :initialize
    def initialize(*args)
      if args.size >= 4 && args[2].to_i == $tj_orig_w && args[3].to_i == $tj_orig_h
        args[2] = $tj_canvas_w
        args[3] = $tj_canvas_h
      end
      __tj_vp_init(*args)
    end
  end
end

if defined?(Window)
  class Window
    alias_method :__tj_win_init, :initialize
    def initialize(*args)
      if args.size >= 1 && args[0].is_a?(Integer)
        args[0] = args[0] + $tj_ui_shift
      end
      __tj_win_init(*args)
    end
  end
end

# Only 640x480 bitmaps are full-screen artwork. Character chips, icons and
# tilesets never match, so they are left untouched.
if defined?(Sprite)
  class Sprite
    alias_method :__tj_bmp_set, :bitmap=
    def bitmap=(bmp)
      __tj_bmp_set(bmp)
      return if bmp.nil?
      if bmp.width == $tj_orig_w && bmp.height == $tj_orig_h
        self.zoom_x = $tj_canvas_w.to_f / bmp.width
      end
    rescue Exception
      # a failed scale must never break the caller
    end
  end
end
