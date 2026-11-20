#!/usr/bin/env python3
"""生成 shader/ 与 assets/ 的 C 头文件（等价于 make_xxd.sh 的 xxd -i）。

Windows 上没有 xxd，用这个脚本替代。输出格式与 xxd -i 一致：
  unsigned char shader_mmpx_frag[] = { 0x2f, ... };
  unsigned int shader_mmpx_frag_len = N;

用法（在 mkxp-z 目录下）：
  python gen_xxd.py
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
PER_LINE = 12


def sym(path: str) -> str:
    name = re.sub(r"[^0-9a-zA-Z]", "_", path)
    return name if not name[0].isdigit() else "_" + name


def dump(src: str, dst: str) -> None:
    data = open(src, "rb").read()
    name = sym(os.path.relpath(src, HERE).replace(os.sep, "/"))
    lines = [f"unsigned char {name}[] = {{"]
    for i in range(0, len(data), PER_LINE):
        chunk = ", ".join(f"0x{b:02x}" for b in data[i:i + PER_LINE])
        lines.append("  " + chunk + ",")
    lines.append("};")
    lines.append(f"unsigned int {name}_len = {len(data)};")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def main() -> None:
    total = 0
    for sub in ("shader", "assets"):
        src_dir = os.path.join(HERE, sub)
        out_dir = os.path.join(HERE, "xxd", sub)
        if not os.path.isdir(src_dir):
            continue
        os.makedirs(out_dir, exist_ok=True)
        for name in sorted(os.listdir(src_dir)):
            src = os.path.join(src_dir, name)
            if not os.path.isfile(src):
                continue
            dump(src, os.path.join(out_dir, name + ".xxd"))
            total += 1
    print(f"generated {total} xxd files under {os.path.join(HERE, 'xxd')}")


if __name__ == "__main__":
    main()
