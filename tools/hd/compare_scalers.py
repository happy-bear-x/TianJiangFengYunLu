"""对比常见放大算法在《天降风云录》真实素材上的表现。

用途：为高清修复方案选型提供可视证据，不参与构建。
运行：python tools/hd/compare_scalers.py
输出：docs/hd-research/*.png
"""

import os
import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GFX = os.path.join(ROOT, "tianjiang_game", "Graphics")
OUT = os.path.join(ROOT, "docs", "hd-research")


def rgba(arr):
    """统一成 RGBA ndarray。"""
    return np.asarray(arr.convert("RGBA"), dtype=np.uint8)


def nearest(arr, factor):
    im = Image.fromarray(arr, "RGBA")
    return np.asarray(im.resize(
        (int(arr.shape[1] * factor), int(arr.shape[0] * factor)),
        Image.NEAREST), dtype=np.uint8)


def bilinear(arr, factor):
    im = Image.fromarray(arr, "RGBA")
    return np.asarray(im.resize(
        (int(arr.shape[1] * factor), int(arr.shape[0] * factor)),
        Image.BILINEAR), dtype=np.uint8)


def lanczos(arr, factor):
    im = Image.fromarray(arr, "RGBA")
    return np.asarray(im.resize(
        (int(arr.shape[1] * factor), int(arr.shape[0] * factor)),
        Image.LANCZOS), dtype=np.uint8)


def lanczos_sharp(arr, factor, percent=60, radius=1.0):
    """Lanczos + 轻锐化，模拟"换插值 + 后处理"能做到的上限。"""
    out = lanczos(arr, factor)
    im = Image.fromarray(out, "RGBA").filter(
        ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=0))
    return np.asarray(im, dtype=np.uint8)


def scale2x(arr):
    """Scale2x / EPX：纯规则边缘感知放大 2x，无浮点插值、不产生新颜色。"""
    src = arr.astype(np.int32)
    h, w = src.shape[:2]
    pad = np.pad(src, ((1, 1), (1, 1), (0, 0)), mode="edge")
    a = pad[0:h,     1:w + 1]   # 上
    b = pad[1:h + 1, 2:w + 2]   # 右
    c = pad[1:h + 1, 0:w]       # 左
    d = pad[2:h + 2, 1:w + 1]   # 下
    p = pad[1:h + 1, 1:w + 1]   # 中心

    out = np.empty((h * 2, w * 2, 4), dtype=np.uint8)
    e0 = np.where((d == b) & (b != a) & (d != c), d, p)
    e1 = np.where((b == a) & (b != c) & (a != d), b, p)
    e2 = np.where((d == c) & (d != a) & (c != b), d, p)
    e3 = np.where((a == c) & (a != b) & (c != d), a, p)

    out[0::2, 0::2] = e0.astype(np.uint8)
    out[0::2, 1::2] = e1.astype(np.uint8)
    out[1::2, 0::2] = e2.astype(np.uint8)
    out[1::2, 1::2] = e3.astype(np.uint8)
    return out


def crop(arr, box):
    x, y, w, h = box
    return arr[y:y + h, x:x + w]


def label_strip(width, height, text):
    """顶部标签条，粗略的 bitmap 字体由 PIL 默认字体绘制。"""
    from PIL import ImageDraw
    bar = Image.new("RGBA", (width, height), (24, 24, 28, 255))
    d = ImageDraw.Draw(bar)
    d.text((6, 4), text, fill=(235, 235, 240, 255))
    return np.asarray(bar, dtype=np.uint8)


def compose(panels, gap=8, bg=18, labels=None):
    """panels: list of HxWx3/x4 ndarray，横向拼接。"""
    prepared = []
    for p in panels:
        if p.shape[2] == 4:
            bgc = Image.new("RGB", (p.shape[1], p.shape[0]), (18, 18, 22))
            bgc.paste(Image.fromarray(p, "RGBA"), (0, 0),
                      Image.fromarray(p[:, :, 3], "L"))
            p = np.asarray(bgc, dtype=np.uint8)
        prepared.append(p)
    h = max(p.shape[0] for p in prepared)
    w = sum(p.shape[1] for p in prepared) + gap * (len(prepared) - 1)

    out = Image.new("RGB", (w, h), (bg, bg, bg + 4))
    x = 0
    for p in prepared:
        out.paste(Image.fromarray(p, "RGB"), (x, h - p.shape[0]))
        x += p.shape[1] + gap
    return np.asarray(out, dtype=np.uint8)


def build_case(name, arr, box, factor, out_file, bg_fill=None):
    """对整图做各算法 → 裁同一区域 → 拼图。"""
    src = arr
    variants = []

    def add(label, up):
        piece = crop(up, box)
        if piece.shape[2] == 3:
            piece = np.dstack(
                [piece, np.full(piece.shape[:2], 255, dtype=np.uint8)])
        if bg_fill:
            # 棋盘底，便于观察半透明边缘
            tile = 8
            hh, ww = piece.shape[:2]
            yy, xx = np.mgrid[0:hh, 0:ww]
            checker = ((yy // tile + xx // tile) % 2).astype(np.uint8)
            base = np.where(checker[:, :, None] == 0, 40, 62).astype(np.uint8)
            base = np.repeat(base, 3, axis=2)
            alpha = piece[:, :, 3:4].astype(np.float32) / 255.0
            rgb = (piece[:, :, :3].astype(np.float32) * alpha
                   + base.astype(np.float32) * (1 - alpha)).astype(np.uint8)
            piece = np.dstack(
                [rgb, np.full(piece.shape[:2], 255, dtype=np.uint8)])
        strip = label_strip(piece.shape[1], 18, label)
        variants.append(np.vstack([strip, piece]))

    add("NEAREST (现状)", nearest(src, factor))
    add("BILINEAR", bilinear(src, factor))
    add("LANCZOS", lanczos(src, factor))
    add("LANCZOS+SHARP", lanczos_sharp(src, factor))
    add("SCALE2X -> RESIZE", lanczos(scale2x(src), factor / 2.0))

    img = compose(variants)
    path = os.path.join(OUT, out_file)
    Image.fromarray(img).save(path)
    print("written", path, img.shape)
    return path


def main():
    os.makedirs(OUT, exist_ok=True)

    # 1) 标题画面：640x480 → 2.25x，1080p 实机就是这么做
    title = rgba(Image.open(os.path.join(GFX, "Titles", "Title.png")))
    build_case("title", title, (150, 120, 340, 220), 2.25, "compare-title.png")

    # 2) 图块集：32px 图块 3x，观察边缘与接缝
    tiles = rgba(Image.open(os.path.join(GFX, "Tilesets", "室内.png")))
    build_case("tiles", tiles, (0, 0, 160, 160), 3.0, "compare-tiles.png",
               bg_fill=True)

    # 3) 行走图：32x48 小人 3x
    chars = rgba(Image.open(os.path.join(GFX, "Characters", "001.png")))
    build_case("char", chars, (0, 0, 128, 192), 3.0, "compare-char.png",
               bg_fill=True)


if __name__ == "__main__":
    main()
