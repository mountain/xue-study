# 2026-09-24 基础变量配置与资料源实查

用户给出 16 个基础物理量并授权自行修改。新增
`experiments/basic-state/{variables.py,check_sources.py,test_variables.py,README.md}`。
可直接核查的入口是 `experiments/basic-state/README.md`。
全部原物理量保留，补 sp、msl、u500、v500、q850、q700、ssr。
合计 23 个时变量：19 个学习候选、1 个外部强迫、3 个诊断；另有 lsm、zs 两个静态辅助。

变量表统一生成名称/codes；纠正 t2m 和 tisr 的源键。记录 K、Pa、位势、omega、
雪水当量以及辐射累积单位。实现显式产品辐射换算和地上/海陆域掩膜；
这些函数尚未接入一个多变量学习器。月均地面气压筛查不等于小时地下值剔除。

现场检查两个 ARCO ERA5 `.zmetadata`：低分辨率源缺 RH、净短波、净长波、雪水当量；
高分辨率源有后三项、仍缺 RH。单位核对全部通过。高分辨率源当时元数据报告
final ERA5 至 2026-06-30，ERA5T 至 2026-09-18；这不是我们预报系统的资料时效。

实读取样为 **2020-01-01 00 UTC 单时次**：21 个可用时变量、2 个静态场。
精确选择压力层，显式经纬维度转置。低分辨率原始选场 NPZ 1,912,812 字节，
高分辨率 ssr/str/sd NPZ 4,921,122 字节。样本保存于仓库外
`/home/ubuntu/climatetensor-inputs/era5/basic-state-smoke-20200101/`，
完整 sha256、字段范围、有限值比例在 `receipt.json`。
源核查与取样摘要：`archive/basic-state-v1/source-audit.json`。
此样本是原始场，尚未做掩膜、重网格、辐射换算或月均；没有将两种网格拼成训练输入。
RH 保留官方 CDS 月均请求项，未自动从 q 近似转换。

检查：`test_variables` 4/4 通过（保留原量/风配对、辐射时间尺度、地下/陆海掩膜、
CDS 请求精确覆盖）；methodology_check 7/7 通过，其中 Adva 卡片验证器依旧不可用，
该子步骤是跳过而非验证通过。git diff --check 通过。

数值环境增加 zarr 3.1.6 与依赖，供源读取使用。最初使用 Xue 环境因缺 fsspec 失败，
空输出目录删除后改用数值环境，重试成功；没有更改 Xue 编码器环境。

当前完成的是配置、源核查、单时次下载与未提交的 CDS 月均请求计划。
未训练多变量模型，未执行同化，未新增网站预报变量，未更改冻结 wind500 v1。
下一步先统一月均历史、网格与有效域，再设计标量/矢量谱与联合学习的预注册留出实验。
