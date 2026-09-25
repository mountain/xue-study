# Xue 可视化、采集与下载：2026-09-24 实看记录

本地版本：`xue ed6b638`。本轮查看线上页面，下载并解码实际数据，另从 NOAA
原始资料跑通一次单变量、单时次的原生构建。未启动常驻采集或执行线上发布。
作者：Codex（OpenAI）。

## 1. 可以直接打开的页面

- [CFSv2 500 hPa 风场，亚洲视角](https://xue.ringsaturn.me/?lang=zh&model=cfs&type=wind500&res=half#map=3/32/90)
- [GFS 500 hPa 风场，同一视角](https://xue.ringsaturn.me/?lang=zh&model=gfs&type=wind500#map=3/32/90)
- [32°N、90°E 多模式对比](https://xue.ringsaturn.me/compare.html?lang=zh&lat=32&lon=90)
- [数据目录入口](https://dataset.ringsaturn.me/xue/)
- [STAC 根目录](https://dataset.ringsaturn.me/xue/catalog.json)

本轮 Chromium 实际打开了第一个页面：底图、500 hPa 风速填色、风粒子、
层次切换和月刻度时间轴均出现，页面没有抛出 JavaScript 异常。
截图见本地 [cfs-wind500.png](../archive/inspection-20260924/cfs-wind500.png)。
截图时播放到 F042，并非初始分析或真实观测。

随后实际拖到 **F6552**，页面显示 2027-06-23 的末帧；点选 **32°N、90°E** 后，
500 hPa 风速曲线显示 `1092 / 1092 序列已完整`，地面变量曲线也加载出来。
这轮浏览记录到 **212 个 HTTP 206 响应**，说明确实使用了范围读取，未抛出页面异常。
末帧点选前数据卡显示约 **561 KB**，这是当时该场的浏览传输量，不是完整 store 大小，
也不包括此后点选引发的其他图层请求。
[末帧与点选截图](../archive/inspection-20260924/cfs-point-series.png)、
[浏览记录](../archive/inspection-20260924/browser-report.json)。

当前交互结构：左上切换数据源，右侧选择变量/叠加层，下方切换气压层与播放时间；
点击地图可展开地点的时间序列。另有探空、机场 METAR/TAF、台风路径及历史个例。
多模式对比页面按地点展示不同模式；当前常规比较窗口为五日或十五日，
不能把它当成已经实现的季节概率验证页。

实现入口在 `xue/web/src/main.ts`、`layer.ts`、`particles.ts`、`probe.ts`、
`meteogram.ts`、`compare.ts` 及 `web/src/zarr/`。
数据通过 Rust/WASM 解码，在 WebGL2 上绘制；Zarr 数据可按 HTTP Range 读取可视范围内的块。
浏览器下载到缓存不等于研究归档。

## 2. 季节预报数据确实存在

本轮从实际 `latest-cfs.json` 跟随到 `cfs.2026092312/manifest.json`，
并核对 manifest CRC32 为 `430afe09`。该清单声明：

- 模式 CFSv2，起报时间 **2026-09-23 12:00 UTC**。
- **32 个图层包**，包含地面与多个气压层的场；一个风包包含 U/V 两个分量。
- F006 至 F6552，每 6 小时一次，共 **1,092 帧**，覆盖 **273 天 / 39 周**。
- 本轮风场实读有效时间为 **2026-09-23 18:00 至 2027-06-23 12:00 UTC**。
- 根据本地源注册及发布配置，该产品取 **00/12 UTC 周期的成员 01**，不是完整集合。

这为数月至半年研究提供了可以比较的现成模式产品和可视化基础。
展示未来九个月的场，不意味着已经具有逐日九个月的可靠预报技巧；
单次预报也不够构成历史回报资料。需要保存不同起报周期，并匹配验证资料。

## 3. 已验证两种下载路径

### A. 下载 Xue 已编码的发布数据

路径为 `latest-cfs.json → manifest.json → wind500.half.zarr/`。
Zarr 是一组对象，不能仅把目录 URL 当作一个文件下载。
本轮保留原有键路径，下载该 store 全部 **11 个对象**：

| 项目 | 实测结果 |
| --- | --- |
| 数据 | CFSv2 500 hPa U/V 风，全时段 half 层级 |
| 网格 | 180×91，2°，含两极 |
| 总字节 | **18,992,847**，与清单完全一致 |
| 根 zarr.json CRC32 | `9927c1b4`，与清单一致 |
| 解码 | xarray/Zarr 完整读取两分量全部时次成功 |
| CF 解码核对 | 与原始码值 `code−127`（255 为缺失）逐值一致 |
| 缺失 | 此份文件两分量有限值比例均为 1 |

数据位于
`archive/inspection-20260924/cfs.2026092312/wind500.half.zarr/`。
此处 `half` 是空间降分辨率版本，时间轴完整。
发布时的 balanced 风分量量化步长为 1 m/s；量化、裁剪与降采样须计入后续观测误差，
不能把它当作无损原始模式输出。

[下载收据](../archive/inspection-20260924/download-receipt.json)记录每个本地文件的 SHA256；
[解码记录](../archive/inspection-20260924/decode-report.json)记录网格、时段和逐值核对。
根元数据 CRC 与总字节核对不冒充上游逐文件加密签名。

可在本机读取：

```python
import xarray as xr

ds = xr.open_zarr(
    "/home/ubuntu/xue-study/archive/inspection-20260924/"
    "cfs.2026092312/wind500.half.zarr",
    consolidated=True,
    chunks=None,
)
u = ds["ugrd500"]
v = ds["vgrd500"]
# xarray 已应用 CF scale_factor/add_offset，不要再次反量化。
```

用 `/home/ubuntu/xue/.venv/bin/python` 运行，依赖已通过 `uv sync --frozen --group zarr` 安装。

### B. 从 NOAA 原始资料获取并自行编码

实际运行了下面的有界样本：只取 `wind500` 的 F006 一个时次。

```sh
cd /home/ubuntu/xue
XUE_ENCODER=native .venv/bin/python -m xuebuild build-bin \
  --model cfs --run 2026092312 --hours 6 --bundles wind500 \
  --skip-video --skip-variants --zarr --no-xue \
  --raw-dir /home/ubuntu/xue-study/archive/inspection-20260924/raw \
  --output-dir /home/ubuntu/xue-study/archive/inspection-20260924/built \
  --work-dir /home/ubuntu/xue-study/archive/inspection-20260924/work
```

结果：从 NOAA CFS 对象对 U、V 各作一次范围请求，得到 **110,028 字节** GRIB2；
经 `xuepy 0.27.0` 原生编码器生成 **68,253 字节**的 Zarr store。
输出是 **360×181、一个时次**，xarray 已重新打开验证。
这是默认 quality profile 的独立构建，不能与上面的 balanced half 文件作字节相等比较。

`--bundles` 会写 `manifest.part.wind500.json`，不写 live pointer，
适合小范围流水线检查。这份单层分片没有被伪装成完整已发布 run。
[原始构建日志](../archive/inspection-20260924/raw-build.log)、
[构建核对](../archive/inspection-20260924/raw-build-report.json)。

核心实现位于 `xuebuild/fetch.py`（范围抓取）、`sources.py`（源与时间轴）、
`encoder.py` / `native.py`（编码分派）、`zarrstore.py`（store 导出）。
线上更新由 `.github/workflows/publish-*.yml` 完成；CFS 配置以每天两次完整周期为主，
另设幂等恢复轮次，默认只保留一个已发布周期。

## 4. 本地归档还没有形成持续采集

本轮未发现运行中的 `xue_collect.py` 进程；恢复时没有原有 `archive/` 数据。
本次 `archive/inspection-20260924/` 是专项查看样本，不是连续时间归档。

`xue-study/scripts/xue_collect.py` 与上游抓取发布流程分开。检查发现：

1. **默认不收 CFS 风场。** `wanted('cfs','wind500')` 为 False，
   `wanted('cfs','manifest')` 为 True；默认得到目录/部分预览，不能据此认为数值场已存下。
2. **失败后不会按同一 item 补取。** 用临时目录和模拟网络重现：manifest 下载失败后，
   第一轮仍把 item 放入 `seen`；第二轮直接跳过，未再次请求该 manifest。
   [复现记录](../archive/inspection-20260924/collector-review.json)。
3. **store 下载的校验与预算尚不完整。** `fetch_store(..., max_bytes)` 没使用参数限制
   实际传输；调用方只比较声明大小，下载后只是记录实际与声明大小，没有拒绝不一致。
   逐节点元数据失败还会被忽略。这是代码检查结果，未制造线上损坏数据。
4. **归档布局不是标准 store。** 旧脚本将键扁平化成 `node__c__...`，不能直接用
   `xr.open_zarr` 或现有播放器读取；其 `block_page.py` 也明确只展示归档快照。
   本次下载保留了正常 store 目录，已验证可直接读取。

因此下一步建立长期资料时，需要明确挑选变量、保存每个起报周期，
修正失败补取与完整性判定，并配套实际总存储预算。
单纯按旧说明启动 `--loop 600` 不会自动得到所需的长期风场库。
本轮完成查看和复现，未修改旧采集策略或启动守护进程。

## 5. 当前工作区状态

`xue` 的受跟踪源文件未改；已安装前端 npm 依赖与 Python/Zarr 环境。
此次看到的是线上页面，本地没有启动 Vite 服务，WASM 本地构建工具链仍未配置。
第三方样本、截图及收据均位于忽略跟踪的 `archive/inspection-20260924/`。
前面的谱/frame 理论实验保留。
