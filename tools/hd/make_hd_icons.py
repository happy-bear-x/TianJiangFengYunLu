# -*- coding: utf-8 -*-
"""给高清版生成带 HD 标识的启动图标。

策略：
- 只叠加角标，不改原图，保证与仓库里已有的美术一致；
- 传统图标（ic_launcher.png）把 HD 放底部居中偏下，避开人物脸部；
- 自适应图标（ic_launcher_foreground.png）必须落在 66dp 安全圆内，
  所以放 y=0.68 的胸口位置，避免被圆形/方形遮罩裁掉；
- 白字 + 深色描边，在深色背景和红色日轮上都可读，小尺寸（48px）也不糊。
"""
import os
from PIL import Image, ImageDraw, ImageFont

RES = os.path.join(os.path.dirname(__file__), "..", "..", "app", "src", "main", "res")
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arial.ttf",
]


def load_font(px):
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return ImageFont.truetype(p, px)
    return ImageFont.load_default()


def draw_hd(img, cy_ratio, text_ratio=0.30):
    S = img.size[0]
    txt = "HD"
    font = load_font(max(8, int(S * text_ratio)))
    stroke = max(2, int(S * 0.022))

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = S / 2.0, S * cy_ratio

    # 描边 + 填充，用 anchor=mm 保证按字形实际外框居中
    d.text((cx, cy), txt, font=font, anchor="mm",
           fill=(255, 255, 255, 255),
           stroke_width=stroke, stroke_fill=(18, 12, 10, 235))

    img.alpha_composite(layer)
    return img


def draw_banner(img):
    """TV/Leanback 横幅：右侧加 HD，避免压到中间的文字排版。"""
    W, H = img.size
    font = load_font(max(12, int(H * 0.26)))
    stroke = max(2, int(H * 0.018))
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.text((W * 0.90, H * 0.52), "HD", font=font, anchor="rm",
           fill=(255, 255, 255, 245),
           stroke_width=stroke, stroke_fill=(18, 12, 10, 235))
    img.alpha_composite(layer)
    return img


def main():
    done = []
    for d in sorted(os.listdir(RES)):
        if not d.startswith("mipmap-"):
            continue
        base = os.path.join(RES, d)
        for name, cy, ratio in (("ic_launcher.png", 0.845, 0.30),
                                ("ic_launcher_foreground.png", 0.725, 0.165)):
            p = os.path.join(base, name)
            if not os.path.exists(p):
                continue
            img = Image.open(p).convert("RGBA")
            draw_hd(img, cy, ratio)
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
