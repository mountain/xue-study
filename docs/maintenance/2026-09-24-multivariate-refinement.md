# 2026-09-24：空间加密 L12，保留原始 L6 调用

实现与复现入口：`experiments/multivariate-refinement/README.md`。
训练前协议：`experiments/multivariate-refinement/contract.json`。

用户要求继续按比例加细，同时保留粗网格数据。本轮将谱阶 L6→L12、输出网格 2.5°→1.25°，保持月均、相同原始观测、16 变量和时间划分。L12 使用 2698 系数，验证选中 rank=64、penalty=0.1。原始 L6 的代码、训练产物、模型身份 `ctmulti` 和数据 URL 均保留；新增 `ctmulti12`，没有用细版降采样替换粗版。

唯一有效域 Gram 矩阵及逐月索引节省约 2.62 GiB 重复数组。所有月份、通道的 L12 投影残差不大于 L6；原生有效域一致。独立原生格点重建核对风场误差，防止把不同维度系数误差直接用作加密收益。训练与选择不读取回测标签；2020—2025 此前已经查看，仍是开发回测。

跨分辨率汇总采用相同原生观测域完整物理 MSE、固定 L6 训练期气候态尺度、13 通道及六个提前量等权平均。L12 联合模型较 L6 下降 36.46%，气候态同样下降 35.70%；主要收益是季节背景表示加密，不能宣称异常预报能力提高 36%。比湿以物理单位评分，独立通道与其他基线保留。SST 仍有低温越界，仅研究下载；没有静默截断。

`forecast-on-coarse-grid.npz` 是 L12 在原有 2.5° 点的精确取样，明确区别于原始 L6。[公开数据目录](https://climatetensor.io/research/resolutions.json) 统一列出三类下载、网格、单位和 SHA；`/resolution.html` 提供可视化及结果解释。地图默认 L12，L6/L12 切换保持变量、月份、视角及播放状态。

L12 tmp2m 编码范围改为 −80—47°C、步长 0.5°C，并记录于元数据，容纳南极的 −65°C 输出。全部 11×6 帧通过原生 decoder 与独立 Zarr 回读，零截断。前端新增寒冷值解码覆盖；原始粗档编码未改。

归档：`archive/multivariate-l12-v1/`。公开粗档的 140 个对象在工作开始前记录 SHA，本地和新发布均须匹配该快照。六项数值测试、121 项相关前端测试和 TypeScript/Vite 构建通过。浏览器检查覆盖 11 图层、默认入口、四模型、粗细切换、六个月点位序列及手机布局。最终部署与公网凭据记录于本目录对应归档的 `implementation-verification.json`。

发布代码位于 `/home/ubuntu/climatetensor-xue/scripts/climatetensor_refinement_publish.py`；发布检查为 `scripts/climatetensor/refinement-browser-check.mjs` 和 `scripts/climatetensor/public-refinement-check.py`。所有凭据写入新归档，不覆盖旧证据。

本轮仍为 2025-12 初始、2026-01—06 目标、2026-09-24 生成的历史月均实验，未同化、非实时、非原生 Adva 学习器。更密输出网格不是同尺度局地天气技巧的证明。下一阶段先约定日/周训练资料与验证，之后再考虑 L24。

最终发布到 `/var/www/climatetensor/releases/multivariate-l12-v1-20260924`，416 个静态文件与构建一致，`current` 原子切换，旧 release 保留。Caddy 配置先 validate 再 reload，新增研究目录缓存规则。公网 282 个对象 SHA、全部 140 个原始粗档对象、四个指针 CRC/缓存头、粗细后缀 Range 206、目录 CORS 均通过。线上默认细版、粗细往返保留状态、旧 FULL/EVEN、6/6 点位序列、桌面研究图和两个手机页面通过，无网页或 HTTP 错误。本地逐层覆盖全部 11 个细版图层，线上字节校验覆盖全部数据。方法纪律检查为 7/7，Adva card validator 仍不可用并明确跳过。汇总在 `implementation-verification.json`；临时预览已停止，Caddy 保持 active。
