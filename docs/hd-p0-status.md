# P0 状态：MMPX 放大管线

> 分支：`hd-remaster`（已 rebase 到 main@2138e7f）　｜　日期：2026-11-21
> 引擎仓库：`engine-src` commit `8291aad`

## 0. 一句话

**代码写完了，shader 编译验证通过，但引擎还没编译过，真机效果没看到。**
卡在 5 个必须先交叉编译的依赖库上，不是代码问题。

---

## 1. 做了什么

| 文件 | 改动 |
| --- | --- |
| `shader/mmpx.frag` | 新增。官方 MMPX.glc（310 es compute）逐条改写成 GLSL ES 1.0 fragment |
| `src/display/gl/shader.h/.cpp` | 新增 `MMPXShader`，构造时 try/catch，失败置 invalid 不崩启动 |
| `src/display/gl/gl-meta.h/.cpp` | 新增 `blitRectangleMMPX()`，校验 dst 必须是 src 的精确 2 倍 |
| `src/display/graphics.cpp` | 新增 `hdUpscaleBuffer`（固定 scRes×2）+ 在 `redrawScreen` 接入 |
| `src/config.h/.cpp` | 新增 `hdUpscale` 开关 |
| `gen_xxd.py` | Windows 无 `xxd`，等价替代（生成 `xxd/shader/*.xxd`） |
| `get_deps_codeload.sh` | 代理对 github.com 的 CONNECT 返回 502，改走 codeload tarball |

管线：

```
screen.composite() → frontBuffer (853×480)
    └─[MMPX 2x]→ hdUpscaleBuffer (1706×960)
        └─[nearest 1.125x]→ 屏幕 (1920×1080)
```

与 `integerScaling` 完全独立：中间缓冲固定 2 倍，任何分辨率都能用。
1080p 上是 `2x → 1.125x`；720p 上是 `2x → 0.75x`，同样成立。

### 三个容易踩的点（已处理）

1. **精度**：1706 个目标像素需要 11 位，`mediump`（10 位尾数）会把奇偶性量化错，整列像素偏移。
   用 `#ifdef GL_FRAGMENT_PRECISION_HIGH` 声明 highp；不支持时 shader 编译失败 → 回退普通 blit。
2. **坐标推导**：不用 `gl_FragCoord`（依赖 viewport 状态），改用 `v_texCoord * texSize * 2`。
   四顶点 UV 线性插值后，`floor((i+0.5)/2 * 2) = i`，与目标像素索引严格一致。
3. **边界**：邻居采样手工 `clamp(0, texSize-1)`，不依赖纹理 wrap 模式。

---

## 2. 验证到哪一步

| 项 | 状态 | 证据 |
| --- | --- | --- |
| shader 语法 / 链接（GLES2 语义） | **通过** | `docs/hd-research/mmpx-compile-test.html` 在 Edge/ANGLE 下 `<title>PASS</title>` |
| 坐标推导数学 | **通过** | 见上第 2 点，可手算 |
| MMPX 视觉效果 | **此前已通过** | `docs/hd-research/pipeline-*.png`、`proof-zoom-char.png`（Python 移植版） |
| C++ 编译 | **未做** | 见第 3 节 |
| 真机渲染 / 帧率 | **未做** | 引擎没编出来 |

> `mmpx-compile-test.html` 是给以后改 shader 用的：改完丢进去跑一次，看 title 是 PASS 还是 SHADERFAIL。
> 注意它必须靠 http 访问（`python -m http.server`），`file://` 下部分浏览器会拦截 WebGL。

---

## 3. 卡在哪：5 个依赖需要先交叉编译

`ndk-build` 只能编「源码编译」那批（SDL2、SDL2_ttf、SDL2_image、physfs、uchardet、libogg/vorbis/theora、SDL2_sound）。
另外 5 个是 `PREBUILT`，要求 `app/jni/build-<abi>/lib/` 下已有产物：

| 库 | 需要 | 说明 |
| --- | --- | --- |
| ruby | `lib/libruby.so` + `include/ruby-3.1.0/` | **最费时**。configure 需 autoconf 生成（git 分支不带） |
| openssl | `lib/libcrypto.a`、`lib/libssl.a` | 静态 |
| pixman | `lib/libpixman-1.a` | 静态 |
| openal | `lib/libopenal.so` | 动态 |
| libiconv | `lib/libiconv.a` | 静态 |

`preconfigured/universal/` 里只有三个库的**头文件**（libogg/libtheora/libvorbis 的 .h），不是二进制，救不了。

### 下一步（按顺序）

```bash
# 1. 依赖源码（已拉好，11/13 就绪，缺 ruby 的要走 heads 而非 tags）
cd D:/Android/tjfyl/engine-src && bash get_deps_codeload.sh
# ruby 需单独补：
curl -sSL -o /tmp/ruby.tgz \
  https://codeload.github.com/mkxp-z/ruby/tar.gz/refs/heads/mkxp-z-3.1
mkdir -p app/jni/ruby && tar -xzf /tmp/ruby.tgz -C app/jni/ruby --strip-components=1

# 2. 在 WSL 里用 Linux NDK 编译（Windows 版只有 ndk-build.cmd，且自举脚本是 shell）
NDK=/mnt/d/Android/SDK/ndk/r23c-linux/android-ndk-r23c
# → 两个 ABI 先各编一遍 ruby / openssl / pixman / openal / libiconv
# 3. 再 ndk-build 编 mkxp-z
$NDK/ndk-build -C app/jni APP_ABI=arm64-v8a -j8
```

**预估**：ruby 40 分钟（含 autoconf）+ openssl 15 + 其余 15 + mkxp-z 10 ≈ **1.5 小时**，
两个 ABI 翻倍。每步都可能撞 Windows 路径 / MSYS 环境坑。

### 编译产物落位

编出来的 `libmkxp-z.so` 要拷回主仓库：

```bash
D:/Android/tjfyl/TianJiangFengYunLu/app/src/main/jniLibs/arm64-v8a/libmkxp-z.so
```

---

## 4. 主仓库侧改动

`tianjiang_game/mkxp.json` 新增 `"hdUpscale": true`。

- 老引擎不认识这个键；`config.cpp` 的 `GUARD` 宏会吞掉异常，**不会崩**。
- 新引擎 shader 编译失败时 `hdReady=false`，`redrawScreen` 完全走原路径，画面与现在一致。
- 所以这个开关打开是安全的，但**未在真机验证过**。

---

## 5. 建议

1. 先做体积瘦身（删 Droid 字体 + Noto 子集化，省 13.9 M，零风险），把编译环境准备的时间利用起来。
2. 编译环境独立于画质验证：就算 MMPX 最后效果不满意，这套环境以后改引擎都用得上。
3. 如果 MMPX 在真机上观感提升不明显（预期只有斜线台阶 -3.4%），下一步才值得动「文字按 2 倍渲染」——
   那才是玩家最容易察觉的糊。
