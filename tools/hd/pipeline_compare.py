"""高清放大管线实测：在真实倍率下对比五条管线

背景（已从引擎源码确认）：
  逻辑画布 scRes = 853x480（16:9 时 $tj_canvas_w = 480*aspect）
  真机 1080p 屏 → 853x480 放大到 1920x1080 = 2.25x 非整数
  现状：smoothScaling=false → GL_NEAREST 一把 2.25x
  引擎已有 integerScale 机制（graphics.cpp:1041），可做 2x 整数 + 收尾缩放

本脚本对比的五条管线：
  A 现状      直接 NEAREST 2.25x
  B 插值      直接 BILINEAR 2.25x
  C 锐化      LANCZOS + unsharp 2.25x
  D 整数缩放  NEAREST 2x → NEAREST 1.125x   （现有 integerScale 开关，零代码改动）
  E MMPX      MMPX 2x   → NEAREST 1.125x   （需新增 shader）
  F MMPX软收尾 MMPX 2x   → BILINEAR 1.125x

用法：python tools/hd/pipeline_compare.py
输出：docs/hd-research/pipeline-*.png
"""
import os
import sys
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mmpx import mmpx2x

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GRAPHICS = os.path.join(ROOT, "tianjiang_game", "Graphics")
OUT = os.path.join(ROOT, "docs", "hd-research")
os.makedirs(OUT, exist_ok=True)

# 853x480 -> 1920x1080 的真实倍率
SRC_W, SRC_H = 853, 480
DST_W, DST_H = 1920, 1080
TWO_X = (SRC_W * 2, SRC_H * 2)          # 1706x960
FROM_2X = (DST_W / TWO_X[0], DST_H / TWO_X[1])   # 1.125 x 1.125


def resize(im, size, method):
    return im.resize(size, method)


def midpoint(im, size):
    """Image.NEAREST 的替代：手工整数像素复制，保证完全无插值。

    注意 size 是 PIL 约定的 (width, height)。
    """
    a = np.asarray(im)
    h, w = a.shape[:2]
    tw, th = size
    yi = (np.arange(th) * h // th)
    xi = (np.arange(tw) * w // tw)
    return Image.fromarray(a[yi][:, xi])


def scale2x(arr):
    """Scale2x / EPX：纯规则边缘感知放大 2x，不产生新颜色。通道数自适应。"""
    src = arr.astype(np.int32)
    h, w, ch = src.shape
    pad = np.pad(src, ((1, 1), (1, 1), (0, 0)), mode="edge")
    a = pad[0:h, 1:w + 1]      # 上
    b = pad[1:h + 1, 2:w + 2]  # 右
    c = pad[1:h + 1, 0:w]      # 左
    d = pad[2:h + 2, 1:w + 1]  # 下
    p = pad[1:h + 1, 1:w + 1]  # 中心

    out = np.empty((h * 2, w * 2, ch), dtype=np.uint8)
    e0 = np.where((d == b) & (b != a) & (d != c), d, p)
    e1 = np.where((b == a) & (b != c) & (a != d), b, p)
    e2 = np.where((d == c) & (d != a) & (c != b), d, p)
    e3 = np.where((a == c) & (a != b) & (c != d), a, p)
    out[0::2, 0::2] = e0.astype(np.uint8)
    out[0::2, 1::2] = e1.astype(np.uint8)
    out[1::2, 0::2] = e2.astype(np.uint8)
    out[1::2, 1::2] = e3.astype(np.uint8)
    return out


def unsharp(im, radius=1.2, percent=90):
    from PIL import ImageFilter
    blur = im.filter(ImageFilter.GaussianBlur(radius))
    a = np.asarray(im, np.float32)
    b = np.asarray(blur, np.float32)
    return Image.fromarray(np.clip(a + (a - b) * (percent / 100.0), 0, 255).astype(np.uint8))


# ---------------- 六条管线 ----------------

def pipe_a(src):
    """现状：nearest 2.25x"""
    return midpoint(src, (DST_W, DST_H))


def pipe_b(src):
    """bilinear 2.25x"""
    return resize(src, (DST_W, DST_H), Image.BILINEAR)


def pipe_c(src):
    """lanczos + 锐化"""
    return unsharp(resize(src, (DST_W, DST_H), Image.LANCZOS))


def pipe_d(src):
    """nearest 2x + nearest 1.125x —— 现有 integerScale 开关的效果"""
    mid = midpoint(src, TWO_X)
    return midpoint(mid, (DST_W, DST_H))


def pipe_e(src):
    """MMPX 2x + nearest 1.125x"""
    a = np.asarray(src.convert("RGB"))
    up = Image.fromarray(mmpx2x(a))
    return midpoint(up, (DST_W, DST_H))


def pipe_f(src):
    """MMPX 2x + bilinear 1.125x"""
    a = np.asarray(src.convert("RGB"))
    up = Image.fromarray(mmpx2x(a))
    return resize(up, (DST_W, DST_H), Image.BILINEAR)


def pipe_g(src):
    """MMPX 2x + LANCZOS 1.125x —— 收尾更锐"""
    a = np.asarray(src.convert("RGB"))
    up = Image.fromarray(mmpx2x(a))
    return resize(up, (DST_W, DST_H), Image.LANCZOS)


def pipe_h(src):
    """EPX(Scale2x) 2x + nearest 1.125x —— 最轻量的规则型算法做对照"""
    a = np.asarray(src.convert("RGB"))
    up = Image.fromarray(scale2x(a))
    return midpoint(up, (DST_W, DST_H))


def pipe_i(src):
    """MMPX 2x，不做收尾缩放，直接 1080p 中心裁切 —— 代表"完美整数倍"的理论上限"""
    a = np.asarray(src.convert("RGB"))
    up = Image.fromarray(mmpx2x(a))          # 1706x960
    canvas = Image.new("RGB", (DST_W, DST_H), (0, 0, 0))
    canvas.paste(up, ((DST_W - up.width) // 2, (DST_H - up.height) // 2))
    return canvas


PIPES = [
    ("A 现状 NEAREST 2.25x", pipe_a),
    ("B BILINEAR 2.25x", pipe_b),
    ("C LANCZOS+锐化", pipe_c),
    ("D NEAREST 2x+1.125x", pipe_d),
    ("E MMPX 2x+NEAREST", pipe_e),
    ("F MMPX 2x+BILINEAR", pipe_f),
    ("G MMPX 2x+LANCZOS", pipe_g),
    ("H EPX 2x+NEAREST", pipe_h),
    ("I MMPX 2x 无收尾(理想)", pipe_i),
]


# ---------------- 拼图 ----------------

def label(text, width, height=22):
    bar = Image.new("RGB", (width, height), (248, 248, 250))
    d = ImageDraw.Draw(bar)
    d.text((6, 5), text, fill=(20, 20, 24))
    return bar


def build(src_crop, crop_box, scale_hint, out_name, cols=3):
    """src_crop 是 853x480 源图；crop_box 在源图坐标系里取一块放大细看"""
    tiles = []
    for name, fn in PIPES:
        out = fn(src_crop)
        k = DST_W / src_crop.width
        x0 = int(crop_box[0] * k); y0 = int(crop_box[1] * k)
        x1 = int(crop_box[2] * k); y1 = int(crop_box[3] * k)
        piece = out.crop((x0, y0, x1, y1))
        t = Image.new("RGB", (piece.width, piece.height + 22), (32, 32, 36))
        t.paste(piece, (0, 22))
        t.paste(label(name, piece.width), (0, 0))
        tiles.append(t)

    cw = max(t.width for t in tiles)
    ch = max(t.height for t in tiles)
    rows = (len(tiles) + cols - 1) // cols
    canvas = Image.new("RGB", (cw * cols + 8 * (cols - 1), ch * rows + 8 * (rows - 1)), (60, 60, 66))
    for i, t in enumerate(tiles):
        r, c = divmod(i, cols)
        canvas.paste(t, (c * (cw + 8), r * (ch + 8)))
    path = os.path.join(OUT, out_name)
    canvas.save(path)
    print(f"  -> {out_name}  {canvas.size}")
    return path


def make_source_from_asset(path, size):
    """把素材图平铺成 853x480 的"画面"，像素完全来自原素材。"""
    im = Image.open(path).convert("RGB")
    canvas = Image.new("RGB", size)
    for y in range(0, size[1], im.height):
        for x in range(0, size[0], im.width):
            canvas.paste(im, (x, y))
    return canvas


def main():
    print("构建源画面（853x480）...")
    tiles = make_source_from_asset(os.path.join(GRAPHICS, "Tilesets", "室内.png"), (SRC_W, SRC_H))
    print("  图块源:", tiles.size)

    print("生成管线对比（裁剪 90x64 源区域，1:1 像素显示）...")
    build(tiles, (104, 64, 194, 128), 2.25, "pipeline-tiles.png")

    # 行走图：单独放大一张，看角色轮廓
    char_path = os.path.join(GRAPHICS, "Characters")
    names = sorted(os.listdir(char_path))
    print("  角色素材:", names[:3])
    ch = Image.open(os.path.join(char_path, names[0])).convert("RGB")

    # 拼成 853x480：角色图 + 背景
    bg = Image.new("RGB", (SRC_W, SRC_H), (40, 44, 36))
    for ty in range(0, SRC_H, ch.height):
        for tx in range(0, SRC_W, ch.width):
            bg.paste(ch, (tx, ty))
    build(bg, (8, 8, 98, 72), 2.25, "pipeline-chars.png")

    # 标题图：640x480 撑满
    title = Image.open(os.path.join(GRAPHICS, "Titles", "Title.png")).convert("RGB")
    print("  标题素材:", title.size)
    tb = title.resize((SRC_W, SRC_H), Image.LANCZOS)
    build(tb, (250, 150, 340, 214), 2.25, "pipeline-title.png")

    print("完成。输出目录:", OUT)


if __name__ == "__main__":
    main()
