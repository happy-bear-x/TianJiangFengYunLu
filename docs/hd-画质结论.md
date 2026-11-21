# 高清化：MMPX / 缩放链路实测结论

日期：2026-11-21　分支：`hd-remaster`

## 一、MMPX 之前为什么一直"没生效"

不是 shader 编译失败。日志显示 shader 一直是好的：

```
mmpx shader compiled, texSize uniform=3
```

真正的原因是 `gl-meta.cpp` 里**原生 blit 路径与采样路径的两处假设冲突**：

| 位置 | 原生路径（GLES3 的 `glBlitFramebuffer`） | 采样路径（MMPX）需要 |
|---|---|---|
| `_blitBegin()` | 只 `BindFramebuffer`，**不 push viewport、不做投影** | `applyViewportProj()` 要从 `glState.viewport` 推正交矩阵 |
| `blitSource()` | 只记 `READ_FRAMEBUFFER`，**不 `TEX::bind`** | 采样器必须能在 texture unit 上看到源纹理 |

后果依次是：

1. 投影矩阵按窗口的 1280x720 算，而 quad 是 1706x960 → 大部分投影到画布外，
   剩余区域是未初始化显存 → **左上角一块白**。
2. 补了 viewport 之后画面铺满了，但 sampler 在 unit 0 上取到的是上次绘制残留的
   白纹理 → **整屏纯白**。

修法：MMPX pass 自己 `glState.viewport.pushSet(0,0,dst.w,dst.h)` 再 pop（`blitEnd()`
在原生分支同样不 pop，所以配平），并把源 `TEXFBO` 显式传进来做 `TEX::bind`。

## 二、诊断日志

`std::clog` / `std::cerr` 在 Android 上**根本不会进 logcat**（没有任何东西把 C++ 流接到
`__android_log_print`），所以之前排查时完全看不到输出、只能靠画面瞎猜。

现在全部走 `SDL_Log`，logcat tag `SDL/APP`，前缀 `TJHD:`：

```
adb logcat | grep TJHD
```

能看到：配置值、画布尺寸、缓冲尺寸、uniform location、首帧是否真的跑了、跳过原因。

## 三、实测数据（MuMu，同一台机器改分辨率做的对照）

指标：Tenengrad 梯度能量（越高越锐）、整帧平均像素差。

| 分辨率 | 方案 | 梯度能量 | 结论 |
|---|---|---|---|
| 1280x720 | 原版 nearest | 689.3 | 基准 |
| 1280x720 | MMPX + nearest | 671.5 | **-2.6%，负收益** |
| 1280x720 | MMPX + sharp | 650.0 | 更差 |
| 1280x720 | 无 MMPX + sharp | 686.5 | 基本持平 |
| 1920x1080 | MMPX + sharp | 456.4 | 基准 |
| 1920x1080 | 无 MMPX + sharp | 453.9 | 差 0.5% |

**720p 为什么负收益**：MMPX 是固定 2x 算子，1280x720 装不下 1706x960，结果还得缩回去，
这一步丢的像素比锐化补回来的多。已加尺寸守卫，窗口两个方向都 ≥ 2x 画布才真跑。

**1080p 为什么也几乎没收益**：整帧平均像素差只有 **0.03**，放大 3 倍对比肉眼无差别。
两个原因叠加：

1. 本作是**手绘/卡通美术**（开场就是一张卡通插画），不是像素画。MMPX 的像素块推断
   本来就只对像素画有效。
2. 1706x960 再放大 1.125x 到 1080p，2x 的细节又被抹平一次。

## 四、sharp-bilinear 是对的，但只能解决"网格不均"

`shader/sharpbilinear.frag`：把插值带宽限制在源像素中心 ±0.5 目标像素以内，带内混合、
带外吸附。1:1 时退化为精确 nearest；放大时边缘 1px 锐利但网格均匀；缩小时带宽超过一个
纹素、自动退化为 bilinear。

它解决的是 `853x480 -> 1280x720`（1.5x）时 nearest 让相邻源像素占 1px 和 2px 交替的问题，
不是"造细节"。

## 五、真正的瓶颈：853x480 原生分辨率

文字和贴图都是在这个尺寸下生成再放大的。**shader 只能决定"怎么放大"，不能凭空造细节。**
继续调 shader 已经到顶了。

要真正达到"主流清晰水平"，必须动两头：

1. **素材 2x**（Pictures 里 640x480 的插画、Tilesets、Characters 等）
2. **引擎倍率**：Bitmap 加载时区分"像素尺寸"和"逻辑尺寸"，`width()` 返回逻辑值，
   绘制时按 2x 渲染；画布仍是 853x480 逻辑坐标，但渲染到 1706x960 的 FBO
   —— 正好可以复用现在 MMPX 用的那块缓冲。

工作量估计 1~2 周，主要风险是 Ruby 侧大量硬编码坐标和字体的 2x 渲染。

素材规模：1086 个文件 / 49.5 MB（897 png + 189 jpg），其中 `Pictures` 41 MB 是插画大头。
这类"单一批量处理"适合派子 agent 并行。

**超分工具**：本机 torch 2.15 已装，但 `opencv-python-headless` 不含 `dnn_superres`；
OpenCV 5.0 的新 dnn 引擎解析 FSRCNN/EDSR 的 `DepthToSpace` 层会失败。
建议直接用 `realesrgan-ncnn-vulkan` 独立可执行文件（无需 Python 依赖）。

## 六、当前配置

`tianjiang_game/mkxp.json`：

```json
"hdUpscale": true,       // 屏幕 ≥ 2x 画布才真跑，否则跳过
"hdSharpFinal": true,    // 最终 blit 走 sharp-bilinear
```

## 七、代码位置

| 文件 | 内容 |
|---|---|
| `mkxp-z/shader/mmpx.frag` | MMPX 2x（官方 GLC 改写为 GLSL ES 1.0） |
| `mkxp-z/shader/sharpbilinear.frag` | 最终缩放 |
| `mkxp-z/src/display/gl/gl-meta.cpp` | `blitRectangleMMPX` / `blitRectangleSharpBilinear` |
| `mkxp-z/src/display/graphics.cpp` | `redrawScreen()` 的 HD 链路、尺寸守卫、日志 |
| `mkxp-z/src/config.{h,cpp}` | `hdUpscale` / `hdSharpFinal` |

引擎 CI：push 到 `engine/build` 分支触发，约 6 分钟，产物落在 `engine/prebuilt` 分支的
`prebuilt/arm64-v8a/`。
