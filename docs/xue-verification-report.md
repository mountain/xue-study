# xue 实证验证报告：容器 ↔ Zarr store 的字节一致性与体积代价

> 验证时间：2026-09-16 · 上游 `ringsaturn/xue@main` · 全部结论来自**本机实际运行**，非阅读推断。
> 脚本：`verify.py`（独立读取器 + 字节比对）、`measure.py`、`sweep.py`，与本报告同目录。

---

## ⚠️ 0. 对上一版结论的更正

上一版报告的头条是：**"线上 store 比被取代的容器大 10.2%"**。

**该结论对 `tmp2m` 成立，但作为总体结论是错的。** 我把一个变量的结果外推到了全部。

扩到 8 个代表性 bundle 后的实测：**线上（全 RAW）store 合计比容器小 2.1%**；
而全开 `--delta` 反而比容器**大 0.9%**、比现网默认**差 3.1%**。

再把全部 **43 个变量**扫完后（§5.4），真正的结论是：

> **时间残差不是普适的。20 个变量适合残差、23 个适合 RAW——容器的"线性码本一律 PREVIOUS"
> 这条一刀切规则对过半数变量是错的**，其中云量、气压、垂直速度三个家族**整体**站错了边。
> 逐变量选择的收益经标定约为发布字节的 **1.1%**（§5.5）。
>
> 但**实测客户端代价后，我把自己提出并实现的改进建议降级了**（§5.8–§5.10）：
> store 里只要有一个数组用自定义 codec，**整个数据集**对 xarray 就不可读；
> 1.84% 的体积换一半数据集对生态失明，不划算。**现网"全 RAW"是正确的取舍。**

---

## 1. 方法论：怎么保证这不是自我印证

1. **两侧解析器全部由我按规范手写**，不调用 `xuebuild.zarrstore` / `xuebuild.binformat` 的任何函数：
   容器 v2 索引（IDX2 三张表 + **前缀和**偏移 + 8 字节对齐 + 零填充断言）、
   Zarr shard（`sharding_indexed` + suffix index + `xue.delta` 运行和）。
2. **CRC-32C 自己实现**（Castagnoli `0x1EDC6F41`）——刻意不用 `zlib.crc32`，那是 IEEE 多项式，错的也能通过。
3. **第三方裁判是 Rust 解码器**（`xuepy` wheel 的 `xue.Bundle`），与 Python 编码器是两套独立实现。
4. **数据是真的**：NOAA 公开桶按字节范围抓取的 GFS **2026-09-16 00Z**、**161 帧全轴**、全分辨率 1440×721、
   `--profile balanced`（线上所用）。不是合成图案。
5. **预测器优劣用一个完全独立的实验复核**（§5.3）：我自己用 zstd 对同一批数据分别按 RAW 与时间残差压缩求和。

---

## 2. 环境：无系统 GDAL、无 ffmpeg 下跑通全链路

Python 3.14.0 · numpy 2.5.2 · **xuepy 0.16.0**（wheel 自带 GDAL）· 系统 GDAL 与 ffmpeg **均无**。

8 个 bundle 的 161 帧全轴构建：首次 **11 分 32 秒**（含下载），缓存后 **25 秒**。
这本身验证了 `docs/encoder.md` 的主张：**定时发布流程完全不装 GDAL 是可行的**。

---

## 3. 决定性结果：逐字节复现线上产物

| 变量 | 本机重建 store | 线上 manifest | 字节数 | `?v=` CRC-32 |
|---|---:|---:|---|---|
| `tmp2m` | 40,643,714 | 40,643,714 | ✅ | ✅ `7d18ca5f` |
| `prate` | 46,745,894 | 46,745,894 | ✅ | ✅ `4f988fff` |

**不只是"符合规范"，而是同一串字节。** 这条流水线是确定性的。

> 插曲：最初用默认 profile（`quality`）构建，`tmp2m` 是 40,643,713——**恰好差 1 字节**。
> 原因：`quality`(7 字符) 与 `balanced`(8 字符) 在元数据 JSON 里差一个字符。
> 对 `tmp2m` 两个 profile 码本相同故只差这 1 字节；`prate` 则差很多——
> balanced 的 128 级降水码本省 **14.2%**（quality 54,350,752 → balanced 46,631,568）。

---

## 4. 字节一致性的确切边界（161 帧生产轴）

| 变量 | predictor | store 链 | 可比块 | **字节完全相同** |
|---|---|---|---:|---:|
| `tmp2m` | PREVIOUS | `[bytes, zstd]` ← **线上默认** | 7800 | **0** |
| `tmp2m` | PREVIOUS | `[xue.delta, bytes, zstd]` | 7800 | **7800** |
| `tcdc` | PREVIOUS | `[bytes, zstd]` | 7800 | **0** |
| `tcdc` | PREVIOUS | `[xue.delta, …]` | 7800 | **7800** |
| `prate` | RAW | 任一链 | 7800 | **7800** |
| `wind10m` 两个数组 | PREVIOUS | `[xue.delta, …]` | 15600 | **15600** |

另：每个变量 **161/161 帧**经我的读取器解出的码与 Rust 解码器完全一致；
shard 索引 CRC-32C（11340 条目）全部通过；`index_location: "start"` 与 `"end"` 两条路径都验过。

**精确复现规范原话**：*"压缩字节在布局重合处完全相同……预测变量在 delta 链下，RAW 变量在任一链下。"*

### 为什么"可比块"只有 7800 / 11340

容器把时间组切在**等步长分段内**，store 是**固定 6 帧**网格。GFS 在 f120 变步长：

```
容器 28 组:   0,6,…,114 (20 个对齐) │ 120(单帧) │ 121,127,133,139,145,151,157 (7 个错位)
store 27 块:  0,6,12,…,156
```

第二段起整体错位，**一个都对不上**。这是规范写明的 "coincide up to the first change of step"，
也正是导出报告要老实数 `comparableChunks` 而不是假设的原因。

> 我第一版校验器在这里出过错：隐含假设"第 i 组 ↔ 第 i 个时间块"，报出 10140。修正后 = 7800，
> 与作者记账一致。**这个 bug 在 13 帧下不会暴露**（那时组恰好对齐）。

---

## 5. 核心发现：时间残差不是普适的

### 5.1 八个体量在 161 帧生产轴上的实测（profile=balanced）

| bundle | 容器 `.xue` | store（全 RAW，现网默认） | store（全 delta） | **逐变量最优** | 胜者 |
|---|---:|---:|---:|---:|---|
| `tcdc` | 80,430,288 | **0.795×** | 1.009× | 0.795× | **RAW**（省 21.2%） |
| `prmsl` | 21,126,784 | **0.934×** | 1.012× | 0.934× | **RAW**（省 7.7%） |
| `rh850` | 85,218,064 | **0.996×** | 1.010× | 0.996× | RAW（省 1.4%，≈中性） |
| `prate` | 46,631,568 | **1.002×** | 1.002× | 1.002× | RAW（设计如此） |
| `wind10m` | 100,185,720 | 1.040× | **1.009×** | 1.009× | delta（省 3.0%） |
| `tmp2m` | 36,885,368 | 1.102× | **1.010×** | 1.010× | delta（省 8.3%） |
| `cape` | 31,590,480 | 1.023× | **1.011×** | 1.011× | delta（省 1.1%） |
| `htsgw` | 16,923,448 | 1.053× | **1.014×** | 1.014× | delta（省 3.8%） |
| **合计** | **418,991,720** | **410,306,512 (0.979×)** | 422,786,392 (1.009×) | **402,747,134 (0.961×)** | |

- **现网默认（全 RAW）比容器小 2.1%** ——迁移到 Zarr 没有付出体积代价，反而略有收益。
- **全开 `--delta` 比现网默认差 3.1%** ——我上一版暗示的"打开 delta 就好了"是错的。
- **逐变量最优比容器小 3.9%、比现网默认小 1.8%** ——这是真正可行动的空间。

### 5.2 机制：移动的不连续面

三个变量的方向差异有清晰的物理解释：

- **`tmp2m`（+12.4% 收益）**：连续平滑场，相邻帧几乎相同，残差接近零。
- **`tcdc`（−19.1% 收益，即 RAW 更优）**：云量有大量"满覆盖/晴空"的平台区，且随天气系统**移动**——
  固定网格差分会在系统**进入**与**离开**两侧各造出一整条边缘，与 `docs/format.md` 对降水的论证**逐字相同**。
- **`prmsl`（RAW 更优 5.3%）**：海平面气压本身平滑，但空间自相关极强，RAW 让 zstd 的匹配查找器
  充分发挥；残差场反而抬高了空间熵。

### 5.3 独立复核（不依赖容器/store 的构建）

我自己用 zstd 对**帧 30–35 的全部 420 个瓦片**分别按 RAW 与时间残差压缩求和：

| 变量 | RAW 合计 | 残差合计 | 残差/RAW | 更优 |
|---|---:|---:|---:|---|
| `tmp2m` | 1,481,620 | 1,298,267 | 0.876 | 时间残差 **+12.4%** |
| `htsgw` | 623,844 | 584,977 | 0.938 | 时间残差 +6.2% |
| `cape` | 1,204,055 | 1,134,394 | 0.942 | 时间残差 +5.8% |
| `rh850` | 3,158,387 | 3,088,706 | 0.978 | 时间残差 +2.2%（§5.1 判 RAW，**分歧但接近中性**） |
| `prmsl` | 709,492 | 749,317 | 1.056 | RAW **+5.3%** |
| `prate` | 1,773,828 | 2,036,070 | 1.148 | RAW **+12.9%** |
| `tcdc` | 2,335,402 | 2,885,889 | 1.236 | RAW **+19.1%** |

**方向与整文件测量一致**（唯一分歧 `rh850` 本就接近中性），机制得到独立确认。

> 我最初做这个复核时只取了 1 个瓦片（北极附近、单块），得出"所有变量 RAW 都更优"的错误结论——
> 小样本下 zstd 建立不了统计，且极区本身就极均匀。改为整个时间块全部 420 瓦片后方向才稳定。

### 5.4 全量扫描：43 个变量，一半站错了边

把全部 37 个 bundle（43 个变量）都测了一遍——**判据是 6 帧块内的局部性质，所以用 13 帧短轴即可**，
无需建 161 帧全轴。做法与 §5.3 相同：对全部瓦片分别按 RAW 与时间残差压缩求和。

**结论：20 个变量残差更优，23 个变量 RAW 更优。** 而容器的规则是"线性码本变量一律 PREVIOUS"，
也就是说这条一刀切规则**对 23 个变量（过半数）是错的**。

按家族看，规律非常干净：

| 家族 | 变量数 | 残差更优 | 说明 |
|---|---:|---:|---|
| **云量**（tcdc/lcdc/mcdc/hcdc） | 4 | **0** | RAW 优 20–28% |
| **气压**（prmsl + hgt250/500/700/850） | 5 | **0** | RAW 优 5–13% |
| **垂直速度**（vvel500/700/850） | 3 | **0** | RAW 优 13–17% |
| 风 / 波 / 水汽通量 | 12 | 8 | 残差普遍优 1–8% |
| 温度类（tmpsfc/tmp2m/dpt2m/aptmp2m/tmp925/tmp850/tmp500） | 7 | 5 | 平滑场优 3–10%，但 `tmp500` 反过来 RAW 优 11% |
| 其他（cape/vis/gust/rh/icec/icetk/perpw/prate…） | 13 | 8 | 混合 |

单个变量上最划算的几笔（块级预测，未标定）：

```
tmpsfc  0.865  →  省 13.5%      tcdc  1.233  →  RAW 省 23.3%
tmp2m   0.870  →  省 13.0%      mcdc  1.274  →  RAW 省 27.4%
dpt2m   0.900  →  省 10.0%      hcdc  1.282  →  RAW 省 28.2%
wind10m 0.925  →  省  7.5%      vvel500 1.165 →  RAW 省 16.5%
```

### 5.5 幅度标定：块级测量会放大，真实收益约 1.1%

块级测量只看一个时间块，会**系统性放大**效应。用 8 个 bundle 的全轴真值标定：

| bundle | 块级预测省 | 全轴真值省 |
|---|---:|---:|
| `tmp2m` | 5,283,683 | 3,371,617 |
| `wind10m` | 7,817,167 | 3,143,804 |
| `htsgw` | 1,087,452 | 673,308 |
| `cape` | 1,809,912 | 370,649 |
| `rh850` | 2,631,099 | **0**（全轴上 RAW 反而更优） |
| 合计 | 18,629,313 | 7,559,378 |

**标定系数 = 0.406**。全量块级预测 47,119,654（2.7%）→ **标定后约 19.1 MB ≈ 1.1%**
（对 1,769,956,427 字节的全分辨率 store 计）。

所以：**方向确凿（23/43 变量站错边），幅度约 1%，是"该修但不紧急"的量级。**

### 5.6 可行动的结论

容器当前的规则是**一刀切**的（`docs/format.md` §"Encoder rules (v2)"）：

> Predictor: RAW for `prate` and `cref`; **PREVIOUS for every linear-codebook field**.

实测表明这条规则对**云量、气压、垂直速度三个家族整体不成立**。关键是：
**`tcdc`/`lcdc`/`mcdc`/`hcdc`、`cape`、`gust`、`vis`、`vvel*` 都是本地快照之后才加入的变量**
（上游 2026-09-11 起陆续加入），加入时那条一刀切规则**没有被重新审视**。
对云量家族，`docs/format.md` 用来论证降水该用 RAW 的那段话——*"降水区随天气系统移动，
固定网格差分会在进入与离开两侧各造出边缘，实测增大压缩后体积"*——**逐字适用于云量**。

**建议**：
1. **store 侧**：把预测器从全局开关（`--delta` 现在作用于所有 PREVIOUS 变量）改成**逐数组策略**。
   store 是派生的，改它不影响任何已发布字节，也不需要格式变更。
2. **容器侧**：编码器的 predictor 规则应按家族重定，云量家族与 `prate`/`cref` 同等对待。
   这需要动 `xuebuild/temporal.py` 的 predictor 表并同步 Rust 侧（`build_chunks` 的 CPU 预测器表），
   且会让 golden 夹具与编码器 parity 测试全部重生成——**是一次有成本的改动**。

> ⚠️ **这两条建议在 §5.8–§5.10 被实测后降级了**：第 1 条（store 侧）我实现并跑通了，
> 但客户端代价实测出来是"整个数据集对 xarray 失效"，1.84% 不划算。
> 请以 §5.10 的修正结论为准。

---

### 5.7 原型实现：`--delta auto`（已跑通）

我把建议的 **store 侧**那条实现了出来，在上游克隆里跑通（补丁见 `delta-auto.patch`，178 行，纯 Python）。

**关键前提**：store 导出**完全在 Python 侧**——`binconvert`（参考管线）与 `native.py`（原生管线）
都调用同一个 `xuebuild/zarrstore.py::export_bundle`。所以这个改动**不需要同步 Rust**，
也不影响两条编码路径的字节一致性。这比我上一版说的成本要低。

### 做法

`export_bundle(delta=...)` 增加第三种取值 `"auto"`：对每个数组把自己**按两种链各压一遍**
（全部时间块求和），取更小的那个。CLI 是 `--delta`（=all，向后兼容）/ `--delta auto`。
`ExportReport` 增加 `deltaArrays` 记录逐数组的选择。

**决策是精确的，不是采样的。** 我试过三种采样，都不够：

| 采样方式 | 结果 | 错在 |
|---|---|---|
| 只取第 1 个时间块 | 7/8 正确 | `rh850` 判错（选 delta，实际 RAW 更小 1.4%） |
| 首/中/末三块 | 3/8 正确 | 中末落在 3 小时步长区，**高估**粗步长段的代价 → `cape`/`htsgw`/`wind10m` 判错 |
| 每第 8 块 | 7/8 正确 | `rh850` 仍错（1.4% 的边缘案例采样判不了） |

这是**变步长时间轴的直接后果**：GFS 大部分块是 1 小时步长、其余是 3 小时，差分收益随步长变化。
所以最终选**全块精确测量**——代价是每个数组多一遍压缩（payload 丢弃，不占内存）。

### 实测结果（8 个全轴 bundle，161 帧）

| bundle | 现网默认（全 RAW） | `--delta auto` | 逐数组决策 |
|---|---:|---:|---|
| `tmp2m` | 40,643,714 | **37,272,097** | delta |
| `prate` | 46,745,894 | 46,745,894 | — |
| `prmsl` | 19,732,068 | 19,732,068 | — |
| `rh850` | 84,874,170 | 84,874,170 | — |
| `cape` | 32,319,852 | **31,949,203** | delta |
| `tcdc` | 63,934,835 | 63,934,835 | — |
| `wind10m` | 104,228,889 | **101,085,085** | delta（两个数组） |
| `htsgw` | 17,827,090 | **17,153,782** | delta |
| **合计** | **410,306,512** | **402,747,134** | |

- **`auto` 的结果 8/8 命中理论最优**（=`min(RAW, delta)`），因为决策是精确测量而非估计。
- **收益 7,559,378 字节 = 现网默认的 1.84%**；相对容器则是 0.961×（小 3.9%）。
- **代价**：单 bundle 导出 3.3 秒 → 9.3 秒（2.8×）。`auto` 是选择加入的模式，默认行为不变。

### 正确性与回归

- 我的独立校验器：4 个 auto store **161/161 帧**与 Rust 解码器一致；链与决策相符
  （`tmp2m` delta → 7800/7800 与容器逐字节相同；`tcdc`/`rh850`/`prmsl` RAW → 0/7800，符合预期）。
- 上游 `test_zarr` **OK**、`test_bin` **OK**。
- `test_native` 报 6 个错，**全部是 `setUpClass` 里缺系统 `gdal_translate`**（参考管线需要），
  **与本次改动无关**。装了 GDAL 即消失。

### 尚未做的

- **没有接到 `build-bin --zarr` 上**，只在 `export-zarr` 上可用；接上去才会让定时发布真正用上。
- **没有覆盖 43 个变量的完整收益**（只测了 8 个全轴；§5.5 标定后估计全量约 1.1%）。
- ~~没有考虑客户端代价~~ → **已在 §5.8 实测，结论是我的建议需要降级**。
- **没有提交上游**，只是一个在 `/tmp` 克隆里跑通的原型。

### 5.8 客户端代价实测：这是全有或全无的（**结论因此改变**）

上一版我把"客户端需要注册 codec"列为未评估的风险。装上 `zarr 3.3.0` + `xarray 2026.7.0` 实测后，
它的代价比我预估的**重得多**。测试用 `wind10m`（双变量），并额外构造了一个**混合 store**
（`ugrd10m` 走标准链、`vgrd10m` 走 delta 链），以回答"只有一部分数组用自定义 codec 会怎样"。

| store | 未注册任何 codec 的普通客户端 |
|---|---|
| 全 RAW | ✅ `open_group` 成功；坐标正确读出（lat 90→89.75、lon −180→−179.75、time 0→3600→7200）；两个数组可读；`xarray.load()` 载入全部 334,313,280 个值 |
| 全 delta | ❌ **`open_group` 直接抛 `UnknownCodecError: Unknown codec: 'xue.delta'`** |
| **混合（2 个数组中 1 个 delta）** | ❌ **同样在 `open_group` 抛错** |

**关键事实：代价不是"丢掉那一个变量"，而是整个 group 打不开。**
只要 store 里有**任何一个**数组用了 `xue.delta`，这个数据集对普通 Zarr/xarray 客户端就**完全不可读**。

对照 §5.7 的 `auto` 决策（8 个 bundle 里有 4 个出现 delta 数组），
**`--delta auto` 会让约一半的数据集对 xarray 完全失效，换取 1.84% 的体积**。

### 5.9 标准 codec 替代方案：已排除

既然要付互操作代价，自然的问题是：**能不能用标准 codec 达到同样的时间预测效果？**
唯一候选是 numcodecs 的 `Delta`。实测排除了它：

| 变量 | 说明 |
|---|---|
| `numcodecs.Delta(dtype="uint8")` | **往返不是无损的**（三种形状全部 `lossless=False`）。我一度测出它比 `xue.delta` 压得更小（0.850× vs 0.876×），但那是在**压缩已经损坏的数据**——无效比较 |
| `numcodecs.Delta(dtype="uint8", astype="int16")` | 把元素宽度加倍后，**比 RAW 还大**（1.037× vs `xue.delta` 的 0.876×）——加宽带来的熵增超过了差分的收益 |

原因是 `Delta` 没有 axis 参数，它差分的是**展平缓冲区**；而 uint8 的模 256 环绕语义它不提供，
要无损就必须加宽中间类型，代价超过收益。

**这个负面结果反过来证明了 `xue.delta` 作为自定义 codec 的必要性**——规范里那句
*"它不是 numcodecs 的 `Delta`，后者差分包平后的缓冲区"* 不是吹毛求疵，而是唯一可行的做法。

### 5.10 修正后的建议

我上一版建议"把 store 预测器改成逐数组策略"。**实测后我把它降级为：不要设为默认。**

- **对项目自己的前端**：代价为零。**这一条已从代码审查升级为执行验证**——
  我装好 `wasm32` target 与 `wasm-pack`、构建了 WASM 解码器，并**新写了一个测试**
  （`zarr-mixed.test.ts` + `prepare_mixed_fixture.py`，见本目录）：
  造一个 `ugrd10m` 走标准链、`vgrd10m` 走 delta 链的**混合 store**，
  断言**两个数组的每一帧、每一条格点序列都与容器解码逐字节一致**。**4/4 通过。**
  上游自己的 `zarr.test.ts` 覆盖了"整包一条链"和"整包另一条链"，**但没有覆盖混合**——
  这正是我补的缺口。机制上：`zarr/session.ts:114` 逐数组取自己的 `zarr.json` 读链，
  `session.ts:127-134` 的一致性检查**只比几何**（`tileHeight`/`tileWidth`/`timeChunk`/`shardFrames`）。
- **对第三方生态（xarray / zarrs / zarrita）**：代价是**整个数据集不可读**（§5.8 实测），
  而迁移到 Zarr 的初衷正是"让 xarray 不用自带解码器就能读一次 Xue run"。
- **1.84% 的体积，换一半数据集对生态失明**——这笔账不划算。

所以现网"全 RAW"**不是漏掉的优化，而是正确的取舍**。逐数组预测器应当保留为
**面向自家前端的可选项**（例如一个仅供站点的发布档），而不是发布默认值。

> **对上游的一条公正评价**：我原以为前端 Zarr 通道是"最大的验证空白"。跑起来之后发现
> `tests/web/zarr.test.ts` 有 **44 个测试**，而且**恰好覆盖了我从规范独立推导出的那些点**——
> "CRC-32C 是 Castagnoli 不是容器的 IEEE 多项式"、64 KB 范围合并阈值、
> 不知道对象长度也能读的 suffix range、以及"合并前后各花多少请求"。
> 上游的覆盖比我先前暗示的强得多；我的独立推导的价值在于**独立**，而非填补空缺。

---

## 6. 为什么现网"全 RAW"反而比容器小

三条同时成立：

1. 现网发布的字段组合里**不连续场占比很大**（云量 ×4、降水、CAPE、能见度、垂直速度……），
   RAW 对它们是赢的；
2. 容器对**每个**线性码本变量强加 PREVIOUS，把云量这类场也拖下水；
3. store 的额外开销（索引 16 字节/块 vs 容器 8 字节、shard 补零到整瓦片整时间块）
   在 161 帧全轴上只有约 1%（§4 已量化，短轴时才会放大到 10% 量级）。

---

## 7. 附带发现：`xue.delta` 与 shard padding 相互作用差

`_pad_block()` 先补 nodata 到整个 inner chunk，`_delta_encode()` 再在**已填充的块**上差分
（`zarrstore.py:421`、`:430`）。于是真实帧之后的第一个填充帧变成 `(255 − 真实值) mod 256`——
近满熵，zstd 压不动。

- 13 帧实测：padding 时间块在 delta 链下是容器的 **1.988×**，无 delta 下 1.008×；吃掉 9.4 个百分点。
- 161 帧实测：同一项只占 **0.5 个百分点**。

**不能随手修**：填充帧必须解码回 `fill_value: 255`（规范明确保证，`test_chunks_come_back_trimmed` 在测），
delta 链下这个保证**必然**要求那一帧携带高熵残差。唯一"修法"是放弃该保证（profile 变更），换 0.5%。
**结论：现状合理，但文档该写明这个交互。**

---

## 8. 自我纠错记录

| 我最初的结论 | 核实后 |
|---|---|
| "线上 store 比容器大 **1.67×**" | ❌ `bandwidth` 是 **HLS 比特率**不是字节数（`binconvert.py:1294`）。真值见 §5.1 |
| "线上 store 比容器大 **10.2%**（总体）" | ❌ 把一个变量外推到全部。**总体是 0.979×（更小）**，见 §0 |
| "打开 `--delta` 就能省" | ❌ 全开比现网默认**差 3.1%**。只有逐变量选才对 |
| 校验器报 `comparable=10140` | ❌ 我的 bug：假设"第 i 组 ↔ 第 i 时间块"，变步长后错位。修正后 7800 |
| 直接压缩实验：所有变量 RAW 都更优 | ❌ 取样太差（1 个极区瓦片）。改为整时间块 420 瓦片后方向稳定 |
| 上游 `test_assemble`/`test_ocean` 报错 | ❌ 我的环境缺 `gdal_translate`。**不是上游 bug，不要上报** |

---

## 9. 上游测试套件实跑（无 GDAL / 无 ffmpeg）

| 模块 | 结果 |
|---|---|
| `test_bin`（容器结构） | **77 通过** |
| `test_zarr`（store 等价） | **12 通过，6 跳过**（需 zarr-python，属 `zarr` 依赖组） |
| `test_stac` | 19 通过，1 跳过 |
| `test_pressure` / `test_surface` / `test_isobaric` | 全部通过 |
| `test_assemble` / `test_ocean` | 各 2 例报错，**原因是我环境缺系统 GDAL** |

---

## 10. 复现步骤

```sh
cd /tmp/xue-upstream
export UV_CACHE_DIR=/tmp/uv-cache          # 沙箱不允许写 ~/.cache/uv
uv sync                                     # Python 3.14 + numpy + xuepy 0.16（自带 GDAL）
export XUE_ENCODER=native

# ① 全量预测器评估：13 帧短轴就够（判据是 6 帧块内的局部性质）
uv run python -m xuebuild build-bin --model gfs --run 2026091600 --hours 12 \
  --profile balanced --raw-dir /tmp/xue-verify/raw-all --output-dir /tmp/xue-verify/all \
  --work-dir /tmp/xue-verify/work-all --skip-video --skip-variants      # 约 6 分钟
uv run python predictors.py /tmp/xue-verify/all/gfs.2026091600 /tmp/xue_manifest.json

# ② 生产轴真值（用于标定幅度）
uv run python -m xuebuild build-bin --model gfs --run 2026091600 --hours 240 \
  --bundles tmp2m prate prmsl rh850 cape tcdc wind10m htsgw --profile balanced \
  --raw-dir /tmp/xue-verify/raw-full --output-dir /tmp/xue-verify/bal \
  --work-dir /tmp/xue-verify/work-bal --zarr --skip-video --skip-variants
uv run python sweep.py  /tmp/xue-verify/bal/gfs.2026091600 /tmp/xue-verify/bal-delta \
                        tmp2m prate prmsl rh850 cape tcdc wind10m htsgw

# ③ 独立验证
uv run python verify.py /tmp/xue-verify/bal/gfs.2026091600/tcdc.xue \
                        /tmp/xue-verify/bal-delta/tcdc.zarr tcdc
```

`xue_manifest.json` 是线上 `https://dataset.ringsaturn.me/xue/gfs.2026091600/manifest.json` 的快照
（用于取每个 bundle 的已发布 store 体积）。

---

## 11. 诚实的局限

1. **幅度只有约 1.1%，且是标定值**：43 个变量的**方向**是逐块实测的（可靠），但**幅度**靠 8 个 bundle
   的全轴真值标定（系数 0.406）。全量真值需要把 37 个 bundle 都建成 161 帧全轴，**我没做**。
2. **只验了 GFS**。ECMWF / sflux / HRRR（走重投影）/ MRMS / JMA 未验，风险面不同。
   预测器偏好可能随源而变（分辨率、量化码本都不同）。
3. **浏览器端只到了单测层**。我已构建 WASM 解码器并跑通全部前端单测
   （**408 个通过 / 27 个文件**，含 `zarr.test.ts` 44 个与我新写的混合链测试 4 个），
   但**仍未在真实浏览器里跑过页面**：Playwright e2e 需要下载 Chromium 到工作区外，
   我**没有**做；`wasm-pack test --headless --chrome` 也没有跑。
   所以"渲染出来对不对"（视觉、WebGL 图层、粒子、底图）**依然未验**。
4. §5.3 / §5.4 的块级测量只取了**一个时间块**（帧 30–35 / 帧 0–5）。`rh850` 就是块级与全轴的分歧点
   （块级判残差优 3%，全轴判 RAW 优 0.4%），说明这类接近中性的变量结论不稳。
5. **未验 v1 容器导出路径**（`index_location` 两种取值验过，但未验 v1 输入）。
6. **容器侧的建议没有实现也没有提交**。store 侧的那条我实现并跑通了（§5.7），
   但实测后自己降级了（§5.10）。

---

## 12. 附录：把前端跑起来需要什么（实测）

上游 CI 的 `web` job 在本机复现时踩到的三处**工作区外写入**，全部可以用环境变量绕开：

| 组件 | 障碍 | 绕法 |
|---|---|---|
| `rustup target add wasm32-unknown-unknown` | 写 `~/.rustup` | **绕不开**，需要一次更宽权限（我申请并获批了一次） |
| `wasm-pack` | `cargo install` 写 `~/.cargo` | `CARGO_HOME=/tmp/cargo-home cargo install wasm-pack --root /tmp/xue-tools` |
| `wasm-pack` 自身的工具缓存 | 写 `~/Library/Caches/.wasm-pack` | `HOME=/tmp/fake-home`（配 `RUSTUP_HOME` 指向真实目录） |
| `npm install` | 写 `~/.npm` | `npm install --cache /tmp/npm-cache` |

跑通后的实际结果：

```
npm run test:web   →  27 files / 408 tests passed   （含 zarr.test.ts 44 个）
npm run build      →  tsc --noEmit 通过；vite 产出 dist/，xue_bg.wasm 206.90 kB
```

**另一条实测事实（对"本地跑站点"很关键）**：数据桶的 CORS **只对生产 origin 开放**——

```
Origin: https://xue.ringsaturn.me   →  access-control-allow-origin: https://xue.ringsaturn.me
Origin: http://localhost:4173       →  （无 CORS 头）
Origin: http://localhost:8899       →  （无 CORS 头）
```

所以**本地起的站点读不了线上数据**（浏览器会拦）。要在本地看，必须自己构建一份 run 放进
`web/public/data/`（同源，无 CORS 问题）。这也解释了为什么 `web/.env.deploy` 只在部署构建里生效。

---

## 13. 追加更正（本节起改为 append-only）

**从本节开始，这份报告不再被重写。** 后续发现以带日期的条目追加到本节，
正文中已被推翻的段落**保留原样**，由本节指出它被什么取代。

> 为什么改：Adva 的 `docs/research/README.md` 写着——
> *"编号笔记是追加记录。后续笔记可以取代它，但**不重写**它。"*
> 本报告此前**被整篇重写过两次**（第一版头条件为线上体积回归，第二版改为合计更小），
> 两版原文都已被就地覆盖、**从文件里不可恢复**。
> 那些结论是怎么被推翻的，现在只活在上面 §8 的叙述里，而不是活在有出处的文本里。
> 这是纪律问题，不是笔误。

### 2026-09-16 · 更正一：§5.8 混合 store 一格的**证据无效**

§5.8 的四格矩阵里，"混合 store 也打不开"那一格，当时的 store 是这样造的：
用 `--delta auto` 导出（两个数组都判 delta），再**覆盖掉 `ugrd10m/` 目录**——
**没有同步重写分组文档里的 `consolidated_metadata`**。
于是分组文档声明两个数组都是 delta，与磁盘上的数组不符，
而 zarr-python 默认走 `use_consolidated=True`，读的正是那份文档。
**结论侥幸正确，证据无效。**

已用 `tests/prepare_mixed_fixture.py` 生成的自洽夹具重做（分组文档与其数组逐字核对一致），
结果不变：整包标准链不注册即可打开；自洽混合 store 在 `open_group` 抛
`UnknownCodecError: Unknown codec: 'xue.delta'`；注册后三种均可打开。

**不变的结论 + 被替换的证据。** 该实验的 `assumptions` 与 `forbidden_conflations` 已记入
`claims.toml` 的 `xue.store.per-array-chain-interop.v0`。

### 2026-09-16 · 更正二：一条被写成"规则是错的"的规范判断

§5.4 与 §5.6 使用的措辞是"容器的编码器规则**对过半数变量是错的**"。
按 Adva 的 `forbidden_conflations` 纪律复核后，这句话混淆了两件事：

- 本次测量建立的是**压缩字节**：某个变量在某条链下更小；
- 而容器的规则是 `docs/format.md` 里一条**规范性的编码器规则**，
  其作用是把两条编码路径锁成字节一致——它是规范，不是压缩启发式。

**压得更小并不使它成为错误，正如压得更大也不使它成为错误。**
准确的表述是"该规则对 23 个变量在压缩字节上不是最优的"。
见 `claims.toml` 的第一条 forbidden conflation。

### 2026-09-17 · 更正三：「没有任何一方被指定为权威」——这句话是错的

我此前反复写过（README §七、本报告会话中多次）：等值线半码对齐规则"没有任何一方被指定为权威"。
**在被要求把它变成可检验的问题之后，我查了，这句话站不住。**

`tests/test_pressure.py` 的**模块 docstring 自己就写明了**：

> *"把它们三者绑在一起的是 `tests/fixtures/pressure-registry.json`，一份本模块重新生成并比对的 golden；
> Rust 编码器的单测与前端的 vitest 读同一个文件，所以一个数字只能三者同时移动。
> **除了一个测试，没有任何东西陈述这条规则**——容器既不知道也不关心。"*

而且这套机制是**系统性的**，不只是压力族：

| golden | 由谁读 |
|---|---|
| `pressure-registry.json` | `test_pressure.py` + Rust 单测 + `web/src/pressure.ts` 的 vitest |
| `isobaric-registry.json` | `test_isobaric.py` + 前端 |
| `surface-registry.json` | `test_surface.py` + 前端 |
| `ocean-registry.json` | `test_ocean.py` + 前端 |
| `tc-registry.json` | `test_tc.py` + 前端 |

`test_the_committed_registry_still_describes_this_encoder` 逐一比对编码器注册表与 golden，
而 `test_every_contour_lands_half_a_code_off` 在**整个码本跨度**上检验半码对齐且要求每变量多于 8 条等值线。
**我假设的那个洞（新增压力变量、测试照过、等值线画错）是堵住的。**

正确的说法是：**xue 的权威不是某个组件，而是一份提交进仓库的、被所有实现共读的 golden，
每个族一份。** 这与 Adva"Rust 是语义唯一权威"是两种不同的答案，而 xue 的这一种在它的语境里是成立的。

**教训**：我连续两轮把"我没找到"说成了"不存在"。这与更正一（实验证据无效）是同一类错误——
都是把**尚未检验**当成了**已经建立**。

### 2026-09-17 · 记录：权威问题带出的一个真实发现

把权威问题变成可检验的问题之后，找到一个**此前没人注意到的**东西——
不是什么"权威空缺"，而是**派生量的覆盖面不对称**：

- `derive_vapour_flux` **有**数值测试（`test_the_vapour_flux_is_q_v_over_g`：喂进 q/u/v，断言手算值，**并钉住精确的运算顺序**以保 parity）
- `derive_theta_e` **没有**。测试只覆盖"注册了 / 在哪些模式上发布 / 输入是 `tmp850` + `spfh850`"，
  **从不检验那个数对不对**。

而 θe 的公式链比水汽通量长得多（Bolton 1980 式 43 + 式 15 + 式 10），
两个编码器只被**字节一致**绑在一起——而 parity 是**关系性**保证：它说 Python 与 Rust 一致，
不说它们与物理一致。

我于是独立算了一遍（用**发布的 `rh850` 反推 q**，与编码器用的 `spfh850` 是不同输入路径）：
**平均偏差 +0.109 K**——**公式是对的**。但发布场**每一帧的上界都恰为 357.00 K**，即码本上限。

追下去，结论与我的预期相反：

| 区域 | 独立算得 θe | 发布场顶到上限的点 |
|---|---|---|
| 西太平洋暖池（真实气象） | 308–364 K，均值 339 K | **0–4 / 7021** |
| 青藏高原 | 318–397 K，均值 **359 K** | **62%–66%** |

**根因不是上限太低，而是 850 hPa 在高原上是地下约 3 km 的外推值。**
后果是：在 θe 这一层上，**青藏高原被画成比热带暖池更极端**，而那是伪值。

补一句与权威直接相关的：**编码器为每个变量都统计了截断点数**（`binconvert.py:1225` 的 `PlaneStats.clamped_points`），
但报告里只输出 `tmp2m` 与风场两项（`:1969`、`:1976`）——**θe 的计数被算出来然后丢掉了**。

已注册为 `xue.derived.theta-e-plateau-clamp.v0`。

### 2026-09-17 · 记录：θe 高原截断的**渲染后果已坐实**（这是本研究中第一份来自真实浏览器的证据）

`xue.derived.theta-e-plateau-clamp.v0` 的 `counterexample_boundary` 里原本写着
"我没有看页面，'高原在图上更亮'是从数值推的，不是截图"。**这一步现已关闭。**

用户先在真实浏览器里看了本地站点并确认（"没错"）。随后我把这件事做成了**可复现的产物**：
无头 Chrome 经 Playwright 驱动（`channel: "chrome"`，SwiftShader 软件渲染），
打开本地站点 `?type=thetae850`，得到 `thetae850-tibetan-plateau-clamp.png`。

图上（F045，整幅视口）：**青藏高原上空是一整片色标顶端的深红，可见地比热带暖池更极端。**
与数值分析一致（高原 62%–66% 的格点顶到 357 K 上限，而暖池只有 0–4/7021）。

**这条记录同时标志着本研究第一次跑通真实浏览器路径**——此前"没在真实浏览器里跑过页面"
是一切前端结论上挂着的边界。现在至少证明：构建产物能加载、worker 能解码、
WebGL2 图层能出图、时间轴与图例正确（"161 frames ready"、F045、09/18 23:00 UTC、色标 255–355 K）。

**尚未建立**：观看者会不会把它读成错误（UX 判断）；其他层次与其他调色板下的表现；
以及截图截的是**我本地构建的数据**，不是线上服务发布的那一份。

**过程中的一次工具失误，记下来**：先用 `--virtual-time-budget` 截，得到的是停在
"Loading manifest" 的空壳——虚拟时间在真实网络下推进，请求还没回来就截图了。
改用 Playwright 的真实等待后正常。**第一次看到"卡住"就以为是站点有问题，其实是我的等待方式错了。**

### 2026-09-17 · 上游漂移核查：基线 +59 个提交，**格式与编解码器未被改动**

按"尽快确认、避免重大风险"的要求，拉取上游并做了风险核查。

**基线漂移**：`8af4376` → `main`+59 个提交，139 个文件变更，71 个新增。
新增目录：`xuebuild/sounding/`（6 文件）、`xuebuild/airport/`（8 文件）、
`docs/sounding.md`、`docs/airport.md`；发布工作流 9 → **13**。

**风险核查（最要紧的一项）**——会动摇本报告全部字节级结论的文件：

| 被动过 | 未动 |
|---|---|
| `rust/xue/src/encode/sources.rs`（+32/−20） | `binconvert.py` · `zarrstore.py` · `quantize.py` · `temporal.py` · `binformat.py` · `manifest.py` |
| `rust/xue/src/bin/xue-encode.rs`（+1/−1） | **`docs/format.md` · `docs/zarr-profile.md`** |
| `xuebuild/sources.py`（+0/−0） | `rust/xue/src/format.rs` · `decode/` · `encode/` 其余 |

**结论：`claims.toml` 的 6 条 claim 全部不受影响。**
它们测的是格式、编码器、store 与派生量，而这 59 个提交**新增产品**，没有修改既有产物的产出路径。
唯一实质改动是源注册表（新增源），不触及任何被测量的行为。

**并且——我有一条推断被上游以另一种方式实现了，因此作废：**

README §三 原把**探空观察者**列为"没有被服务好"，推断修法是
「把各层次合成多变量 bundle，格式本来就装得下」。上游实现了这个观察者，
但用的是**一个独立的 JSON 产品**（`docs/sounding.md`：*"an ascent is not a raster,
so soundings are another, smaller product … plain JSON"*），复用同一套
「指针 → 不可变 CRC 目录」契约。

**这是同一类错误的第四次**：把**我的推断**讲得比证据支持的更肯定。
但这次它没有造成损害，因为它当初被我标注为"未测量，因此不进注册表"——
**它不在 claim 层，作废它不需要动任何一条已注册的结论。**

记下这条纪律的收益：**把未测量的东西挡在注册表之外，代价是少一个"发现"，收益是少一次污染。**

### 2026-09-17 · 与 Adva 工具链的合规核查：**字段兼容，但工具读不了**（已修）

Adva 主线在 2026-09-16 落地了工具工作流的前三个助手，其中 `scripts/navigate.py`
会按 `code_symbol` / `proof_or_certificate` / `scope` 里的**路径 token** 去观察文件是否存在，
并把每条 claim 归为 `historical` / `runnable-here` / `not-yet-executed`。

我把上游工具**原样**跑了我的 `claims.toml`（搭沙箱：它按脚本位置定 ROOT，
所以把 `navigate.py` 放在 `scripts/`、我的注册表放在 `docs/claims.toml` 即可）：

| | 之前 | 之后 |
|---|---|---|
| `navigate.py` | **`not-yet-executed=6`** | **`runnable-here=6`** |
| `navigate.py --corrections` | **空** | **3 条** |

**工具把六条已执行的测量全部判成"尚未执行"**，理由栏写的是
*"no evidence path or checker is recorded, or none of the recorded paths exists here"*——
而检查器我当时就摆在 `scripts/` 下。原因是 token 提取要求路径
**以 `experiments/ docs/ programs/ scripts/ tests/ crates/` 之一开头**，
而我写的是裸文件名与散文。

**这是本轮最值得记的一条**：一份看起来符合规范、实际工具读不了的注册表，
比没有注册表更危险——它把"已执行"呈现成"未执行"，而且没人会去查。

两处不合规都已修：检查器移入 `scripts/`、`code_symbol` 改为 root-relative；
六条更正从"一个大文件里的若干节"拆成 `docs/maintenance/` 下三份各自成篇的笔记
（工具的更正索引只扫那两个目录下的**独立文件**，且要求前 14 行同时含标记与被更正的**文件名**）。

**尚未采用**：`run_bounded.py` 的「五条轴分开」与 `problem_card.py` 的十字段问题卡。
本笔记的边界仍靠散文写。

### 2026-09-17 · 对 adva-machine 工具链的合规：**我的六条 claim 没有达到它的标尺**（已补契约）

`mountain/adva-machine`（本地 HEAD `6646582` 与上游一致）的 `toolchain/` 是一个统一的本地工具链接口：
`adva-machine capabilities | doctor | run --engine rust|python | conform`。
它立下的标尺比 `navigate.py` 高一层：

- **`conformance.contract.json` 在**执行之前**钉死十六个用例**——语料按 **sha256** 固定，
  不是事后挑的；
- 报告保留请求与可执行文件摘要、精确结局、指令计数、**资源限制、子进程退出码与时间**；
- `limits` 显式声明（wall 120s / cpu 110s / launches 100 / artifacts 64 MiB），
  `automatic_retries: 0`，`attempts_per_invocation: 1`；
- `protected` 列出不得违反的不变量；
- **"No program is considered equivalent solely because a report has a success string or digest."**

**我的六条 claim 一条都不满足这条标尺**：用例是我看过数据之后定的，预算写在 `assumptions` 的散文里，
没有按哈希钉住的语料，没有重试与预算的显式声明。

补齐（不改变任何已记录结论）：

- 新增 `docs/conformance.contract.json`（`xue.conformance-contract.v0`）：
  语料 = 注册表本身，**按 sha256 钉死**（`30c646cc…`），`cases: 6`；
  `protected` 七条（"摘要相同不是逐字节相同"、"跳过不是通过"、"未执行不是失败"、
  "边界属于 claim 并随它同行"、"未测量不进注册表"、"更正取代而非重写"）；
  `limits` 与 `automatic_retries: 0`。
- 新增 `scripts/check_contract.py`：**验证钉子还成立**——只回答"契约点名的语料是否还是磁盘上的那份"，
  并沿用 `RECORDED` / `OBSERVED HERE` 的标注纪律。当前：`digest match`，`cases 6 / 6`。

**仍然没达到的地方，写在契约的 `note` 里而不是遮掉**：我的契约钉了**一个语料**（注册表），
但**没有钉逐用例清单**——每个 claim 的检查器各自接受输入，而注册表**还没有逐 claim 的预算字段**。
这正是 adva-machine 那份契约比我的严格的地方。

**也未采用**：`adva-machine` 的 `doctor`（环境与钉子核查）与 `run --engine`（双引擎同请求对比）。
它们需要 `blake3`、`pytest` 与 `cargo build --locked --release -p adva-witness`，本轮没有跑。

### 2026-09-17 · xue 补足：克隆已快进到 `a20c774`，六条 claim **在新基线上执行级复验通过**

按"先把 xue 的最新进展补足"，做了三件事。

**一、克隆更新**：`git fetch` 走 HTTP/2 失败（`HTTP2 framing layer` / `Empty reply from server`），
改 `HTTP/1.1` 成功；`--ff-only` 快进 `8af4376 → a20c774`（59 个提交）。
本地原型改动（`delta-auto`）在更新前丢弃，补丁已存在于 `docs/delta-auto.patch`，未丢失。

**二、执行级复验（这是之前只能做文件级判断的那一步）**：

| 检查 | 结果 |
|---|---|
| 前端全量单测 | **514 passed**（基线 408；上游新增 106，**全部通过**） |
| 我新增的 `zarr-mixed.test.ts` | **4/4 passed** —— 在 59 个提交之后仍然成立 |
| `test_bin`（容器结构） | OK |
| `test_zarr`（store 等价） | OK（3 跳过，需 zarr-python 的依赖组） |
| `test_pressure`（压力族 + 半码对齐） | OK |

**结论**：`claims.toml` 六条在新基线上**仍然成立**，"格式与编解码器未被改动"这一判断
从文件级升级为执行级。

**三、claim 前提在线上重验**：

| 前提 | 今日实测 |
|---|---|
| 线上 store 全是标准链（`xue.store.per-array-chain-interop.v0` 的边界） | ✅ `tmp2m`、`thetae850` 仍为 `['bytes','zstd']` |
| GFS run 的 bundle 集合与 schema | ✅ 37 个 bundle、schemaVersion 5、变量集与上次核查**逐字相同**、37/37 带 zarr 描述符 |
| 当前 run | `2026091618`——**正是我本地构建过的那个 run**，manifest `335029a3`（我本地 6-bundle 版为 `de00bbe9`，差异来自 bundle 子集） |

**四、笔记补足**：把三个新读者（探空 / 机场 / 台风）加进观察者表，
并记下要点——**它们拿到的是 JSON，不是栅格，而交付契约一模一样**。
上游自己写下的理由（*"an ascent is not a raster"*、*"an airport's weather is a line of text"*）
是「契约是不变量、表示随观察者变」最硬的一处证据，且**不是我的推论**。

**仍未做**：把 6 个 bundle 的全轴数据重建在新基线上（约 15 分钟）。
上面三项复验没有依赖它——它们用的是上游自己的测试套件与线上的既有产物。

### 2026-09-17 · 三条 adva 主线更新：`adva` 的主线**被重写过**，不是"落后"

按要求同步 `adva`、`adva-library`、`adva-machine` 三条主线。结果与预期不同，记下。

**更新结果**

| 主线 | 结果 |
|---|---|
| `adva-machine` | ✅ 已是最新（`6646582`），且它的 `adva-library` 子模块这次**成功检出**（pysnark / zksnake / zksnake-py） |
| `adva` | ❌ **无法快进**。`--ff-only` 报 *"Not possible to fast-forward"* |
| `adva-library`（adva 的子模块） | ⚠️ 嵌套子模块 `Merricx/zksnake` 克隆失败 |

**根因：三条主线在 2026-09-16 被刻意重写。**

- 本地与远端**共同祖先停在 2026-09-09**（`e8da77a`），本地独有 **881** 个提交、远端独有 **921** 个，**互不为祖先**。
- 政策文件 `PUBLICATION_BOUNDARY.md`（明理 2026-09-16 的指示）：
  **"material outside the public domain must not be brought into the public repositories"**，
  **该共同政策适用于 `adva`、`adva-library`、`adva-machine` 三者**；
  **默认不予准入**，且"开放许可（CC BY / MIT / Apache）本身不构成公有领域依据"。
- 同时新增 `LICENSING.md`、`Unknown-LICENSE-v0.2/v0.3.md` 与
  **`.github/workflows/publication-boundary.yml`**（CI 强制，含 `withdrawn-content` 作业）。

**重写撤回了什么（已实测）**

两条主线 tip 之间：761 处变更，其中**撤回 145 个文件**——**全部在 `trials/` 下**
（`meaning-pair-round-02` 139 个：第三方论文 PDF、全文转录、页面图像；`burau-boundary-pair-round-01` 4 个；
`meaning-pair-round-01` 2 个）。**非 `trials/` 的撤回项为零。** 新增 589 个。

**两处已核实的结论**

1. **本地独有的 881 个提交是同内容的新哈希，不是丢失的工作**：
   本地 `d5b5d0c tooling: implement the first three problem-workflow helpers`
   与远端 `42f0263` **提交信息相同、哈希不同**。因此 reset 不会丢工作，只会丢掉那 145 个被撤回的第三方副本。
2. **我引用过的东西无一被撤回**：`README.md` / `AGENTS.md` / `docs/claims.toml` /
   `docs/SEMANTIC_SCOPE.md` / `docs/research/README.md` 在差异集里都只是**被修改**（`M`），不是 `D`。
   而且——`scripts/navigate.py` 在新主线里**逐字节相同**（198 行），
   `docs/claims.toml` 的字段集**恰好就是**我采用的 11 个字段。
   **本笔记的合规结论与注册表 schema 在新主线上仍然成立。**

**我没有做的事**：没有 `git reset --hard`。那会丢弃 881 个提交、且属于你的仓库与你的政策，不该由我决定。
改为在 `/tmp/adva-main` 拉一份**干净的新主线**（`03c9c12`）用于重新学习，你的三个检出**原样未动**。

**过程中的一次自查**：我第一遍核对我引用的文件是否被撤回时，grep 匹配到了 `M`（修改）行而非 `D`（撤回）行，
一度得出"README.md / claims.toml 被撤回"的错误结论。**修正后才是上面的结论。**

### 2026-09-17 · adva 三线第二轮拉取：两条线未前进，`adva-library` 的公开历史确认被重写

| 位置 | 提交 | 日期 | 与公开线的关系 |
|---|---|---|---|
| `adva` 公开 main | `03c9c12` | 09-17 | — （**本轮无新提交**，我的 `/tmp/adva-main` 已是最新） |
| `adva-machine` 公开 main | `6646582` | 09-16 | — （**本轮无新提交**，本地一致） |
| `adva-library` 公开 main | `7e73821` | 09-16 | — |
| 两个超级项目钉的子模块 | `73a6af4a` | 09-16 | ✅ 公开线的祖先，**落后公开 HEAD 8 个提交** |
| `~/Adva/adva-machine/adva-library` | `73a6af4a` | 09-16 | ✅ 正确（与钉子一致） |
| **`~/Adva/adva/adva-library`** | **`9928b118`** | 09-13 | ❌ **不在公开历史里**——被重写掉了 |

**确认**：`adva-library` 的历史同样被重写——公开线上共 94 个提交，而本地那个 `9928b118` **根本不在其中**。

**找到了撤回机制**（不是手工重写）：提交 `b6f9131 Execute verified removal of withdrawn content from library history`
新增了三件东西——`scripts/withdraw_publication_history.py`（167 行）、
`governance/withdrawals/run-history-correction.json`（记录）、
`.github/workflows/publication-history-correction.yml`（CI）。
另有 `44a8619 fix: withdraw external visual inputs pending rights verification`，
正对应 `trials/` 里那批被撤回的页面图像（`pixels/alpha-*.png`）。

**所以：本轮的净变化只有一处——`~/Adva/adva/adva-library` 停在一个公开线上已不存在的提交上，
与它的超级项目 `~/Adva/adva`（`cb84d21`，含 145 个已撤回文件）一样。**
`~/Adva/adva-machine` 及其子模块则**完全正确**。

### 2026-09-17 · 用 STAC 目录补数据：**它是产物体积与 CRC 的正确来源，我此前的方法错了**

按提示拉取 STAC 目录（`https://dataset.ringsaturn.me/xue/catalog.json`）。
新增 `scripts/catalog_inventory.py`，产出 `docs/catalog-inventory.json`。

**全量清单（2026-09-17）**

| | |
|---|---|
| collection | **11 个**：gfs / ecmwf / sflux / hrrr / **cma** / mrms / jma / **sounding** / **airport** / **tc** / showcase |
| asset | **339 个**，其中 **store 203 个** |
| 已发布字节 | 全分辨率 **3,461,772,777** + 半分辨率 **1,161,987,966** = **4,623,760,743**（约 4.62 GB） |
| gfs 单个 run | 105 个 asset（35 个变量 × 全档 + 半档 + poster） |

**目录把每个产物的 `file:size` 与 `xue:crc32` 写在一个文档里**，另有 `xue:kind`（store/poster）、
`xue:tier`（full/half）、`xue:grid`，Item 上是 `cube:dimensions`、`xue:frameCount`、
`xue:forecastHours`、`xue:manifestSchemaVersion`。

**这对本报告有直接的方法论后果**：我曾用 manifest 的 `bandwidth`（一个 12 fps 下的 HLS 比特率）
**反解**容器体积，并据此得出过错误结论（见 §0 更正一）。**目录里本来就有精确的字节数。**
那条弯路本可以不走。

**已核对**：目录与 manifest 在 `tmp2m` / `prate` / `thetae850` 上**字节数与 CRC 逐项一致**——
两者是同一份数据的两种渲染。

**README 的生态路径已实测跑通**（不是照抄）：

```python
run = next(pystac.Catalog.from_file("…/catalog.json").get_child("gfs").get_items())
xr.open_zarr(run.assets["tmp2m"].get_absolute_href())
# → dims {'time': 161, 'latitude': 721, 'longitude': 1440}，解码后 −60.0..43.0 °C
```

**新看到的形态**

- **`cma` 已是活的 collection**，资产形态与预报 run 相同（`cref.zarr` / `cref-half` / `cref-poster` / `manifest`），
  身份是 `CMA-RADAR / l3-mst-cref`；而 `showcase/shadel-2026` 是**同一产品族的策展 case**——
  同一个产品，两条交付路径。
- 点产品带 **NDJSON** 资产：`sounding` 的 `soundings` 10.8 MB、`airport` 的 `history` 11.3 MB；
  `tc` 则是**每个风暴一个 JSON asset**（`WP242026`、`x-al-2026091612-1` …）。
- 每个点产品的 Item 都用**台站/风暴的包围盒**作 geometry。

### 2026-09-17 · 重新学习 adva #190：它让我在**自己的工具里**找到并修掉了一个塌陷

**#190 已合并**：`03c9c12 → f8341c8`（`Merge PR #190: finite continuation ledger and commit/reply boundary`）。
先查我依赖的两样：**`scripts/navigate.py` 未变**（我的合规继续成立）、`docs/claims.toml` **字段集未变**
（仍是那 11 个字段，182 条 claim）。新增的是 `experiments/decision_ledger/` 与一条 claim：

> `adva.bounded-experiment.decision-ledger.v0`
> *"…replays a committed continuation without a second abstract debit and **distinguishes commit from reply
> observation**"*……*"Missing acknowledgment must not silently renew allowance."*

**它的契约形态**（`experiments/decision_ledger/contract.json`）比我的严格，有几处值得抄：
`status: FrozenBeforeExecution` + **`base_commit`**（钉住冻结时对标的那个提交）、
**`controls`**（十项负向控制：重初始化拒绝、缺台账拒绝、同键冲突、容量暂停、零额度暂停……）、
**`faults`**（注入的故障位：commit 前退出 17 / commit 后退出 19）、
`transaction_assumptions`、以及一份 `residuals`。

**它照出了我自己的一个缺陷。** `scripts/verify.py` 原来在没有任何可比块时打印
`comparable chunks=0 byte-identical=0`——**"没有可比对象"与"比过且全不同"是同一个输出**。
这与它说的"回执丢了不能当成没发生"是同一个结构。

修的过程中**我又犯了一次同类错误**：第一版判语把 `720/720 不同` 判成 `DIFFERED`，
而对**预测变量 + 标准链**那**正是规范预期的结果**。第二版按「链 × 预测器」重写判语，
区分 `NOT COMPARED` / `ALL COMPARED CHUNKS IDENTICAL` / `NONE IDENTICAL — EXPECTED` /
`NONE IDENTICAL — UNEXPECTED` / `MIXED`。

**判语一改就抓到了真东西。** 对上游夹具报出 `UNEXPECTED`，追下去是：

- **码：121/121 帧完全一致** ✓ 数据没问题
- **字节：720 个可比块无一相同**，且 store 的块**一致更小**（344 vs 404、369 vs 451、337 vs 411）
- 根因：`tests/prepare_web_fixture.py:211` 的 `level = 3`，注释写明
  *"keep fixture generation fast; **the contract is level-independent**"*——夹具的容器用 level 3，
  而 store 导出用默认 level 15。

**不是缺陷，是一个真反例**：它把 `xue.store.container-byte-identity.v0` 的边界钉得更实——
**字节相等只在"同一套 zstd 设置"的前提下成立**，而项目自带一对文件正好在这个前提之外。
已补进那条 claim 的 `assumptions`。

### 2026-09-17 · 预报：把 θe 那条 claim 的机制**向前检验**——在第二个变量上复现，但带一个部分反证

θe 那条 claim 的边界里明写着："它**没有**建立其他层次或其他变量的表现。"
按"推进学习与预报"，我把这句话变成一次**有预测的检验**。

**预测（先写出，再测）**：机制是"850 hPa 在高原上是地下约 3 km 的外推值"。
若成立，同一异常必须出现在**温度**上——在**位于高原地面之下的层次**出现，在**地面之上的层次不出现**。
高原平均海拔约 4500 m，而 GFS 恰好发布了 `tmp925`（约 762 m）、`tmp850`（约 1458 m）、`tmp500`（约 5575 m）三层。

新增 `scripts/plateau_mechanism_check.py`，用**同纬度带内、高原框之外**的区域作对照，
把纬向与季节结构除掉，只剩下高原自身的异常：

| 层次 | 约高度 | 在地下 | 高原均值 | 同纬度对照 | **异常** |
|---|---:|---|---:|---:|---:|
| `tmp925` | 762 m | 是 | 27.31 °C | 20.99 °C | **+6.33 K** |
| `tmp850` | 1458 m | 是 | 22.73 °C | 17.57 °C | **+5.16 K** |
| `tmp500` | 5575 m | 否 | −5.16 °C | −7.21 °C | **+2.05 K** |

**结论：机制在第二个变量上复现，且复现出预测的梯度。**
地下两层大幅偏暖（+5～+6 K），地面之上那层明显更小（+2.05 K），量级降了约三倍。

**但有一条部分反证必须如实记下**：500 hPa 的异常**不为零**。
我的判语用了 `>2 K` 作阈值，而**那个阈值是我自己定的**——二值判语掩盖了真实结果是梯度这一事实。
另外 +2.05 K 有未被排除的物理解释：高原夏季本身是热源，其 500 hPa 层贴近地面。

**还有一条无法检验的**：θe 线上**只发布了 850 hPa 一层**（注册表里有 8 层，发布的是 1 层），
所以"换个层次"这一维在 θe 上做不了，只能用温度这一族替代。

已把梯度与那条部分反证写进 `xue.derived.theta-e-plateau-clamp.v0` 的 `counterexample_boundary`。

### 2026-09-17 · 学习与预报各推进一格

**预报：500 hPa 残余的判别性检验——做了，未决。**

θe claim 里那 +2.05 K 需要一个判别：它是**真实的高原热源**，还是外推污染？

| 场 | 高原 | 同纬度对照 | 异常 | 读法 |
|---|---:|---:|---:|---|
| `tmp500` | −5.16 °C | −7.21 °C | +2.05 K | 待解释 |
| `hgt500` | 5835.83 gpm | 5894.23 gpm | **−58.40 gpm** | **被地形混淆**——高原下方是岩石不是空气 |
| `vvel500` | −0.02 Pa/s | +0.01 Pa/s | −0.04 | **比值无意义**（分母近零） |
| `rh500` | 69.47 % | 33.49 % | **+35.98 点** | 新信号，方向与 θe 异常一致 |

**热源假设未获支持，但本检验也不足以证否。** `hgt500` 偏低看似否证热源，
但那是因为对照区是低地气柱、高原下方是岩石——**这个比较本身就不成立**。
`vvel500` 的 283% 是两个近零数之比，**不能当证据**。
`rh500` 的 +36 点是个同方向的新信号，指向"高原的 500 hPa 更像近地面层"，但那是解释不是结论。

**一个检验没能判定问题，本身就是结果**，已连同它的弱点一起写进 claim 的边界
（`scripts/plateau_mechanism_check.py` 里也保留了失败判别的说明）。

**学习：把 #190 契约里我缺的三样补上了。**

`docs/conformance.contract.json` 新增：

- **`base_commit`**——钉住测量对标的提交：`8af4376` 测、`a20c774` 复验，并记下 Adva 工具在这两次拉取间未变。
  **没有这一项，一条 claim 说不出它测的是哪个版本。**
- **`controls`**（6 条）——**只列真正被执行过的负向控制**：
  `check_contract.py` 在摘要不符时**拒绝**（今日已实际触发两次）、
  `verify.py` 在无可比块时报 `NOT COMPARED`、
  `verify.py` 的 `UNEXPECTED` 分支抓到了 zstd 等级那件事、
  `interop.py` 含一个不注册 codec 的客户端、
  `predictors.py` 两个方向的胜者都报、
  以及项目自带的那对"码同字节不同"的反例。
- **`residuals`**（6 条）——这份契约**没有**建立什么。

**契约的钉子今天拦了我三次**，每次都要求"重新钉并写更正记录而不是悄悄改"。
三次都照办，更正笔记用**追加**而非改写，现在 `navigate.py --corrections` 索引到 **5 条**。

### 2026-09-17 · 用实测地形把机制从"整框均值"推进到"逐格点剂量–反应"

此前那条 claim 把"高原约 4500 m"当作**常识假设**写入。按提示引入 **Copernicus DEM** 实测后：

**一、地形实测**（`scripts/dem_elevation.py`，读 `/vsicurl/` 上的 COG 概视图，不落全量）

- 220/220 张 GLO-90 瓦片，3520 个格点
- 高程 **83 .. 6158 m**，**高原框内均值 4140 m** ——假设值 4500 m 略偏高
- **为什么选它**：唯一**无需注册、S3 开放、COG 可范围读**的（NASADEM/SRTM 要 Earthdata 登录，AW3D30 要 JAXA 注册）

**二、逐格点检验**（`scripts/plateau_profile_check.py`）——把整框均值换成"按离地高度分箱"：

| `tmp850` 离地高度 | 格点数 | 异常 | | `tmp500` 离地高度 | 格点数 | 异常 |
|---|---:|---:|---|---|---:|---:|
| [−4000, −3000) m | 348 | **+6.73 K** | | [500, 1500) m | 431 | **+2.72 K** |
| [−3000, −2000) m | 514 | **+3.76 K** | | [1500, 3000) m | 485 | +0.84 K |
| [−2000, −1000) m | 67 | +0.49 K | | [3000, 6000) m | 27 | +2.71 K |
| [−1000, 0) m | 13 | +0.45 K | | | | |

**教科书式的剂量–反应关系。** 而且**一个机制解释了两件事**：

- **在地下（850 hPa）**：越深偏暖越强（−1.5 km 时 ~0 K → −2.5 km 时 +3.76 K → −3.5 km 时 +6.73 K）——**外推伪值**
- **刚出地面（500 hPa，0.5–1.5 km 之上）**：+2.72 K，随高度升到 1.5–3 km 降为 +0.84 K——**受地面加热，真实但与外推无关**

上一轮那个"500 hPa 残余"因此有了完整解释：它不是外推，而是**贴着高原地面的那一段**。

**三、两处必须如实标注**

1. **参照系换了**：此处用该纬度**整圈**的平均作对照，而前一版用的是"同纬度带内排除高原框"。两者未做过比较。
2. **权利状态**：Copernicus DEM 免费且有署名即可再分发，但**不是公有领域、不是 CC0**——按 `PUBLICATION_BOUNDARY.md`，它**不可准入**项目的公开仓库。
   **没有 vendoring**：瓦片经 HTTPS 读取，只保留派生的逐格均值，且**放在 `/tmp`，在本目录之外**。
   代价是**这份派生产物无法在不重新下载的情况下复查**——已写进契约的 `residuals`。

**四、过程中修掉两个自己的 bug**

- DEM 聚合用了 `(previous+value)/2`，**那不是均值**，多于两个贡献值就错（测试区均值 4885 → 修正后 4937 m，范围也从虚高的 1960–5839 收回到 3100–5622）
- 网格对齐里 `lat0 = 90.0 - (lat + step/2)` 算错（i=0 时会得 52°N），改成按纬度值匹配

契约**第五次重钉**（`ed32e1aa…`），更正笔记第五次追加。

### 2026-09-17 · 学习：把欠着的 `problem_card.py` 用上了，它逼出两样我注册表里没有的东西

一直欠着的那个工具（Adva 工具工作流的第二个助手）终于用在了 θe 这条 claim 上。
十字段：原始问题 / 对象与版本 / 成功条件 / 解释与前提 / 当前候选 / 检查范围 / **预算** /
**本轮结果** / 剩余问题 / 下一步，外加 `stop_conditions`、`attempts[]`、`handoff`。

卡片写在 `docs/problem-cards/theta-e-plateau-clamp.json`（12.5 KB）。
上游校验器的判定是：

```
incomplete — 1 open item(s), none filled in for you:
  - handoff: the receiver has not confirmed this is the same question;
    the round stays open rather than complete
```

**十字段全齐、预算合法、四次尝试各自带 `first_failure`、停止条件齐备**——
唯一未决的是接收方确认。**而这一项恰恰是我整份注册表里没有的结构。**

**它逼出的第一样东西：`first_failure`。**
`attempts[]` 的每一次尝试都必须保留**首次失败**。回看这条 claim，我犯了四次错：

| 尝试 | 首次失败 |
|---|---|
| 直接压缩对照 | 只取 1 个瓦片（北极附近）→ 得出"所有变量 RAW 更优"的错误方向 |
| DEM 提取 | `(previous+value)/2` **不是均值**，多于两个贡献值即错：4885 m / 1960–5839 m → 修正后 4937 m / 3100–5622 m |
| 逐格点剖线 | `lat0 = 90.0 - (lat+step/2)` 在 i=0 时得 52°N；`np.asarray(heights)` 漏取单帧导致 3 维掩码索引 2 维数组 |
| θe 分箱 | 码本上限 357.0 K **被硬编码**——脚本在拿自己当对照；另有一次 urlopen 403 缺 User-Agent |

**这四次失败此前都只作为叙述存在于报告里，没有一次被保留为产物。** 卡片要求它们各自成栏。

**它逼出的第二样东西：接收方确认。**
一张卡在**接收方确认"这是同一个问题"之前不算闭合**——不能由出题人自己宣布完成。

**第三样（顺带）**：`check_scope` 逼我把"**没有充分性证明**"写出来，
`objects_and_versions` 逼我把输入分成**原始产物 / 外部数据集 / 派生中间物 / 本仓库代码**四类——
其中"派生高程网格在 `/tmp`、不重新下载无法复查"原本只在契约的 `residuals` 里，
现在在卡片里有了明确的位置。

**这三条已补进契约的 `protected`**（现 10 条）：首次失败须留产物、一轮须经接收方确认方可闭合、
码本边界须从发布元数据读出而不得硬编码。

### 2026-09-17 · 换问题：按问题卡的规则开了第二轮，并实测了界面能量项的供给

提问方指出上一轮把地下层称作"外推伪值"是**措辞失当**，并改变了问题：关心的是
**界面热交换与冰融潜热这个相变过程如何刻画**，并要求补**冰川地图数据**。
按 `problem_card.py` 的规则（改问题须新开一轮 + `predecessor` + `change_reason`），
开了 `docs/problem-cards/interface-heat-exchange-and-melt.json`。两张卡现在都只差
**接收方确认**这一项。

**校验器又抓到一处**：`predecessor` 必须是**相对本卡目录的文件名**
（`previous_path = (path.parent / predecessor)`），我第一版填的是 `question_id`——
它如实报出 "does not exist beside this card"，而不是默默放过。

**本轮实测（供给核对，尚未做检验）**

源文件 `gfs.t00z.sfluxgrbf000.grib2.idx` **共 54 条记录**，与界面相关的：

| 记录 | 是什么 | xue 发布 |
|---|---|---|
| `SHTFL` / `LHTFL` / `GFLUX` | 感热 / 潜热 / 土壤热通量 | ❌ |
| `DSWRF` / `DLWRF` / `USWRF` / `ULWRF` | 四项辐射 | 仅 DSWRF |
| `TMP:surface` | 皮温 | ✅ `tmpsfc` |
| `TSOIL` / `SOILW` / `SOILL` ×4 层 | 土壤温度/含水量/液水 | ❌ |
| `SNOD` / `WEASD` | 雪深 / 雪水当量 | ❌ |

**xue 从这 16 项里发布了 2 项。** 连名为 "GFS surface flux" 的 `sflux` 源，
也只发 `tmp2m` / `prate` / `dswrf` / `wind10m`。

**判据性的一条**：54 条记录里**没有任何 melt / freeze 场**——融化潜热**不是交付物，
而是陆面模式内部的残差**。它可由**同在文件里**的四项重建：
`Qm = Rn − H − LE − G`，`Rn = (1−α)·DSWRF + DLWRF − ULWRF`，`α` 由 `USWRF/DSWRF` 得。

**过程中的一次自查**：第一次检索 `melt|freez|snow|ice|heat|flux` 只回出三条，
**我一度以为检索式写漏**；改用对 54 条记录名**全量去重**后才确认
"没有 melt 场"是可靠的，不是检索失败。**把"我没找到"读成"不存在"**——
本研究反复出现的那类塌陷，这次靠全量枚举排除掉了。

### 2026-09-17 · 第三轮换问题：冰川垮塌的链式地质灾害

提问方指出真正关心的是**大面积冰川垮塌带来的地质灾害**，并提到中科院等机构已有论文、
且已对近期墨脱与尼泊尔的重大灾难作出预报。按问题卡规则开了第三轮
（`docs/problem-cards/glacier-collapse-cascading-disaster.json`）。

**本轮只做文献与字段核对，不做任何预测**，因为这类问题上"我读到的事实"与"我的推断"必须分开。

**读到的一手事实**（姚檀栋等，《创新》2026，DOI 10.1016/j.xinn.2026.101571；
科学网 2026/9/15 报道，链接见卡片 `objects_and_versions`）：

- 2026-08-26 尼泊尔错坚河冰崩；冰川编号 **RGI60-15.04173**、面积 **3.13 km²**
- 冰崩体约 980 m × 780 m（0.76 km²）；下游与我国 22 km 边界河段，与吉隆口岸落差约 3500 m
- 河道由 **170 m 拓至 700 m**；台站记录到 **5.2 级地震**；10:52:15 起崩、10:59 过口岸（约 **190 km/h**）；影响逾 **80 km**
- **触发条件**：距崩点 31 km 的自动站，崩前十几日**平均 7.4 °C、最高逾 16 °C、最低始终在 0 °C 以上**
- **临界前兆**：8/12–8/24 冰体流速约 **0.4 m/天**，高出正常冰川运动**一个量级**
- 机制链：变暖 → 冰裂隙扩张 + 冰面融水向冰内与冰床输送加剧 → **冰床润滑增强** → 流速跃升 → 高位启动、低位展开、链式传导、瞬时成灾

**据此得到的判断（我的解释，非报道原话）**：这条链里**只有第一环是大气模式能给的**；
裂隙与排水通道、冰床润滑是冰体内部与冰床过程；**流速是遥感量**；冰碛物裹挟与洪水演进是水文-泥沙过程。

**一条未能取得的**：中新网那条（冰冻圈灾害频次增加与链式放大）**取回的是要求启用 JavaScript 的空壳**，
未取得正文——**故本轮只引用了确实读到的科学网一篇**，不引用来路不明的转述。

### 2026-09-17 · 预报：冰川垮塌的触发条件**没有判别力**（可量化的负结果）

提问方要的是"大面积冰川垮塌的地质灾害"。我不等论文就能做一件有判别力的事：
用 **GFS 分析场**（NOAA 公开桶，单条 `TMP:2m` 记录经字节范围取回、由 GDAL 解码）
回溯错坚河个例记载的触发条件——**崩前十几日最低气温始终在 0 °C 以上**——
看它在区域内是否罕见。

**结果（区域 25–40°N/70–105°E，窗口 8/12–8/26）**

| 年份 | 连续 ≥10 天日最低 >0 °C | 占比 | 面积 |
|---|---:|---:|---:|
| 2024 | 7,693 / 8,400 | 91.6% | 5,024 千 km² |
| 2025 | 7,717 / 8,400 | 91.9% | 5,040 千 km² |
| **2026** | **7,669 / 8,400** | **91.3%** | **5,008 千 km²** |

**2026 与往年无从区分**（比值 0.997 / 0.994）。

**排除低海拔混淆**——按 GFS **自身地形**分箱（域内 7–5918 m）：

| GFS 地形 | 格点数 | 满足条件 | 占比 |
|---|---:|---:|---:|
| < 3000 m | 4,043 | 4,043 | **100.0%** |
| 3000–4000 m | 1,012 | 1,009 | 99.7% |
| 4000–5000 m | 2,331 | 1,950 | 83.7% |
| **≥ 5000 m** | **1,014** | **667** | **65.8%** |

**即使在模式认为 ≥5000 m 的格点上，仍有三分之二满足。**

**结论：论文记载的触发条件在该区域 8 月是气候常态**——91% 的面积、最高地形上也有三分之二，
且三年不变。**它无法把垮塌的那条冰川与成千上万条没垮的区分开。**

这正是我在上一轮写下的判据：*"若该量在已知个例的崩前并不突出，则这条路无效——
那就应当老实说无效。"* 现在它有数字了。

**边界**：用的是**模式 2 m 温度**，其陡峭地形偏差未量化；但**年际比较对固定偏差稳健**，
而"2026 与往年不可分"这一点不因偏差而改变。论文中真正的临界前兆（**流速 0.4 m/天**）
不在任何大气数据集里，本检验无法触及。

新增 `scripts/collapse_trigger_check.py`。第三轮问题卡已补入该结果。

### 2026-09-17 · 撤回：我曾说「喜马拉雅框基本落在 CMA 拼图覆盖之外」——**错了**，该框横跨覆盖边缘

提问方指定方向：「降雨还有一个雷达拼图的资料，这个方向我们资料更加多，先推这个方向」。
按目录核对，「资料更多」成立：`catalog.json` 下有三个降水雷达/临近集合（`cma`、`mrms`、`jma`），
三个机构、三个区域、三种时次间隔。但**更多不等于更深**，而这轮的两次反转都出在我自己身上。

**先说错的那一条。** 我读了**一个** cma 窗口（20 帧，02:00–04:06Z），在喜马拉雅/西藏框
（80–92E, 26–32N）里只有 851/37,264 = **2.3%** 的格点曾出现回波，而华东对照是 40.7%。
我据此告诉提问方：该框**基本落在覆盖之外**，不只是没下雨；并说码本的 `0` 同时表示
「无回波」与「无雷达」，而 xue 没有任何位图能分开这两者。

**后半句半对，前半句是错的。**

**（一）码本其实声明了 nodata 码——我没读变量的元数据就先断言了。**
`cref` 的 `quantization` 为 `minimumCode 0`、`maximumCode 160`、`scale 0.5` dBZ/码、
**`nodataCode 255`**；zarr 数组的 `fill_value` 也是 255。准确的表述更窄、也更糟：
**码是声明了的，却从不写入**——合并窗口 40,370,176 个样本里码 255 出现 **0 次**，
观测码值范围 **0–139**。射程外的孟加拉湾与阿拉伯海被填成 `0`，与「无回波」**同码**。

**（二）那个低回波比例不是覆盖假象。** 用四个判据检验该框内**已有**的回波——斑块相干性、
时间持续性、帧间 IoU、回波强度——它表现得像**真降水**：回波像元 **74.5%** 落在
≥25 格的 4-连通斑块中、单帧即消失的格点仅 **9.4%**、逐格最长连续帧中位数 **5.0**（共 30 帧）、
帧间 IoU **0.642**、p90 **43 dBZ**、最大 **88 dBZ**。覆盖无疑义的华北对照是
74.4% / IoU 0.581 / p90 34 dBZ——**同级**。

**判据是先在已知伪回波上校准过才用的**：南海框落在所有中国雷达射程之外，是六个方框里
**唯一**一个高 p90（76 dBZ）而大斑块占比低（**20.1%**）、IoU 低（**0.374**）、
单帧格点高（**36.3%**）的框。真降水不长这样，**泄漏长这样**。

**（三）真相在两个版本之间，而且比两者都更锋利：该框横跨边缘。**
80–92E 经向上，26–27N / 27–28N / 28–29N 三带的雷达回波**全为 0.0%**，而模式在
这三带分别报雨 81.8% / 94.8% / 74.0%；到 **29–30N 骤升到 10.4%**，与模式雨强的
Pearson r = **0.507**——**台阶在 29°N，即喜马拉雅山脊**。

**（四）但边缘是参差的，不是射程圆。** 95–100E 经向上方向**相反**：26–27N 有 **8.8%**
回波（r = −0.222），而 29–30N / 30–31N / 31–32N 三带**全为 0.0%**，
模式在该三带报雨 98.8–100%。**相隔 15 度的两条断面在 29°N 交叉。**

**为什么这个错误要紧**：它在降雨方向唯一要回答的问题上，指向与真相相反的一侧。
「覆盖之外」意味着雷达对喜马拉雅什么也说不了；而实测是雷达**看得见高原一侧、看不见
尼泊尔一侧**，边界既未发布、也无法从数据本身推出——因为该标记的码从不写入。
正确结论是一个**有条件的**能力，不是空白；而条件每换一个方框都必须重新测。

**另一处同类的自伤，记在这里**：第一次探测历史窗口时，我对 11 个旧 run 一律试猜的窗口 ID
（`0500`），全部 404。若就此收工，我会报告「连前驱窗口都没有」。改为读源码弄清
`window_hours` 与 run 的关系（run = 窗口**起始**小时）、再按起始小时**稠密扫描**（442 个候选）
之后，才找到前驱窗口。**探测返回空 ≠ 东西不在**——这与 §13 更正三是同一类错误，
已是第三次。

**这轮实际测到的（两个方向都与预期相反）**：

- **保留深度**：三个集合**各只暴露两个滚动窗口**（当前 + 前驱）。cma 442 个候选命中 2 个，
  mrms/jma 各 196 个候选各命中 2 个；列目录接口全部 404。合并 cma 两窗口得 **30 帧、
  01:00–04:06Z**（约 3 小时 6 分钟）。**没有历史档案**——所以「资料更多」在**广度**上成立
  （三个区域、三种间隔），在**深度**上不成立。
- **重建是确定性的**：两窗口重叠的 **15 帧逐格完全相同**（uint8，1024×1792），
  且两次独立构建缺**同一时隙 `03:12Z`**——缺口在源侧，不在构建过程。
  活窗口会推进：同一目录相隔约一小时两次读取，帧数由 **20 → 22**。
- **回波真实性**：见上（三）。同时**保留一处未解释的反例**——华北对照雷达在 **64.6%**
  的模式格点上看到回波而模式只在 **1.5%** 报雨（r = −0.068）；这与「模式在 35–42N 少报」
  和「雷达在华北含非降水回波」都相容，**本轮不判定**是哪一种。
- **一处空结果如实报告**：模式阈值从 0.02 扫到 1.00 mm/h，各带命中率小数点后三位**完全不变**。
  这既说明读数由雷达一侧的存在性主导，也说明该扫描**没有**检验出模式阈值的影响——
  它**不能**当作稳健性证据。

**两个方向的阈值不等价，是这轮最主要的混杂**：雷达一侧是「0.25° 格内最多 32 个子格点 ×
30 帧 ≈ 960 次抽样的『或』」，极灵敏；模式一侧是「5 个小时次里任一次 ≥0.10 mm/h」。
因此「模式报雨而雷达没看到」系统性**偏大**、「雷达看到而模式报干」系统性**偏小**。
所有列联表读数都带这个偏置。

新增 `scripts/radar_coverage_check.py`（码本 + 四判据，六方框，`--box` 可复算任意方框）、
`scripts/radar_vs_model_check.py`（降到模式网格出列联表，`--window` 多窗口且重叠帧不一致即**失败退出**）、
`scripts/radar_coverage_figure.py` 与 `radar-coverage-edge.png`。
新增 claim 两条（注册表扩到 **8** 条），契约已重钉：`docs/claims.toml` sha256
`fbf220b4…` → `aebe4bbf…`，cases 6 → 8，`scripts/check_contract.py` 报 `digest match`。
第四轮问题卡 `docs/problem-cards/radar-mosaic-capability-and-coverage.json` 已开，
校验通过（唯一未决项是接收方确认）。

**边界**：全部数字来自**一个约 3 小时的窗口、一天、三个模式小时次**；mrms 与 jma 只做了
保留深度探测；非降水回波（晴空回波、地物杂波、异常传播）**未排除**；边缘成因**未建立**
（未叠地形数据）；**冰川本体是否落在盲带内未判定**——实测 80–92E/26–29N 全为 0.0%，
而错坚河个例下游包括吉隆口岸一带（约 28.3°N/85.4°E，落在这条盲带内），
但**两个来源都没有给出冰川本体的经纬度**，故不据此断言。

### 2026-09-17 · 更正四：雷达保留深度我**数错了**——是 4 个窗口，不是 2 个；错在探测方法

上一条 §13 记录里我写「三个集合各只暴露两个滚动窗口」，并用「cma 442 个候选命中 2 个」
支撑它。**数字是错的。** 实际是**4 个窗口**：2 个相邻 run（run = 窗口起始小时），
**每个 run 保留最近 2 次构建**——`cma.2026091701/0351`（01:00–03:24Z，24 帧）、
`cma.2026091701/0400`（01:00–03:30Z，25 帧）、`cma.2026091702/0452`（02:00–04:18Z，22 帧）、
`cma.2026091702/0502`（02:00–04:42Z，24 帧，当前活窗口）。

**错因是我自己的探测网格。** 我假设构建 ID 落在 6 分钟网格上，按 6 分钟步长扫——
而构建 ID 是**构建完成时刻**，分钟数没有固定模：实测有 `0351`、`0400`、`0452`、`0502`。
6 分钟步长只抽到约 **1/6** 的可能 ID，于是漏掉了 3/4 的窗口。

**是现场驱逐把它暴露出来的**：写到这一节时我去重跑动画脚本，活窗口已经由
`cma.2026091702/0442` 变成 `cma.2026091702/0502`，而 `0442` 返回 404。
`0502` 不在我的候选网格上（44 分在、02 分不在）——**我在同一次会话里观测到了自己
claim 里描述的驱逐行为，同时发现自己的候选集不完备**。
细网复核：对 5 个 run 各探测 **run+1h 至 run+6h 的每一分钟**，共 **1,505** 个候选，
命中 4 个；run 2026091700 及更早**一个都没有**。

**顺带得到的确定性证据更强了**：不再是两窗口 15 帧，而是**四个窗口两两重叠的帧逐格全部相同**
（含跨 run 的重叠），仍缺 `03:12Z` 同一时隙。活窗口在会话中 `0442 → 0452 → 0502`，
帧数 20 → 22 → 24——**旧构建在被驱逐，尺度是数十分钟**。

**这条错误与我前两次是同一类**：§13 更正三（「我没找到」说成「不存在」）与雷达方向那次
猜错窗口 ID（11 个 run 一律试 `0500`），都是**在候选集不完备时把「探测返回空」当成结论**。
这是第三次，且这次污染的是我自己刚写的 claim。已按纪律**两版读数都留在 claim 里**，
不只改数字：`xue.radar.public-retention-and-rebuild-determinism.v0` 的 `scope` 保留了
粗网那版、写明了错因，`forbidden_conflations` 新增「在一套不完备的候选集里没命中 —— 与 ——
保留期就是那么短」「活窗口的构建 ID —— 与 —— 落在整齐的时间网格上」两条。

**仍未复核**：mrms 与 jma 的窗口数用的是同一个粗网（各 196 个候选、各命中 2 个），
**可能同样被低估**——这一条我已写进 claim 的 `assumptions` 与契约的 `residuals`，
不当作已复核的结论。

契约重钉：`docs/claims.toml` sha256 `8d39bb4d…` → `e30487ad…`，`scripts/check_contract.py`
报 `digest match` / `cases 8/8`。

### 2026-09-17 · 点产品（sounding / 测站）：**补上欠了的一次测量，并让探空独立坐实了 θe 那条 claim 的机制**

提问方指定方向：「sounding 和测站数据有更多细节」。「更多细节」实测成立——
但**深度仍不成立**，而这一轮的形状与雷达那轮完全一样。

#### 一、欠账补上：README §二 那句「两跳、只取那一站」是从注册表结构推出的，没测过

按本笔记自己的纪律，未测量的观察不进注册表，所以它一直挂在 §七「没有建立的」里。现在测了。
结论是**形状对、代价的形状错**：

| 读一次 | 跳 | 字节 | 其中索引 | 相比整份文件 |
|---|---|---|---|---|
| 探空「拉萨这一次上升」 | 3 | **184,739 B**（4.5 s） | **89%**（164,895 B） | 省 98.29%（整份 10,809,718 B） |
| 测站「某机场 24 小时 + TAF」 | 3 | **600,823 B**（5.4 s） | **99%**（596,302 B） | 省 96.41%（整份 16,722,437 B） |

「只取那一站」省的是**数据文件**的 98%，但**索引照付**，而索引才是大头。
`Content-Range` 两边都实测到被精确满足（`bytes 4817089-4836781/10809718`）。

**但这不等于昂贵**：读**全部**站时索引只付一次，而逐站读要付 N 次——探空 491 站 ≈ 81 MB 索引。
规范自己就把两条路并列为「查看器读法」与「分析者读法」。本 claim 只测了「一个」这个端点。

#### 二、探空独立坐实了 θe 机制——把那条 claim 的**首个假设**换成了观测

θe 那条 claim 原本的假设是「850 hPa 在高原上是地下，从高原平均海拔（约 4500 m）**推断**，
没有用地形数据集核对」。探空给的是**实测的逐层气压**：

| 站 | 海拔 | 24 次上升中最高气压 | 850 hPa 在地面之下 |
|---|---|---|---|
| 55299 | 4508 m | **590.2 hPa** | 259.8 hPa |
| 56029 | 3717 m | 650.4 hPa | 199.6 hPa |
| 55591 拉萨 | 3650 m | 655.3 hPa | 194.7 hPa |

**青藏高原框（75–105E, 25–40N）内 6 个站、24 次上升，没有一次的最高气压达到 850 hPa**，
且产品**自己拒算**依赖该层的派生量——这 24 次上升的 `derived.lapse850_500` **全部为 null**。
这不是我的推算，是产品在自己的字段里承认那里没有 850 hPa 层。

顺带把另一条残余也量了：**测站产品在该框内最高的站只有 3,256 m**（VILH 列城），
**36 个站中没有任何一个高于 3,300 m**，`ZULS`（拉萨贡嘎）与 `ZUBD`（昌都邦达）**都不在索引里**。
所以高原的**站级**观测实际只有探空一条路。

#### 三、同一条规律第四次出现：**没有任何一族保留历史**

| 族 | 声明 | 实测 |
|---|---|---|
| 栅格 run | 只发当前 run | 指针只指当前 run |
| cma 雷达 | 滚动窗口 | **4 个窗口 = 2 run × 2 构建** |
| sounding | 每时一发，**目录保留两天** | **5 个 issue（240 分钟）** |
| airport | 每 10 分钟一轮，`KEEP=18` | **19 轮（230 分钟）** |

sounding 的 **5 与规范写明的「两天」不符**——7 天 168 个候选全试过。要区分**目录被裁**与
**数据消失**：sounding 每站携带自己最新的 **4 个名义时次**（实测 412/491 站为 4 个），
最新一期里就含约 1.5 天的站级数据，所以被裁掉的是 **issue 目录**，不是数据。

airport 还多出一处：存在图 `OxOOOOOxOOOOOxOOOOOxOOxOxxx…` 显示**每个小时的 `:10` 那一轮都缺**
（0510/0410/0310/0210，四次齐整缺失），另有 `0140` 缺一次——**有效节奏是每小时 5–6 轮，不是 6 轮**；
19 轮与 `KEEP=18` 也不符，且最旧一轮两次探测都钉在 `0130`，与「保留最近 18 轮」不相容。
发布缺口与清理是两件事，本条只把两者都测到，**不判定成因**。

#### 四、规范里可检验的数值条款：抽稀的 3% 规则，线上**零违规**

`docs/sounding.md` §2 规定：层被发布当且仅当 `sig` 的 1–7 位任一置位、或它是最低/最高层、
或其气压比上一个已发布层低至少 3%（`p_last/p >= 1.03`）。全量读 1,844 次上升、**283,617 层**，
排除规范豁免的最低/最高层后检验 **279,929 个相邻对**：

- 未置位且比值 < 1.03 的：**0 对**
- 未置位**受检**对 **86,074** 个，比值**最小恰为 1.0300**、5 分位 1.0301、中位 1.0308
  ——分布正压在阈值上，**最小值恰好等于阈值**，规则在边界上被零余量地满足
- `p` 严格递减：**0/1,844 违例**；七个平行数组长度都等于 `n`：**0 违例**

**这一条我改过一次数**：「最小 1.0010」是在**未排除豁免最高层**的集合上算的，那版给出
「规则有例外」的假象。旧数不留在注册表里，但改动写在 claim 的 `assumptions` 里，
以免读者把两版混起来。

#### 五、我这一轮的判据错了两次，都记在 claim 里

判定产品该不该算 `lapse850_500` 时，我先用**值域**判（`max(p) >= 85000`）得 86 处「不符」，
再用**恰好报了 85000/50000** 判得 45 处——**两次都不是产品的规则**。反例：站 42056 报的是
85040 与 50080，两个判据都说「没有」，而产品算出了值，说明它在阈值附近取层。
把不是规则的东西当规则去验，得到的「违规」全是判据的错。真正的原因是**缺测哨兵**：
`t == -32768`（int16 最小值）使依赖温度插值的派生量变 null——227/1,844 次上升的四个派生量
全为 null。**而 `-32768` 只写在散文规范里，产物里没有**：sounding 的 `item.json` 没有任何
变量元数据，量纲（`t` 为 **K × 100**、`ws` 为 **m/s × 10**）与哨兵都只在 `docs/sounding.md` 里。
这与 §三 那条「生态读者读降水会拿到码值」是**同一类**：拿到数据的人，如果没有规范，
会把 `-32768` 读成一个数。

**另一处同类错误出在我新写的检查器里**：airport 的目录名是 10 的整数倍，而第一版按
`now - 10k 分钟` 生成候选，探到了 `:x5` 网格上、**0 命中**，看起来像「什么都没有」。
改为先按各族声明的节奏向下取整。这与雷达那轮「6 分钟网格对不上不规则构建 ID」是同一种错误
——**在候选集不完备时把「探测返回空」当成结论**，这是第四次。

#### 六、测站 `elev` 的单位不是统一的（一处未解释的异常）

规范写 `elev` 单位是米。用 5 个已知海拔的站定标：SLLP 报 4061（拉巴斯 El Alto 实测 4,061 m）、
KDEN 1656、EGLL 26、VNKT 1334、ZBAA 31——**都对得上米**。但**5 个站报 >4000 m**，其中
`KC24` 报 **8680**、`KN24` 7700、`KXNI` 6370、`KU96` 4388 —— 按坐标（全在美国）**不可能是米**
（若为英尺则分别为 2646/2347/1942/1337 m，都合理）。**哪 4 个站是异常的我定到了，但它们
到底在什么单位、为什么，未查明**，故只作为测量记录，不当作缺陷断言。

#### 七、落盘

新增 `scripts/point_products_check.py`（三个子命令 `cost` / `retention` / `thinning`，
各对应一条新 claim）。注册表扩到 **11 条**，`navigate.py` 报 **`runnable-here=11`**（此前三条
只指到 `.md` 故被判 `historical`，补上检查器后全部可运行）。契约重钉：
`docs/claims.toml` sha256 `027771f6…` → `f823ad13…`，cases 8 → 11，
`scripts/check_contract.py` 报 `digest match`。

**边界**：探空的站级覆盖是 **6 站 24 次上升**（2026-09-15 12Z 至 2026-09-17 00Z）；
抽稀检验只验「已发布的都合规」，**反方向不可检验**（被抽掉的层不在产物里）；
保留探测把 404 当作「不在」，未区分 403/超时；`reported`（抽稀前层数）未与原始 TEMP 公报比对；
规范的另外几条（同压层折叠、半上进位、无气压层不发布）未验。

### 2026-09-17 · 事实锚点：**第一次拿实测值检验交付的栅格场**

提问方给出定位：「测站和 sounding 都是测量的事实锚点」。此前 11 条 claim **全部**是内部一致性
——容器字节、编解码器、store profile、交付契约、产品自洽。契约的 `residuals` 里一直写着
「没有任何 claim 建立交付场物理正确」。这一条是第一次有**事实**可比。

探空报告了它在某地实际测到的气压、高度、温度；机场报告了它实际测到的温度。
把 GFS 场放到这两个锚集旁边，得到三个结果。

#### 一、850 hPa 在**不存在**的地方，比实测地面暖 9.5 K

2026-09-17 00Z 全球探空。地面层用「报告高度落在站点海拔 ±150 m 内」定位——

**这一条我改过一次，而且改之前的结果是荒谬的**：第一版用 `max(p)` 当地面气压，
于是把 4 次**残缺上升**（只报平流层、最大气压 94–99 hPa、站点海拔 3–4 m）当成了「地面」，
算出 **+93.7 K 到 +101.3 K** 的偏差。改用高度匹配后那 4 次被正确剔除（492 站中 282 次上升
有匹配层，**44 次判为残缺**）。

| 850 hPa | n | 模式 `tmp850` − **实测**地面温度 | 模式更暖 |
|---|---|---|---|
| **不存在**（Ps < 850 hPa） | 19 | 中位 **+9.50 K**（范围 −1.70…+21.20） | **18/19**，且 **19/19** 比模式自己的 `tmpsfc` 更暖 |
| **存在**（Ps ≥ 850 hPa） | 263 | 中位 **−6.30 K** | 29/263 |

**两组干净分离**。最清楚的一例：

| 站 | 海拔 | 地面气压 | 实测地面 | 模式 `tmpsfc` | 模式 `tmp850` | 差 |
|---|---|---|---|---|---|---|
| **55299** | 4508 m | 590.2 hPa | **+1.3 °C** | +2.5 °C | **+22.5 °C** | **+21.2 K** |
| 52836 | 3190 m | 693.6 hPa | 4.2 | 7.0 | 20.0 | +15.8 |
| 56029 | 3717 m | 650.4 hPa | 6.2 | 3.0 | 20.0 | +13.8 |
| 56137 | 3307 m | 684.4 hPa | 8.3 | 4.5 | 22.0 | +13.7 |

55299 站上，模式**自己的地面温度与实测只差 1.2 K**，而它发布的 850 hPa 比那里实测的空气
**暖 21.2 K**——因为 850 hPa 在地面之下 260 hPa。这把 θe 那条 claim 的机制从
「用另一个模式变量间接支持」推进到「用实测值直接锚定」。

**但这仍不是「模式误差」**：那个高度层没有测量可以出错。它建立的是「发布值不是测量值」，
以及它与邻近实测差多远。真正的误差量在下面。

#### 二、低平处模式几乎无偏：5,354 个锚点上中位 **−0.40 K**

同一 GFS 场的 05Z 帧，5,354 个机场站的实测 `t` 对模式 `tmp2m`：

| 站点海拔 | n | 中位偏差 | 均值 | 1 个标准差 |
|---|---|---|---|---|
| <100 m | 2221 | −0.50 K | −0.47 | **2.23 K** |
| 100–500 m | 2027 | −0.30 | −0.40 | 2.48 |
| 500–1000 m | 559 | 0.00 | −0.42 | 3.43 |
| 1000–2000 m | 445 | 0.00 | −0.34 | 3.34 |
| **≥2000 m** | 102 | −0.50 | −1.08 | **4.17** |
| 全体 | 5354 | **−0.40** | −0.44 | 2.62 |

**这是本项目第一次给交付的场一个物理偏差数字，而它是好的**：中位 −0.40 K。
离散随海拔单调增大（2.23 → 4.17 K），与地形代表性的预期一致。

#### 三、代表性天花板：格内两站实测差中位 **1.00 K**

5,076 个被占用的 0.25° 格点中 243 个含 2 站以上。同格内实测温度差：中位 **1.00 K**、
均值 1.40、90 分位 **3.00 K**、最大 12.00 K；**19%** 的格点站间差超过 2 K。
其中 25 个格点的站间海拔跨度超过 100 m（跨度中位 144 m，按 6.5 K/km 只对应 0.94 K）。

**边界很重要**：这 243 个格点测的是**测站网络所在的地形区制**——低平、人口密集处。
陡峭地形下该天花板必然更大，而**该网络在那里没有站**。所以这个 1.0 K **不是**高原的
代表性天花板。

#### 四、两个锚集覆盖的地形区制几乎不相交 —— 这才是它们互补的地方

- **机场网络**：5,416 站，密在低平处；全球仅 **23 站 ≥3000 m**，**青藏高原框内一个都没有**。
- **探空**：492 站，全球稀疏，但**够得着高原**（该框内 6 站，最高 4508 m）。

所以 `surfacebias` 给的低偏差**不能**推广到高原——那一箱只有 102 个站且几乎全在安第斯与
北美西部，**没有青藏高原站**。这就是 round-3 卡里「0.25° 温度在深谷-高峰上的偏差未量化」
那条残余：**本条仍未解决它**，只是给出了该箱的数值（中位 −0.50 K、sd 4.17 K）
并说明其地理构成。**高原那一格，只有探空锚够得着。**

#### 五、这一轮错误仍然同类，且第五次出现在我刚写的脚本里

`max(p)` 当 `tmp850`/`tmp850` 的地面气压 —— 判据不是对象的规则。与前面的「值域判
`lapse850_500`」「恰好 85000/50000」「6 分钟网格」「`now - 10k` 网格」是同一类：
**在判据不对时把结果当成结论**。这次它给出的 +101 K 荒谬到无法忽略，才被抓住；
前几次没有这么幸运。已写进 claim 的 `assumptions`。

#### 六、落盘

新增 `scripts/anchor_check.py`（`underground850` / `cellspread` / `surfacebias`）。
注册表扩到 **12 条**，`navigate.py` 报 **`runnable-here=12`**。
契约重钉 `f823ad13…` → `c78f42e4…`，cases 11 → 12。
契约里那条笼统的残余「没有任何 claim 建立交付场物理正确」**已替换**为窄形式：
一个时次、一次运行、三个变量，且锚点网络在最关心的地形区制上几乎不存在。

**边界**：一个时次（00Z 探空 / 05Z 测站）、一次运行的两帧；只测了 `tmp2m`、`tmp850`、
`tmpsfc`，`prmsl`/`dpt2m`/`thetae850` 未与锚点比对；模式那一侧是**预报**不是分析场；
机场 `obsTime` 跨度一小时与模式帧不同时；`thetae` 那个**量本身**仍未检验——锚定的是机制。

### 2026-09-17 · 追加：高原那个数补上了 —— **sd 4.38 K，逐站 −5.6…+11.1 K**

上一条 §13 记录里写「高原那一格，只有探空锚够得着」，并说 round-3 卡里的残余**本条仍未解决**。
探空锚点本来就在手上，所以补测了。同一 00Z 帧，**282 次上升**的实测地面温度对模式 `tmp2m`：

| 海拔带 | n | 中位偏差 | 均值 | 1 个标准差 |
|---|---|---|---|---|
| <500 m | 221 | −0.20 K | −0.15 | 2.19 |
| 500–1500 m | 43 | **+2.10** | +2.29 | 3.59 |
| 1500–2500 m | 10 | −0.70 | −0.19 | 3.70 |
| 2500–3500 m | 5 | **−3.00** | −0.64 | 4.19 |
| **≥3500 m** | 3 | **−4.20** | −2.80 | 2.87 |
| 全体 | 282 | −0.15 | +0.18 | 2.74 |

**青藏高原框（75–105E, 25–40N）：n=23，中位 −0.20 K、均值 +0.82 K、sd 4.38 K。** 逐站：

| 站 | 海拔 | 实测 | 模式 | 差 |
|---|---|---|---|---|
| 55299 | 4508 m | 1.3 | 2.5 | **+1.2** |
| 56029 | 3717 m | 6.2 | 2.0 | −4.2 |
| 55591 拉萨 | 3650 m | 10.4 | 5.0 | **−5.4** |
| 56146 | 3394 m | 8.6 | 3.0 | **−5.6** |
| 56137 | 3307 m | 8.3 | 5.0 | −3.3 |
| 52836 | 3190 m | 4.2 | 8.0 | +3.8 |
| 52983 | 1875 m | 4.9 | 13.5 | **+8.6** |
| 51777 | 889 m | 11.9 | 23.0 | **+11.1** |

**符号有解释，而且这个解释本身就是结论**：偏差的方向由「站点自身海拔与所处 0.25° 格点
**平均海拔**之差」决定——谷中站（拉萨、昌都一带）比格点暖，模式反而报得更冷；峰上或
格点内含低谷的站（52983、51777）则相反。**这是地形代表性，不是模式误差项**，
所以它**不能**当作一个可以加到模式上的偏差订正。

它给出的是 round-3 那条残余真正想要的东西：**在这个地形区制下，点对格点的 2 m 温度比较
能离谱到什么程度——sd 4.38 K，单站最高 11.1 K。** 这个数量级比测站锚在低平处测到的
格内天花板（中位 1.00 K）大四倍以上，两者之差就是地形。

**仍未做**：没有用一份高程数据把每站的「格点平均海拔」真正算出来做回归——本条靠的是
**符号与该差一致**这一判读，而不是回归。500–1500 m 与 1500–2500 m 两箱非单调
（+2.10 与 −0.70），样本只有 43 与 10，不当作普遍偏差。

新增子命令 `soundingbias`（`scripts/anchor_check.py`），注册表重钉 `c78f42e4…` → `4f182932…`。

### 2026-09-17 · 拉取 adva 主线：#192–#195 四个实验、**工具层零改动**、并把「接收方」学了过来

#### 漂移

| 仓库 | 本地 | main | 结论 |
|---|---|---|---|
| `adva` | `f8722a5` | **`f6106cc`** | **+8 个提交**（4 个 merge，PR #192–#195） |
| `adva-library` | `7e73821` | `7e73821` | **无漂移** |
| `adva-machine` | `6646582` | `6646582` | **无漂移** |

拉取一开始两次失败：`Empty reply from server` 与 75 s 连接超时。诊断后是网络慢——
`github.com` 首个 TLS 请求花了 **19.98 s**，而 `api.github.com` 只要 0.38 s。
放宽 git 的 `http.lowSpeedTime` 后正常。

**风险核查：工具层零改动。** `git diff f8722a5..HEAD -- scripts docs` 只命中
`docs/claims.toml`（+52 行）与一个新的 roadmap；`scripts/` **一个字节都没变** ——
`navigate.py`、`problem_card.py`、`run_bounded.py`、`check_publication_boundary.py` 全部原样。
**我的 12 条 claim 的字段集也未受影响**：四条新 claim 用的仍是同样 11 个字段
（新 status 值 `bounded-experiment` 与我的 `bounded-measurement` 并列，说明它是分类不是枚举）。

#### 四个实验的形状

每个 PR 加一个 `experiments/<name>/`：`README.md`、`contract.json`、`run.py`、
**`receive.py`**、`evidence/{manifest,execution}.json`、`attempt-1.tar.gz`，外加一个 workflow。
roadmap 显示这是**优先级序列**：1 单位运输 → 2 核合成 → 3 有理线性系统 → 4 区间包络，
**priority 5 是有界优化**，并且已经立了那条禁止混同：
「contracted search intervals、小残差、均值吻合**不能替代**最优性证书」。

值得注意的是四个 `contract.json` 的**键集并不相同**——最早那个 19 键、另一套词汇，
后三个收敛到 `level` / `costs` / `protected` / `preexecution_review` / `attribution` / `origin`。
收敛是在四次里发生的，不是一开始就定好的。

#### 学过来的东西：`receive.py` 把「接收方」机械化了

四张问题卡全卡在 `handoff.receiver_confirms_same_question = false` —— 这一格问的是
**工人无法替自己回答的问题**：你交回来的还是我问的那个问题吗。Adva 把它做成了
**独立进程**：`receive.py --expected E --candidate C`，输出一个小词表的判定，并且
**明确声明自己什么也没授权**：`native_authority: false`、`close_authorized: false`、
`free_authorized: false`。

照同样的形状写了 `scripts/receive_question.py`：`--expected <卡> --candidate <交接>`，
判定 `SameQuestion` / `ChangedQuestion` / `ChangedScope` / `InvalidCandidate`，
同样三个 authorized 全为 false。**它不 import 生产者**，读的是**卡在开轮时声明的**那些字段
（`handoff.question`、`candidates`、`check_scope`、`success_condition`），
所以一张卡无法靠重复自己来通过。

**反向控制（关键——只有正向通过等于没测）：**

| 控制 | 判定 |
|---|---|
| 原样交接 | `SameQuestion` |
| 改写问题 | `ChangedQuestion` |
| 加挂子问题 | `ChangedQuestion` |
| 缩窄检查范围 | `ChangedScope` |
| 删掉一个候选 | `ChangedScope` |
| 缺 `question` 字段 | `InvalidCandidate` |
| 用别轮的问题 id | `InvalidCandidate` |
| **仅重排空白** | `SameQuestion`（刻意：换行不是改题） |

八取七区分、一条刻意放行。

**但四张卡的 `receiver_confirms_same_question` 仍然是 `false`，这是刻意的。**
那个通过的候选是我**从卡本身生成**的——退化测试只证明仪器能工作，
**不构成一次真正的接收**。工人无法为自己制造接收方的候选；真正的接收需要
**另一方产出候选**。这一点与 Adva 的 `close_authorized: false` 是同一个立场：
接收通过也只确认一件事——问的是同一个问题——其余一概不授权。

#### 悬置未决：`~/Adva/adva` 只能重置，不能快进

实测：旧 HEAD `cb84d21` 与其子模块 pin `9928b118` 在**改写后的公开线上都不存在**
（`git cat-file -e` 失败，`merge-base --is-ancestor` 也为否）。`adva` 仍带
`adva-library` 子模块映射（`dd1a02a` 注册），而对面的 `main` 是 `7e73821`。
所以这个 checkout 追的是一个**已被 rewrite 掉的历史 + 一个无处可达的子模块 pin**，
**无法 fast-forward**。它还在会话 workspace 之外（写 `.git/FETCH_HEAD` 被沙箱拒绝），
故**本轮未动**，等指示。

**边界**：本轮只做了只读的漂移核查与工具采用；四个新实验的 `run.py` 我**没有执行**
（它们各自声明了 30–35 s 的 wall 预算与独立 workflow，在这里跑不会增加关于 xue 的信息）；
roadmap 与四个 README 只读了与工具层相关的部分。**采用一个约定不等于验证它**——
`receive_question.py` 的判定语义是我按 Adva 的形状重新定义的，不是 Adva 的实现。

### 2026-09-17 · 学习与预报各推进一格：**θe 那个量已在站点上被实测锚定；预报技巧那一格被保留律封住了**

提问方要求推进学习与预测。两件事都做了，**预测是先声明、后检验**——写在脚本的 docstring 里，
跑之前就定了判据，免得出结果再改口径。

#### 一、学习：θe 的「伪值占据值域顶端」现在有实测锚点

此前 θe 那条 claim 的证据是**两个模式场之间的比较**（发布 `thetae850` vs 由发布 `tmp850`+`rh850`
独立算的 θe，均值偏差 +0.109 K），以及逐格点的离地高度剂量–反应。这一格补上的是**实测值**：
用探空报告的**实测地面 p/T/Td** 算 θe，与发布 `thetae850` 在同一格比对。

用的是**同一条**已与发布场校验过的 Bolton 实现（`scripts/thetae_check.py`，只把压力参数化，
以免公式分叉）。在新 run `2026091700` 上复跑，偏差 **+0.083 K**，且**每一帧的上界仍恰为 357.00 K**
—— 温度那侧的行为在新 run 上复现。

**P1（先声明）**：850 hPa 在地下时，发布值应高于实测地面 θe。**成立**：

| | n | 发布值更高 | 中位超出 |
|---|---|---|---|
| 850 hPa **在地下**（Ps < 850 hPa） | 19 | **16/19** | **+4.10 K** |
| 850 hPa **存在** | 263 | 121/263（近于掷币） | **−0.94 K** |

**P2（先声明）**：超出量随「低于 850 hPa 的深度」单调增长。**成立**：
0..+20 hPa 时 **+1.77**（n=4）、+20..+50 **+2.33**（n=3）、+50..+100 **+4.44**（n=4）、
**+100 以上 +10.52**（n=8）。

**最深五例的发布值全部正好等于码本上限 357.00 K**，而那里实测的空气 θe 是：

| 站 | 海拔 | Ps | 实测地面 θe | 发布 850 θe | 超出 |
|---|---|---|---|---|---|
| 55299 | 4508 m | 590.2 | **340.33 K** | **357.00** | +16.67 |
| 56137 | 3307 m | 684.4 | 342.12 K | **357.00** | +14.88 |
| 56146 | 3394 m | 678.5 | 344.18 K | **357.00** | +12.82 |
| 56029 | 3717 m | 650.4 | 344.94 K | **357.00** | +12.06 |
| 55591 拉萨 | 3650 m | 655.3 | 348.02 K | **357.00** | +8.98 |

「伪值占据值域顶端」这句话现在**在站点上、由实测值锚定**。**但这仍不是「发布值错了」**——
850 hPa 在地下没有实测 θe 可以出错；建立的是发布值与实测值之间的距离。地下组只有 19 次上升，
分箱后每箱 3–8 个，**P2 的单调性建立在个位数样本上**。

#### 二、预报：值拿到了，技巧曲线拿不到，而且原因是可指认的

单个 run（`2026091700`，起报 09-17 00Z）对 5,417 个测站的逐小时实测，
整个 `history.jsonl` 一次取回（17,457,347 B，规范自己命名的「分析者读法」）：

| lead | n | 中位偏差 | MAE | RMSE |
|---|---|---|---|---|
| 0 h | 3,949 | −0.50 | 1.69 | 2.26 |
| 3 h | 4,904 | −0.50 | 1.69 | 2.26 |
| 5 h | 4,899 | −0.10 | 1.65 | **2.18** |

**P3（先声明「误差随 lead 增长」）—— 不成立**：RMSE 由 2.26 变到 2.18，没有增长。

**而这不可解释为技巧曲线**：单个 run 下 **lead ≡ 有效时刻 ≡ 一天中的时刻**，三者完全同义，
所以这张表量的是「误差随一天中时刻的变化」，不是技巧衰减。要分开二者，需要
**两个 run 检验同一有效时刻**——也就是需要档案，而保留律正禁止它（sounding 5 个 issue、
airport 24 小时、雷达 4 个窗口、run 一次只发一个）。

**这一格因此得到的是一个有界的量而不是一条曲线**：2 m 温度对约 5,000 个测站的逐小时
**MAE ≈ 1.65–1.71 K、RMSE ≈ 2.18–2.26 K、中位偏差 −0.50…−0.10 K**，
而**技巧随 lead 的变化在本环境不可测**。P3 的失败**不构成**「预报不衰减」的证据。

#### 三、过程中出的一次事故：**claim 注册表被我自己的脚本弄坏，且无备份**

在把上面两格折进注册表时，一次脚本化的字符串拼接损坏了 `docs/claims.toml`：
θe claim 被**复制成两份**、`xue.radar.absence-not-marked-in-band.v0` **丢了头部**、
**`xue.radar.public-retention-and-rebuild-determinism.v0` 整条丢失**，另有四处 TOML 语法被破坏
（裸散文插在键之间、字符串内真实换行、键值对尾逗号）。

**没有备份，`xue-study` 当时不在版本控制下**——契约只钉了 sha256，而 sha256 不能恢复内容。
两条 radar claim 是按**当时的注册表与会话记录重建**的，不是从损坏文件中恢复的；
这一点写进了它们的 `assumptions`，以免读者以为它是原件。

**修复**：删重复、补头部、折回四处坏行、`tomllib` 全量校验通过（12 条、字段精确、id 唯一），
契约重钉 `4f182932…` → `815725b42730`。并把整个 `xue-study` **纳入版本控制**（首次提交
`9e8ab8a`，52 个文件）——这条语料是契约钉住的东西，本该如此。契约的 `controls` 增一条：
**重钉之前先 `tomllib` 全量解析**，结构损坏在编辑点被抓住而不是在下一次读的时候。

**教训**：这一轮我在**判据**上错了五次（`max(p)`、值域、恰好 85000、6 分钟网格、`now-10k` 网格），
而这一次错在**工具**上——用脚本改一个没有版本控制的语料文件。两者同类：**做之前没有先确认
那件事是否可逆**。

新增 `scripts/thetae_anchor_and_skill.py`（`thetae` / `skill` 两个子命令，各对应一组先声明的预测）。

### 2026-09-17 · 技巧曲线拿到了：**固定时段后误差确实随 lead 增长，24 小时 +0.19 K**

上一条记录说「要分开 lead 与一天中的时刻，需要两个 run 检验同一有效时刻——也就是需要档案，
而保留律正禁止它」。**这句话是错的**，而且错在同一个地方：我把**指针**当成了**目录**。

#### 一、先修正保留那一格：一个 run 目录不等于一个 run

按 6 小时循环回探 5 天共 20 个候选，实测 **5 个 run 的 manifest 仍被服务**：
`2026091700`、`2026091618`、`2026091606`、`2026091600`、`2026091418`。
但其中**只有 3 个的 store 可读**——`2026091600` 与 `2026091418` 的
`tmp2m.zarr/zarr.json` 与 `tmp2m.half.zarr/zarr.json` 都返回 **404**，
而它们的 `manifest.json` 仍在服务并**照旧声明**那些 store。

**清单与数据是分两步清理的。** 我此前写的「指针只指向当前 run」对指针成立、对目录不成立。
这条已修正进 `xue.point.retention-and-the-missing-archive.v0`。

#### 二、于是同一有效时刻有了多个 lead

3 个可读 run 对测站观测窗口（约 09-16 14Z–09-17 05Z）给出的 lead：

| run | 起报 | 覆盖到的 lead |
|---|---|---|
| `2026091700` | 09-17 00Z | 0–6 h |
| `2026091618` | 09-16 18Z | 0–12 h |
| `2026091606` | 09-16 06Z | 8–24 h |

逐 lead（约 1,200–3,400 站/时）：**0 h MAE 1.84 / RMSE 2.46**、1–12 h MAE 1.76–1.91、
**18–24 h MAE 1.92–2.07 / RMSE 2.59–2.78**。**13–17 h 缺**——12Z 循环完全未保留（manifest 都 404）。

#### 三、决定性的那一步：固定时段，只变 lead

单 run 的那张表（RMSE 0 h 2.26 → 5 h 2.18）**不是技巧曲线**，因为 lead ≡ 有效时刻 ≡ 一天中的时刻。
换成多 run 后，同一个有效时刻可以用不同的 lead 去检验，**时段被固定住了**：

| 有效时刻 | 短 lead MAE | 中 lead MAE | 长 lead MAE |
|---|---|---|---|
| 09-17 03Z | 3 h **1.83** | 9 h 1.86 | 21 h **2.00** |
| 09-17 04Z | 4 h **1.81** | 10 h 1.82 | 22 h **2.02** |
| 09-17 05Z | 5 h **1.79** | 11 h 1.80 | 23 h **1.99** |
| 09-17 06Z | 6 h **1.80** | 12 h 1.79 | 24 h **1.92** |

**7 个有效时刻的配对汇总**：最短 lead 平均 MAE **1.808 K**，最长 lead 平均 MAE **1.999 K**，
**增长 +0.191 K（+10.6%）**，且 **7/7 个时刻都变差**。

**结论：误差随 lead 增长这件事在固定时段下可检测，方向一致，24 小时的幅度约 +0.19 K。**
这回答了提问方的问题——**有技巧曲线，而且它说明这份 2 m 温度预报是可靠的**：
一天之内误差只涨了约 10%，MAE 始终在 1.8–2.0 K。

#### 四、这条曲线的边界

- 可测 lead 只到 **24 h**，且 **13–17 h 缺**；24 h 以外**未测**。
- 配对比较只有 **7 个有效时刻**，全部落在 09-17 00–06Z，所以「时段固定」实际是固定在这 7 个小时，
  不是任意时段。
- 配对里「最短 lead」在各时刻分别是 0–6 h，所以 +0.191 K 是**这些 lead 对之间**的平均增长，
  **不是拟合出的斜率**，也未建立增长是否线性。
- 误差里含**代表性误差**（点对格点，低平处格内天花板中位 1.0 K、高原 sd 4.38 K），
  本条**没有**把它与模式误差分开。

新增 `scripts/thetae_anchor_and_skill.py` 的 `skill-runs` 子命令（`--runs` 可指定 run）；
`open_field` 增加可选 `run` 参数，旧 run 无 `item.json` 时直取 `<var>.zarr` 并回退到 `.half.zarr`。

### 2026-09-17 · 更正五：那条技巧曲线里约 72% 是**分辨率变化**，不是技巧衰减

上一条我报：7 个有效时刻、时段固定，最短 lead 平均 MAE **1.808 K** → 最长 lead（24 h）**1.999 K**，
增长 **+0.191 K**，**7/7 个时刻都变差**，并据此告诉提问方「这份 2 m 温度预报是可靠的」。

**这是一条混合曲线，而我把它读成了技巧衰减。**

#### 错在哪

三个可读 run **携带的分辨率档不同**——直接探过：

| run | full（0.25°，1440×721） | half（0.5°，720×361） |
|---|---|---|
| `2026091618` | **200** | 404 |
| `2026091606` | 404 | **200** |
| `2026091700` | 200 | 200 |

lead 0–12 来自 full、**lead 18–24 来自 half**。于是那条曲线拿「短 lead 的 0.25° 预报」
去比「长 lead 的 0.5° 预报」，把差值叫成了技巧衰减。

#### 控制：在同一个 run 上直接量分辨率代价

`tier-control` 用**两档都有**的 `2026091700`、**同一批小时**：

| lead | full MAE | half MAE | 代价 |
|---|---|---|---|
| 0 | 1.841 | 2.000 | **+0.159** |
| 3 | 1.830 | 1.964 | +0.135 |
| 6 | 1.803 | 1.948 | +0.145 |

**平均 +0.137 K**，且在 lead 0–6 上几乎恒定（0.120–0.159）——这正是**分辨率效应**的形状，
技巧效应不长这样。**它解释了 +0.191 K 的约 72%。**

#### 干净的那一版（`--tier full`）

时段与分辨率都固定，只用 full 档、7 个有效时刻：
最短 lead（0 h）平均 MAE **1.808 K** → 最长 lead（**12 h**）**1.819 K**，
增长 **+0.011 K（+0.6%）**，**6/7** 个时刻变差。

**即：在 0–12 小时、时段固定、分辨率固定的条件下，2 m 温度误差几乎没有可测的增长。**
这比原来那句更强——原来我说「一天涨 10%」，实际是**一天之内测不出增长**。

**边界**：干净版**只到 12 h**（full 档只有两个 run）；**13–17 h 的洞补不上**——
逐小时回探 144 个候选，只有 5 个 manifest 存活，其中 12Z 循环（`2026091612`）**连 manifest 都没有**。
配对仍只有 7 个时刻且全在 09-17 00–06Z。+0.011 K 不是斜率。half 档那条（0–24 h，+0.191 K）
**保留在 claim 里但不作为技巧证据**。

#### 与前面四次同类

`max(p)` 当地面气压、值域判 `lapse850_500`、6 分钟网格、`now-10k` 网格，加上这一次：
**判据不是对象的规则，却用得很有信心。** 这一次的对象是**一条跨 run 拼出来的序列**，
它必须满足的规则是「序列里每一项用同样的方式测量」——在此之前没有任何检查问过这一句。

**新的具体教训**：当一条序列是**从档案里拼**出来的，**档案自身的不一致就进入了序列**。
我已经量过这里的保留是部分且不规则的，却没有问过**活下来的那些是否可比**。

新增 `tier-control` 子命令与 `--tier` 选项（`open_field` 的 `tier` 参数不再让回退静默混档）。
更正笔记：`docs/maintenance/2026-09-17-skill-curve-resolution-confound.md`。

### 2026-09-17 · 逐一推进之一：一次锚四个场，发现 **2 m 露点系统性偏干 1.4 K**

新增 `scripts/anchor_check.py` 的 `fields` 子命令，一次锚 `tmp2m` / `dpt2m` / `prmsl`。
测站那一侧同一个 METAR 记录里就带着温度、露点与**两种不同的气压订正**，所以四对一起测：

| 模式场 | 测站场 | n | 中位偏差 | MAE | sd |
|---|---|---|---|---|---|
| `tmp2m` | `t` | 4897 | −0.10 K | 1.65 | 2.17 |
| **`dpt2m`** | **`td`** | 4881 | **−1.40 K** | 1.93 | 2.09 |
| `prmsl` | `slp` | 1650 | −0.60 hPa | 1.05 | 2.17 |
| `prmsl` | `qnh` | 4689 | −0.60 hPa | 1.60 | 2.30 |

`qnh` 是**按标准大气订正的高度表拨正值**，与海平面气压**按构造**就不同，所以这一对是四对里
最不对等的，MAE 更大（1.60 对 1.05）在意料之中——**它们被分开报，而不是平均成一个「气压检查」**。

#### 露点那 −1.40 K 不是地形效应

按站点海拔分箱，`dpt2m` 的中位偏差是 <100 m **−1.00**（n=2009）、100–500 **−1.50**（1889）、
500–1000 **−1.25**（494）、1000–2000 **−1.50**（403）、2000–3000 **−1.50**（69）、
≥3000 **−1.60**（17）——**几乎不随海拔变**。对照之下 `tmp2m` 的 **MAE** 才随海拔升
（<100 m 1.52 → 1000–2000 m 2.33）。**地形效应会跟着海拔带走，这个不跟。**

跨时次同样稳定：00Z 中位 **−1.20**（MAE 1.87）、03Z **−1.30**（1.90）、05Z **−1.45**（1.93），
而同期 `tmp2m` 是 −0.50 / −0.50 / −0.10。三次探测里 **100% 的站都报了 `td`**，故非选择效应。

**结论：这是一处平坦的、跨海拔、跨时次的系统偏差 —— 交付的 2 m 露点比实测干约 1.4 K，
而温度本身几乎无偏。** 由于 RH 由 T 与 Td 导出，这意味着**模式近地面的相对湿度系统性偏低**。

**未归因**：测到了偏差与其平坦性，**没有**归因。测站仪器约定、AWC 解码、±30 分钟时间匹配
都仍可能是贡献者，一个都没测。这一条已写进契约的 `residuals`。

#### 顺带补上我自己控制里的一个空洞

插这段文本时我又一次把**真实换行放进了单行 TOML 字符串**（本会话第二次），而
**重钉脚本并没有校验就把它钉上了** —— 契约的 `controls` 里写着「重钉前先 tomllib 全量解析」，
但那条控制**当时并不存在**：我是用一段一次性 Python 直接改 JSON 的。

新增 `scripts/repin_contract.py`：**先解析、再校验 11 个字段与 id 唯一，任何一条不过就 REFUSED 退出 1**，
只有全过才写。反向控制实测：往语料尾部追加一行未闭合的字符串，脚本报
`REFUSED the corpus does not parse, so its digest would pin bytes no reader can load` 并退出 1。

**教训与前面的同类**：写进 controls 的控制**必须真的在运行的路径上**，否则它只是一句期望。

### 2026-09-17 · 逐一推进之二：13–17 h 的洞**不是缺 run**，是测站历史里有 6 小时空档

上一条我写「13–17 h 缺，因为 12Z 循环完全未保留」——**那句话是我从 manifest 探测猜的，是错的。**

#### 先看每个 run 到底贡献了哪些 lead

| run | 档 | 起报 | 实际 lead | 缺 |
|---|---|---|---|---|
| `2026091700` | full + half | 09-17 00Z | 0–7 | — |
| `2026091618` | full | 09-16 18Z | 5–13 | — |
| `2026091606` | half | 09-16 06Z | 8–25 | **12–16** |

run `2026091606` **覆盖** 12–16 这段 lead，所以洞不在 run 上。它缺的 12–16 对应有效时刻
09-16 的 18Z–22Z。

#### 洞在观测里

新增 `scripts/point_products_check.py` 的 `coverage` 子命令（只数 METAR 的 `time` 字段）：

| 小时 | METAR 观测数 |
|---|---|
| 09-16 13Z / 14Z / 15Z / 16Z | 11 / 221 / 1456 / 3687 |
| **09-16 17Z – 22Z** | **6 小时全部为 0** |
| 09-16 23Z | 1419 |
| 09-17 00Z – 06Z | 6824 / 8435 / 8670 / 8635 / 8767 / 8610 / 3783 |

**airport 规范说每站携带「最近 24 小时的 METAR」，实测只有 12 个小时带观测**，
跨度 09-16 13Z–09-17 06Z（18 小时），**其中 6 小时完全空**；有观测的小时里条数从 **11 到 8767**。
这是继 sounding 的「两天 vs 5 个 issue」之后，**第二处规范与实测不符**。

#### 一个差点让我报错的陷阱

直接在原始字节上按 ISO 时间戳字面计数，会得到 18Z 有 11 次、19Z 有 63 次、**最晚到 09-17T23:00Z**
——看起来洞并不存在。**那些是 TAF 的 `periods[].from/to`**（实测 TAF 有效期一直延伸到 09-18 15Z），
**不是观测**。只有按 METAR 的 `time` 字段数，洞才显出来。

**产品确实带了 TAF 的完整解码细节**：`from`/`to`/`change`（FM/BECMG）、`prob`、风、阵风、能见度、
天气现象、云层与云底。这是「测站数据有更多细节」里我此前没展开的那一半。

**成因未查明**：该产品每 10 分钟从一份源缓存重建，洞可能来自源、来自聚合或一次源中断，本条不区分。
已写进 claim 的 `assumptions` 与契约的 `residuals`。

### 2026-09-17 · 逐一推进之三：**雨-冰混合有判别力，而 PDD 没有** —— 候选 A 的关键一格

round-3 卡把「正积温（PDD）的判别力未检验」列为候选 A 成立的唯一关键。PDD 那一格已做且为负
（三年都覆盖 91% 的面积，连 ≥5000 m 也有 65.8%——**一个到处都成立的触发条件判别不了任何事**）。
这一格做的是候选 A 的另一半：**雨-冰混合**。

不受 xue 无档案的限制——像 PDD 那次一样走 **NOAA 的 GFS 深档案**。
每 6 小时窗口（每天 4 循环）× 0.25° 格：`APCP`（6 小时累积）与窗口两端 `TMP:2m` 的均值，
液态 = APCP 落在 T>0 的窗口，**按 GFS 自身地形分箱**（用同一份模式地形，避免引入第二个无关误差）。

#### 总量：异常是**头重**的

| 地形带 | 2024 | 2025 | 2026 |
|---|---|---|---|
| <3000 m | 70.3 | **94.9** | 70.8 |
| 3000–4000 m | 49.1 | **66.1** | 57.4 |
| 4000–5000 m | 39.0 | 53.7 | **64.5** |
| **≥5000 m** | 47.9 | 48.9 | **73.9** |

**≥5000 m 上 2026 是另两年的 1.52–1.54 倍**，而 **<3000 m 上 2026 反而不是最湿的**
（2025 是 94.9）。**异常集中在冰川所在的高度。**

#### 阈值稳健

把液态判据从 T>0 抬到 T>1、T>2，≥5000 m 的比值几乎不动：**1.54 / 1.55 / 1.54**。
**结论不依赖那个微妙的相态切点**——这一条很重要，因为模式 2 m 温度在高原的
代表性误差 sd 是 4.38 K，相态切点正是最脆弱的地方；而**比值在三年间用同一套偏差，所以稳**。

#### 逐日形状：脉冲在个例前约十天

≥5000 m 的逐日液态水（mm/格/天）：

| 日 | 2024 | 2025 | 2026 | 2026/他年均值 |
|---|---|---|---|---|
| 0812 | 5.41 | 2.61 | 3.51 | 0.88 |
| **0813** | 3.78 | 1.67 | **6.95** | **2.55** |
| **0814** | 0.78 | 2.21 | **7.15** | **4.78** |
| **0815** | 0.87 | 3.73 | **7.48** | **3.25** |
| **0816** | 1.89 | 3.27 | **5.80** | **2.25** |
| 0817–0821 | ~3 | ~3.5 | ~4.5 | 1.24–1.61 |
| 0822–0826 | ~4 | ~3.5 | ~4.1 | 0.95–1.14 |

**超额集中在 08-13…08-16，而垮塌当天 08-26 只有 1.13**；中位比值 **1.25**，
**15 天里 13 天是三年中最湿的**。该时段与报道所述「8/12–8/24 冰体流速升至 0.4 m/天」**重叠**。

#### 真正的进展在这一句

**PDD 是饱和的**（91% 的面积、三年不变），**饱和的指标无法判别**；
**雨-冰混合是未饱和的**，因此保留了判别力。这不是「找到了预警指标」——

**仍未建立**：n=3 年，**无法构成分布**（2024 与 2025 在 ≥5000 m 恰好接近，才使 2026 显眼）；
这是**时间上的重合，不是归因**；用的是 GFS **分析场**而非观测；该指标是窗口累积，
**不是一个可以拿去预警的阈值**。

#### 一次被冒烟测试拦下的错，以及一次顺带的自查

第一次跑出 `rain = 0.0`、`solid = 2.5–3.6 mm`——**整个框被判为零下**，而 25–30°N 的印度河平原
八月不可能是零下。原因是 **GDAL 的 GRIB 驱动返回的温度已经是摄氏度**
（`GRIB_UNIT: '[C]'`，量程 −64.7…+46.3 °C），我又减了 273.15，于是全部 ≤0、每次降水都被判成固态。
改为**读 `GRIB_UNIT` 再决定是否换算**。

**顺带核查了已发布的 PDD 负结果**：`scripts/collapse_trigger_check.py` **没有**做这个换算
（直接用原始值比 `>0.0`），所以那条结论**不受影响**——但这是**运气，不是设计**：
两个脚本一个对、一个错，差别只在于谁多写了一次减法。

新增 `scripts/rain_on_ice_check.py`（一次遍历累计三个阈值 + 逐日序列，`--years/--days/--hours` 可调）。
round-3 卡的 `round_result`、`remaining_questions`、`attempts`、`handoff` 均已更新，卡仍开着
（`receiver_confirms_same_question = false`）。

### 2026-09-17 · 融合更多资料之后：**区域信号成立，站点尺度的预警被否掉了**

提问方要求「跑融合了更多资料的学习和预测，看看能否给几个准确的预警信息」。
**答案是不能**——而且这个「不能」是量出来的，不是谨慎起见的说法。

#### 融合了什么

四个场合成一个指数，全部取自同一窗口的同一 run：

| 场 | 用途 |
|---|---|
| `APCP` | 6 小时累积降水 |
| `TMIN:2m` / `TMAX:2m` | 窗口温度**极值**（比端点均值严谨） |
| `WEASD` | 雪水当量——区分「雨落雪面」与「雨落裸地」 |
| `HGT:surface` | 按模式自身地形分箱 |

**液态判据用窗口最低温 > 0 °C**：比用均值更保守，只计那些整段都不可能下雪的窗口。
（这是对我先前「端点均值」那版的收紧，也是对高原相态切点最脆弱的回应。）

#### 区域尺度：2026 确实是六年中最异常的

NOAA 0.25° 档案**止于 2021**，所以基线是 6 年。15 天窗口内落到雪面上的液态水（mm/格）：

| 地形带 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | 2026 排名 |
|---|---|---|---|---|---|---|---|
| 3000–4000 m | 4.2 | 3.5 | 3.0 | 2.5 | **8.0** | 3.3 | 4 |
| 4000–5000 m | 13.7 | 10.3 | 15.7 | 11.7 | 16.6 | **17.6** | **1** |
| **≥5000 m** | 15.2 | 19.7 | 23.1 | 23.9 | 23.2 | **36.7** | **1** |
| <3000 m | 0.1 | 0.1 | 0.1 | 0.1 | 0.2 | 0.1 | 4 |

**≥5000 m 上 2026 是次高年份的 1.54 倍，而低海拔它居中。** 异常是头重的——这是真的。

#### 站点尺度：把同一指数放到冰川实际占据的尺度上，它不成立

两个日期**取自文献而非记忆**：Thame（珠峰区，尼泊尔）**2024-08-16 13:30 当地时**
（[NHESS 26/4131/2026](https://nhess.copernicus.org/articles/26/4131/2026/)）；错坚河 **2026-08-26**。
站点 ±1° 框、只取地形 ≥4000 m 的格，逐日：

| 站点 | 事件日 | 指数 | 同站同日六年排名 | 其余五年同日 |
|---|---|---|---|---|
| **Thame** | **2024-08-16（真 GLOF）** | **1.7** | **6/6（最低）** | 412.4 / 30.4 / 15.3 / 9.8 / 8.2 |
| Thame | 2026-08-16（无事件） | **412.4** | 1/6 | — |
| Chuepcha | 2026-08-26（真事件） | 272.4 | 1/6 | 28.8 / 25.6 / 16.7 / 3.4 / 0.0 |
| Chuepcha | 2024-08-20（无事件） | 251.7 | — | — |

**同一个站点、同一个季节：真事件当天是六年最低，而无事件的那天是六年最高。**
「漏报」对框位移动稳健（+0.0 / +0.5 / +1.0 / −0.5N 上都是 6/6），所以它不是坐标问题。

#### 阈值表：没有任何阈值能用

180 个站点-日，其中 **2 个**是真事件：

| 阈值 | 超阈 | 命中 | 虚警 | 漏报 | 命中率 | 虚警率 |
|---|---|---|---|---|---|---|
| 50 | 50 | 1 | 49 | 1 | 50% | **98%** |
| 200 | 10 | 1 | 9 | 1 | 50% | **90%** |
| 272 | 7 | 1 | 6 | 1 | 50% | **86%** |
| ≥300 | 5 | **0** | 5 | 2 | **0%** | 100% |

**把阈值降到能命中，虚警率就是 86–98%；抬到虚警可接受，命中率就归零。**
这张表**不是准确率**——2 个事件，阈值一动命中率就在 0–100% 之间跳。
但**它足以否掉这个说法**，而否掉正是它做的事。

#### 真正的教训

**区域异常不是站点触发条件。** 这一轮把资料从 3 年扩到 6 年、从一个场扩到四个场，
得到的第一个结论（区域排 1/6）是**监测陈述**而不是预警；
而**从「区域异常」跨到「站点预警」这一步，被唯一能做的检验否掉了**——
否在同一个站点、同一个季节、一个已核实的真事件上。

**这也是对提问方那句话最诚实的回答**：我在一个例子上跑通的方法论，
在**区域尺度上可复现**，在**站点尺度上不成立**；而预警需要的是后者。

新增 `scripts/glacier_warning_index.py`（六年基线，多场融合）与
`scripts/glacier_warning_verdict.py`（站点-日判决，阈值表，框位扫描，**可从 /tmp 缓存离线复算**）。
round-3 卡已更新；卡仍开着（`receiver_confirms_same_question = false`）。

**边界**：6 年、2 个事件；第三个已核实日期（South Lhonak, Sikkim, 2023-10-04）落在八月窗口之外，
本轮**未测**；站点坐标取到 0.1° 且未用冰川编目核对；用的是**分析场**不是观测；
想得到分布需要另找更早的再分析（ERA5 一类），本轮未做。

### 2026-09-17 · 全球范围，重点西藏与秘鲁：**区域排名成立，三事件阈值仍不可分**

那些 GFS 记录本身就是全球场（1440×721），已缓存在 /tmp，所以**换区域不花网络开销** ——
西藏、秘鲁、喀喇昆仑、阿拉斯加、巴塔哥尼亚、全球 ≥4000 m 一次算出。

#### 区域排名

**全球八月**：≥4000 m 陆地上，2026 的液态水 **19.8 mm/格**排 **1/6**（次高 2025 的 15.6）。

| 区域 | 带 | 2026 | 排名 |
|---|---|---|---|
| **西藏/喜马拉雅** | 4500–5500 m | **28.3** | **1/6** |
| **西藏/喜马拉雅** | ≥5500 m | **41.0** | **1/6** |
| 西藏/喜马拉雅 | 3500–4500 m | 7.2 | **5/6** |
| 喀喇昆仑 | 4500–5500 m | 9.8 | 4/6 |
| 喀喇昆仑 | 3500–4500 m | 4.5 | **6/6** |

**西藏的异常专属于最高的那两个带**（4500 m 以上 1/6，3500–4500 m 反而 5/6）；
而**喀喇昆仑同一窗口排在末位**——所以这不是一次覆盖整个高亚的异常。

#### 秘鲁在**结构上**不同，这一点比排名重要

| 窗口 | 带 | 2026 | 排名 | 备注 |
|---|---|---|---|---|
| 湿季 02-01…02-15 | ≥4000 m | **0.0** | — | **五年、十五天全部为零** |
| 过渡季 04-15…04-29 | 4500–5500 m | **40.3** | **1/6** | 次高 25.8 |
| 旱季 08-12…08-26 | 3500–4500 m | 10.4 | 1/6 | 绝对值低 |

**湿季的零不是缺数据**：热带安第斯湿季的对流层冻结高度约 4800–5000 m，
4000 m 以上的降水以**雪**为主 —— **雨-冰混合在秘鲁的湿季根本不发生**。
**同一指数在两个半球的活跃季节相反，所以一个全球窗口不能读成一个数字。**
这是我先前那条「八月对秘鲁是错季」的提醒所指向的、但更彻底的事实：不是季节错，
是**机制在该季节不成立**。

#### 三事件判决，用三天累计（预警需要提前量）

第三个事件**取自原文而非记忆**：**Vallunaraju 2025-04-28**，Cordillera Blanca 的 Casca 谷，
Nevado Vallunaraju 东壁（~5000 m）岩崩 → 两个小湖（0.01 / 0.007 km²）溃决 → 14 km 到 Huaraz，
2 死、5 桥、29 房受损（npj Natural Hazards 3:51, 2026）。
**该文明确写岩崩前只有中等降雨（平均 3 mm/天），伴随的是温度峰值** ——
所以它是对指数**特异性**的一次好检验。

| 事件 | 当天 | **3 天累计** | 7 天累计 |
|---|---|---|---|
| Thame 2024-08-16 | 6/6 | **4/6** | — |
| Chuepcha 2026-08-26 | 1/6 | **1/6** | 2/6 |
| Vallunaraju 2025-04-28 | 3/6 | **1/6** | **1/6** |

三天累计把三个里的**两个排到 1/6**，但 **Thame 仍只排 4/6**。

#### 阈值表：依然不可用

84 个站点-日、3 个事件：

| 阈值 | 超阈 | 命中 | 虚警 | 漏报 | 命中率 | 虚警率 |
|---|---|---|---|---|---|---|
| 50 | 57 | 3 | 54 | 0 | **100%** | **95%** |
| 80–100 | 30–39 | 2 | 28–37 | 1 | 67% | 93–95% |
| 110–200 | 14–28 | 1 | 13–27 | 2 | 33% | 93–96% |
| 275 | 6 | 0 | 6 | 3 | **0%** | 100% |

**三个事件的三天累计值跨越 4 倍（Thame 68.2 / Vallunaraju 109.9 / Chuepcha 274.9），
所以不存在一个能同时抓住它们的阈值。**

#### 那么能给出什么

**不是预警，是分区域分季节的异常度排名**：西藏 ≥4500 m 1/6、秘鲁过渡季 1/6、
喀喇昆仑 4–6/6（负）、全球 ≥4000 m 1/6。加上一条方法学结论：
**指数必须按季节读；而从区域异常到站点预警这一步，仍未被任何阈值跨过。**

#### 三个错，都不是数据的问题

1. **参考帧假设**：脚本用 `years[0]` 当参考窗口，而**档案从 2021-04-01 才开始**，
   `--start 0201` 在取参考场时就 404、**整跑立即死掉、一个循环都没试**；已改为逐年后退。
2. **退出码被掩盖**：抓取命令写成 `… | tail -20`，**退出码来自 tail**，失败被报成
   「completed, exit 0」；已加 `set -o pipefail`。
3. **缓存识别下标错**：文件名是 `_gw_<stamp>_<hour>_<key>.grib2`，我取了错的下标，
   造成「90/90 未缓存」的假象。

**三个都是我没有先验证自己的读取路径就下结论。** 与前面几次同类，但这次都在几分钟内自查出来了。

新增 `scripts/glacier_index_regions.py`（命名区域的全球读出，可指定窗口，纯离线）。

### 2026-09-17 · 接入移动硬盘上的 ERA5：**本仓库第一次有了「自身以外」的对照**

提问方提供了一块移动硬盘，上面是 ECMWF ERA5 的一批资料。**全部收进来了** ——
但「收进来」在这里有明确含义，先说清楚。

#### 收进来了什么

`/Volumes/Newsmy` 上 **12 个变量、372 个文件、304.3 GB**，全部是 **2024 年 1 月**、
每天一个 NetCDF、全球 0.25°（721×1440）、**逐小时**：

| 类别 | 变量 |
|---|---|
| 单层 | `t2m`、`d2m`、`sp`、`sd`（雪深）、`sst`、`tisr`、`u10`/`v10`/`u100`/`v100` |
| 单层单变量 | `total_precipitation`、`boundary_layer_height`、`surface_net_thermal_radiation` |
| 多层（**23 层**：5…1000 hPa，含 **850/700/500**） | `temperature`、`geopotential`、`relative_humidity`、`u`/`v`、`vertical_velocity`、`divergence`、`vorticity` |

**本机只剩 21 GB 可用**，所以字节留在盘上、**就地读**。这在许可上也是唯一正确的做法：
**ERA5 是 Copernicus 产品，可自由使用但不是公有领域**，而本仓库（沿 Adva 的
`PUBLICATION_BOUNDARY.md`）**只准入公有领域** —— 与 Copernicus DEM 同一条规则。
所以：**原始字节不进仓库**，进仓库的是 `docs/era5-catalogue.json`
（路径、大小、mtime、首尾各 1 MiB 的 SHA-256、结构参数、许可声明）。

清单里也写明了它**不是**什么：**不是全文件摘要**，只能发现文件被改动/截断/替换，
**不能证明与 ECMWF 发出的字节逐位相同**（也没有提供下载记录）。

#### 它能回答什么：一个此前问不出的问题

此前每一条 check 都是 **GFS 对 GFS**，或对测站 —— 而没有测站档案能覆盖这些日期，
也没有第二个模式。ERA5 提供了第二个模式。

**同一天、同一时刻、同一方框（2024 年 1 月，12Z）：**

| 方框 | 场 | ERA5 − GFS（三天） |
|---|---|---|
| 高原 80–92E/26–32N | `t2m` | **−0.29 / +0.39 / +0.66 K** |
| 暖池 120–180E/15S–15N | `t2m` | −0.47 / −0.18 / −0.38 K |
| **安第斯 80–68W/18–8S** | `t2m` | +0.63 / +0.25 / +0.78 K |
| 高原 | θe 850 hPa | +1.25 / +2.19 / +2.62 K |
| 暖池 | θe 850 hPa | +0.28 / +0.02 / +0.47 K |
| 全球 ±60° | `t2m` | +2.73 / +2.69 / +0.76 K |

**区域上两个独立再分析吻合到 1 K 以内**（θe 到 0.02–2.6 K）。这是本仓库第一次能说
「交付的场与自身以外的东西一致」。**全球方框那 +0.8…+2.7 K 的系统差未解释**，如实留着。

#### 与 θe 那条 claim 的关系：**方向相反，但季节不同，所以还不能下结论**

单独看 ERA5 的一月：850 hPa 高原 θe 中位 **313 K**、暖池 **345 K** ——
**高原比暖池低 32 K**，且**没有任何顶格**（仅 0.1–0.2% 落在当日最大值 0.5 K 内）。
而 θe 那条 claim 记录的是**九月**的发布场**顶在码本上限 357 K**、高原比暖池更极端。

**两者方向完全相反，但一是一月、一是九月。** 该 claim 自己就写着「高原夏季本身是热源」，
所以顶格**是夏季现象**。**硬盘上只有一月，因此这个跨再分析的检验只做了一半。**

#### 这一轮我错了三次，全是读取路径

1. **单位**：GDAL 给的 GRIB 温度已是 °C 而 ERA5 的 NetCDF 是 K，我在 `t2m` 那一支只换算了一边，
   得到「GFS 比 ERA5 暖 16 K」的荒谬结果；改为**读 tags 里的 `units`**，两边同一规则。
2. **经度惯例**：ERA5 是 0–360、GFS 是 −180–180，安第斯方框（−80…−68）在 ERA5 上选中 **0 格**，
   被我误读成「无数据」；改为**每个源用自己的坐标建掩膜**，并对 0–360 做回绕。
3. **掩膜串用**：先前用一方的坐标掩膜去索引另一方的数组，是那个「+16.3 K」的真正来源。

**三次都不是数据的问题。** 这与本报告里反复出现的那一类完全同源，只是这次都在几分钟内自查出来了。

新增 `scripts/era5_catalogue.py`（清单与完整性指纹）、
`scripts/era5_vs_gfs_check.py`（跨再分析对照，含 0–360 回绕与单位规则）、
`scripts/era5_plateau_check.py`（单看 ERA5 的 850 hPa 行为）、
并把 Bolton 实现抽成无依赖的 `scripts/bolton.py`（`thetae_check.py` 改为导入，
**树里仍只有一份公式**，且不需要 xarray 即可被 ERA5 侧的检查复用）。

**边界**：硬盘上是**一个月（2024-01）**，不是长基线 —— 它**不能**替代此前说的
「换 ERA5 拿 30–40 年分布」；它是**第二个模式**，不是更长的历史。
`single_lvl` 的 10 个变量本轮只用了 `t2m`/`d2m`；`sd`、`str`、`blh`、
多层 8 个变量与 23 层中的 21 层**都还没用**。

### 2026-09-17 · 用 SAR 再核对一轮：**指数在站点尺度上没有信号，而 SAR 证明那里确实变了**

提问方给了 [blog.ringsaturn.me 的 Langtang SAR 一文](https://blog.ringsaturn.me/posts/2026-08-28-langtang-sar/)，
问能不能用「巨大信息量的 SAR 资料」再核对一轮。**能，而且这一轮给出了此前给不出的判决。**

#### 它先纠正了我一个猜错的东西

**事件**：2026-08-26 02:52:10 UTC，Langtang Lirung（约 7200 m）**北壁冰川覆盖陡崖冰岩崩塌**，
沿 Bhote Koshi 与 Trishuli 下行约 100 km，摧毁吉隆口岸（热索桥 / Rasuwagadhi）。
**脱离点坐标 28.2853°N, 85.5252°E** —— 我 round-3 卡里写的「Chuepcha 28.50N, 85.30E」
**是我猜的**，差了约 30 km。用文中已核实的坐标重算：

| 站点 | 半径 | 2026 三天累计 | 排名 |
|---|---|---|---|
| **28.2853, 85.5252（已核实）** | **0.25°**（≈28 km，一个模式格点） | **14.2** | **3/6** |
| 同上 | 1.0°（≈111 km） | 220.5 | 1/6 |
| 28.50, 85.30（**我猜的**） | 0.25° | 0.0 | 4/6 |
| 同上 | 1.0° | 274.9 | 1/6 |

**那个「1/6」只存在于 1° 尺度；缩到单个模式格点就掉到 3/6。** 用**正确**坐标后，点尺度比先前更弱。

#### SAR 复现：从公开数据独立做出变化检测

数据是 **Sentinel-1 RTC γ⁰（Microsoft Planetary Computer，匿名可读，经 SAS 端点签名）**，
UTM（此处 EPSG:32645）10 m、线性功率、nodata −32768。流程照原文：
**同轨配对**（升/降轨不可逐像元互比）、平均到 20 m、转 dB、5×5 平滑、±3 dB、最小图斑 2 万 m²，
**噪声底用灾前同轨对实测**而不是假设。本文只取走廊 85.15–85.60°E / 28.10–28.40°N。

| | 噪声底（08-04→08-16，无事件） | 跨事件（08-16→08-28） | 信噪比 |
|---|---|---|---|
| VV 增亮 | **0.5 km²** | **4.0 km²** | **8×** |
| VV 变暗 | 0.9 km² | 1.9 km² | 2× |
| VH 增亮 | 0.2 km² | 3.4 km² | 17× |
| VH 变暗 | 8.1 km² | 2.2 km² | **低于底噪** |

**变化密度随距脱离点的距离衰减**：

| 距脱离点 | 变化密度 |
|---|---|
| **0–2 km** | **12.50%** |
| 2–6 km | 2.98% |
| 6–15 km | 0.49% |
| 15–40 km | 0.27% |
| 全 AOI 均值 | 0.61% |

**源区浓度高出 20–45 倍** —— 与冰岩崩塌应当产生的形态一致。

**与原文的数字不可直接比**：他们的 AOI 是全幅（85.09–85.71 / 27.79–28.51，约 4400 km²），
我的是走廊（约 1650 km²），面积类的量随 AOI 缩放。可比的是**密度**：他们全 AOI 均值 VV 1.1%、
源区 VV 5.6%；我全走廊 0.61%、**脱离点 2 km 内 12.50%**。**两边都指向源区集中。**

#### 判决：这正是否掉站点预警的那一步

**SAR 证明事件在脱离点 2 km 内确实施加了剧烈的地表改变（12.5% 的像元），
而同一个位置上，我的大气指数在它自己的格点尺度只排 3/6 —— 中位。**

**一个独立、信息量远大于大气场、空间分辨率高 1400 倍（20 m 对 0.25°）的观测，
证实了事件的真实与局地性；而大气指数在那里没有信号。** 这与 Thame 那一格同向，
而且这次用的是**已核实的坐标**，不是我猜的。

**边界**：本文只做了 path 85 升轨的**一个**跨事件对；三条轨道的其余配对、
NISAR 的 L 波段、以及**偏移产品（GOFF）测位移**都未做 —— 而位移正是 round-3 卡里
「流速 0.4 m/天」那个前兆所对应的量。**这是下一步最该做的一件事**：
它测的是降水指数**在原理上不可能有**的东西。

#### 四次读取错误，全在自己这一侧

1. **CRS 混用**：`read_scene` 返回 UTM 变换，调用方却按经纬度建掩膜，`lat>=27.79` 恒假，
   区域为空 → 变化面积恒为 **0.0 km²**，看起来像「什么都没发生」而不是像 bug。
2. **缩放因子写反**：`res/target` 与 `target/res` 弄反，输出像元成了 **5 m 而非 20 m**，
   而面积仍按 20 m 算 —— **面积一律放大 16 倍**。修正后 VV 增亮噪声底 349.2/16 = **21.8 km²**，
   与文中 VV 22 km² 几乎相等，这才确认流程对了。
3. **窗口为空**：第一次直接用经纬度 `from_bounds` 去切 UTM 栅格。
4. **磁盘写满**：把 6 个 10 m 窗口落盘缓存（每个约 670 MB）把本机写到 **100%（剩 795 MiB）**；
   已立即清除并改为不落盘、只取走廊。

**四个都不是数据的问题。** 其中第 2 个尤其危险：16 倍偏差下所有数字仍然「看起来合理」，
只有与一个独立公布值对照才暴露出来 —— 这也正是提问方建议用 SAR 再核对一轮的价值所在。

新增 `scripts/sar_change_check.py`（匿名取数、SAS 签名、UTM 几何、噪声底实测、逐距离带密度）。
**未纳入仓库的字节**：Sentinel-1 RTC 是 Copernicus 数据（同 ERA5 的许可立场），
本轮只读不存，派生的数字带出处记录。

### 2026-09-17 · 坐实方法论：**三轨道收敛检验，源区重复性 6%，远场不收敛且原因可指认**

提问方要求「先把方法论坐实」。坐实不是再写一段论述，而是**执行此前声明的可证伪检验**：
把同一批锚定测量换到**独立数据**上重做，看数字移动是否小于它自己声明的误差条。

#### 做法

SAR 现成可做：此前只做了 **path 85 升轨一个对**，而同一事件另有 **path 121 与 19 两个降轨**。
每个轨道给出**一个灾前对**（按构造什么都没发生，所以它的变化面积**就是**该轨道的噪声底）
与**一个跨事件对**。三个独立几何看同一片地面 —— **它们的散度就是这条流水线的经验重复性**，
而这是单个轨道给不出的。

**预测在跑之前声明**：三条轨道的密度剖面应在各自噪声底范围内一致；若超出，要么几何看到的东西不同
（升/降轨的叠掩与阴影落在相反的坡面上），要么流水线不稳。

#### 结果：分裂，而且分裂是可诊断的

| 轨道 | 底噪 VV 增亮 | 事件 VV 增亮 | 信噪比 | **0–2 km** | 2–6 km | 15–40 km |
|---|---|---|---|---|---|---|
| path 85 升轨 | 0.51 km² | 3.97 km² | **7.8×** | **12.50%** | 2.98% | 0.27% |
| path 121 降轨 | **22.68 km²** | 44.09 km² | 1.9× | **12.31%** | 10.93% | **19.34%** |
| path 19 降轨 | 1.44 km² | 3.30 km² | 2.3× | **13.05%** | 1.37% | 0.37% |

**（一）源区收敛。** 脱离点 2 km 内的变化密度：**12.50 / 12.31 / 13.05%**，
**散度 0.73 个点，相对约 6%**。**这是这条线里第一次重复测量真的收敛。**

**（二）远场不收敛，而且原因是可指认的。** 15–40 km 的密度是 0.27 / **19.34** / 0.37%，
散度 19.07 个点。**path 121 的灾前底噪本身就是另外两条的 40 倍**（22.68 对 0.51 与 1.44），
它的信噪比只有 **1.9×**，而另外两条是 7.8× 与 2.3×。

**排除 path 121 的判据是它自己的灾前信噪比，不是它与别人不一致** —— 这一点很重要：
若按「结果不同意就剔除」来筛，那是循环论证。此处它的事件信号（44.09）还不到其底噪的两倍，
**在任何阈值下都不该被当作检测**。

#### 所以这条流水线的重复性是多少

| 量 | 估计 | 依据 |
|---|---|---|
| **脱离点 2 km 内变化密度** | **12.3–13.1%（重复性约 ±0.4 个点）** | 三个独立几何 |
| 区域面积类统计（增亮 km²） | **不可比** | 底噪跨轨道差 40 倍，随叠掩/阴影与几何变化 |
| 远场密度 | **不可用** | 一个几何被自身底噪淹没 |

**一个可复用的结论**：**密度类统计（按可用面积归一）跨几何稳健；面积类统计不稳健。**
因为叠掩与阴影让不同几何的"可用像元数"不同，而面积统计不归一。

#### 方法论一侧：把纪律变成一条能失败的命令

新增 `scripts/methodology_check.py`，七项检查，**其中两项是对抗性的** —— 它故意损坏一份语料副本，
**要求守卫必须拒绝**。理由就是第五条模式：**没人见它拒绝过的守卫只是意图，不是控制。**

```
1 corpus         11 字段、id 唯一、pin 与契约一致
2 checkers       每条 claim 声明的检查器文件都在
3 corrections    每条更正笔记仍在、且仍指向存在的文件（append-only 规则本身被检查）
4 cards          四张问题卡通过 Adva 的校验
5 helpers        手工写的 box filter / 连通域 / TOML 转义器的单元测试
6 guard-refuses  repin_contract.py 必须 REFUSE 一份解析不了的语料
7 guard-accepts  同一守卫必须接受真语料且不改动已匹配的 pin
```

**实测 7/7 通过。**

#### 两次自查，都在检查自身

1. **报告器把「establishes」那行在失败时照常打印** —— 描述了与事实相反的东西，把诊断藏了。
   改为**失败时只打印失败原因**。
2. **`corrections` 检查因为错误的原因失败**：它在本仓库里找 `docs/format.md`、
   `tests/fixtures/pressure-registry.json`、`tc-registry.json` —— 这三个都**在上游 xue 克隆里**，
   笔记引用它们是对的。**一条因为错误原因而失败的检查，和一条不能失败的检查一样糟：它会训练人忽略 FAIL。**
   改为先判归属、上游引用在有克隆时解析、**其余显式列为 SKIPPED 而不是算通过**；
   并允许唯一裸文件名按名字解析，且**注明是按名字解析的**。

**这两次都不是数据的错，是检查的错** —— 与前八次更正同类，只是这次的观察对象是检查器本身。

### 2026-09-17 · 位移（前兆）这一格：**仪器底噪太高，测不出 0.4 m/天；但两条路都探明了**

round-3 卡记的前兆是**流速约 0.4 m/天**（12 天约 4.8 m），它**不在任何大气数据集里**，
而 SAR 测它。这一格是去补那一块。

#### 第一条路：NISAR GOFF —— **不可达，而且是不可靠地可达**

NISAR 的 GOFF（几何偏移）正是为此设计的产品，这个山谷上有四个（path 48 降轨的 07-23→08-16
与 08-16→08-28、path 98 升轨的 07-26→08-19 与 08-19→08-31 等）。
**ASF 的检索接口匿名可用**，产品名里直接给出配对（`..._20260816T..._20260828T...`）。

**但取不到**：对同一 URL 反复请求得到**互相矛盾**的响应 —— 无范围 HEAD 先返回 **200（1.09 GB）**，
随后 **401 Unauthorized**；GET 一律 **401**；只有带范围的 HEAD 偶尔 206。
域名落地页标题是 "Egress"。**这是需要 Earthdata 登录的产品挂在一个不稳定的边缘上。**

**建立在偶然出现的 200 之上，正是本仓库的方法论禁止的事** —— 所以这一路记为不可达，
而不是"大概能取"。

#### 第二条路：Sentinel-1 振幅偏移追踪 —— 做到了，但**底噪淹没了信号**

用同一批可靠匿名可读的 RTC 数据，patch-wise 归一化互相关 + 抛物线亚像元精化。
两个同轨对，各间隔 12 天：

| | 中位位移 | 脱离点 3 km 内 |
|---|---|---|
| **底噪对** path 85，08-04→08-16（无事件） | **1.33 m** | 1.52 m |
| **事件对** path 19，08-12→08-24（**正是 0.4 m/天被观测到的那段**） | **2.74 m** | 2.74 m |
| 比值 | 1.80 | 1.80 |

**判定为不可用，判据不是"信号小"，而是它的空间形状**：
**全窗口 24,616 个像块的中位数与脱离点 3 km 内的中位数完全相同（2.74 m）**。
若真有冰川在动而周边静止，全窗口中位应贴近底噪、只有冰川像块突出。
**两者相等 ⇒ 这是两次采集之间的整体配准差**（RTC 是按 DEM 地理编码的，不同轨道与时刻之间
本来就有一到数米的定位差），不是局地位移信号。

**结论：这个仪器的底噪（1.3–2.7 m）与要测的量（4.8 m）同量级，而信号被整体配准差支配。**
要做这件事需要 (a) 先拟合并扣除整体偏移、(b) 改用 GRD 或 SLC 而不是地形校正过的 RTC。
**本轮没做这两件事，所以前兆这一格仍然空着** —— 但空着的原因现在是量出来的，不是猜的。

#### 两个 bug，以及为什么这次不会复发

第一次跑，两个对都给出**约 664 m**，且比值 **1.00** —— 底噪与事件完全相同，
**这是伪影的样子，不是位移的样子**（我在跑之前就把这句话写进了脚本）。

**没有猜，用合成数据做了单元测试**：把散斑整体平移已知量，看相关器能否还原。

| 真实平移 | 峰值位置 | 我的公式还原 |
|---|---|---|
| (0,0) | (6,6) | (0,0) ✓ |
| (+3,0) | **(3**,6) | (−3,0) ← 符号反 |
| (0,−4) | (6,**10**) | (0,+4) ← 符号反 |

**正确约定是 `shift = SEARCH − peak`，我写的是 `peak − (PATCH/2 + SEARCH − 0.5)` ——
符号反了，原点也错了（29.5 应为 6）。** 修正后合成测试全部还原正确。

**这个合成测试已接入 `methodology_check.py` 的第 5 项**，与 box filter、连通域、TOML 转义器并列 ——
**这是它不会再悄悄退化的唯一原因。**

#### 这一格的净收获

- **NISAR GOFF 的可得性被否掉**（需要登录，响应不可靠）—— 省得后面再试。
- **Sentinel-1 振幅偏移的底噪被实测**：1.3–2.7 m，且被整体配准差支配 —— 对 4.8 m 的前兆不够用。
- **一条可复用的判据**：位移场的**空间形状**能区分整体配准差与局地位移，
  只看量级区分不了（1.80 倍的"信号"其实是配准差）。

新增 `scripts/sar_offset_check.py`（互相关、亚像元精化、合成自检、底噪对与事件对并列）。

### 2026-09-17 · 主线 #198 与**测量同时性**：我把三个钟当成一个，而且其中一处的方向反而**加强**了结论

提问方问「有关于测量同时性的问题，你是否考虑了」。**考虑了，但不够 —— 这一节是补齐。**

#### 主线：#198 正好是这件事

`adva` 前进到 `1bdadfc`（PR #198），新增两个实验，其中 **`adva.bounded-experiment.clock-history.v0`**
的题目就是同步性：**three affine clock comparisons / rate and offset holonomy**。它的表述可以直接搬用 ——

三个带标签的钟，有向边 A→B、B→C、C→A，每条边一个仿射映射（`rate` a 与 `offset` b）。
绕环路复合：**`R = a_CA·a_BC·a_AB`，`D = a_CA·(a_BC·b_AB + b_BC) + b_CA`**。

- **`ClockConsistent` 当且仅当 `R = 1` 且 `D = 0`**
- **`RateConsistent`：`R = 1` 但 `D ≠ 0`** —— 速率一致、偏移不一致：**每个钟走得一样快，仍然没有一致的同时性**
- **`ClockInconsistent`：`R ≠ 1`**
- **「One fixed point does not certify an identity.」** —— 在一个点上吻合，不证明两个钟恒等

该实验自己声明了物理边界：**仿射钟标签没有时空度规、也没有物理同步信号**。
（`scripts/` 未改动、claim 字段集未改动 → 本仓库 12 条不受影响。
另：**`adva-machine` 出现漂移**，远程 `52a18fe`，我本地 `6646582`，本会话第一次。）

#### 我自己的同时性审计：探空产品对**同一次上升**就带着三个钟

| 钟 | 相对 `time`（名义） | \|差\|>30 min | >60 min |
|---|---|---|---|
| **`launched`（实际施放）** | **−41.0 分钟**（中位） | **55.1%** | 4.6% |
| `arrived`（到达） | +103.4 分钟 | 96.6% | 76.3% |

**n = 1,845 次上升。** 而我此前把 `time` 当作观测时刻，与 GFS 同名时刻的帧比对 ——
**即假定三个钟恒等，从未检查另外两个。** 这正是「一个不动点不证明恒等」。

（`arrived` 是传输钟，不影响测量发生在何时；真正相关的是 `launched`。）
`launched` 还带 `sondeType`/`gateway` 差异，本轮未按来源分层。

#### 这个位移值多少：用两个相邻帧的温度倾向量它的界

帧 00Z 与 01Z 之间，六个高原站的 850 hPa 温度倾向与 41 分钟的位移：

| 站 | 00Z | 01Z | 倾向 K/h | 41 min 位移 |
|---|---|---|---|---|
| 55299（4508 m） | 22.5 | 23.0 | +0.50 | +0.34 |
| 55591 拉萨 | 23.0 | 23.0 | 0.00 | 0.00 |
| 56146 | 21.0 | 21.0 | 0.00 | 0.00 |
| 52836（3190 m） | 20.0 | 21.5 | +1.50 | **+1.02** |

**中位 0.34 K，最大 1.02 K。**

#### 于是两条结论的命运不同

**（一）θe 那一格不受影响。** 55299 的超出量是 **+16.67 K**（发布 357.00 对实测地面 θe 340.33），
时钟不确定性 0.3–1.0 K **小一个量级**。

**（二）露点那条反而被加强 —— 这是本轮最值得记的一点。**
观测实际发生在名义时刻**之前**约 41 分钟，而这些时刻的温度倾向是**正**的（升温、增湿）。
所以「模式(名义) − 观测(更早)」被时钟误差推向**正值**。
而我测到的是 **−1.40 K（负）**。**去掉这个正向偏移，真实的偏干只会更强。**
**时钟问题在这里不是混淆，而是反向确认：真实偏干至少 −1.40 K。**

**（三）一处我仍未分开。** `cellspread` 那个「格内代表性天花板中位 **1.00 K**」是在
**同格各站观测时刻不同**（索引 `obsTime` 跨度近一小时）的前提下算的，
所以那 1.00 K 里混着**时间**变差，而我只把它归因于地形。**本轮未把它分开**：
分离方法是把成对温差对成对时间间隔回归，或按「同分钟 vs 不同分钟」分组 —— **没做。**
这一条已列入契约的 `residuals`。

#### 可复用的规矩

**把两个来源说成「同时」，是对两个钟之间关系的一个断言，必须绕闭合环路检查，不能从一个巧合推断。**
对本仓库的具体形式：**任何 A 对 B 的比对，都要先问「A 的时间戳是哪一个钟、B 的是哪一个钟、
它们的差有多大、这个差会不会把结论推到另一边」。** 本次的收获是：**问完之后，
一条结论（θe）被证明免疫，另一条（露点偏干）被证明被低估。**

### 2026-09-17 · 同时性审计的收尾：那 1.00 K 的**时间成分只有 1%**，原数字站得住

上一节记下了一处我未分开的混淆：`cellspread` 的「格内代表性天花板中位 **1.00 K**」是在
同格各站**观测时刻不同**的前提下算的，可能混着时间变差。现在用**同一份机场索引**把它分开了。

新增 `anchor_check.py` 的 `separation` 子命令：把格内**每一对**站拿出，把成对温差对成对观测时间间隔回归，
并**带上成对海拔差作第二回归项**（它是显然的竞争解释）。

**预测在跑之前声明**：若那 1.00 K 是纯地形的，时间间隔的斜率应为零。

```
格内站对 314 对
观测时间间隔：中位 3.0 分钟，90 分位 217 分钟，最大 1,062 分钟
同一分钟观测的：120 对，占 38%
|ΔT| 中位 1.00 K        仅取同分钟的 120 对：中位同样是 1.00 K

|ΔT| = 1.102 + 0.00474 · 间隔分钟 + 0.00363 · 海拔差米     (n = 314)
  中位间隔（3 分钟）处的时间项 = +0.014 K，占观测中位数的 1%
```

**结论：时间成分约 1%，可忽略；主导回归项是海拔（3.63 K/km），即原 claim 给出的地形解释。**
**我担心的那个「近一小时」是索引全局的 `obsTime` 跨度，不是格内的** —— 同格站点几乎同时观测
（中位差 3 分钟），这在物理上也合理：业务探空与地面观测都在同一批名义时次。

**仍未建立的**：同分钟的对同时也是「同天气的对」（慢变天气下），所以这个截距
**不等于**纯地形差。这一条已写进 claim 与契约。

**这一格的形状值得记下**：我标出了一个真实存在的方法论漏洞，**量了它，结论是它不影响**。
这与前面八次更正方向相反 —— 那八次是数字错了、被更正；这一次是**顾虑被否掉、数字留下**。
两者的共同点是：**都不是靠断言，而是靠测量**。

### 2026-09-17 · **顶格不是地形 —— 是 GFS 的外推**：ARCO-ERA5 在顶格那个季节给出了判决

提问方问盘上有没有夏半年资料，没有就给 CDS 账号。**盘上没有**（373 个 `.nc` 全是 2024-01；
另外那些是语言模型的代码与权重）。**但账号也不需要** —— 找到一条匿名可读、而且更好的路：

| **ARCO-ERA5**（Google 公共桶，Zarr） | |
|---|---|
| 变量 | **273 个**，`[时间, 37 层, 721, 1440]` 逐小时 |
| 覆盖 | 1940-01-01 起；正式 ERA5 到 **2026-06-30**，**ERA5T 到 2026-09-11** |
| 层 | 37 层，含 850；另有 `specific_humidity`（与 GFS 编码器读的 `spfh850` 同量） |
| 分块 | **每小时一块**，故只取所需，无批量下载；打开 3.6 s |

**2026-09-10，850 hPa 相当位温：**

| 时次 | 来源 | 方框 | p50 | p90 | max | 顶着 357 K |
|---|---|---|---|---|---|---|
| 00Z | **ERA5** | 高原 | **329.6** | 353.8 | 358.4 | **1.6%** |
| 00Z | GFS | 高原 | **366.2** | 381.4 | 394.0 | **59.1%** |
| 00Z | ERA5 | 暖池 | 340.41 | 346.2 | 352.6 | 0.0% |
| 00Z | GFS | 暖池 | 340.42 | 345.3 | 350.3 | 0.0% |
| 12Z | **ERA5** | 高原 | **331.3** | 356.4 | 366.2 | **11.5%** |
| 12Z | GFS | 高原 | **371.3** | 385.1 | 404.2 | **81.8%** |
| 12Z | ERA5 | 暖池 | 340.91 | 346.4 | 352.1 | 0.0% |
| 12Z | GFS | 暖池 | 341.15 | 345.4 | 350.7 | 0.0% |

**（一）暖池上两个再分析几乎完全一致**（340.41 对 340.42；340.91 对 341.15）—— 方法可靠，
分歧不是方法造成的。

**（二）高原上差 36–40 K。** ERA5 的高原中位**低于**它自己的暖池（330 对 340），物理顺序正确；
**GFS 的高原高于暖池**（366–371 对 340）—— 即 claim 所述的倒置。

**（三）关键控制：地形是同一个。** 两个模式在高原框上：

| | ERA5 | GFS |
|---|---|---|
| 地面气压中位 | **582.9 hPa** | **582.6 hPa** |
| `ps < 850 hPa` 的格点 | **69.1%** | **68.5%** |
| **850 hPa 埋在地下（中位）** | **267.1 hPa** | **267.4 hPa** |

**同地形、同深度、同为地面下外推，只有结果不同。**

**所以顶格不是「地形对任何模式的作用」，也不是「850 hPa 在地下」这件事本身，
而是 GFS 具体的地面下外推方案**：它在此处产生 36–40 K 的偏暖偏湿。

**（四）顺带印证了 claim 的一句判断**：我从 GFS 的 `tmp850`+`rh850` 独立算出的 θe
在高原上达 **394–404 K**，远在 357 K 之上 —— 正如 claim 所写「提高上限只会把更多外推伪值映射进值域」。

**（五）这一格把此前那条「冬季 ERA5 对九月 GFS、季节不同所以不能下结论」的悬置闭合了**：
现在两侧都是 2026 年 9 月。

新增 `scripts/era5_thetae_season.py`（ARCO 匿名读取 + NOAA GFS 同刻对照 + 地形控制）。
**未纳入仓库的字节**：ERA5 与 Sentinel-1 同属 Copernicus，只读不存。

### 2026-09-17 · 六十三年九月的分布：**顶格的频率差约 150–500 倍**（部分完成，任务仍在跑）

上一条证明了「同地形、同深度，只有 GFS 的外推给出 36–40 K 的偏暖」。**一天不是分布**，所以接着问：
在 ERA5 覆盖的年份里，高原九月 850 hPa 的 θe 有没有接近过 GFS 那些值？

#### 成本是怎么降下来的

桶里除细档外还有**粗档**：`1959-2022-6h-240x121`，**块 `[8, 13, 240, 121]` ≈ 1.2 MB**，
而细档是 `[1, 37, 721, 1440]` = **84.77 MB** —— **约七十倍**。代价是分辨率：
1.5° 网格上高原框只有 **32 格**（细档 1,225 格），够做区域分布，不够做空间型。
粗档含 13 层，**含 850**，覆盖 1959–2021。

#### 已有的结果（四个年份，跨 15 年）

| 年份 | 高原九月均值 K | 高原单格最大 K | 暖池均值 K | 落在 357 K 附近 1 K 内 |
|---|---|---|---|---|
| 1960 | 331.89 | 357.78 | 339.09 | **0.45%** |
| 1965 | 329.78 | 358.09 | 337.77 | **0.53%** |
| 1970 | 332.72 | 358.72 | 338.57 | **0.40%** |
| 1975 | 332.50 | 357.22 | 338.08 | **0.15%** |

**三条稳定的事实：**

1. **ERA5 的高原九月均值始终在 330–333 K**，与我 2026 年单日测到的 329.6 / 331.3 一致；
2. **高原均值始终低于暖池均值约 6–7 K**（330–333 对 338–339）—— **顺序正确且跨十五年稳定**，
   而 GFS 是**倒置**的（高原 366–371 高于暖池 340）；
3. **ERA5 的单格极值确实能到 357–359 K**，即**触及**了 GFS 的那个上限值 ——
   **但只有 0.15–0.53% 的格点**，而 GFS 是 **59.1% / 81.8%**。

**所以最锋利的一句话是频率差，不是均值差**：
**GFS 把高原框 59–82% 的格点放在一个 ERA5 六十余年里只有 0.15–0.53% 的格点能达到的水平上 —— 约 150–500 倍。**

#### 如实记账

- **任务仍在跑**（约 1 年/分钟），此处只是 1960/1965/1970/1975 四个采样点。全量会细化而非改变结论，
  但**「六十三年」这个说法在跑完之前不能被引用**。
- 粗档止于 2021，细档到 2026-09-11，**两者网格相差六倍** —— 这个接缝是**换仪器**，
  不只是换年份，本条**没有**建立跨接缝的可比性。
- **没有**建立 GFS 那个外推方案的内部机制（为什么它给 36–40 K）；只建立了结果与地形的分离。

新增 `scripts/era5_thetae_climatology.py`（粗档读取、按 dims 归一化轴序、逐年统计）。
**两次轴序错误都在这里**：第一次把 240 长的掩膜套到 121 长的轴上；第二次 `order` 取的是
水平维里的序号却直接用作数组轴排列，得 `transpose(0,1,0)`。改为按 `dims` 计算并加断言。

### 2026-09-17 · 六十三年跑完：**结论成立，但我上一条里的那个倍数错了**

上一节我只跑了四个采样年就写下了「频率差约 150–500 倍」。**全量六十三年的结果否掉了那个倍数。**

#### 完整结果（1959–2021，每年九月，850 hPa，粗档 1.5°）

| | min | median | max |
|---|---|---|---|
| 高原九月均值 K | 327.55 | **331.62** | 334.74 |
| 高原单格九月最大 K | 354.61 | 358.12 | **366.41** |
| 暖池九月均值 K | 335.72 | 338.64 | 340.80 |
| 高原落在 357 K 的 1 K 内 | 0.00% | **0.40%** | **4.71%** |

```
高原均值超过暖池均值的年份：            0 / 63
高原九月单格最大值 > 350 K 的年份：    63 / 63
高原九月单格最大值 > 357 K 的年份：    52 / 63
```

#### 三条成立

1. **均值差与顺序**：ERA5 高原九月均值中位 **331.6 K**，与 2026 年单日测到的 329.6 / 331.3 一致；
   **63 年里没有一年高原均值超过暖池均值**（331.6 对 338.6）—— **顺序正确且六十年不变**，
   而 GFS 是**倒置**的（高原 366.2 / 371.3 高于暖池 340）。
2. **量级**：GFS 的高原值比 ERA5 六十三年的中位**高约 35–40 K**。
3. **频率**：ERA5 落在 357 K 附近的格点比例**中位 0.40%**，而 GFS 同一天是 **59.1% / 81.8%** ——
   **中位比值约 150 倍**。

#### 一条被否掉的（我上一条说的就是这个）

**「150–500 倍」是四个采样年给的，全量后不成立。** ERA5 的该比例在六十三年的范围是
**0.00% 到 4.71%**（不是 0.15–0.53%）。因此与 GFS 的 59–82% 相比：
**中位约 150 倍，但在 ERA5 最极端的那一年只有约 12 倍。**

#### 还有一条我原话说反了

我说 ERA5 的单格极值「触及」357 K —— 全量显示它**远超**：
**ERA5 自己的单格九月最大可达 366.41 K**，落在 GFS 高原中位（366.22 K）**同一水平**，
且 **52/63 年**都超过 357 K。

**所以两个模式的差别不在「能不能达到」，而在分布的体量与位置**：
GFS 把整个高原框**压在一个 ERA5 只有百分之零点几的格点才到得了的水平上**；
而 ERA5 偶发地也能给出一个同等极端的格点。**「GFS 超出了 ERA5 能达到的范围」这句话是错的**，
正确的是**「GFS 把这个范围当成了常态」**。

#### 记账

- 粗档止于 2021，细档到 2026-09-11，**网格相差六倍**：接缝是换仪器，不只是换年份，
  本条**没有**建立跨接缝可比性。
- 1.5° 下高原框只有 **32 格**，本条的分布是**区域分布的粗样本**，不是格点分布。
- **没有**建立 GFS 那个外推方案的内部机制，只建立了结果与地形、与「在地下」这两件事的分离。

**这是本会话里第四次「快读数被全量否掉」，而且这一次两个读数都在同一天内、前者已被明确标注为
部分完成。** 标注部分完成是必要的，但**不足以让那个数字免于被引用** —— 教训是：
**部分结果里的数量级同样要标成不可引用，而不只是标注样本量。**

### 2026-09-17 · MERRA-2 作第三个意见：**三家对「地下 850 hPa」各选了一种约定**

#### 动机

ERA5 与 GFS 在同一高原框上差约 35 K，而地形一致（ps 中位 582.9 对 582.6 hPa）。
剩下要分的是：这个钳位是 GFS 特有的缺陷，还是**任何再分析在被问及
「地面在 580 hPa 的高原上的 850 hPa」时都会做的事**。MERRA-2 是独立的同化系统，
可以分开这两者。

#### 判据（写在跑之前）

```
高原均值 325–340 K  → 与 ERA5 一致，钳位是 GFS 特有
高原均值 350–375 K  → 也钳，是「向高地形的 850 hPa 要值」的通病
两者之间            → 不确定，不往故事上凑
```

**实际出现了第四种结果，判据里没有这个出口。**

#### 结果（MERRA-2 M2T1NXSLV，2020-09-15，24 时次）

```
高原框 (80-92E, 26-32N)
  T850 屏蔽 65.14%      PS 屏蔽 0.00%
  PS 中位 579.7 hPa     PS<850 hPa 占 67.9%
  屏蔽位置与「PS<850」吻合 97.3%   ← 屏蔽就是地下，不是数据空洞
  有效子集 34.86%
  有效子集 θe 850:  均值 353.81 K  中位 354.25 K  最大 363.81 K

暖池框 (120-180E, 15S-15N)  ← 能失败的对照
  T850 屏蔽 0.07%       PS 中位 1009.8 hPa   PS<850 占 0.3%
  吻合 99.8%
  有效子集 θe 850:  均值 338.63 K  中位 340.02 K
```

**对照通过**：暖池上 MERRA-2 的 338.63 K 与 ERA5 六十三年的中位 338.64 K 吻合到 0.01 K，
与 GFS 的约 340 K 差 1.4 K。**三者在暖池一致，所以高原上的分歧是真分歧，不是读法问题。**

**地形交叉验证**：MERRA-2 579.7 / ERA5 582.6 / GFS 582.9 hPa —— 三套系统地形差在 3 hPa 内。

#### 结论：三种做法，不是两种

| | 高原 850 hPa θe | 对该量的做法 |
|---|---|---|
| ERA5 | ~331.6 K（63 年九月中位） | 给值，贴着地面 |
| GFS / xue | 366.2–371.3 K | 给值，按递减率外推 |
| MERRA-2 | **65.1% 屏蔽** | **拒绝作答** |

所以钳位**既不是 GFS 特有的缺陷，也不是各家的通病** —— 而是三家**对一个观测上
没有定义的问题各自选定的约定**。原结论因此更清楚而不是被推翻：
xue 把地下外推值当作实测发布；而 MERRA-2 示范了正确做法是**不给这个数**。

#### 一处必须自己踩住的不可比性

MERRA-2 有效子集的 353.81 K **不能**与 ERA5 的 331.62 K 并列 ——
**前者是对「850 hPa 在地面之上」的那 34.86% 格点求的，后者是对整个框求的。**
三者的「高原均值」平均的不是同一批格点，这个量在系统之间**根本不可直接比较**。
并排放进一张表会显示成「MERRA-2 居中」，那是假象。

#### 两处自我更正

**一、判据的出口要穷举。** 我写了两个出口（近 ERA5 / 近 GFS），
现实给出第三个（拒绝作答）。判据写在跑之前是对的，但**出口不穷举时，
人会本能地把新结果往已有的两个里塞**。

**二、填充值只用来判断、没有用来屏蔽。** 暖池均值一度算出 `4.65e8 K`，
而同一批数的中位数是合理的 `340.02 K`。

> **荒谬的均值 + 合理的中位数，是「掩码没有生效」的签名。**
> 中位数对少量离群稳健，所以它会掩盖问题而不是暴露它；
> 这个组合本身就该触发告警。

（另：本步还错了两处小的 —— `Content-Range` 取 `$2` 取到了字面量 `bytes` 而非总长；
MERRA-2 压面比湿叫 `Q850` 不是 `QV850`，`QV` 前缀只给 2m/10m。守卫拒绝继续而非硬凑，
所以两处都只是耗时，没有污染结果。GES DISC 每连接限速约 45 KB/s，
单连接取 408 MB 需 2.5 小时，16 路分块并行 9 分 34 秒。）

### 2026-09-17 · ITS_LIVE：拿到了缺的那个**分母**，但没有前兆加速

#### 为什么做这一步

早先的 SAR 偏移测量得到事件对中位 2.74 m，却**无法判定它是不是前兆** ——
因为整窗中位数等于近崩解区中位数，只能判为整体配准偏移，且**没有参照分布**：
不知道那条冰川「正常」动多快。ITS_LIVE 正是这个分母。

#### 取数

公开 S3（`s3://its-live-data`，**匿名，不需要 Earthdata 凭据**），Zarr 立方体，
分块 `[20000,10,10]`，故**懒读**即可，未整块下载。

```
立方体  datacubes/v2-updated-october2024/N20E080/...EPSG32645_G0120_X350000_Y3150000.zarr
朗唐    28.2853N 85.5252E → UTM45N X=355369 Y=3129689 → 列 461 / 行 585（偏移 4 m / 22 m）
跨度    1987-12-29 .. 2025-05-20     127,000 个影像对
邻域    41×41 中冰川像元 564 个（33.6%）
```

#### 结果一：分母有了

```
每像元 11 年基线：中位 9.0 m/yr   P25 7.0   P75 15.0
```

#### 结果二：**没有加速**

固定像元集（564 个冰川像元，2014–2024 每年 ≥20 观测），逐像元相对自身基线：

```
2014 1.00  2015 1.14  2016 1.00  2017 1.17  2018 1.14  2019 1.17
2020 1.00  2021 0.73  2022 0.69  2023 0.67  2024 0.89
```

**2021–2023 反而降到基线的 0.67–0.73，2024 部分回升。** 没有加速。
对照：三个季节窗口（全部 / 仅 9–11 月 / 仅 1–3 月）给出一致形态，
故不是季节构成造成的。

#### 结果三：但传感器构成确实在变，且必须单独检验

```
2014 L-L 100% 含Sentinel  0%
2018 L-L  56% 含Sentinel 44%
2021 L-L  10% 含Sentinel 90%   ← Sentinel 成为主导
```

同一年内两种传感器的流速中位（同批像元）：

```
年     L-L中位  S-S中位  S/L比   L-L样本    S-S样本
2014     9.0    72.0    8.00    319,969      4,582
2017    10.0    35.0    3.50    368,511     63,010
2021     7.0     7.0    1.00    188,352    733,358
2023     8.0     6.0    0.75    583,238  1,152,718
```

早年 S/L 高达 8 倍，但 S-S 样本极小（2014 年仅 4,582 对 32 万），是选择性小样本，
**不可作为尺度结论**；2021 年后两者样本都大，S/L 收敛到 0.75–1.12，即 ±25% 以内。

**只看 Landsat（单一传感器，贯穿全部年份）**：
`9,10,9,10,11,8,8,7,7,8,8` —— 同样从 10–11 降到 7–8。
所以那个变慢**不只是**传感器构成造成的。

#### 边界（三条，都很硬）

1. **盲窗 15 个月**：数据止于 2025-05-20，崩解在 2026-08-26。
   本条**只能说明前兆不早于 2025 年年中**，**不能**排除 2025-06 之后的加速。
2. **仪器在结构上可能是盲的**：ITS_LIVE 由光学影像特征追踪测**冰面流速**。
   岩冰崩解的前兆可能位于**岩体**（蠕动、裂隙扩展），**该仪器不测这个**。
   即便数据完整，也可能看不见。
3. **传感器系统偏差未消除**：2021 年前后传感器构成剧变，S/L 在近年仍有 ±25% 量级差异。
   跨传感器的绝对量级比较不可靠。

#### 本次的自我更正（四处）

1. **块命名是中心不是角点。** 我按左下角推算，选错了立方体；
   实测覆盖范围 `x 300052..400012`，中心 350032 ≈ 命名值 350000，**命名是中心**。
2. **汇总到了非冰川像元。** 崩解点坐标处 `landice=0`（是岩体），
   我却对那个像元做了逐年统计并据此报告「37 年记录」。
3. **「所有像元×所有影像对一起取中位」不是物理量。** 它随「当年用了哪些影像对」而变；
   观测数在 2020–2022 之间变化 8 倍。改为逐像元基线 + 相对异常后才可信。
4. **把时间当数值转**（`mid_date` 是 datetime64）导致溢出，一度中断。

#### 未做

- ITS_LIVE 桶里还有 `height_change/` 与 `mass_change/`。
  **对 Chamoli 型失稳，减薄（去支撑）比流速更贴机理**，这一步没做。
- RGI/GLIMS 冰川边界未取。

### 2026-09-17 · 想取「本底季节基线」，结果发现它与采样设计不可分离

#### 动机（方法论上的，来自一次纠正）

得到 `OBSERVED HERE` 与 `RECORDED` 的区分：**论文交给我们的是可以对照的外部数字，
不是可以采信的结论。** Sah (2026, EarthArXiv, DOI 10.31223/X59N5N) 对本次事件
在 **Sentinel-1 振幅记录**里做了前兆检验，结论为「无可检测前兆」，
并给出检测限 **约 1 dB / 两个月**；它否掉自己表观趋势的手法，是**从数据里建一条
同轨道十年季节基线**（2026 落在 2017–2025 中位的 0.3 dB 内）。

**该基线是他从数据里取的，不是从论文里取的。** 所以这一步做的是同一件事：
从我们自己的数据里取本底变率。没有它，「异常」没有定义。

#### 数据与做法

ITS_LIVE 朗唐（Zarr 懒读），127,000 个影像对，564 个冰川像元（邻域 41×41）。
逐像元除以自身 2010–2024 基线，得到相对异常，再按月统计。

#### 结果：季节循环取决于你选哪些影像对

```
全影像对   峰 3 月 1.83   谷 6 月 0.67   振幅 1.167
仅短对(dt<=60)  峰 10 月 1.28  谷 12 月 0.89  振幅 0.388
```

固定像元集（每月 >=10 个短对观测的像元，564 个全部满足）下结论不变。

原因：`date_dt` 中位 **264 天**（P5 24 / P95 512）。**一个跨 264 天的影像对测的是
近一年的平均流速，其 `mid_date` 落在几月并不代表那个季节。** 而短对只占 13.1%
且分布极不均匀（6–8 月仅 3–7%，12 月 14%）。

> **在这份数据里，季节信号与采样设计不可分离。**
> 要的本底季节基线取不出来 —— 不是数据量不足，是这个估计量被 pair 选择绑架了。

#### 一处自我更正：**我报了一次假警报**

我一度判定「564/564 通过」在算术上不可能而停下核查，理由是
「需要 564×12×10=67,680 个观测，但短对只有 14,780 个」。

**错在我的算术**：一个影像对给出的是整幅 41×41 的流速场，
不是只给出一个像元的值。供给远大于我所算。实测每像元每月 49–553 个，
判定逻辑正确。

**这是本会话第一次把正确结果误判为 bug** —— 之前的错都是采信了错的。
方向相反，成因相同：**没有把量纲和基数想清楚就下判断。**

### 2026-09-17 · 滑动团块的前提：采集器，以及 xue 目录的真实结构

#### 架构（用户口述，记录如下）

预报不是「训练一个模型再一次预测」，而是**维护一个向前滑动的时空团块**：
团块内装着已核实的状态与关系，新数据持续进入，在每个时空点上做
**预测 vs 实况**的对比，团块向前推一格，重复。**技巧是在滑动中持续量出来的。**

因此有一条硬前提：**上游不留档，团块无法事后补建。**
实测目录时间范围即为证据：`cma` 当时只有 **2.4 小时**，
而 `gfs` 的自述是 **"Four cycles a day; only the newest is kept"**。

#### xue 目录的真实结构（此前只记录了 5 个产品族，实为 16 个源）

```
预报侧  gfs · ecmwf · aifs · sflux · hrrr · tc
实况侧  cma · mrms · jma · himawari · goeseast · goeswest · meteosat · sounding · airport
外加    showcase
```

`catalog.json` 是 **STAC 1.1.0**；每个 collection 带 `item.json` 与一个
**`xue:pointer` → `latest.json`**，即此前记录的「可变指针 → 不可变 CRC 目录」。
条目 id 形如 `cma.2026091722.0040`（collection.运行.帧）。

#### 关键发现：Zarr 存储不能当文件取

`item.json` 声明 `cref.zarr` 且给出 `file:size = 915661`，
但对 `<path>.zarr` 直接 GET/HEAD **均 404**。原因不是文件被删，而是
**它本就是存储**：`file:size` 是这个**存储的总字节数**，按单文件的形式声明。

分块键名格式（穷举试出，非文档所得）：

```
<节点>/c/<索引…>        cref/c/0/0/0 → 200
                        cref/c0/0/0 · c0/0/0 · 0/0/0 · c/0/0 → 全部 404
```

`c` 是**独立的路径段**。

存储结构（Zarr v3 + 合并元数据，`zarr.json` 一次 GET 拿全）：

```
cref  shape[25,1024,1792] uint8  chunk[30,1024,1792]   ← 外层只有一块
      codecs: sharding_indexed → shard[6,64,64] → bytes → zstd(15, checksum)
      fill_value 255
```

取全 9 个键后与声明值核对：**完全一致**（root zarr.json + 4 个数组各自
的 zarr.json + 4 个分块 = 声明的 byteLength）。

#### 一处自我更正

核对的差值一度恒为 2.8 kB。**不是网络问题，是我用
`len(json.dumps(obj).encode())` 计数 —— 重新序列化的长度不等于原始字节数。**
改用原始字节后完全对上。

另外，我先前说「cma cref 只有 0.92 MB，够小可全取」，那个数是从
`file:size` **读来的声明值**，我的探测脚本在 `file:size` 存在时不会去 HEAD，
**从未验证过它取得到**。这与更早记录的「声明了 `nodataCode 255` 却从未写过」
是同一模式：**采信声明而未实测。**

#### 上游不一致（两处，均记录不掩饰）

- `meteosat`：目录 advertise 了 `meteosat/collection.json`，实际 **404**。
- `showcase`：`manifest` 与 `cref-poster` 均 **404**。

#### 产物

`scripts/xue_collect.py` —— 按策略采集（默认只取 manifest/index/poster
及小而完整的存储），append-only 索引，逐 collection 落盘，
不可达与跳过分别记录且**分开标注原因**（策略性跳过 vs 出错/超限）。
原因：全盘收是 ~2 GB/小时的量级（`dustrgb` 单幅 416–496 MB × 四颗卫星），
那不是采集而是消防水带。

### 2026-09-17/18 · 配对引擎：团块第一次真正打出分

#### 与采集器的分工（这是它能便宜的原因）

```
xue_collect.py  每轮归档【索引与元数据】—— 便宜，且是不能事后补的那部分
block_pair.py   只在被要求评分时才【按需懒取数值】—— 每点昂贵，绝不预先取
```

**索引完整的团块，任何时候都能评分**；数值没取过的团块，
只要上游存储还在，事后仍能补评。**这就是「先归档索引」的全部理由。**

#### 分工的第二层：时效是产物，不是误差

一次运行在 T 发出，帧落在 T+h。用第 h 帧对上 T+h 时刻的实况，
得到的误差归因于**时效 h**。所以一切都按 **(模式, 变量, 时效)** 累积 ——
把误差在时效上平均掉，得到的数没有人能用。

#### 第一次打分（GFS tmp2m vs 5447 个机场站）

块内重叠 1922 对，覆盖 0–7 小时：

```
时效h     n     模式-实况中位    MAE     sd
  0      48       -1.00       2.75    8.17
  1      24       -0.50       1.85    2.28
  3      71       -1.00       2.31    3.26
  5      66       -1.50       2.43    2.93
  7    4770       -0.50       1.62    2.14
```

h=7 的中位 −0.50 K / sd 2.14 与本会话早先**完全独立路径**测到的
−0.10 K / sd 2.17 一致。

#### 第一次打分前，出现了一个 −71 K 的「结果」

首次跑出的是各时效**一律 −71 K**、sd 仅 3.5–4.5。**这不是偏差，是解码错误。**

```
zarr.json 声明 quantization: {offset: -60.0, scale: 0.5, nodataCode: 255}
xr.open_zarr 之后的 .encoding: {scale_factor: 0.5, add_offset: -60.0}
```

**xarray 已经把量化解好了，脚本又套了一遍**，于是 `-60 + 0.5×(已是摄氏度)`。

> **与本会话早先那个 GRIB 错误是同一类**：GDAL 返回的 GRIB 气温**已经是摄氏度**，
> 脚本又减了 273.15，把整个结果反过来。
>
> **两次都是：读取器已经解码，而我把文档里的变换又套了一遍。**
> 判据是 `.encoding` / `GRIB_UNIT` —— **在变换之前先问读取器做没做**。

#### 未做

- 只在**最近邻格点**取样，不做插值：插值会把「山谷测站 vs 山脊格点」这类
  代表性误差抹平，而那正是本研究发现最多的东西。格点偏移已随记录保留。
- 只跑了 `gfs × airport × tmp2m` 一个组合。团块里的其它 36 个变量、
  ecmwf/aifs/hrrr 三个模式、sounding/mrms/jma/cma 四个实况源都还没配。

### 2026-09-18 · 可视化：绑定修正 + 团块页面

#### 绑定

`npm run dev -- --host localhost` 在 macOS 上只解析到 `::1`，于是
**`127.0.0.1:5199` 连不上**（`localhost` 与 `[::1]` 正常）。改为 `--host ::`
后三种写法全部可达，监听 `*:5199`。

**代价要说明**：`--host ::` 绑的是所有网卡，同一局域网内可访问。
本机自用无妨，共享网络需留意。

#### 团块页面

```
http://localhost:5199/block.html     或   http://127.0.0.1:5199/block.html
```

由 `scripts/block_page.py` 生成 `block.json` + `block.html` 写入
Vite 的 `publicDir`（`web/public`），**因此与主页面同源同端口，无第二个服务、无 CORS**。

**为什么不喂给现有播放器**：上游是 STAC 树
（`catalog.json` → `<coll>/collection.json` → 带 asset href 的 item），
而本归档是 `<coll>/<item id>/<asset>`，且 Zarr 键被扁平化为 `__`。
两者形状不同，硬接会得到一个「静默什么都不显示」的页面。

页面渲染的是**快照**并明说生成时间 —— 一个看起来实时却在显示陈旧数字的监控页，
比一个诚实标注为静态的更糟。

#### 一处自我更正：**我的验证本身是假的**

首次验证时 `block.html` 与 `block.json` 都返回 `HTTP 200` 且**同为 57912 B**，
我据此判为通过。实际两者都是 Vite 的 SPA 回退页（`<title>Xue · ...`），
**我写的页面根本没被提供** —— 服务启动早于文件写入，publicDir 索引已缓存。

> **两侧返回完全相同的字节数，就是「这个检查不会失败」的签名。**
> 修正为按**唯一内容标记**验证（`团块 · block` vs 主页的 `Xue ·`），
> 并重启服务后才真正通过。

这是本会话第三次「检查本身不成立」：前两次是判据出口未穷举、
以及把「需求 67680 > 供给 16590」算错而误报 bug。

### 2026-09-18 · 学习阶段的关键一步：**先算上限，再谈特征**

#### 为什么先算这个

本会话实测了三个探测器，全部无可用技巧：

```
正积温（PDD）      91% 的时间都触发 —— 饱和，无分辨力
雨-冰液态水阈值     阈值 50 → 100% 命中 / 95% 误报；阈值 275 → 0 命中
ITS_LIVE 流速      已核实崩解点 2021–2023 相对自身基线 0.67–0.73，是【变慢】
```

本能反应是「去找更好的特征」。**这个反应是错的**，本条用算术而非意见说明理由。

#### 上限是基率的性质，不含物理

**完美排序**下（所有真事件都排在前面），标出总体比例 a：

```
精确率 = p / a        召回率 = 1        p = 基率
```

**大气物理不进入这一行。它只是计数的性质。**

单位取**站年**（一条冰川在一年，即季节性预警真正作用的对象）。
朗唐邻域实测：N = 564 像元 × 11 年 = **6,204 站年**，已核实事件 E = 1
（2026-08-26 Langtang Lirung，28.2853N 85.5252E）。**p = 1.61e-4（约 1/6,204）**。

```
报警率      完美排序下的精确率上限
  50%            0.03%
  10%            0.16%
   1%            1.61%
1/1,000         16.12%
1/10,000       100.00%
```

**要让一半报警是真的，报警率必须 ≤ 2p = 3.22e-4，即 1/3,102 的站年。**

实测探测器与基率之比：正积温的 91% 是基率的 **5,646 倍**，
雨-冰阈值 50 的 95% 是 **5,894 倍**。放进上限：**0.018% 与 0.017%**。

> **误报不是特征的毛病，是报警率与基率不匹配的算术后果。**
> 「换一个更好的特征」不会修好它；要修的是报警率，
> 或者把总体限制到已知不稳定的那部分站点上。

#### 一个看起来像 bug 的恒等式，已显式说明

「最多标出 2 个站年」在朗唐、喜马拉雅、全球三个尺度上**完全相同**。
原因是 `2p·N = 2E/N·N = 2E`，**与 N 无关**；E = 1 时恒为 2。
**随总体扩大而收紧的是「率」，不是「个数」**（3.2e-4 → 1.8e-6 → 9.1e-7）。
脚本输出里已写明，以免被误读为缺陷。

#### 它的用处：把问题转形

本条对**总体如何定义高度敏感**，而这正是它最有用之处 ——
它把「如何提高技巧」的问题转成「**如何缩小总体**」的问题。
若把候选限制到 ITS_LIVE 里已显示异常、或已有冰湖接触的冰川，p 上升几个数量级，
同一条算术立刻宽松。

#### 未做

- 事件的「非事件集」仍未建立。目前**只有 1 个**有坐标、日期与来源的已核实事件，
  因此 p 的估计极不稳（增减一个事件即翻倍）。这是学习阶段剩下的真正缺口，
  且它不能靠再分析数据补上 —— **需要事件来源**（自测、或公开清单）。

### 2026-09-18 · 修正一条我自己上一轮写错的 claim：**像元不是站点**

#### 错误

上一轮加入的 `xue.derived.discrimination-ceiling.v0` 里，我写了
「单位是**站年**（一条冰川在一年）」，却用 **564 像元 × 11 年 = 6,204** 作 N。
**同一冰川上的相邻像元不是独立站点。**

那个 564 落在朗唐 41×41（约 **4.9 km 见方**）的邻域里，显然不可能装下 564 条独立冰川。

#### 实测（scipy.ndimage.label）

```
564 个冰川像元的连通域：
  4-邻接 → 4 个 (400 / 96 / 64 / 4)
  8-邻接 → 3 个 (404 / 96 / 64)
  最大一个占 70.9% 的冰川像元
→ 独立对象的站年数 33–44，不是 6,204
```

#### 影响：基率被低估约 140 倍

```
原:  p = 1/6,204 = 1.61e-4     报警率 91% → 上限 0.018%
正:  p = 1/33–44 ≈ 2.3e-2      报警率 91% → 上限 2.5%
```

**结论方向不变，强度大减。** 误报仍主要由报警率与基率的比值决定，
但在 33–44 这个尺度上，「91% 的报警率」并不像原先说的那样荒谬。

#### 但修正后的数也不该采信

**两端都不是可辩护的「总体」**：3–4 个连通体只是 4.9 km 见方的一隅，
而像元根本不是独立单位。**要定出站年数，必须先用冰川边界（RGI/GLIMS）
定义「一条冰川」** —— 那个数据本会话至今未取到。

所以本条现在的正确状态是：**代数成立，数量级不成立**。
`precision = p / a` 不依赖任何测量；填进去的 N 依赖一个我们还没有的东西。

#### 两次被闸门拦下（都拦对了）

1. 首次修正时 `re.sub` **解释了替换串里的转义**，把转义好的 `\n` 变回真换行 →
   校验拒绝写入（`Illegal character '\n'`）。改用 lambda 后通过。
2. 我自己加的断言 `'\n' not in 块` **本身写错了** —— claim 块本来每个字段一行，
   含换行是正常的。真正有效的校验是 TOML 能否解析，那条已经过了。
   **删掉自造的错误断言，保留解析校验。**

#### 顺带记录：又一个主机阶段性不通

`zenodo.org` 本轮**整个不可达**（含根路径 000），而同期
`eartharxiv.org`、`dataset.ringsaturn.me`、`api.github.com` 均 200。
本会话已见的第四个：harmony.earthdata.nasa.gov、eos.org（Cloudflare 403）、
archive.org、zenodo.org。**外部事件清单这条来源此刻取不到。**

### 2026-09-18 · 转向：**事件 = 带不确定度的观测进入系统**

#### 为什么学习阶段卡住，以及为什么那是个错的要求

卡住的是一件事：带标注的事件集。建一份冰川垮塌编年史需要外部清单，
而本会话试过的清单全都取不到（zenodo.org 整个不可达、Durham 403、
NASA COOLR 主机消失）。

**但那是错的要求。事件不是灾难编年史里的一行 —— 事件是一条观测，
带着它的不确定度，进入系统。** 团块本来就在摄入观测流，
**那条流就是事件流**。不需要任何外部东西。

这不是绕路。团块设计本来就意味着这件事：它在覆盖的每个点上比对预测与观测。

#### 由此强制的纪律：误差是必填，且必须具名来源

```
每条记录必须带 uncertainty，且带 uncertainty 的来源。
没有误差棒的观测不能进入 —— 与它的比对只能被【断言】，不能被【计分】。
```

本会话在这件事上一直含糊，而且是重复地含糊：报出
「GFS tmp2m 对 5,354 个测站：中位 −0.10 K、sd 2.17」，
然后把它当成关于**模式**的事实 —— 而它其实是关于
**模式 + 代表性误差 + 仪器**的事实。把不确定度设为必填并强制具名来源，
就是为了让这个区分被写下来而不是留在隐含处。

#### 三类不确定度，严格分开

```
declared          来自规格（仪器标称精度）
computed          从记录本身导出（比例的二项误差）
observed-scatter  跨比对测出的散布 —— 【受污染】：混了仪器、代表性与模式误差，
                  因此永远不得当作观测自身的误差引用
```

只有前两类是观测的误差。第三类照报，因为它有用，**但必须标注，因为它不是同一回事**。

#### 我在这一步捏造了一个数，且自己抓了出来

初版脚本用的 SAR 密度是 **0.300 / n=5123**。**两处都错**：

- `0.300` 是 EarthArXiv 那篇里的数（500 m 半径、6 dB 阈值）—— 与我们的量**不同**，
  且是 **RECORDED 而非这里观测到的**
- `n=5123` 是**我编的**。500 m 圆盘在 10 m 像元下是 π×500²/100 = **7,854 个**，不是 5,123

**它既不是 declared、也不是 computed、也不是 observed-scatter —— 是第三个类别：捏造。**
而这正是「带误差的观测真值」这条要求要杜绝的东西。

改用**本仓库自己的三轨道测量**：`0.1250 / 0.1231 / 0.1305`（跨度 0.73 点），
均值 **0.1262**；`n = 31,415` 由 0–2 km 圆盘与 20 m 像元**导出**（并如此标注，
不冒充计数所得）；二项误差 **±0.0019，即 1.5% 相对误差**。
论文的 0.300 保留在 provenance 里并显式标为**另一个量、RECORDED**。

#### 产出

`scripts/event_ingest.py` → `docs/event-stream.jsonl`

```
事件 32,222 条，不合格 0 条
  airport.t        10,896      declared ±0.5 K   (WMO/CIMO)
  airport.td       10,884      declared ±0.5 K   (WMO/CIMO)
  airport.qnh      10,441      declared ±0.1 hPa (WMO/CIMO)
  sar.vv.change-density.source-region  1   computed ±0.0019 (二项)
不确定度类别: declared 32,221 / computed 1
```

**`observed-scatter` 刻意不出现在事件流里** —— 它混了模式与代表性误差。
它记录在脚本的 `OBSERVED_SCATTER` 表中（`gfs.tmp2m.vs.airport.t: sd 2.14 K`），
标注为受污染。

#### 边界

- `declared` 用的是 **WMO/CIMO 规格值，不是本仓库的测量**。
  真实的地面气温误差还含辐射屏蔽、通风、安装等成分，规格值只是标称。
- `n = 31,415` 是**导出值**，不是从掩膜数出来的；若实际分析用的像元集不同，
  误差应重算。
- 事件流目前只有两个来源（airport、SAR）。sounding、radar、cma、mrms 尚未接入，
  它们各自也带可计算或可声明的误差。

### 2026-09-18 · 把不确定度接进评分：**判决取决于误差标准，而非数据**

#### 为什么要做

本会话多次报出偏差与散布，然后就当作技巧问题已经定了。**并没有。**
「预报是否与观测一致」完全取决于把什么算作误差，而这个标准通常是隐含的。

同一次比对（GFS `tmp2m` 对机场站气温，观测自身误差按 WMO/CIMO 取 **0.5 K**）：

```
时效    n     中位偏差   散布sd   |d|<2σ观测   |d|<2σ观测+代表
  0    59     -1.20    7.68      22.0%         98.3%
  1    23     -0.50    2.26      34.8%         95.7%
  3    70     -1.00    3.31      24.3%         92.9%
  5    65     -1.50    2.96      23.1%         89.2%
  7  4196     -0.30    2.13      36.2%         94.5%
```

**36.2% 还是 94.5% —— 同一个模式、同一个观测。**
两个判决都不是关于模式的事实，都是关于**选择**的事实。

#### 我的脚本先说了一句假话，已改

初版脚本印出「散布随时效增长：sd 7.68 → 2.13（增 −5.55 K）」——
**「增 −5.55」是自相矛盾的**，且真实情况是**不单调**：最小时效的 sd 反而最大。

原因清楚：各时效样本数 **23 到 4196**，相差 180 倍；小样本的 sd 几乎必由少数离群站主导。

修正后脚本明确输出：**「时效依赖：未建立」**，并说明要先按时效平衡样本才能做这条。
**该条在本文档中不作为结论。** 未做离群剔除，也不据此下任何判断。

#### 三类误差标准，再次分开

```
declared            仪器标称精度（观测自身的误差）—— 0.5 K
representativeness  网格 0.25°(约 28 km) 对站点是一个点；本证据下它是主导项
observed scatter    跨全部配对测出的 2.14 K —— 含仪器+代表性+模式，
                    因此永远不能当作其中任何一项的误差引用
```

#### 未做

- 「代表误差」一列是 `sd` 减去观测误差后的残差，**混了代表性与模式误差**，
  不可单独归因。要分开需要**同一格点内多个测站**的对照，本步未做。
- 时效平衡后的技巧曲线未做（受块内观测覆盖所限，目前 0–7 小时）。

### 2026-09-18 · 尝试把团块的场画出来：**未成功，且我不交出错的图**

#### 做了什么

团块页面此前只报清单（多少条、多少字节、什么时间窗），那只能回答
「采集器活着吗」。团块的意义在**数据**，所以试着把归档的场渲染成图。

poster 不是图像，是 **zlib 压缩的量化码平面**（魔数 `78 da`，
解压后恰为 `W×H` 字节，1 像元 1 字节）。xue 自己的解码路径是：

```
value = offset + code * scale        (code == nodataCode 或 > maximumCode → 透明)
color = interpolate(STOPS, value)
```

量化取自 bundle 的 **manifest**（首版我从 item 的 asset 元数据里找，找不到，
于是**静默退回中性灰** —— 连 nodata 都没屏蔽）。色标取自
`web/src/palettes.ts` 的 `TEMPERATURE_STOPS`，**照抄，不自编**。

#### 结果：渲染出来的不是场

55 张 PNG 全部生成有效（IHDR 正确），但图像是**紫白横条纹**，
温度色标里本该出现的黄橙色完全缺席。原始字节直接画灰度**也是同样的条纹**，
所以问题不在调色、不在布局。

诊断：

```
行内相邻相关 +0.500   列内相邻相关 +0.191
行均值标准差 40.58    列均值标准差  7.05    ← 行与行之间剧烈跳变
布局与元数据一致（720×361, 0.5°, row-major, north-to-south）
```

**结论：我对 poster 数据语义的假设是错的。** 它可能在时间维上有折叠、
可能是另一种平面编码、或压根不是「一帧空间场」。**本条未查明。**

#### 处置

**未经验证的渲染全部删除**，页面不显示它。
一张错的图比没有图更糟 —— 尤其在这个仓库里，
它会被当成「团块里的场长这样」而被引用。

正确路径不是继续猜，而是**读 xue 自己的 `web/src/poster.ts` 全文**，
看平面到像素的映射到底怎么做的（那里面的调用方 `main.ts:5601`
明确说 poster 是「paint the variable's tiny first-frame poster」——
**first-frame** 这个词提示 poster 可能是多帧的）。下一轮从这里入手。

### 2026-09-18 · 团块的场画出来了：缺的是**垂直差分反滤波**

#### 病因（上一轮未查明的那一步）

`web/src/poster.ts` 的注释写着 "Inflate and **unfilter** one poster payload"，
而它的循环是：

```js
for (let row = 1; row < height; row += 1) {
  plane[current + column] = (plane[current+column] + plane[previous+column]) & 0xff;
}
```

**poster 是垂直差分编码的：每一行存的是与上一行之差（模 256）。**

**我上一轮一直在看差分，不是值。** 所以那片紫白横条纹不是调色错、不是布局反 ——
是**画的量根本不对**。这与 PNG 的 Up 滤波是同一个东西，我漏了反滤波。

行统计正是这个错的签名：

```
漏掉反滤波：行内相关 +0.500  列内相关 +0.191  行均值标准差 40.58（列仅 7.05）
```

差分行之间跳变剧烈是**应该的**；真实场不该如此。**当时我也看到了这组数，却没有从
「行间跳变异常」推到「我读错了量」**，而是先去查了布局和调色。

#### 完整解码链（现已验证）

```
zlib 解压
  → 【垂直差分反滤波】cumsum(axis=0) % 256
  → 量化解码 value = offset + code × scale   (code == nodataCode 或 > maximumCode → 透明)
  → xue 自己的色标（web/src/palettes.ts 的 TEMPERATURE_STOPS，照抄）
  → 最小 PNG 编码器（无图像库依赖）
```

结果**对得上物理**：大陆轮廓清晰，南极与北极冷（蓝），撒哈拉与阿拉伯热（深红），
**青藏高原与安第斯在温度场上显出冷脊**。

#### 产物

```
scripts/poster_render.py     55 张 PNG，14 张用温度色标
/blockimg/*.png              与主页面同源同端口
/block-posters.json          图集索引（含色标来源、是否取到量化）
block.html                   新增「团块里归档的场」区块
```

页面明说：poster 是**降低后的网格**（GFS 0.5°，而 stores 是 0.25°），
故这是 poster 的视图，不是全分辨率产物；并写明解码链与「差分那一步漏掉会画出横条纹」。

#### 教训（与本会话其它几次同类）

**「结果看起来像噪声」时，第一该怀疑的是「我读的是不是那个量」，而不是布局或配色。**
差分、累积量、已经是物理单位的值（GRIB 那次是摄氏度）——
这三类在本会话各出现过一次，症状都是「数据看着不对」，
而我三次都先去调了外围参数。

### 2026-09-18 · 技巧曲线接进页面：**时效依赖仍未建立，但出现一个可检验的观察**

#### 做法

对归档里每一次 gfs 运行、每一批 airport 观测做配对，按**时效**分组累积，
并规定：**每组自带 n，低于 30 的组报为「样本不足」而不是画进曲线** ——
十二对的与四千对的中位数不是同一种主张，曲线穿过两者会把这件事藏起来。

#### 结果

```
归档中的 gfs 运行 1 次，airport 观测 16,347 条

时效    n      合偏差    MAE
  0    143    -1.00    2.76
  1     71    -0.50    1.84
  2     97    -0.50    1.87
  3    212    -1.00    2.32
  4    157    -1.00    1.69
  5    212    -1.50    2.43
  6   3646    -0.50    1.69
  7  10597    -0.50    1.60
  8    671     0.00    1.80
```

**MAE 随时效单调不减：False → 「误差随时效增长」在本数据上仍未建立。**

**注意「跨运行汇总」并没有真的发生**：归档里只有 **1 次** gfs 运行。
曲线从 5 个时效扩到 **9 个（0–8 小时）**，靠的是**观测累积**，不是运行变多。
这条要说清楚，否则会把「样本变多」误记成「方法变好」。

#### 一个可检验的观察（**假说，不是结论**）

MAE 在 0–8 小时内**基本持平**（1.60–2.76，无趋势）。

**这与「代表性误差主导」相符** —— 代表性误差（网格 0.25° 对站点是一个点）
**不随时效增长**，而模式误差会。若模式误差主导，短时效应当明显更小；
这里没有。

要检验它需要**同一格点内多个测站**的对照：同一格点内的测站间差异给出代表性
误差的直接估计，把它从总散布里扣掉后剩下的才是模式的。**本步未做。**

#### 页面

`block.html` 新增「团块的技巧」表，逐时效给出 n、中位偏差、MAE，
并显式标注单调性检验的结果与「未建立」。

验证（按内容，非状态码）：

```
block.html 含「团块的技巧」   2 次
block-skill.json              真 JSON
block.html 字节数  6,587      主页（回退页）字节数 57,912   ← 两数不同即为判据
```

### 2026-09-18 · 直接量出代表性误差：**我的假说被推翻了，模式误差才是主导项**

#### 方法

**同一模式格点内的两个测站看到同一个模式值**，所以它们之间的差异**不可能**是模式造成的 ——
那是真实大气在一个格点内部的差异，加上各自的仪器误差：

```
var(同格点测站对之差) = var(代表性) + 2·var(仪器)
```

**必须同时刻比。** 拿 09Z 的报和 12Z 的报比，量到的是日变化（数 K 量级），
会把一切淹没。故按 **(格点, 小时)** 分组，只用同时刻的对。

#### 结果

```
观测 16,347 条；同格点同时刻有成对测站的格点 247 个，测站对 n = 478
测站间距 中位 13.13 km   P90 22.43 km   最大 28.08 km   （格点 0.25° ≈ 28 km）

同格点同时刻温差: 中位 +0.00 K   sd 1.52 K
→ 单站偏差 sd = 1.08 K（代表性 + 仪器）
→ 扣掉仪器 0.5 K 后，代表性 sd = 0.96 K
```

三项分解（总量取本会话实测的 2.14 K）：

```
  总散布            2.14 K
  代表性(实测下限)   0.96 K    20% 的方差
  仪器(declared)     0.50 K     5%
  模式(余项)         1.85 K    75%
```

#### 这推翻了我上一轮的假说

上一轮我写：**「MAE 在 0–8 小时内基本持平，与代表性误差主导相符」**。

**代表性只占方差的 20%，模式占 75%。假说错了。**

那条推理的错误在于：我从「MAE 不随时效变化」推出「主导项不随时效变化」，
**但主导项是什么，需要单独测量，不能从平坦本身反推。**
平坦也可以由「短时效的模式误差已经和长时效一样大」造成 —— 而分解显示正是后者。

#### 边界（这一条必须先说）

**机场集中在大城市，同格点两站通常不横跨整个格点。**
实测间距中位 **13.1 km**，约为格点尺度（28 km）的一半 —— 比预想的好，
但仍**不是**该格点整体的代表性误差。**这是下限，不是真值。**
真值只会更大，从而让「模式占比 75%」这个结论**更强**，不会被削弱。

#### 未做

- 只做了 **tmp2m**。dpt2m、prmsl 的代表性误差未量。
- 只用 airport 一站源。sounding（同格点不同站）可作为独立复核，未做。
- 未按地形/海拔分层 —— 山区测站的代表性误差应显著大于平原，
  而这正是本研究最关心的区域。**下一步应做的正是这一层。**

### 2026-09-18 · 代表性误差按海拔分层：**方法对我们关心的地形在结构上无法作答**

#### 结果

```
海拔带 m        对数    温差sd K   代表性sd K(LB)   间距中位km
    0-100        242      1.55        0.98          12.6
  100-500        154      1.25        0.73          14.1
  500-1000        44      2.07        1.37          10.4
 1000-2000        34      1.45        0.90          15.9
 2000-10000        2        —           —             —      样本不足
```

**没有单调趋势**：500–1000 m 最高（1.37 K），1000–2000 m 反而降到 0.90 K。

#### 但真正的结论是结构性的

**海拔 2000 m 以上只有 2 对测站。** 机场在山谷和城市里，**不在高山，也不在冰川上**。
所以「按海拔分层看代表性误差」这个方法，**对高原与喜马拉雅 —— 我们唯一关心的地形 ——
在结构上无法作答**。

这与本会话早先那两条是同一类限制：

```
ITS_LIVE   测冰面流速，对【岩体】前兆在结构上是盲的
PDD        触发器 91% 饱和，对【任何】分辨都无功率
本次        机场不在高山，对【高海拔代表性误差】在结构上量不到
```

**共同点是：限制不在数据量，而在观测所在的位置 —— 而位置由观测系统的目的决定，
不由我们的问题决定。**

#### 因此那个悬案仍未解

「在高海拔，代表性误差是否反超模式误差」——**本步答不了**，
因为能回答它的测站不存在。要答它需要高山区的**成对同格点观测**，
而那样的观测要么没有，要么不是常规业务（例如高海拔自动气象站，
本仓库至今未接入）。

#### 仍然成立的

低海拔（0–2000 m）的代表性误差 **0.73–1.37 K**，占 2.14 K 总散布方差的 **12–41%**。
故「模式误差占多数」这个分解结论在**有测站的地方**成立；
它**没有被外推到高山**，也**不应被这样引用**。
