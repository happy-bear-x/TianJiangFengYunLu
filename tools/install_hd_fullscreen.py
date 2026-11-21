#!/usr/bin/env python3
"""让战斗背景的显示区域跟随素材实际尺寸。

Sprite 的位图换成 2x 素材后，Spriteset_Battle 里写死的
`src_rect.set(0, 0, 640, 480)` 只会取到左上角四分之一，
战斗背景会变成一幅被放大四倍的残图。这里改成按位图尺寸取全部。

mkxp_compat.rb 里的全屏图缩放补丁会据此把 2x 纹理压回画布尺寸，
显示结果与 1x 素材完全一致。可重复执行，已修则跳过。
"""
import shutil
import zlib
from pathlib import Path

from rubymarshal.reader import loads
from rubymarshal.writer import writes

from paths import GAME

SCRIPTS = GAME / "Data" / "Scripts.rxdata"
ENTRY = 29
NAME = "Spriteset_Battle"

OLD = "@battleback_sprite.src_rect.set(0, 0, 640, 480)"
NEW = ("@battleback_sprite.src_rect.set(0, 0, "
       "@battleback_sprite.bitmap.width, @battleback_sprite.bitmap.height)")


def main():
    data = loads(SCRIPTS.read_bytes())
    name = data[ENTRY][1].decode("utf-8", "replace")
    assert name == NAME, f"条目 {ENTRY} 是 {name!r}，预期 {NAME!r}"

    src = zlib.decompress(data[ENTRY][2]).decode("utf-8")
    if NEW in src:
        print("  已是修复后状态，跳过")
    else:
        hits = src.count(OLD)
        assert hits == 1, f"锚点出现 {hits} 次，预期 1 次，已中止"
        backup = SCRIPTS.with_suffix(".rxdata.bak-hdbattleback")
        if not backup.exists():
            shutil.copy2(SCRIPTS, backup)
        data[ENTRY] = [data[ENTRY][0], data[ENTRY][1],
                       zlib.compress(src.replace(OLD, NEW).encode("utf-8"), 9)]
        SCRIPTS.write_bytes(writes(data))
        print(f"  {NAME}: 已修复 src_rect")

    check = loads(SCRIPTS.read_bytes())
    code = zlib.decompress(check[ENTRY][2]).decode("utf-8")
    assert NEW in code and OLD not in code
    print("verified ok, scripts:", len(check))


if __name__ == "__main__":
    main()
