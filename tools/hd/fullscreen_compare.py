"""全屏效果对比：三种交付形态，让"填满 vs 像素完美"的取舍可见

源用真实游戏截图 final16-map.png 缩到逻辑画布 853x480 后重放，
输出统一模拟 1920x1080 手机屏。

  ① 现状      NEAREST 2.25x                     填满
  ② 推荐      MMPX 2x + NEAREST 1.125x          填满
  ③ 像素完美  MMPX 2x 居中 + 黑边                画面 1706x960，左右各 107px、上下各 60px 黑边

用法：python tools/hd/fullscreen_compare.py
"""
import os
import sys
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mmpx import mmpx2x
import pipeline_compare as pc

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "docs", "hd-research")
SHOTS = os.path.abspath(os.path.join(ROOT, "..", "shots"))


def nearest(im, size):
    return pc.midpoint(im, size)


def main():
    src_path = os.path.join(SHOTS, "final16-map.png")
    shot = Image.open(src_path).convert("RGB")
    print("参考截图:", shot.size)

    # 截图是 853x480 的 1.5x，缩回逻辑画布作为"源"
    src = shot.resize((pc.SRC_W, pc.SRC_H), Image.LANCZOS)
    src.save(os.path.join(OUT, "fullscreen-source.png"))

    # ① 现状
    a = nearest(src, (pc.DST_W, pc.DST_H))

    # ② MMPX + 1.125x nearest
    up = Image.fromarray(mmpx2x(np.asarray(src)))
    b = nearest(up, (pc.DST_W, pc.DST_H))

    # ③ MMPX 2x 居中带黑边
    c = Image.new("RGB", (pc.DST_W, pc.DST_H), (0, 0, 0))
    c.paste(up, ((pc.DST_W - up.width) // 2, (pc.DST_H - up.height) // 2))

    panels = [
        ("① 现状  NEAREST 2.25x  (填满)", a),
        ("② 推荐  MMPX 2x + 1.125x  (填满)", b),
        ("③ 像素完美  MMPX 2x + 黑边  (画面缩至 88.9%)", c),
    ]

    # 排成 1 列 3 行，每张缩到 760 宽便于查看
    disp_w = 760
    tiles = []
    for title, im in panels:
        h = int(im.height * disp_w / im.width)
        small = im.resize((disp_w, h), Image.LANCZOS)
        t = Image.new("RGB", (disp_w, h + 26), (28, 28, 32))
        d = ImageDraw.Draw(t)
        d.text((8, 7), title, fill=(240, 240, 245))
        t.paste(small, (0, 26))
        tiles.append(t)

    gap = 10
    W = disp_w
    H = sum(t.height for t in tiles) + gap * (len(tiles) - 1)
    canvas = Image.new("RGB", (W, H), (50, 50, 56))
    y = 0
    for t in tiles:
        canvas.paste(t, (0, y))
        y += t.height + gap

    out = os.path.join(OUT, "fullscreen-options.png")
    canvas.save(out)
    print("->", out, canvas.size)

    # 顺带算一下 2x 缓冲的显存与黑边比例
    print(f"\n2x 缓冲 {up.size} = {up.width*up.height*4/1048576:.1f} MB (RGBA)")
    print(f"黑边方案画面占比: {(up.width*up.height)/(pc.DST_W*pc.DST_H)*100:.1f}%")


if __name__ == "__main__":
    main()
