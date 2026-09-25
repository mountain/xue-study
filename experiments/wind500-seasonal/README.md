# 500 hPa 风场谱学习与 Xue 发布，v1

这一轮实际训练了一个有限数值原型。它不是 Adva 原生学习器，不是 NOAA/CFSv2 预报的转发，也没有执行同化。

输入是 NOAA PSL 的 NCEP/NCAR 再分析 500 hPa 月平均 U/V 风，1979-01 至 2025-12。数据源实查更新至 2026-02，因此本轮固定为历史起报：2025-12 初始月，预测 2026-01—06，实际生成于 2026-09-24。没有重建历史业务实时资料可用性；不能称为当时已经发布的预报或今天起报的实时预报。

## 模型与对照

`contract.json` 在读取训练资料之前固定了表示、时间分割、候选阻尼和指标。

- 实球面矢量谐波 1—6 阶，共 96 个系数，旋转与梯度两类。以局部东、北分量建立基，按 cos(latitude) 加权求解 Gram 系统。
- 精确极点两行不参与投影；2.5° 发布网格不是 2.5° 的有效预报分辨率。
- 训练期每月气候态加独立系数 AR(1)。系数限制在 [-0.98, 0.98]；额外阻尼从 [0, .25, .5, .75, 1] 按验证集选择。没有学习模态耦合、海洋慢变量或外强迫。
- `full` 保留所有低阶异常；`even` 只保留偶阶旋转异常的 27 个系数。**两者均叠加相同完整季节气候态**。它不是对整张风场彻底删除奇阶的实验。
- 拟合 1979—2014（432 月）；验证 2015—2019（60 月）；测试 2020—2025（每个提前量 72 个目标月）。所有参数在测试前固定。

在本次留出数据的低阶投影上，full 一月提前量 MSE 比气候态低 9.05%，even 低 3.77%；full 三、六月仅低约 0.632%、0.033%。这是描述性回报结果，没有独立同分布样本假设、显著性承诺或半年业务技巧声明。完整分辨率误差和被截断部分的误差保留在报告中。

## 文件与复现

数值环境 `/home/ubuntu/climatetensor-env`；依赖版本在 archive 的 `requirements.txt`。

```bash
cd /home/ubuntu/xue-study/experiments/wind500-seasonal
/home/ubuntu/climatetensor-env/bin/python fetch.py
OPENBLAS_NUM_THREADS=2 /home/ubuntu/climatetensor-env/bin/python -m unittest test_model -v
OPENBLAS_NUM_THREADS=2 /home/ubuntu/climatetensor-env/bin/python train.py
```

缓存与证据位于 `/home/ubuntu/xue-study/archive/wind500-seasonal-v1/`：原始选层数据及下载凭据、模型系数、浮点预报、报告、编码回读与 Zarr 检查、浏览器检查与截图。`forecast.npz` 中有 full_u/full_v、even_u/even_v、lat/lon、months。输入缓存校验和见两个下载凭据。

发布适配器在独立工作树 `/home/ubuntu/climatetensor-xue` 的 `scripts/climatetensor_publish.py`。它直接使用 Xue 现有编码器/格式，不将我们的产品命名成 GFS 或 CFS。

```bash
cd /home/ubuntu/climatetensor-xue
.venv/bin/python scripts/climatetensor_publish.py \
  --inputs /home/ubuntu/xue-study/archive/wind500-seasonal-v1 \
  --output web/public/data
npm run build
```

已经存在的 v1 发布目录会被拒绝覆盖。再次发布不同结果必须创建新版本与独立指针，不得静默覆盖 v1。网页原始月份帧标记为月中 15 日；帧之间的动画只是显示插值。风分量量化步长 1 m/s，最大误差 0.5 m/s，浮点 NPZ 保留细小差异。

四个科学检查覆盖解析刚体旋转/梯度恢复、基的数值正交性、留出数据不改变拟合、异常投影与不足训练样本拒绝。网页另检查清单身份、必需风场、逐帧原生解码、标准 Zarr 读取、HTTP ranges、真实浏览器和手机显示。交付检查不能当作天气技巧验证。

## 下一步：共同研究同化

保留这份不做同化的冻结基线。先定义谱状态、观测位置/时次和误差，再定义观测算子 H 以及 R、B。月平均状态不能直接与瞬时观测作相同量比较；需要先统一时间窗口。还需解决当前资料时效，并按当时实际可用的数据做顺序检验。当前未选择或运行 EnKF、3DVar 或其他同化算法。
