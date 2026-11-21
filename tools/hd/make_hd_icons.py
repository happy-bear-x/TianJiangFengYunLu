# -*- coding: utf-8 -*-
"""给高清版生成带 HD 标识的启动图标。

策略：
- 只叠加角标，不改原图，保证与仓库里已有的美术一致；
- HD 统一放右下角，半透明，像水印一样不抢主体；
- 传统图标（ic_launcher.png）按比例直接贴右下角；
- 自适应图标（ic_launcher_foreground.png）只能显示中间 108dp 里的 66dp 安全圆，
  所以把文字沿对角线推到安全圆内最远处，避免被圆形/方形遮罩裁掉；
- 白字 + 深色描边，在深色背景和红色日轮上都可读，小尺寸（48px）也不糊。
"""
import math
import os
from PIL import Image, ImageDraw, ImageFont

RES = os.path.join(os.path.dirname(__file__), "..", "..", "app", "src", "main", "res")
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arial.ttf",
]

# 自适应图标安全区：66dp / 108dp 的圆，半径占整图 33/108/2 ≈ 0.3056
ADAPTIVE_SAFE_R = 66.0 / 108.0 / 2.0
# 安全圆内留一点点余量（贴满会顶到描边抗锯齿边缘）
SAFE_FILL = 0.98

ALPHA = 190          # 主体透明度（约 75%）
STROKE_ALPHA = 150   # 描边再淡一点，避免小图发糊


def load_font(px):
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return ImageFont.truetype(p, px)
    return ImageFont.load_default()


def _fit_diag(ax, ay, R):
    """矩形半宽/半高 ax、ay 沿 45° 方向推到圆内最远处，返回圆心到该点的距离。"""
    lo, hi = 0.0, R
    for _ in range(40):
        mid = (lo + hi) / 2.0
        dx = dy = mid / math.sqrt(2.0)
        ok = all(math.hypot(dx + sx, dy + sy) <= R
                 for sx in (-ax, ax) for sy in (-ay, ay))
        if ok:
            lo = mid
        else:
            hi = mid
    return lo


def draw_hd(img, right_ratio, bottom_ratio, text_ratio, safe_circle=None):
    """在右下角叠加半透明 HD。safe_circle 给半径比例时，保证四角都落在圆内。"""
    S = img.size[0]
    font = load_font(max(8, int(S * text_ratio)))
    stroke = max(2, int(S * 0.020))

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    l, t, r, b = d.textbbox((0, 0), "HD", font=font, anchor="mm", stroke_width=stroke)
    w, h = float(r - l), float(b - t)

    # 先按比例把文字右下角对齐到目标点
    cx = S * right_ratio - w / 2.0
    cy = S * bottom_ratio - h / 2.0

    if safe_circle:
        c = S / 2.0
        R = S * safe_circle
        dist = _fit_diag(w / 2.0, h / 2.0, R)
        cx = c + dist / math.sqrt(2.0)
        cy = c + dist / math.sqrt(2.0)

    d.text((cx, cy), "HD", font=font, anchor="mm",
           fill=(255, 255, 255, ALPHA),
           stroke_width=stroke,
           stroke_fill=(18, 12, 10, STROKE_ALPHA))

    img.alpha_composite(layer)
    return img


def draw_banner(img):
    """TV/Leanback 横幅：右下角加淡 HD，避免压到中间的文字排版。"""
    W, H = img.size
    font = load_font(max(12, int(H * 0.26)))
    stroke = max(2, int(H * 0.018))
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.text((W * 0.955, H * 0.90), "HD", font=font, anchor="rs",
           fill=(255, 255, 255, ALPHA),
           stroke_width=stroke, stroke_fill=(18, 12, 10, STROKE_ALPHA))
    img.alpha_composite(layer)
    return img


def main():
    done = []
    for d in sorted(os.listdir(RES)):
        if not d.startswith("mipmap-"):
            continue
        base = os.path.join(RES, d)
        # (文件名, 右边界, 下边界, 字号比例, 安全圆)
        jobs = (
            ("ic_launcher.png", 0.865, 0.885, 0.235, None),
            ("ic_launcher_foreground.png", 0.865, 0.885, 0.150, ADAPTIVE_SAFE_R * SAFE_FILL),
        )
        for name, rr, br, ratio, safe in jobs:
            p = os.path.join(base, name)
            if not os.path.exists(p):
                continue
            img = Image.open(p).convert("RGBA")
            draw_hd(img, rr, br, ratio, safe)
            img.save(p)
            done.append((d, name, img.size))
        b = os.path.join(base, "ic_banner.png")
        if os.path.exists(b):
            img = Image.open(b).convert("RGBA")
            draw_banner(img)
            img.save(b)
            done.append((d, "ic_banner.png", img.size))
    for x in done:
        print("%-18s %-28s %s" % x)


if __name__ == "__main__":
    main()
