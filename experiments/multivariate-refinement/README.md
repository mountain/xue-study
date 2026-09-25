# L6 → L12 空间加密，保留原始粗档

用户要求按原比例继续加细，同时保留粗网格调用。本轮完成月均 L6→L12 谱加密及 2.5°→1.25° 显示网格；没有提高时间分辨率，也没有插值制造新的训练观测。

旧代码、数据和模型在 `experiments/multivariate-seasonal/`、`archive/multivariate-seasonal-v1/`；全部冻结，新实验单独位于本目录及 `archive/multivariate-l12-v1/`。开始前对公开粗档的 140 个数据/下载/指针文件记录 SHA-256，后续逐项比对。`ctmulti` 仍然是原始 L6，新增 `ctmulti12` 为细档；不得将 L12 的降采样结果写进旧路径。

16 个物理变量、13 个通道不变。标量通道各 169 个系数，三个成对风通道各 336，共 2698；保留完整奇偶和正余弦相位。输入仍为已缓存的 NOAA PSL NCEP/NCAR R1 和 ERSST v5 原生网格、1979—2025 月均，共 564 月。所有有效域均与 L6 逐格相同，SST 海洋缺测不补零，气压层保留地下筛选，比湿在对数状态中学习。

训练前约定为 `contract.json`。训练 1979—2014 / 验证 2015—2019 / 开发回测 2020—2025；后者已在 L6 检查过，不是新独立检验。候选 rank 8/16/32/64、惩罚 0.01/0.1/1 与 L6 相同。验证选中 rank=64、penalty=0.1，没有按回测结果改选参数。

`project.py` 将每月重复 Gram 改为唯一观测域矩阵 `*_gram_bank` 和 `*_gram_index`。数学上仍是原有无正则化最小二乘投影，条件数上限 1e8，超限失败。实际矩阵及索引共 6,383,856 bytes，避免 2,810,448,720 bytes 重复存储。L12 投影残差在所有通道和月份不大于 L6，验证其确实增加了可表示空间，而不是只改像素。学习进程峰值 RSS 991,988 KiB，已缓存投影后的训练/回测/导出约 28.4 秒；这不是含首次下载和投影的总耗时。

跨分辨率评分比较相同原生观测场上的完整物理 MSE（包含截断残差），比湿还原为 kg/kg。每通道使用固定 L6 **训练期**气候态的完整物理 MSE 作尺度，最后对通道和提前量等权平均。不能直接比较 778 维与 2698 维的系数误差。`check_artifacts.py` 还直接重建两个模型的原生格点风，独立核对一月和六月的完整风场误差。

开发回测中，联合 L12 的汇总完整物理 MSE 较 L6 下降约 36.46%；气候态本身的同一指标也下降约 35.7%，大部分收益来自季节背景表示加细，不能宣传为异常预报能力提高 36%。独立通道、AR1、持续等对照仍完整记录。与旧模型相同，没有守恒、因果识别或实时天气能力证明，不是 Adva 原生学习器，未进行同化。

两档纬度中心范围均为 87.5°N—87.5°S。细网格 141×288，粗档 71×144；细网格每隔一点与粗网格坐标完全相同。

- `forecast.npz`：L12，在 1.25° 网格，16 物理场（SI 单位）及月份/经纬度/系数。
- `forecast-on-coarse-grid.npz`：L12 在原 2.5° 格点精确取样，显式携带 `spectral_degree=12`。这是另一个取样格式，**不是原始 L6 模型**。
- 旧 `archive/multivariate-seasonal-v1/forecast.npz`：原始 L6，不覆盖。
- `model.npz`：拟合参数、独立基线及历史谱系数；重新载入后精确复现预报系数。
- `backtest.npz`：所有基线和联合模型的回测谱输出。
- `report.json`：每通道误差、跨分辨率比较、数据来源与训练约定 SHA。

Xue 由 `/home/ubuntu/climatetensor-xue/scripts/climatetensor_refinement_publish.py` 编码。11 图层（14 分量），sp 和 SST 继续只放在完整研究下载。SST 最低 269.16 K，仍有越过源资料 271.35 K 下界的重建值，未静默截断，不作为地图预报层。L12 更细的南极低温超出了原网页 −60°C 编码范围，因此新版本 tmp2m 编码改为 −80—47°C，仍为 0.5°C 步长，在元数据中显式描述，未修改旧版本。原生 decoder、标准 Zarr 和网页物理值解码均检查此边界。

入口：`/resolution.html`。API：`/research/resolutions.json`，包含独立粗/细模型和细模型粗网格取样的下载地址、网格、变量 SI 单位及 SHA。原始 `/research/multivariate-v1/*` 和 `/data/latest-ctmulti.json` 路径继续有效。地图模型切换保留变量、月份、视角和播放状态。

已有 L6 数据的本机复现命令（仓库根目录）：

```bash
OPENBLAS_NUM_THREADS=2 /home/ubuntu/climatetensor-env/bin/python experiments/multivariate-refinement/test_model.py
OPENBLAS_NUM_THREADS=2 /home/ubuntu/climatetensor-env/bin/python experiments/multivariate-refinement/project.py
OPENBLAS_NUM_THREADS=2 /home/ubuntu/climatetensor-env/bin/python experiments/multivariate-refinement/train.py
OPENBLAS_NUM_THREADS=2 /home/ubuntu/climatetensor-env/bin/python experiments/multivariate-refinement/check_artifacts.py
```

已完成的训练会拒绝覆盖 `report.json`；修订须另开输出版本。公开 `source.zip` 保留三目录相对布局及依赖代码；原始资料仍在仓库外缓存，未重复下载。新采集时可用旧目录 `fetch.py`，但远端再分析可能修订，必须核对来源快照 SHA，不能假定以后下载的同名文件与本次字节相同。

下一阶段仍需先决定日/周聚合与检验协议，再考虑 L24；本轮只执行 L12 空间加密。
