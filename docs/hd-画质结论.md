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

---

# 素材 2 倍超分（2026-11-21）

## 一、不需要改引擎

原先判断"素材 2x 必须配套引擎位图倍率，工作量 1~2 周"。实测推翻了这个结论：
本作所有全屏大图都是**单个 Sprite**，只要给 Sprite 一个缩放系数，2 倍纹理就能
1:1 映射到屏幕物理像素。

算式（1080p、16:9）：

```
逻辑画布 853×480  →  渲染 1706×960  →  屏幕 1920×1080
Sprite zoom = 853/1280 = 0.667
屏幕物理宽 = 1280 × 0.667 × (1706/853) = 1706 ≈ 1:1 纹理像素
```

## 二、改一处全局补丁就够

`mkxp_compat.rb` 原本就有一个 Sprite 补丁：位图恰好 640×480 时按画布宽度横向拉伸。
现在把它放宽到**整数倍分辨率**：

```ruby
if (bmp.width % $tj_orig_w).zero? && (bmp.height % $tj_orig_h).zero? &&
   bmp.width / $tj_orig_w == bmp.height / $tj_orig_h
  factor = bmp.width / $tj_orig_w
  self.zoom_x = $tj_canvas_w.to_f / bmp.width
  self.zoom_y = 1.0 / factor
end
```

640×480 → factor 1，zoom 1.333/1（原行为不变）
1280×960 → factor 2，zoom 0.667/0.5（显示结果与 1x 完全一致，只是纹理更清晰）

整除判断保证 960×576 的战斗动画帧、256×9100 的图块集、128 宽的行走图都不会误匹配。

## 三、处理范围

| 目录 | 张数 | 处理 |
|---|---|---|
| `Pictures/Endflash`（结局动画） | 180 | AI 2x |
| `Pictures/KC`（开场动画） | 182 | AI 2x |
| `Pictures/TrueEnd` | 10 | AI 2x |
| `Titles` / `Battlebacks` / `Gameovers` | 3 | AI 2x |
| `Panoramas` / `Fogs` | 8 | **不动**（平铺无缝，超分会破接缝） |
| `Tilesets` / `Characters` / `Battlers` / `Animations` / `Icons` / `Windowskins` | 590 | **不动**（像素风） |
| `Transitions` | 20 | **不动**（纯遮罩） |

`Spriteset_Battle` 里 `src_rect.set(0,0,640,480)` 是写死的，换 2x 后只取左上四分之一，
已改为跟随 `bitmap.width/height`（`tools/install_hd_fullscreen.py`）。

## 四、像素风不能 AI 超分（实测）

同一张行走图：AI 2x 之后眼睛、五官、衣物褶皱全部糊成一团，像素画的硬边被抹成渐变，
**像素感彻底消失**。所以地图、人物、图标一律保持原样。

而且像素素材放大本就没有收益：源信息量不变，GPU 按逻辑尺寸采样，最近邻 2x 与直接放大等价。
地图想提升是另一条路——需要像素专用放大算法（xBR / Scale2x 类）在 shader 里做，
属于单独工程。

## 五、显示方式

宽屏下有三种选择，实测对比后定版为**保持原版拉伸**：

| 方式 | 效果 | 结论 |
|---|---|---|
| 横向拉伸铺满 | 构图与旧版完全一致，人物横向略胖 | **采用**（零改动风险） |
| 等比居中+黑边 | 不变形，左右各留 106px 黑边 | 画面利用率低 |
| 等比铺满+裁上下 | 不变形无黑边，但上下各裁约 1/6 | 改构图，裁切有风险 |

## 六、体积与性能

- 素材：40 MB → 77.5 MB（q92 / 4:4:4 的 JPEG；无损 PNG 会是 247 MB）
- `game.zip`：73 MB → 110 MB，APK：137 MB
- 超分速度：375 张 29 秒（RX 7600 XT / Vulkan，`realesr-animevideov3-x2`）
- 首次启动解压时间相应变长，之后有 `.ready` 标记跳过

## 七、已知问题

**开场动画每只翼龙下都吊着主角。** 核实为**原作美术如此**，不是超分造假：
从 git 取出原始 `40.jpg`，3 只龙各挂 1 个主角，AI 版数量位置完全一致。
原版 640×480 时那个主角只有约 30 像素，糊成白点所以看不出来。

自动修正不可行，已实测：模板匹配（主角每帧形变）、ORB 特征（区域太小提不出特征）、
颜色+橙色上下文（白衣与云、高光混淆）三种定位方式全部失败；定位后无论用
`cv2.inpaint` 的 TELEA 还是 NS，都因为主角压在"深红翅膀／橙色龙身／蓝天"三色交界处
而留下明显糊块。真要修只能人工逐帧处理 180 帧。

## 八、相关工具

| 文件 | 用途 |
|---|---|
| `tools/install_hd_fullscreen.py` | 修 `Spriteset_Battle` 写死的 `src_rect` |
| `_build/hd/resrgan/` | realesrgan-ncnn-vulkan 可执行文件与模型（未入库） |
| `docs/hd-verify/` | 显示方式对比、像素风对比、翼龙原图对比 |

---

# 素材画风复核：Battlers / Animations（2026-11-26）

上一节把 `Battlers` / `Animations` 笼统归进"像素风，不动"。复查后要拆开说，
因为**这两类的真实构成完全不同**，而且我一开始被样本骗过一次。

## 一、判据：相邻像素差的中位数（med）

早期用"色数"分类会被抗锯齿污染（P 模式转 RGBA 后每张都有 250+ 唯一色），不能用。
有效判据是**水平相邻像素的最大通道差的中位数** `med`：

- 像素画：大面积纯色内部，**一半以上的相邻像素对完全相同** → `med == 0`
- 手绘：明暗连续变化 → `med` 在 15~34

辅助指标 `zero`＝相邻差为 0 的像素占比，但单独用会误判"大片纯色 + 少量渐变"的卡通画。

## 二、Battlers：主流是像素画，**不适合超分**

148 张的分布：`med==0` 38 张、`med` 1~3 有 22 张、`med>3` 87 张。
但**按 med 一刀切是错的**——熊头 `1.png` 的 med 只有 1，超分效果却很好（它本是手绘）。

把 60 张可疑样本铺成缩略图人工核对后，真实情况是：

> 蝙蝠、骷髅、史莱姆、兔子、狮子、蛇、老鼠、像素人物…… **绝大多数是硬边像素画**，
> 手绘的只有熊头（`1.png`）、蓝衣女（`82.png`）这类少数几张。

实测 `101.png`（紫衣像素人物）2x 超分：黑发被抹成平滑渐变、轮廓长出灰边、
衣服色块变成过渡 —— 正是"像素硬边被抹掉"的典型破坏。

**结论：Battlers 整体保持原样。**
像素画在 2 倍渲染画布上被 nearest 放大，方块边缘清晰、风格统一，这本来就是正确显示方式。
只挑少数手绘图上 2x 会让同一场战斗里立绘风格分裂，弊大于利。

## 三、Animations：主流是手绘光效，**该超分，但卡在引擎**

38 张里约 30 张是柔和光效（火焰 / 冰 / 雷 / 水 / 风 / 光 / 暗 / 爆炸 / 治愈光球 / 龙卷风），
只有棕色宝箱、剑、黄色光标、ZZZ 睡眠图标等少数几张是实心像素物。

超分实测（`003-Attack01.png` 首帧，192×192，Tenengrad 梯度能量）：

| 方案 | 梯度能量 | 观感 |
|---|---|---|
| nearest 2x（当前实现） | 13814 | 放射光芒呈方块阶梯，最难看 |
| bilinear 2x | 8614 | 糊成一团，光芒细节丢失 |
| **ESRGAN x2** | **13308** | 光芒锐利连续、光晕过渡自然，无假细节 |

也就是说现在的 1x 贴图在 2x 画布上被放大，**战斗特效正在呈现方块阶梯**，超分收益明确。

**但做不了**：动画帧由引擎按固定尺寸切分（`Sprite#animation` / `loop_animation`），
而 `_src/all` 下的 211 个脚本里没有任何切帧代码（只有调用点）。
`engine-src` 这份源码的 `sprite-binding.cpp` 只注册了 6 个属性、不含 animation，
与运行时 `libmkxp-z.so` 不是同一版本，改不了。

要推进只有两条：
1. 拿到与运行时一致的引擎源码，让帧尺寸从 `bitmap.width / 5` 推导（改一处，2x sheet 免配置）
2. 在 Ruby 层用 Sprite 自绘动画，绕开引擎（工作量大、要覆盖战斗与状态两类调用）

## 四、透明通道处理（如果以后做立绘或特效 2x）

- 素材混有 `P`（调色板，132 张）和 `RGBA`（16 张），**必须落 PNG，不能用 JPEG**
- 超分前把全透明区填白，否则模型会在边缘生成暗边
- 超分后**不要用模型输出的 alpha**（会被推成半透明渐变），改成原 alpha 单独放大再合回去
- `0.png` 本身是 148 张里唯一全透明的空占位，不是处理失败

---

# 二轮：全局 2 倍逻辑分辨率（hdScale）

日期：2026-11-26　分支：`hd-remaster`

## 五、"两版看起来一模一样"的根因

HD 版此前只做了两件事：全屏 CG 换成 1280×960、加上 MMPX 后处理。但
**画布本身始终是 853×480，素材信息量锁死在 480 高**，MMPX 只是把这个
小图插值放大。而且日志实证：

```
TJHD: mmpx skipped: window 1280x720 cannot hold 1706x960
```

1280×720 的模拟器窗口根本放不下 2 倍画布，MMPX 一次都没启用。
所以在游戏内看到"和原版没区别"是**必然结果**，不是打包错了。

## 六、方案：逻辑坐标不动，物理像素翻倍

引擎新增两个配置项（`mkxp.json`）：

| 键 | 默认 | 含义 |
|---|---|---|
| `hdScale` | 1 | 全局逻辑→物理倍率 |
| `hdFontScale` | 0 | 字体独立倍率，0 表示跟随 `hdScale` |

核心约定：**Ruby 层永远工作在逻辑像素（640×480 的世界），引擎内部所有
Bitmap 分配、坐标、字体栅格化都按倍率放大，binding 层做逻辑↔物理换算。**

- `Graphics::width()/height()` 返回**逻辑值**（`scRes / tjHdScale`）
- `Graphics::resizeScreen()` 收逻辑值，内部乘倍率；`screen.setResolution()`
  必须收到**物理值**（否则帧缓冲只有半尺寸、画面缩在左上角）
- `Bitmap`：构造、`blt`、`stretch_blt`、`fill_rect`、`get/set_pixel`、
  `draw_text`、`text_size`、`gradient_fill_rect`、`clear_rect`、`rect` 全部换算；
  `width/height` 读值除倍率
- `Sprite`/`Window`/`Viewport`/`Plane`/`Tilemap` 的 `x/y/ox/oy/width/height`
  全部走 `DEF_GFX_PROP_SCALED_I`；`src_rect`/`viewport.rect`/`cursor_rect`
  保持逻辑值，由核心类在使用点换算
- `Window` 皮肤矩形、`contentsRect` 的 16px 内边距、`buildControlsVert`
  的控件坐标全部乘倍率
- `Input::mouseX/Y` 结果除倍率，触摸层继续按逻辑坐标工作

素材规则随之简化为一条：**所有素材文件都是原始的 2 倍**（最近邻放大，
像素画无损），于是"物理尺寸 = 文件尺寸、逻辑尺寸 = 物理/2"恒成立，
不需要任何目录白名单。

## 七、踩到的四个坑

1. **`bitmapHeight` getter 漏除倍率**（批量替换只命中了 `bitmapWidth`）。
   症状：`Bitmap.new(640,480)` 读出 `640x960`，`mkxp_compat.rb` 的全屏图
   整除判断 `w/640 == h/480` 失败（1≠2），`zoom_x` 不设置 → 全屏图只占左上角。
2. **`resizeScreen` 把逻辑尺寸传给 `screen.setResolution`** → 帧缓冲半尺寸。
3. **Window 内容区 16px 内边距没缩放** → 文字裁剪与绘制定位错位。
4. **Tilemap atlas 布局是硬编码 32**（`gl/tileatlas.cpp` 的 `atBuffer`、
   `atAreaW/H`、`tilesetW`、`tsLaneW`、`tileToAtlasCoor` 的 `tileX*32`）。
   tilemap 已按 64 绘制而 atlas 仍按 32 排布 → **每个图块取到隔壁 32px 的内容**，
   画面撕裂错位。另有 `autotileRects` 这张 32 基准的分块表、以及
   `handleTile` 里 `texRect(…, 31, 31)` 也漏改。

## 八、实测结果

设备：1280×720 模拟器，`hdScale=2`。

```
TJHD: graphics init: hdUpscale=0 canvas=1280x960 … scale=2 fontScale=2
TJHD: resizeScreen: logical 853x480 -> physical 1706x960 (scale=2)
```

画布 1706×960 物理（= 853×480 逻辑 ×2），最终缩到窗口 1280×720。

- 标题、开场 CG、地图、菜单、子窗口、对话全部铺满无黑边
- `tj_dbg` 探针：`BMP 640x480 -> 640x480`、`SPR zoom=1.333x1.0`
- 地图图块排列正确，无错位
- CPU 7.6%（`top`，行走中），RSS 296 MB

与原版同机型同分辨率对比标题菜单（3 倍放大目视）：

| | 文字边缘 | 窗口边框 |
|---|---|---|
| 原版 1.6.2（480 高画布） | 阶梯状锯齿，笔画粗断 | 花纹是放大后的方块 |
| hdScale=2 | 笔画连续平滑 | 花纹干净 |

## 九、代价与遗留

- **arm64-only**：`abiFilters 'arm64-v8a'`，旧的 v7a 库没有新特性，直接删；
  包名独立为 `com.tianjiang.fengyun.hd`，与正式版共存不冲突存档
- **APK 137 MB**：素材 2 倍（game.zip 121 MB）+ 单 ABI native 34 MB
- **Tilemap atlas 胀到 3072×4096（约 50 MB VRAM）**：tileset 本身 512×18200
  就要 37 MB。低端 2048 纹理上限的机器会抛
  `Cannot allocate big enough texture for tileset atlas`。
  真要省内存，得让 tileset 保持 1 倍、atlas 按 1 倍排布而绘制时放大 2 倍
  （像素画视觉等价），是下一步的优化项
- **`tileatlasvx.cpp`（VX 版图块）未适配**，本项目 rgssVersion=1 用不到
- **战斗场景本轮未实测**：已走到城镇地图与对话，未能触发遇敌

---

# 三轮：锯齿从哪来，以及为什么只能压到这个程度

日期：2026-11-28　分支：`hd-remaster`

## 十、两个真实缺陷

### 1. 图块之间的黑缝（已修）

`atSelectSubPos` 里 autotile 四分块偏移是硬编码 `+16`，2 倍下应该是 `+32`。
结果四块只占满 48×48，右和下各空 16px，相邻格子一拼就是每格一圈黑框。
量出来缝宽正好 16 物理像素 = 1/4 个 64px 图块，周期 48px。

修法：`pos.x += 16 * s` / `pos.y += 16 * s`，`BottomLeftTable` 的 `24` 同理。

### 2. 0.75 降采样的核太窄（已修）

画布 1706×960，窗口 1280×720，缩放比 **0.7503**。

`sharpbilinear.frag` 原本在缩小路径上 `uv = v_texCoord` 原样采样，
而纹理由 `smoothScaling:false` 设成 `GL_NEAREST` —— 等于每 4 个像素丢 1 个，
所有斜边都是碎台阶。注释写的"degrades to ordinary bilinear"是错的，
它退化成了最近邻。

第一版修法：显式 2×2 双线性。有明显改善，但**核太窄**：
双线性的有效宽度约 1 个源像素，压不住 1.33 倍的降采样足迹，
角色和敌人的轮廓仍然留 1~2px 的台阶，且边缘出现半透明杂色。

第二版修法：**Catmull-Rom 4×4**（16 tap）。核宽度 4 个源像素，
足以覆盖 1.33 的足迹，同时保留高频（不像 box filter 那样糊）。

```glsl
if (scale.x < 1.0 || scale.y < 1.0) {
    // 4x4 Catmull-Rom，权重 w(x) = 1.5|x|³-2.5|x|²+1 / -0.5|x|³+2.5|x|²-4|x|+2
}
```

采样点必须落在 texel 中心（`clamp(p, 0.5/texSize, 1-0.5/texSize)`），
因为纹理 filter 是 NEAREST，采到 1.0 会绕到另一边。

## 十一、实测数据

1280×720 模拟器，同机位对比 Tenengrad（梯度能量，越高越锐）：

| 场景 | 4-tap 双线性 | Catmull-Rom | 变化 |
|---|---|---|---|
| 水面波纹 | 340 | 395 | +16% |
| 敌人（野猪） | 511 | 559 | +9% |
| 战斗主角 | 425 | 436 | +3% |
| 存档界面行走图 | 2030 | 2301 | +13% |

梯度能量高说明保留了更多细节；纯双线性那版是"糊"，不是"平"。
视觉上：行走图的头发从"灰边+碎块"变成实心黑，领口浅蓝干净，
野猪的腿和描边明显更连续。

性能：CPU 7.6%（`top`，行走中）、RSS 262 MB，与 2×2 版本没有可测差异。
16 tap 只在最终上屏那一次，不是逐精灵。

## 十二、压不下去的部分（本质限制）

屏幕 1280×720，游戏逻辑 853×480，倍率 **1.5006**。

非整数倍率下，每个逻辑像素占 1 或 2 个屏幕像素，**块大小必然交替**。
这是数学问题，不是算法问题：

- 走 NEAREST：块大小 1/2 交替，颜色纯 → "锐利但碎"
- 走双线性：块大小仍在交替，但被插值成半透明 → "碎且糊"
- 走 Catmull-Rom：兼顾，是目前能拿到的最好结果

要真正消除，只有两条路：

1. **让物理画布等于屏幕尺寸**（倍率 1.5 是浮点数，破坏 Bitmap 尺寸整除，
   且素材得重做成 1.5 倍，1.5 倍放大像素画本身就会产生 1/2 交替块，绕回原点）
2. **素材重制**（AI 超分像素画会毁掉硬边，已排除）

所以：**字体、UI、窗口边框的收益是真实的（2 倍栅格化），
像素素材只能做到"最好的 1.5 倍显示"**。

## 十三、素材尺寸核对

逐个目录确认过 2x 转换没有遗漏（对比 `b1e2f6d` 的 1x 原件）：

| 目录 | 原始 | 现在 | 说明 |
|---|---|---|---|
| Tilesets | 256×… | 512×… | 含 512×18200 的大图集 |
| Characters | 128×256 | 256×512 | 99 个 |
| Battlers | 80×100 | 160×200 | 148 个，另有 400×240 等 |
| Icons | 24×24 | 48×48 | 57 个单图标文件本来就是 24×24，属正常 |
| Animations | 960×384 | 1920×768 | 38 个 |
| Windowskins | 192×128 | 384×256 | 2 个 |
| Pictures / Transitions | — | 1280×960 | 原版就是高清，不参与 2x |

## 十四、分发

- 三个分支都已重打，`_dist/` 下：
  - `TianJiangFengYun-1.6.2.apk`（main，100.0 MiB）
  - `TianJiangFengYun-1.6.2-optimized.apk`（optimized，100.0 MiB）
  - `TianJiangFengYun-1.6.2-hd2x.apk`（hd-remaster，130.8 MiB）
- 局域网：`http://192.168.10.200/tjfyl/`，旧的 `-hd.apk`（MMPX 方案）已删除
- 引擎提交：`81285fd`（2×2 双线性）→ `d22f307`（Catmull-Rom）
