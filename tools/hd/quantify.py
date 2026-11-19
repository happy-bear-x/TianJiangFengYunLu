"""管线定量评估：用可量化指标比较各放大方案

指标说明
--------
1. 唯一颜色数 unique_colors
   像素画的核心特征是"受调色板约束"。规则型算法（MMPX/EPX）只重排已有像素，
   不产生新颜色；插值类（BILINEAR/LANCZOS）会造出大量中间色，导致画面"脏"、
   且和原画配色脱节。这一项能硬性区分两类算法。

2. Tenengrad 梯度能量 sharpness
   sum(Gx^2 + Gy^2)，Sobel。越高越锐利。但注意：nearest 也会很高（硬台阶），
   所以必须和第 3 项一起看。

3. 边缘台阶率 stair_ratio
   沿 45 度斜线方向，检测"应该连续却断开成台阶"的比例。越低说明斜线越顺。
   这是区分"锐利但有锯齿"和"锐利且顺滑"的关键。

4. 与 4x 参考的偏差 ref_rmse
   先把源图用 LANCZOS 4x 放大、再 LANCZOS 缩回目标尺寸，作为"平滑参考"，
   计算与各方案结果的 RMSE。反映整体形状是否贴近真实轮廓。
   （不是绝对真值，只用于横向比较）

用法：python tools/hd/quantify.py
"""
import os
import sys
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline_compare as pc


def unique_colors(im):
    a = np.asarray(im.convert("RGB"))
    return len(np.unique(a.reshape(-1, 3), axis=0))


def tenengrad(im):
    a = np.asarray(im.convert("L"), np.float32)
    # Sobel
    kx = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], np.float32)
    ky = kx.T
    from scipy.signal import convolve2d  # noqa
    gx = convolve2d(a, kx, mode="same", boundary="symm")
    gy = convolve2d(a, ky, mode="same", boundary="symm")
    return float(np.mean(gx * gx + gy * gy))


def stair_ratio(im):
    """沿 45 度方向统计"斜线断裂"比例。

    做法：把图按 45 度方向做一次轻微平滑投影，比较 45 度邻域与 90 度邻域的
    梯度一致性。台阶越明显，45 度方向的局部方差越大。
    这里用更直接的代理：统计每个像素在 45 度方向上的二阶差分能量占比。
    """
    a = np.asarray(im.convert("L"), np.float32)
    # 45 度二阶差分
    d45 = np.abs(a[:-2, :-2] - 2 * a[1:-1, 1:-1] + a[2:, 2:])
    d135 = np.abs(a[:-2, 2:] - 2 * a[1:-1, 1:-1] + a[2:, :-2])
    dh = np.abs(a[:-2, 1:-1] - 2 * a[1:-1, 1:-1] + a[2:, 1:-1])
    dv = np.abs(a[1:-1, :-2] - 2 * a[1:-1, 1:-1] + a[1:-1, 2:])
    diag = d45.mean() + d135.mean()
    ax = dh.mean() + dv.mean() + 1e-6
    # 对角线二阶差分 / 轴向二阶差分。像素画的台阶会让对角能量偏高
    return float(diag / ax)


def ref_rmse(im, src, out_size):
    """用 LANCZOS 4x 再缩回作为平滑参考，算 RMSE。"""
    ref = src.resize((src.width * 4, src.height * 4), Image.LANCZOS)
    ref = ref.resize(out_size, Image.LANCZOS)
    a = np.asarray(im.convert("RGB"), np.float32)
    b = np.asarray(ref, np.float32)
    return float(np.sqrt(np.mean((a - b) ** 2)))


def main():
    tests = [
        ("图块", pc.make_source_from_asset(
            os.path.join(pc.GRAPHICS, "Tilesets", "室内.png"), (pc.SRC_W, pc.SRC_H))),
        ("行走图", pc.make_source_from_asset(
            os.path.join(pc.GRAPHICS, "Characters", "001.png"), (pc.SRC_W, pc.SRC_H))),
        ("标题图", Image.open(os.path.join(pc.GRAPHICS, "Titles", "Title.png"))
            .convert("RGB").resize((pc.SRC_W, pc.SRC_H), Image.LANCZOS)),
    ]

    out_size = (pc.DST_W, pc.DST_H)
    print(f"{'素材':8s} {'方案':22s} {'颜色数':>7s} {'锐度':>10s} {'斜线台阶':>9s} {'参考RMSE':>9s}")
    print("-" * 72)

    rows = []
    for tname, src in tests:
        base_colors = unique_colors(src)
        print(f"{tname:8s} {'(源图)':22s} {base_colors:>7d}")
        for pname, fn in pc.PIPES:
            out = fn(src)
            c = unique_colors(out)
            s = tenengrad(out)
            st = stair_ratio(out)
            r = ref_rmse(out, src, out_size)
            rows.append((tname, pname, c, s, st, r, base_colors))
            print(f"{'':8s} {pname:22s} {c:>7d} {s:>10.1f} {st:>9.3f} {r:>9.2f}")
        print()

    # 汇总：颜色膨胀倍数 + 归一化
    print("=" * 72)
    print("按素材对颜色膨胀做归一化（越大越差，1.0 = 未膨胀）")
    print("-" * 72)
    for tname in [t[0] for t in tests]:
        sel = [r for r in rows if r[0] == tname]
        base = sel[0][6]
        parts = [f"{r[1].split()[0]}={r[2]/base:.1f}x" for r in sel]
        print(f"{tname:8s} " + "  ".join(parts))


if __name__ == "__main__":
    try:
        import scipy  # noqa
    except ImportError:
        print("需要 scipy：pip install scipy", file=sys.stderr)
        sys.exit(1)
    main()
