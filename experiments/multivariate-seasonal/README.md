# 多变量月均谱学习，第一阶段

用户要求加入多变量学习，再逐渐提高时空分辨率。本阶段已经真实下载、投影、训练、回测及生成预报，不只是变量配置。实验约定先写入 `contract.json`，结果见 `archive/multivariate-seasonal-v1/report.json`。

16 个物理变量组成 13 个谱通道：t850、t2m、sst、sp、msl、z500、q850、q700、w500、w700，以及三个成对的 u/v 风层（850/500/250 hPa）。标量每组 49 个系数，风每组 96 个，共 778 个；保留奇偶性、相位和梯度/旋转分量。最高 L6，月平均，未增加信息分辨率。显示网格 2.5° 不代表预报技巧达到 2.5°。

数据来自 NOAA PSL NCEP/NCAR R1 月均再分析和 ERSST v5 月海温；1979-01—2025-12 共 564 月。不是 ERA5 数据训练。原始文件和选取的 SI 单位 NPZ 在仓库外 `/home/ubuntu/climatetensor-inputs/ncep-multivariate/`，附下载时间、来源、源单位/变换与 SHA-256。公开页署名 NOAA PSL。辐射、积雪、z1000 和 RH 诊断留到后续源适配，不作同名替换。

训练 1979—2014（432 月）；验证 2015—2019（60 月）；开发回测 2020—2025（72 月）。500 hPa 的这段回测在第一版已看过，不能重新声明全新独立测试。回测不参与本轮参数选择。没有重建历史实时可得性，月资料本身是事后再分析/重建。

表示在各场原生网格上进行。权重由纬度单元边界计算球面面积；不使用精确极点。海温使用训练期有效域；气压层用插值后的月地面气压筛选，固定训练期保守域并附加逐月筛选。缺测在矩阵运算前排除。Gram 不作隐藏正则化，条件数超过阈值即失败；保存每月 Gram 和截断残差，用于完整观测域误差分解。比湿先取 `log(max(q, 1e-7))`，逆变换保持正值；同时单独计算物理单位的全场 RMSE。

季节均值、通道 RMS 尺度和 EOF 只由训练期拟合。联合 EOF 初态映射到各目标月全状态，六个提前量分别拟合岭回归；每个训练输入/目标对都完全位于训练期。候选 rank 8/16/32/64、平均损失惩罚 0.01/0.1/1；所有通道和提前量的验证误差共同选择，最终 rank=32、penalty=0.1。这是有跨变量系数的统计预报，不是逐变量 AR1 的重新包装，也不是因果或 Floquet 结论。

对照包括气候态、持续异常、独立系数 AR1、逐通道 EOF/ridge（同候选集，逐通道验证选参）。开发回测整体归一化系数误差：联合 16.9318，独立通道 16.0666，气候态 20.3693。联合较气候态降低 16.88%，但较独立通道高 5.39%。500 hPa 风一月谱 MSE 技巧 6.60%，独立 AR1 为 9.05%；联合六个月为 1.19%。不要据此宣布“多变量一定更好”。不去长期趋势，部分温度/海温技巧可能反映趋势，而非年际异常预测。

初始为 2025-12 月均状态，预报 2026-01—06 月均，生成于 2026-09-24。`model.npz` 保存归一化、映射、EOF、基线和历史系数；重载后精确复现预报系数。`backtest.npz` 保留所有对照输出。`forecast.npz` 含 16 个物理场（SI 单位）、月份、lat/lon 和系数；掩膜之外为 NaN。SST 最低约 268.20 K，2252 个输出格点/月份低于源资料 271.35 K 下界；未做静默截断，见 `quality-check.json`。尚无守恒和物理边界保证。

Xue 独立工作树 `/home/ubuntu/climatetensor-xue` 的 `scripts/climatetensor_multi_publish.py` 发布 `ctmulti`。11 个图层覆盖 14 个物理分量；sp 和 SST 仅在完整下载中提供，SST 未通过物理边界检查。每层 6 帧，缺测码保留掩膜，全部经过原生 decoder 和标准 Zarr 独立逐格回读。没有修改线格式；温度 K→°C、位势→位势高度、气压 Pa→hPa、比湿 kg/kg→g/kg 仅在显示编码时转换。页面量化有损，所有误差界限在编码凭据中。

第一版 FULL/EVEN 产物和页面保留。联合实验入口 `/multivariate.html`，地图 `/?lang=zh&model=ctmulti&type=wind500`。新模型并不作为已胜出模型宣传。没有同化、没有原生 Adva 学习或证明、没有自动每日更新。

复现（仓库根目录，numeric Python 3.11 环境）：

```bash
OPENBLAS_NUM_THREADS=2 /home/ubuntu/climatetensor-env/bin/python experiments/multivariate-seasonal/fetch.py
OPENBLAS_NUM_THREADS=2 /home/ubuntu/climatetensor-env/bin/python experiments/multivariate-seasonal/test_model.py
OPENBLAS_NUM_THREADS=2 /home/ubuntu/climatetensor-env/bin/python experiments/multivariate-seasonal/train.py
```

发布编码使用 Xue 的 `.venv` 和该工作树 `PYTHONPATH=.`；运行目录不可覆盖。训练产物已冻结，方法修订必须另建输出版本，不能覆盖这批已公布结果。网站生成器 `publish_report.py` 同时创建图、数值 QC、下载 SHA 清单和静态页面；依赖 NumPy/SciPy/xarray/h5netcdf/matplotlib。四项科学检查覆盖未来污染隔离（包括选参）、真实跨变量可学关系、掩膜污染与全场误差分解、单位缩放不变性；交付测试不等同预测验证。

后续的受控步骤：保持月资料和协议，L6→L12；之后再接日资料并明确日/周聚合与采样规则；最后评估 L24。当前联合模型逊于逐通道对照，增加空间阶数时必须保留该对照、检查过拟合、海温边界和计算预算。更高阶和日资料阶段尚未执行。

本机 2 CPU / 7.6 GiB RAM。相同 13 通道在 L12 为 2698 系数，L24 为 9994 系数。当前为评分保存每月 Gram 的直接布局，未压缩数组分别需约 0.22 / 2.62 / 36.05 GiB（L6/L12/L24），因此加阶前先改为唯一观测域的 Gram 加月份索引，不能直接用 L24 运行现有内存布局。SST 的掩膜域条件数也须随加阶重新检查。这里是维度/内存预算，不是已经做完高阶训练。
