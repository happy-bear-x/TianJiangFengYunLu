"""MMPX 收益取证：把同一局部再放大 4 倍，消除"看不出差别"的争议

左：现状 NEAREST 2.25x   右：MMPX 2x + NEAREST 1.125x
两边都从 1920x1080 输出里裁同一块，再各自 nearest 4x，纯像素展示。

用法：python tools/hd/proof_zoom.py
"""
import os
import sys
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline_compare as pc

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "docs", "hd-research")
ZOOM = 5


def zoom_nearest(im, k):
    a = np.asarray(im)
    return Image.fromarray(np.repeat(np.repeat(a, k, axis=0), k, axis=1))


def strip(text, w, h=24):
    bar = Image.new("RGB", (w, h), (250, 250, 252))
    ImageDraw.Draw(bar).text((8, 6), text, fill=(16, 16, 20))
    return bar


def case(src, box_src, title, fname):
    """box_src 是源图坐标下的裁剪框（853x480 坐标系）"""
    k = pc.DST_W / src.width
    box = (int(box_src[0] * k), int(box_src[1] * k),
           int(box_src[2] * k), int(box_src[3] * k))

    a = pc.pipe_a(src).crop(box)
    e = pc.pipe_e(src).crop(box)

    # 保证尺寸一致（2.25 取整可能差 1px）
    w = min(a.width, e.width); h = min(a.height, e.height)
    a = a.crop((0, 0, w, h)); e = e.crop((0, 0, w, h))

    a = zoom_nearest(a, ZOOM)
    e = zoom_nearest(e, ZOOM)

    gap = 12
    W = a.width + e.width + gap
    H = a.height + 24
    canvas = Image.new("RGB", (W, H), (55, 55, 62))
    canvas.paste(strip("现状 NEAREST 2.25x", a.width), (0, 0))
    canvas.paste(a, (0, 24))
    canvas.paste(strip("MMPX 2x + 1.125x", e.width), (a.width + gap, 0))
    canvas.paste(e, (a.width + gap, 24))

    head = strip(title, W)
    final = Image.new("RGB", (W, H + 24), (55, 55, 62))
    final.paste(head, (0, 0))
    final.paste(canvas, (0, 24))

    path = os.path.join(OUT, fname)
    final.save(path)
    print(f"  -> {fname}  {final.size}")
    return path


def main():
    chars = pc.make_source_from_asset(
        os.path.join(pc.GRAPHICS, "Characters", "001.png"), (pc.SRC_W, pc.SRC_H))
    tiles = pc.make_source_from_asset(
        os.path.join(pc.GRAPHICS, "Tilesets", "室内.png"), (pc.SRC_W, pc.SRC_H))

    print("生成取证图（取完整角色帧 32x64，放大 5 倍展示）...")
    case(chars, (0, 0, 32, 64), "角色整帧（32x64 源，nearest 5x 展示）", "proof-zoom-char.png")
    case(tiles, (96, 64, 160, 128), "图块（64x64 源，nearest 5x 展示）", "proof-zoom-tile.png")


if __name__ == "__main__":
    main()
