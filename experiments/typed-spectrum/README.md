# 有类型的球面谱与时间谱原型

2026-09-24。状态：表示、合成演化和单时次真实场拟合已运行；尚未训练多变量时间模型。
原始资料在仓库外，派生报告位于 `../../archive/typed-spectrum-v1/`。

## 空间表示

`spectrum.py` 区分位置球面 r 与观测方向球面 a。局部向量 v 的响应为 a·v，
局部对称张量 Q 的响应为 aᵀQa；分别有完整球面上的反演公式。
局部标量是方向无关的，但全球标量场 f(r) 可以包含任意空间阶数。
整个场使用 dΩ/(4π) 下正交的实球谐，零阶为 1；切向风使用
∇Y/√ℓ(ℓ+1) 与 r×∇Y/√ℓ(ℓ+1) 两族。

标量卷积 Q_K、风的散度响应 D_K 和旋度响应 R_K 是不同物理通道。
原 sphaera 风谱对应 R_K 的 K(x)=|x|，会消去梯度风和奇数阶旋转风。
补充 K(x)=x|x|/2 的奇核和梯度通道，或保留截断范围内完整系数，可以表达这些区别。
`wind_channels` 输出单位球面角散度/旋度；物理散度/旋度需除以半径。
垂直速度 w 是压力坐标 omega（Pa/s），在单个等压面按标量处理。

掩膜先于投影：SST 只拟合海洋、等压面只拟合地上点，两风分量共用有效域。
受限域 Gram、秩、条件数与 ridge 均显式报告；域外的谱延拓不是观测。
不能将陆地 SST 或地下无效值填零后当作完整球面资料。

## 演化与时间频率

`advection_operator` 只实现给定定常风下的 Galerkin 标量平流；没有风场反馈、
热力学或水汽过程。刚体旋转例子检验均值、平方范数和传播相位。
原偶风谱对非零整体旋转响应为零，因而仅保留该响应不能确定标量的未来位置。

`temporal.py` 将实余弦/正弦对编码成 C=a_real+i a_imag，保留复相位。
采用这个约定，向东刚体输送给出 C(t)=C(0)exp(i m Ω t)，标准 FFT 峰在 +mΩ。
它与通常复球谐系数的共轭约定不同，不能混用符号。
FFT 要求有限值、严格递增的等间隔采样；缺测不自动插值。
输出双侧频率、复幅度、窗归一化功率、频率分辨率和 Nyquist；没有预测功能。
Hann 幅度未作相干增益修正；精确正弦幅度示例使用矩形窗。

`check_time_bridge.py` 同时检验空间阶数与时间周期不能混同：
纯 ℓ=2 场可以有精确三步周期而保持所有状态间距离，不能据此套用区间混沌定理。
`annual-contract.json` / `check_annual.py` 检验年周期加独立扰动、调幅、调相及一个
标量周期系数微分方程。四年扰动是指定的合成参数，不是发现的气候周期。
完整解释与 Adva 阅读记录见 [研究笔记](../../docs/sphaera-spacetime-and-adva-periods.md)。

## 已完成的核对

| 检查 | 结果及边界 |
| --- | --- |
| `test_spectrum.py` | 11 项通过：局部反演、基底、奇偶核、旋转协变、掩膜/秩拒绝、平流与不可辨识驱动 |
| 解析刚体平流 | 最大误差 1.71e-12；均值漂移为零；无天气预报含义 |
| ERA5 2020-01-01 单时次 | 12 标量与 3 个风层，L=6；只报告域内拟合残差 |
| SST 掩膜对照 | 海洋拟合 RMSE 1.436 K；原始绝对温度在陆地填零的对照为 68.895 K |
| 联合时空谱 | (ℓ,m)=(1,1),(2,1),(2,2) 在 Ω=1 下频率为 1,1,2；Parseval 误差 8.89e-16 以下 |
| 年周期检验 | 独立四年扰动产生 0.25 次/年；调幅产生 0.75 和 1.25 次/年；训练期拟合不受留出值污染 |
| 球面交互页 | 桌面/手机、滑块、动画、下载链接、无页面异常通过 |

真实单时次并未覆盖全部 23 变量。RH 无样本；高分辨率 ssr/str/sd 尚需专门的
重网格验证。辐射 tisr 保留源 J/m²，未由本实验推断累积时长。
新空间基底与旧 `wind500-seasonal/train.py` 的系数排列不同；读取旧模型必须用旧标签。
此前已经发表的 wind500 v1 没有被改写；它有逐月气候态和全年共用的逐系数 AR(1)。

## 查看与重放

先打开 `../../archive/typed-spectrum-v1/demo.html`（球面）或
`../../archive/typed-spectrum-v1/annual-demo.html`（年周期）。它们是本机研究页面。

在本目录执行，输出目录或文件必须是新的：

```sh
OPENBLAS_NUM_THREADS=2 /home/ubuntu/climatetensor-env/bin/python -m unittest test_spectrum -v
OPENBLAS_NUM_THREADS=2 /home/ubuntu/climatetensor-env/bin/python run.py --output /tmp/typed-spectrum-replay
timeout 15s env OPENBLAS_NUM_THREADS=2 /home/ubuntu/climatetensor-env/bin/python check_time_bridge.py --output /tmp/time-bridge-replay.json
timeout 15s env OPENBLAS_NUM_THREADS=2 /home/ubuntu/climatetensor-env/bin/python check_annual.py --output /tmp/annual-check-replay.json
```

真实场重放依赖 `contract.json` 指定的仓库外 NPZ 和变量注册表。
`run.py` 生成球面演示；年周期页面由本目录的静态 HTML 直接复制到产物目录。
Adva 复核的有限精确试验与原生 Rust 测试单独存于
`../../archive/adva-period-three-review-20260924/`，不构成新的 Adva 原生天气学习器。
