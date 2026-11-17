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

# --- canvas width follows the device aspect ratio -------------------------
# The game is authored for a 640x480 (4:3) canvas: 20x15 tiles, with all
# windows positioned against that frame. Stretching that frame onto a wide
# surface distorts every tile horizontally.
#
# Instead the canvas is widened to match the panel: 853x480 on 16:9,
# 960x480 on 18:9, up to 1066x480 (20:9). The vertical view keeps all 15
# tile rows and the art is never stretched -- the world simply shows more
# columns, the way ultrawide ports normally work (Hor+).
#
# 1066 is a deliberate ceiling: past 20:9 the extra columns cost more than
# they show, because 113 of the 183 maps are narrower than the 27 tiles a
# 16:9 canvas already reveals, so wider canvases mostly expose empty map
# data rather than scenery.
#
# The physical screen size is not available from RGSS, so MainActivity
# writes "WxH" into the game directory before the native library starts.
$tj_orig_w   = 640
$tj_orig_h   = 480
$tj_canvas_h = 480

$tj_aspect = begin
  raw = File.read("tj_screen").strip
  m = raw.match(/(\d+)\s*x\s*(\d+)/)
  if m && m[1].to_i > 0 && m[2].to_i > 0
    m[1].to_i.to_f / m[2].to_i
  else
    16.0 / 9.0
  end
rescue Exception
  16.0 / 9.0
end

$tj_canvas_w = ($tj_canvas_h * $tj_aspect).round
$tj_canvas_w = 640 if $tj_canvas_w < 640
$tj_canvas_w = 1066 if $tj_canvas_w > 1066
$tj_ui_shift = ($tj_canvas_w - $tj_orig_w) / 2

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
