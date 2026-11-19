# APK 体积构成分析

> 分支：`hd-remaster`　｜　日期：2026-11-20　｜　样本：`app-debug.apk`（104,864,566 B = 100.0 MiB）

## 0. 一句话结论

**100 MB 里只有 21 MB 是游戏素材，79 MB 是"移植到 Android 必须补的运行时"。**
所以"0 几年的游戏怎么这么大"这个疑惑，答案是：不是游戏变大了，是它以前白嫖的系统组件现在要自己扛。

可无痛砍掉 **25.4 MB**（不损失任何画质），压到 **74.6 MB**；再动 `Endflash` 可到 **43 MB**。

---

## 1. 第一层：APK 内部构成

| 组件 | 压缩后 | 占比 | 说明 |
| --- | ---: | ---: | --- |
| `assets/game.zip` | 73.68 MiB | **73.7%** | 游戏全部数据（已内部 DEFLATE） |
| `lib/arm64-v8a` | 12.49 MiB | 12.5% | 8 个 64 位原生库 |
| `lib/armeabi-v7a` | 11.45 MiB | 11.4% | 8 个 32 位原生库（完整重复一套） |
| `res/` + `resources.arsc` | 2.31 MiB | 2.3% | 图标、启动图 |
| dex + manifest + 签名 | 0.07 MiB | 0.1% | Java 层几乎没有代码 |
| **合计** | **100.0 MiB** | | |

> `assets` 的压缩率是 100%（73.68 → 73.68），因为 game.zip 本身已压缩，AGP 检测到后按 STORED 存。**这 73.68 MiB 就是素材的有效大小，没有二次压缩余量。**

## 2. 第二层：game.zip 解开后

| 路径 | 文件数 | 原始 | 压缩后 | 占 game.zip |
| --- | ---: | ---: | ---: | ---: |
| `Graphics/Pictures/Endflash` | 180 | 33.70 M | **33.62 M** | **46.0%** |
| `Fonts` | 2 | 20.33 M | **15.74 M** | **21.5%** |
| `Audio`（SE/BGS/BGM） | 262 | 8.22 M | 7.74 M | 10.6% |
| `Graphics/Pictures`（其余） | 240 | 5.88 M | 5.74 M | 7.9% |
| `Graphics/Animations` | 38 | 3.70 M | 3.63 M | 5.0% |
| `Graphics/Tilesets` | 4 | 1.65 M | 1.62 M | 2.2% |
| `Graphics/Icons` | 257 | 1.16 M | 1.10 M | 1.5% |
| `Graphics/Battlers` | 148 | 0.94 M | 0.91 M | 1.2% |
| `Graphics/Characters` | 99 | 0.88 M | 0.84 M | 1.1% |
| `Data` | 198 | 2.36 M | 0.70 M | 1.0% |
| `Graphics` 其余（Titles/Autotiles/System/Panoramas…） | 117 | 1.58 M | 1.40 M | 1.9% |
| **合计** | **1551** | 80.4 M | **73.1 M** | |

**两个目录吃掉 67.5%：`Endflash`（结局序列帧）和 `Fonts`。**

---

## 3. 这 100 MB 是否"合理"

把体积按性质重新归类：

| 性质 | 体积 | 判断 |
| --- | ---: | --- |
| 游戏素材（图块/行走图/动画/音乐/数据） | **≈ 21 M** | 合理。RMXP 游戏本该这么大 |
| 移植补齐的运行时（两套 ABI 的 ruby + SDL2 + openal） | **≈ 24 M** | 现代必需，但**一套就够了** |
| CJK 字体 | **15.7 M** | Android 无中文系统字体，必须自带；但**99.6% 字形用不到** |
| 结局序列帧 `Endflash` | **33.6 M** | 0 年代的分发方式，逐帧 PNG 存视频内容 |

### 为什么 0 几年的游戏会到 100 MB

RMXP 游戏在 Windows 上只要几十 MB，因为它**白嫖系统**：

| 依赖 | Windows | Android |
| --- | --- | --- |
| 脚本运行时 RGSS | 系统装 RGSS103J.dll | 自带 `libruby.so`（**11.7 M × 2 套**）|
| 图形/音频层 | 系统 DirectDraw + DirectSound | 自带 SDL2 + OpenAL（约 8 M × 2 套）|
| 中文字体 | 系统宋体/黑体（0 成本）| 自带 Noto CJK（**16.5 M**）|
| 引擎本体 | RGSS103J.dll（约 1 M，用户装一次）| 打包进 APK（4.1 M）|

**同一个游戏，换平台后"系统帮我扛的部分"全变成了 APK 的负债。** 这跟素材多少没关系。

---

## 4. 实测：每一项能省多少

所有数字都是在本机对真实文件跑出来的，不是估算。

| # | 优化项 | 现状 | 可降至 | 省 | 风险 | 性质 |
| --- | --- | ---: | ---: | ---: | --- | --- |
| 1 | **删 `DroidSansFallbackFull.ttf`** | 2.05 M | 0 | **2.05 M** | 无 | **纯死重**，`fontSub` 没任何条目指向它 |
| 2 | **`NotoSansCJKsc` 子集化** | 13.68 M | 1.8 M | **11.9 M** | 低 | 6.5 万字形，游戏只用 2148 个 |
| 3 | **去掉 `armeabi-v7a`** | 11.45 M | 0 | **11.45 M** | 低 | 32 位设备已近乎绝迹 |
| 4 | `Endflash` → JPEG q88 | 33.62 M | 13.3 M | 20.3 M | 中 | 无需改引擎，纯素材替换 |
| 5 | `Endflash` → 视频 | 33.62 M | ≈ 2 M | 31.6 M | 高 | 需引擎支持播放 |
| 6 | `Endflash` 去重 | 33.62 M | 24.9 M | 8.7 M | 中高 | 180 帧里 47 帧完全相同，需改脚本帧映射 |

### 关键项实测细节

**字体子集化**（用 `fontTools.subset`，保留 ASCII + 全角标点 + 日文假名）：

| 方案 | 字符数 | 体积 | 相对原始 |
| --- | ---: | ---: | ---: |
| 原字体 | 65,535 字形 | 16.48 M | 100% |
| A：游戏精确用字 | 2,494 | **1.14 M** | 7% |
| **B：A + GB2312 一级（3755 字）** | **4,457** | **2.09 M** | **13%** |
| C：A + GB2312 全集 | 7,797 | 3.62 M | 22% |

游戏 `Data/*.rxdata` 里实际出现的汉字只有 **2148 个**，两个字体都能 100% 覆盖。
推荐 **B 方案**：覆盖全部剧情文本 + 3755 常用字（玩家起名够用），省 15.2 M 原始 / 11.9 M 压缩后。

**`Endflash` 的性质**（180 张 640×480）：

- 帧间平均差 **3~8**（同一画面的微调），有 **47 帧与前一帧字节完全相同**
- 抽样 10 帧，**0 帧含真透明通道** → 可安全转 JPEG
- 无损 WebP：单帧只要原 PNG 的 71%；有损 WebP q90：全量仅 9.0 M
- 这意味着它本质上是**一段视频**，被存成了 180 张独立位图

---

## 5. 已验证「无效」的路径

省下以后别再试：

| 尝试 | 实测结果 | 结论 |
| --- | --- | --- |
| PNG 无损重压（`optimize=True, compress_level=9`） | 2.09 M → **2.88 M（+37.7%）** | **反而变大**，原始 PNG 已是高度优化过的 |
| `.so` 符号剥离 | `readelf` 查无 `.symtab` | **已经 strip 过**，没有空间 |
| 音频重编码 | 262 个全是 ogg/mp3/mid | 已是有损压缩，无余量 |
| WebP 替换 PNG | `libSDL2_image.so` 里无 `libwebp` 符号 | 引擎**没有 WebP 解码器**，要重编 SDL2_image 才能用 |

---

## 6. 建议的执行顺序

**第一批（零风险，收益 25.4 M，APK → 74.6 M）**

1. 删 `DroidSansFallbackFull.ttf`（2.05 M）—— 先确认 `fontSub` 无引用，然后直接删
2. Noto 子集化到 B 方案（11.9 M）—— 生成脚本入 `tools/`，可复现
3. 去掉 `armeabi-v7a`（11.45 M）—— 需确认是否还有 32 位用户

> 这三项**不改变任何一个像素**，纯粹是"把用不到的东西扔掉"。

**第二批（需决策，收益 20~31 M）**

`Endflash` 的处理方式取决于能接受多大改动：

- 想一次到位 → 转视频（31.6 M，但要给引擎加播放能力，工作量大）
- 想稳 → JPEG q88（20.3 M，纯素材替换，画质可接受因为本来就是过场 CG）
- 想零画质损失 → 去重（8.7 M，但要改脚本，帧时序容易错）

**与高清修复的关系**

高清 2x 会让像素类素材从 11 M 涨到约 28 M（+17 M），正好被第一批省下的 25.4 M 覆盖。
**也就是说：做完瘦身再做高清，APK 反而比现在更小（约 92 M）。** 这两件事不是取舍关系。

---

## 7. 复现方式

```bash
# APK 分层
python - <<'PY'
import zipfile, collections
z = zipfile.ZipFile('app/build/outputs/apk/debug/app-debug.apk')
print(sum(i.compress_size for i in z.infolist())/1048576, 'MiB')
PY

# game.zip 分层
python - <<'PY'
import zipfile, collections
z = zipfile.ZipFile('app/src/main/assets/game.zip')
agg = collections.defaultdict(lambda: [0,0])
for i in z.infolist():
    k = '/'.join(i.filename.split('/')[:2])
    agg[k][0] += i.file_size; agg[k][1] += i.compress_size
for k,(r,c) in sorted(agg.items(), key=lambda x:-x[1][1])[:12]:
    print(f'{k:<34}{r/1048576:>8.2f}M -> {c/1048576:>7.2f}M')
PY
```

字体子集化见 `tools/hd/subset_fonts.py`（随第一批一起落地）。
