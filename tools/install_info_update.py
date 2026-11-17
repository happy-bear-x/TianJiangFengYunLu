#!/usr/bin/env python3
"""Refresh the in-game 游戏相关 / 游戏帮助 pages.

Two edits in 186_详尽任务显示界面.rb:

1. 游戏相关 — the author's personal QQ is replaced by the port's Q group,
   and the stale second group number is dropped so only one number shows.

2. 游戏帮助 — the original three hints stay, but they now sit under a
   「原版提示」 heading preceded by a 「触屏操作」 section describing the
   Android input layer (joystick, tap-to-select, tap-outside-to-back,
   corner menu). New players on a phone never see a keyboard.

Line-based matching keeps the surrounding Ruby string intact (the values
are multi-line literals with \\c / \\p control codes).
"""
import re
import zlib
from pathlib import Path

from rubymarshal.reader import loads
from rubymarshal.writer import writes

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "tianjiang_game" / "Data" / "Scripts.rxdata"

TARGET = "详尽任务显示界面"

# ── 游戏相关 ──────────────────────────────────────────────────────────
QQ_OLD = "个人QQ：980454969"
QQ_NEW = "Q群：1134180232（点此页任意位置可复制）"
OLD_GROUP = "游戏群：62647686"
VER_OLD = "版本号：V15.11"
VER_NEW = "版本号：V15.11　安卓适配：1.6.0"

# ── 游戏帮助 ──────────────────────────────────────────────────────────
HELP_OLD = '简介 ="1.主角初始房屋的衣柜可更换衣物；'
HELP_NEW = (
    '简介 ="【触屏操作】\n'
    "左下半区按住拖动＝浮动摇杆，可斜向行走，贴墙自动滑行；\n"
    "点菜单项＝选中并确认，点菜单外面＝返回；\n"
    "轻点屏幕左上角＝打开菜单；\n"
    "点存档栏＝直接保存/读取。\n"
    "\n"
    "【原版提示】\n"
    "1.主角初始房屋的衣柜可更换衣物；"
)


def _name(entry):
    n = entry[1]
    if isinstance(n, bytes):
        return n.decode("utf-8", "replace")
    return getattr(n, "text", None) or str(n)


def rewrite(text):
    """All edits are idempotent: each one checks for its own result."""
    before = text

    if QQ_OLD in text:
        text = text.replace(QQ_OLD, QQ_NEW)
    if OLD_GROUP in text:
        text = text.replace("\n\n" + OLD_GROUP, "")
        text = text.replace(OLD_GROUP, "")
    if VER_OLD in text and "安卓适配" not in text:
        text = text.replace(VER_OLD, VER_NEW)
    if HELP_OLD in text:
        text = text.replace(HELP_OLD, HELP_NEW)

    # 删掉旧群号会剩下成片空行，页面会被撑开。
    # 脚本源是 CRLF，所以空白要按 \r?\n 匹配。
    text = re.sub(r"(Q群：1134180232[^\r\n]*)(?:\r?\n){3,}",
                  r"\1\r\n\r\n", text)
    return text, text != before


def patch(data):
    changed = 0
    for entry in data:
        if TARGET not in _name(entry):
            continue
        body = zlib.decompress(entry[2])
        text, did = rewrite(body.decode("utf-8"))
        if did:
            new = text.encode("utf-8")
            entry[2] = zlib.compress(new, 9)
            changed += 1
            print(f"  patched {_name(entry)} ({len(body)} -> {len(new)} bytes)")
    return changed


def main():
    data = loads(SCRIPTS.read_bytes())
    n = patch(data)
    if n == 0:
        print("  nothing to patch (already updated?)")
        return
    SCRIPTS.write_bytes(writes(data))

    check = loads(SCRIPTS.read_bytes())
    found = next((e for e in check if TARGET in _name(e)), None)
    assert found is not None, "script entry missing"
    body = zlib.decompress(found[2]).decode("utf-8")
    assert "1134180232" in body, "Q group number missing"
    assert "980454969" not in body, "old personal QQ survived"
    assert "62647686" not in body, "stale group number survived"
    assert "触屏操作" in body, "touch help section missing"
    print(f"  verify OK: QQ group set, help updated, "
          f"{SCRIPTS.stat().st_size} bytes")


if __name__ == "__main__":
    main()
