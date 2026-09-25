# 基础气象变量：下一版实验的采集与学习配置

2026-09-24，按用户给出的 16 项扩展为 **23 个时变量 + 2 个静态辅助场**。
这是变量定义、资料源检查和取样入口；多变量模型尚未训练，也尚未发布这些新变量。
已经公开的 `wind500-seasonal` v1 仍是独立、冻结的历史实验。

## 清单

唯一配置源为 `variables.py`，由同一张表生成 `variables` 和 `codes`，避免两份列表错位。
避免用 Python 内置名 `vars` 当变量名。带 `_850hPa` 的名称是逻辑通道名；
下载时必须拆成源变量和压力层，不能把完整名称直接拿去索引 ARCO。

| 用途 | codes | 含义 |
|---|---|---|
| 学习候选：温度 | t850, t2m, sst | 850 hPa 温度、2 米气温、海表温度 |
| 学习候选：压力与高度 | sp, msl, z500 | 地面气压、海平面气压、500 hPa 位势 |
| 学习候选：水汽 | q850, q700 | 两层比湿；水汽含量与温度造成的饱和度变化分开表示 |
| 学习候选：水平风 | u850, v850, u500, v500, u250, v250 | 三层东、北风分量，成对进入矢量谱 |
| 学习候选：垂直运动 | w500, w700 | 气压垂直速度 omega，Pa/s，负值表示上升 |
| 学习候选：地表 | ssr, str, sd | 地表净短波、净长波、雪水当量 |
| 外部强迫 | tisr | 大气顶入射太阳辐射 |
| 诊断/检验 | z1000, r850, r700 | 1000 hPa 位势、两层相对湿度 |
| 静态辅助 | lsm, zs | 陆海掩膜、地表位势 |

19 个学习候选通道、1 个强迫、3 个诊断。该清单不是封闭的物理预报方程组，
增加变量本身不保证提升技巧；后续必须与已有风场基线做相同时间分割的留出比较。

相对于用户原表：保留全部 16 项物理量，补 `sp/msl/u500/v500/q850/q700/ssr`。
`2_metre_temperature` 映射为 CDS/ARCO 实际键 `2m_temperature`；
`total_incoming_shortwave_radiation` 映射为 `toa_incident_solar_radiation`，均保留旧名别名。
`ssr + str` 才是地表净辐射的短波与长波两部分，不能把大气顶 `tisr` 和地表 `str` 相加
称为地表净辐射。温度原始单位 K，压力 Pa，位势 m²/s²；需要位势高度时除以 9.80665。
`sd` 是米水当量，不是几何雪厚；本轮分析域只取陆地雪，海冰上的雪不计入。

## 时间、掩膜和谱的约束

- ERA5 小时再分析辐射累计量除以 3600 得 W/m²；官方整月月均产品的累计量
  有效时段为一天，除以 86400。不能根据文件的 6 小时采样间隔猜累计时段。
  转换函数对未知产品拒绝换算。遵循 ECMWF 向下为正约定，净长波的负号保留。
- 压力层只在 `sp >= 100 * level_hPa` 的位置作为地上资料使用，500/700 hPa 同样适用。
  不能用海平面气压代替地面气压。小时采集应先按同一时次掩膜再汇总，记录有效样本数；
  单用月均 sp 只能做月均筛查，不能保证这个月每小时均在地上。
- 海温与陆地雪分别用陆海掩膜和源的有限值标志限制有效域。首版海陆分界使用 0.5，
  所有网格、时次必须先对齐；原始取样脚本保存原值，不冒充已完成掩膜的数据集。
  不可把缺测、地下值或不适用区域填零后直接套用当前完整球面的谱投影。
- 相对湿度在 ERA5 压力层使用混合相饱和定义。`r` 与 `q` 不是名称转换，
  本轮不自行用缺少温度/饱和约定的公式生成 `r`，也不宣称月均量的非线性换算等于月均 RH。
- 温度、水汽、海温等标量需保留球面零阶均值；奇偶消融应独立设计，
  不能把风场删奇阶的实验机械搬到所有标量。矢量风保留局部东、北分量的正确几何。
- 每个通道的月气候态、标准化和拟合只能使用训练期；SST、雪、辐射等未来再分析
  不可作为预报时已知输入。未来 `tisr` 需要由日期/天文几何生成并单独验证，
  目前还没有实现未来强迫生成器。标记为 forcing 不代表未来实况可直接读取。

## 来源与采集方式

两个 ARCO 存储的实时元数据由 `check_sources.py` 检查，不凭变量名称假定可用。

- 1.5°、6 小时镜像：缺 `r850/r700/ssr/str/sd`。压力变量维度顺序是
  time, level, longitude, latitude，必须显式转成 latitude, longitude。
- 0.25°、逐小时镜像：有 `ssr/str/sd`，仍没有 `relative_humidity`。
  名称虽以 `.zarr-v3` 结尾，实际数组元数据标记 Zarr format 2。
  一个压力变量的块包含全部 37 层和全球网格，解压约 154 MB；不能因只选一个点
  就假定只下载一个点。取样优先用低分辨率源，只从细网格补三个地表变量。
- 官方 CDS 压力层/单层整月月均产品是完整训练历史的候选入口。
  `cds_monthly_requests()` 生成逐年请求计划，按变量及实际需要的层配对，
  不额外取所有变量与所有层的笛卡尔积。计划尚未提交，CDS 账户访问尚未验证。
  静态场另取，原始 ERA5 保存在仓库外并保留来源归属。

两种 ARCO 分辨率的单帧样本不能直接拼成训练数据。正式训练前还需统一网格、
时间窗口、历史覆盖、数据版本及可用时效，完成带掩膜的谱表示。
本轮不拼接 NOAA 风场历史和 ERA5 其他变量来冒充同一个再分析系统。

```bash
cd /home/ubuntu/xue-study/experiments/basic-state
/home/ubuntu/climatetensor-env/bin/python variables.py
/home/ubuntu/climatetensor-env/bin/python -m unittest test_variables -v

# 默认只读元数据，并生成未提交的 CDS 2020 年月均请求计划。
/home/ubuntu/climatetensor-env/bin/python check_sources.py \
  --report /home/ubuntu/xue-study/archive/basic-state-v1/source-audit.json

# 可选：精确读取一个历史时次；目标目录必须是新的仓库外目录。
/home/ubuntu/climatetensor-env/bin/python check_sources.py \
  --report /home/ubuntu/xue-study/archive/basic-state-v1/source-audit-with-sample.json \
  --sample-date 2020-01-01T00:00 \
  --sample-output /home/ubuntu/climatetensor-inputs/era5/basic-state-example
```

元数据检查只需要 Python 标准库；取样另需 numpy、xarray、zarr、fsspec、aiohttp。
测试验证单位、掩膜、字段覆盖和风分量配对，不是多变量预报的技巧检验。

## 官方参考

- [ERA5 数据文档：时间统计、参数和月均换算](https://confluence.ecmwf.int/spaces/CKB/pages/76414402/ERA5+data+documentation)
- [ARCO ERA5 变量表和数据块说明](https://github.com/google-research/arco-era5)
- [CDS 压力层月均](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-pressure-levels-monthly-means)
- [CDS 单层月均](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels-monthly-means)
