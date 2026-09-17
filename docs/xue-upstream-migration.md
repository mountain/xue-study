# xue 上游演进与 `.xue` → Zarr v3 迁移对照

> 研究快照：2026-09-16。本地 checkout `/Users/mingli/Climate/xue` 停在 `b034048`（09-10），
> 上游 `ringsaturn/xue@main` 在我研究期间从 `7e261843` 推进到 `8af4376`——**这是一个正在被持续推送的活仓库**，
> 本文所有上游结论都以抓取时刻为准。

---

## 0. 摘要

1. 本地那份 checkout 落后上游 **121 个提交**；上游代码量在 6 天内**翻了一倍**（37.8k → 75.9k 行）。
2. 项目做了一次方向性转向：自研 `.xue` 容器于 **2026-09-15 从线上退役**，改发 **Zarr v3 store**。
   这不是推翻，而是**把已验证的布局搬到标准格式上**——容器 v2 的每一个概念都有 Zarr 原生对应物。
3. 转向的收益是互操作性（xarray / pystac / odc-stac 直接读），代价是四处必须自己补的工程缺口。
4. 数据源从 4 个扩到 7 个，并且**推翻了自己"不做重投影"的原则**（HRRR / MRMS / JMA）。
5. 我上一份报告标记的技术债：**1 条已被上游修复**（wasm 测试字段名），**2 条仍在**，另发现 1 条轻微文档 bug 上游也没修。

---

## 1. 规模对比

| | 本地快照（09-10） | 上游（09-16） | 变化 |
|---|---:|---:|---:|
| Python（`xuebuild/` + 测试） | 12,281 | **28,027** | +128% |
| Rust（三 crate + 测试） | 9,453 | **13,115** | +39% |
| TypeScript（`web/src`） | 13,479 | **30,815** | +129% |
| HTML / CSS | 2,543 | **3,910** | +54% |
| **合计** | **37,756** | **75,867** | **+101%** |

`xuebuild/` 从 24 个模块增至 **31 个**，新增的分量都在说明方向：

```
assemble.py     zarrcodec.py    zarrstore.py    stac.py
reproject.py    jmacli.py       tc/（热带气旋产品）
```

`web/src/` 从 22 个模块增至 **36 个**：新增 `zarr/`（6 个文件，第三种解码通道）、`tc/`、`locales/`、
`composite.ts`、`meteogram.ts`、`timezone.ts`、`fetchimmutable.ts`、`sessionkeys.ts`、`sheet.ts`、`site.ts`、`pagemeta.ts`、`levels.ts`、`domain.ts`、`identity.ts`。

测试从 12 个 Python 模块增至 **23 个**：`test_zarr.py`、`test_stac.py`、`test_assemble.py`、`test_tc.py`、
`test_hrrr.py`、`test_mrms.py`、`test_jma.py`、`test_ecmwf.py`、`test_ocean.py`、`test_surface.py`、
`test_isobaric.py`。

---

## 2. 为什么转向 Zarr：技术论证

上游 `docs/zarr-profile.md`「Why a profile」一节给出了核心论证，值得原文引用其结构：

> 一个容器 v2 bundle，除了索引格式以外，**就是一个分片的 Zarr v3 `uint8` 数组**：
> 一个 chunk = 一个空间瓦片 × 一个六帧时间组；一个 group = 行主序瓦片顺序上的一段连续 chunk；
> 每个 chunk 是一个 Zstandard frame；时间残差是 chunk 内对前一帧的回绕差分。
> Zarr 把这些表达为 `sharding_indexed` codec、`zstd` codec，以及可选的 array-to-array delta codec。

也就是说：**自研容器发明的东西，Zarr v3 恰好都有对应的标准构件**。既然能 1:1 映射，就没有理由继续维护一套只有自己实现能读的格式。

值得强调的是设计没有丢：量化码平面、六帧时间组、tile 化、按前帧残差、每 chunk 独立 zstd——全部保留，只是换了容器外壳。

---

## 3. 逐项迁移对照

| `.xue` 容器 v2 概念 | Zarr v3 对应物 | 备注 |
|---|---|---|
| FixedHeader + 元数据 JSON | 组的 `zarr.json` → `attributes.xue` | **元数据 JSON 逐字节原样**，解析器复用 |
| 元数据 schema v1–v3 | 同上（不变） | `xue_profile` 单独给 profile 版本 |
| 量化码本 | 数组 `attributes.xue.variable.quantization` | 另写 CF 的 `scale_factor` / `add_offset` / `_FillValue` |
| chunk（瓦片 × 六帧组） | inner chunk | 见下方"注意" |
| GroupEntry（时间组） | time chunk（固定 6 帧） | **布局不再等同** |
| 物理序 group → tile → variable | shard 内 inner chunk 行主序（time chunk，然后 tile） | 一个 time chunk 仍是连续一段 |
| ChunkEntry（8 字节，offset 是前缀和） | shard index：每 inner chunk 一对 `(offset, nbytes)` + **CRC-32C** | 16 字节/块，比容器**更宽**（多了 nbytes 与 CRC） |
| 索引前缀 `[0, dataOffset)` | shard 末尾的 index（`index_location: "end"`） | 用 HTTP **suffix range** `bytes=-N` 读，无需知道对象长度 |
| 每 payload 一个 zstd frame | inner codec chain `[bytes, zstd{level 15, checksum}]` | 任意 Zarr 客户端零注册可解 |
| PREVIOUS predictor | **`xue.delta` codec**（自研，需注册） | 见 §4.4 |
| `nodataCode` | `fill_value` | 同时承担 padding 语义 |
| 半分辨率 `.half.xue` | 独立的 `<bundle>.half.zarr` | 从 `.half.xue` 派生，规则相同 |
| 区域网格（showcase 裁剪） | 同（grid 块描述窗口） | 不变 |
| CRC-32（每平面/chunk） | shard index 的 CRC-32C + zstd checksum | 校验强度持平 |
| 结构性前缀一次读 | 每数组一次 index 读（开数组时） | 请求数形状相同 |

### 三个必须注意的差异

1. **时间分组不再等同**。容器把组切在等步长分段内（GFS 在 f120 处产生一个单帧组），
   Zarr 的 time chunk 固定 6 帧，**可能跨越容器的两个组**。上游明确写：
   *"The two layouts coincide up to the first change of step"*，并规定
   **"a reader never consults the container's grouping"**。
2. **每个 shard = 整个数组**（本轮修订）。outer chunk 是 `[6×timeChunks, tileRows×tileHeight, tileColumns×tileWidth]`，
   GFS 161 帧即 `[162, 728, 1440]`。padding 帧/格用 `fill_value` 填。
   更早的 store 是"一个 time chunk 一个 shard"（`c/<t>/0/0`），**读者必须两种都读**。
3. **容器不再发布**，但**仍是编码器的中间产物**：先写 `.xue`，再把码读回来导出 store。
   `--no-xue` / `XUE_CONTAINER=0` 才在派生完 store 与视频伴随文件后**退役**容器
   （`binconvert.retire_container`），manifest 条目只留 store。

---

## 4. 迁移中必须自己补的四个缺口

这是整件事最有工程价值的部分：标准格式不覆盖的地方，上游逐个补上了。

### 4.1 对象数计费

Zarr 的自然切法是"一个 time chunk 一个对象"。上游算了一笔账：

> 按 time chunk 切，一次 GFS run 约 **5000 个对象**；容器只要 **60 个**。bucket 对每个写入的对象计费。

于是改成**一个数组一个 shard**：一个 store 只有"每标量变量 3 个对象 + 每额外变量 2 个 + 坐标 6 个"，
且**与时间轴长度无关**。一个 shard 用 range 读，等价于原来的单文件容器。

### 4.2 索引读取

shard index 放在 shard **末尾**（`index_location: "end"`），客户端用 HTTP suffix range `bytes=-N` 读，
**不需要事先知道对象长度**——这正好对应容器里"先取结构前缀"那一步。
规范要求读者同时接受 `start` 与 `end` 两种（zarrita 只读 `end` 形式）。

index 大小：`16 × timeChunks × tileCount + 4` 字节（GFS 27×420 块 = 181,444 字节）。
和容器的 94 KB 索引量级相当，但**多 4 字节 CRC-32C**，读者必须先校验再使用任何 offset。

### 4.3 请求数：24 → 4 的差距要靠合并补回来

这是转向最实在的代价，上游没有掩饰：

> 一个 shard 的 inner chunk 在瓦片顺序上连续，所以一个瓦片行是一段连续 span。
> 但**逐 inner chunk 发一次 range 的读者，一个瓦片要付一次往返**：
> 一个 6×4 瓦片的视口要 **24 个请求**，而容器只要 **4 个**。

对策写进了 profile 作为推荐：**把一次读需要的一个 shard 内的 range 收集起来，按 offset 排序，
把间隔小的邻居合并**（前端阈值 **64 KB**），逐段发一次 range——**合并间隙的过读比省下的往返便宜**。
合并后：全局视图每个 time chunk 一个 range，视口每个瓦片行每个 time chunk 一个 range，
点位序列每个 time chunk 一个 chunk，外加每个未读过的 shard 一次 index 读（本轮修订下 = 每数组一次，在打开时）。

### 4.4 `xue.delta`：必须自己写一个 codec

容器的 PREVIOUS predictor 是"沿时间轴对前一帧做模 256 差分"。
Zarr 生态里最接近的是 numcodecs 的 `Delta`，但**它差分的是展平后的缓冲区**，语义不同。
于是上游写了自研的 array-to-array codec：

```json
{"name": "xue.delta", "configuration": {"axis": 0}}
```

沿 `axis` 第一片整体存储，之后每片存与前一片的模 256 差；解码是模 256 的累加。
它只加在"从前一帧预测"的变量上（降水、反射率这类 RAW 变量**不加**）。
`xuebuild/zarrcodec.py::register()` 为 zarr-python 注册它——**只有读 `--delta` 写的 store 才需要**。

规范里一句很关键的话：

> 在 `[xue.delta, bytes, zstd]` 下一个 inner chunk，压缩出的字节与 bundle 在相同帧、相同未裁剪瓦片上的 chunk **完全相同**。

这正是"迁移零损失"的技术依据。

---

## 5. 换来的互操作性

`docs/stac.md` 说得很直白——*"so the Zarr stores can be found the way that ecosystem finds data"*：

| 能力 | 靠什么 |
|---|---|
| `xr.open_zarr(url)` 直接开，无需 `consolidated=` 参数、无需目录列举 | 组文档里携带 **inline 形式的 consolidated metadata**，把每个数组的 `zarr.json` 逐字重复一遍 |
| CF-aware 客户端自动反量化 | 线性码本写 `scale_factor` / `add_offset` / `_FillValue` |
| `pystac` 遍历目录 | 派生的 **STAC 1.1.0** 静态目录 |
| `xpystac` / `odc-stac` 把 Item 的 `application/vnd.zarr` asset 开成 xarray | 同上 |
| 任意 Zarr 客户端解 inner chunk | 默认链是标准 `[bytes, zstd]`，零注册 |

STAC 目录的构造延续了同一套纪律——**派生而非权威**：

> 每个文档都是 manifest、`showcase.json` 一行与源注册表的**纯函数**，
> **没有时间戳、没有主机名**，这让"整轮构建"与"分片构建"写出相同字节。

链接全部相对（`../catalog.json`、`tmp2m.zarr`），**没有 `self` 链接**，所以客户端从哪个 origin 读都能解析。

新对象：`catalog.json`、`<source>/collection.json`、`<source>/item.json`（**永不改变的路径**，指向当前 live run）、
`<source>.<run>/item.json`、滚动窗口源的 `<run>/<HHMM>/item.json`、`showcase/collection.json` 与 `showcase/<case>/item.json`。

---

## 6. 副产品：一个自愈式部署方案

这解决的是我上一份报告里指出的那个硬约束——"schema 拓宽是双向部署，新壳必须先上线"。

上游现在多了一层保险：**校验不过的旧标签页会自我重载一次**。

- 前端校验器拒绝一份更新的 live manifest → `ManifestRejectedError`
- Zarr 读者打不开 live store → `StoreRejectedError`
- 两种情况都触发 `main.ts::reloadForNewerShell`，**按 manifest 的 crc32 记在 `sessionStorage` 里，每份 manifest 只重载一次**
  （避免无限重载循环）

这比"发布顺序约定"更可靠：约定靠人遵守，重载靠代码兜底。**任何做"静态壳 + 可变数据指针"的人都该抄这一条。**

---

## 7. 数据源扩张，以及一条原则的反转

| 源 | `--model` | 网格 | 时间轴 | 指针 |
|---|---|---|---|---|
| NOAA GFS 0.25° | `gfs` | 1440×721 | 1h→F120，3h→F240（161 帧） | `latest.json` |
| GFS surface flux | `sflux` | 3072×1536 高斯 | 同 GFS | `latest-sflux.json` |
| ECMWF IFS open data | `ecmwf` | 1440×721 | 3h→144h，6h→F240（65 帧） | `latest-ecmwf.json` |
| **NOAA HRRR** | `hrrr` | 2441×1051，0.03°，美国本土 | 1h→F18，每小时一个 cycle | `latest-hrrr.json` |
| **NOAA MRMS** | `mrms` | 3500×1750，0.02°，美国本土 | 每 2 分钟一帧，滚动 4 小时窗口 | `latest-mrms.json` |
| **JMA 降水临近预报** | `jma` | 5600×5000，**0.005°**，日本 | 每 5 分钟一帧，滚动 3 小时窗口 | `latest-jma.json` |
| CMA 雷达拼图 | `radar` | 瓦片网格 | 每 6 分钟 | 无（仅 showcase） |

**"不做重投影"这条原则被推翻了。** 本地版本的 `CLAUDE.md` 明确写着渲染器不做重投影、编码器也不重采样；
上游新增了 `xuebuild/reproject.py`（`Regrid`），HRRR 从 Lambert conformal 重采样到规则经纬网格，
`reproject.build_resampler` 还要把 footprint 边界对齐到格点。MRMS（0.02°）与 JMA（0.005°）同理。

但原则的内核仍然成立：**格式本身仍然只承载规则经纬网格，重投影发生在摄取期一次，渲染器的片元着色器仍只做逆 Web Mercator**。
换句话说，反转的是"谁来做重采样"，不是"什么时候做"。

另一个新增能力是**滚动窗口源**（MRMS、JMA）：不是"一次 run 到 F240"，而是每几分钟一帧的滑动窗口，
有 `<run>/<HHMM>/item.json` 这种"一轮"（round）粒度。这对容器的时间轴模型是一个新形态，Zarr/STAC 侧反而更自然。

GFS/ECMWF 还新增了 `companion_files`（`CompanionFile(id="wave", ...)`），把 GFS-Wave 的 `htsgw`/`perpw`/`dirpw`
从**另一个文件**取来，并派生出一个"浪向矢量"bundle（把浪高沿传播方向铺成 u/v 对）——于是海浪也能像风一样画粒子。

变量集从 6 个 bundle 扩到 **37 个**：位温、相对湿度、垂直速度、CAPE、阵风、云量（总/低/中/高）、能见度、
露点与体感温度、海表温度、海冰密集度与厚度、浪高与周期、水汽通量……

---

## 8. 我上一份报告标记的技术债：上游现状核查

| 我标记的问题 | 上游状态 | 证据 |
|---|---|---|
| `rust/xue-wasm/tests/web.rs` 用已改名的 `forecast_hour`，无法编译 | ✅ **已修复** | 上游 `web.rs:18` 已是 `frame_offset`，并**新增** `decode_chunk_in_browser` 测试（验证 `xue::decode_chunk`，即 Zarr 通道的解码路径） |
| 浏览器端断言无人守护（CI 不跑 `wasm-pack test`） | ❌ **仍未解决** | 上游 `test.yml` 里 `wasm-pack` 只被安装用于**构建**（`make wasm`）与 e2e，全文没有 `wasm-pack test` —— 测试现在能编译了，但**依然从不执行** |
| 峰值内存无上界（`codes_by_offset` 持整轮所有帧所有变量的码） | ❌ **仍存在** | 上游 `binconvert.py:1692,1756,1806,1846` 结构未变 |
| 参考实现渐不在关键路径上被验证 | ⚠️ **部分缓解** | `tests/test_native.py:169` 新增了一条守卫：*"Parity is worth nothing if both sides skipped the same work."*（若两侧因同一前置条件都跳过，等价性证明为零）。但 <3.14 的 zstd 字节比对跳过仍在（`:9-10, 55-57`） |
| `sources.py` 里"跨段轴 ⇒ schemaVersion 2"的过期 docstring | ❌ **上游也没修** | 上游 `xuebuild/sources.py:118` 一字未改 |
| "必须在 Python 3.14 上构建才能字节一致"只是文档里的隐式约束 | ❌ **仍存在** | 上游 `pyproject.toml` 仍写 `requires-python = ">=3.12"` |

### 可立即贡献的一处：把浏览器解码测试接进 CI

现在测试文件已经能编译，缺的只是执行。一个独立 job 即可（需 Chrome，GitHub 的 ubuntu runner 自带）：

```yaml
  wasm:
    name: wasm browser
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
        with:
          targets: wasm32-unknown-unknown
      - uses: Swatinem/rust-cache@v2
        with:
          workspaces: rust
      - uses: astral-sh/setup-uv@v5
        with:
          python-version: "3.14"        # 让夹具与发布产物同字节
      - name: Sync Python environment
        run: uv sync
      - name: Build the golden fixtures
        run: uv run python tests/prepare_bin_fixture.py
      - name: Install wasm-pack
        run: |
          curl -sSfL "https://github.com/rustwasm/wasm-pack/releases/download/${WASM_PACK_VERSION}/wasm-pack-${WASM_PACK_VERSION}-x86_64-unknown-linux-musl.tar.gz" \
            | tar xz -C "${RUNNER_TEMP}"
          sudo install "${RUNNER_TEMP}/wasm-pack-${WASM_PACK_VERSION}-x86_64-unknown-linux-musl/wasm-pack" /usr/local/bin/wasm-pack
      - name: Run the browser decoder tests
        run: wasm-pack test --headless --chrome rust/xue-wasm
```

细节说明：

- `${WASM_PACK_VERSION}`（`v0.13.1`）已是 `test.yml` 的**工作流级 env**（`test.yml:30`），无需重复钉版本。
- **不需要 GDAL**：上游自己的 `web` job 就只装 `zstd` + `uv sync` 就把夹具建出来了
  （`prepare_bin_fixture.py` 只用 numpy + `xuebuild` + `zstdcli`，走的是 wheel 里链接的 GDAL）。
- 该 job 需要 runner 上的 Chrome；GitHub 的 `ubuntu-24.04` 镜像自带。

> 注：我**未能实测**这段 CI 配置——本机没有 `wasm-pack`，且 `wasm32-unknown-unknown` target 未安装，
> 无法在本地复现 `wasm-pack test`。提交前请在 fork 上先跑一次。

---

## 9. 对采用者/学习者的启示

**可以直接借鉴的**

1. **"先造容器验证布局，再映射到标准格式"** 是一条低风险的路径。前提是布局的描述足够规范化——
   正因为 `.xue` 有 1068 行 normative spec，迁移才可能逐条对照而不是重写。
2. **"一个数组一个 shard"** 这个反直觉的决定（而不是 Zarr 惯用的"一个 chunk 一个对象"）来自**对象计费**这一现实约束。
   存储格式的设计者常常忽略"元数据对象的数量和大小一样会被计费"。
3. **用 HTTP suffix range 读末尾索引**——`bytes=-N` 不需要知道对象长度。这是个漂亮的 trick，
   在"索引放尾部更快"与"先得知道长度才能读尾部"之间绕开了鸡生蛋问题。
4. **范围合并的量化论证**：不要只说"合并更好"，要说"64 KB 的过读比一次往返便宜"。
5. **自愈式重载**（§6）——比部署顺序约定可靠。
6. **派生文档要无时间戳、无主机名、链接相对**，否则"整轮构建"与"分片构建"写不出相同字节。

**需要警惕的**

1. **6 天翻倍的代码量**意味着任何一份 checkout 的"研究结论"都有保质期。这也是本文开头强调快照时刻的原因。
2. **标准格式的互操作性是有代价的**：请求数从 4 变 24、索引变宽、需要一个自研 codec、需要自己实现合并。
   "改用标准格式就一定更简单"是个错觉——它把复杂度从"自己写格式"换成了"补齐标准没覆盖的部分"。
3. **回归风险集中在"两种形态并存"**：读者必须同时支持"一 shard 一 time chunk"（旧 store）与"一 shard 一数组"（新 store），
   外加容器 v1 / v2 / 元数据 schema 1-3。兼容矩阵在持续变宽。

---

## 附录 A：本地环境缺口（已实测）

| 工具 | 状态 |
|---|---|
| `cargo` / `rustc` | ✅ 1.96.1 |
| `node` / `npm` | ✅ v26.4.0 / 11.17.0 |
| `uv` | ✅ 0.11.24 |
| `python3` | ✅ **3.14.6**（有 stdlib `compression.zstd`，即"发布产物字节一致"的那个版本） |
| `zstd` | ✅ 1.5.7 |
| `wasm-pack` | ❌ **缺失** → `make wasm` 无法运行 → 前端无法构建 |
| `gdalinfo` / GDAL | ❌ 缺失 → 无法跑真实数据流水线 |
| `ffmpeg` | ❌ 缺失 → 无法生成 H.264 伴随文件 |
| `wasm32-unknown-unknown` target | ❌ 未安装 |
| Chrome | ✅ `/Applications/Google Chrome.app`（`wasm-pack test --headless --chrome` 可用） |
| `numpy`（系统 python3） | ❌ 缺失（需 `uv sync`） |

`web/src/wasm/` 与 `.venv` 都不存在，所以本地这份 checkout **当前无法构建前端**。

## 附录 B：快速上手命令

```sh
cd xue
git fetch origin && git log --oneline HEAD..origin/main | head -30   # 先看差距
uv sync                     # 建 .venv（Python 3.14.6 已在位）
make wasm                   # 需先安装 wasm-pack
make check                  # 校验 GDAL / zstd / node / wasm-pack
make serve                  # vite preview 于 127.0.0.1
```

看真实底图请用 `http://localhost:4173` 而非 `127.0.0.1`——Protomaps key 锁 origin，
**包含 `localhost` 但不含 `127.0.0.1`**，而 `playwright.config.ts` 恰好用后者，所以 e2e 会 stub 掉瓦片。

## 附录 C：本文引用的一手材料

| 材料 | 位置 |
|---|---|
| 容器规范 | `docs/format.md`（1068 行，normative） |
| **Zarr profile 规范** | `docs/zarr-profile.md`（298 行，normative） |
| **STAC 契约** | `docs/stac.md` |
| 原生编码器与等价性 | `docs/encoder.md` |
| 架构叙事 | `CLAUDE.md`（上游 43 KB） |
| Zarr 导出实现 | `xuebuild/zarrstore.py`、`xuebuild/zarrcodec.py` |
| STAC 派生实现 | `xuebuild/stac.py` |
| 前端 Zarr 通道 | `web/src/zarr/{channel,protocol,session,shard,store,worker}.ts` |
| 在线演示 | <https://xue.ringsaturn.me> |
