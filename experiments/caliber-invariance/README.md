# caliber-invariance（C-1 ＋ C-4 的执行件）

2026-09-29 起。执行提问方 2026-09-28 裁定的两条换代判据（`docs/lifecycle/README.md` §5）：

| 编号 | 判据 | 本件怎么量 |
|---|---|---|
| **C-1 非退化** | 选阶判据必须有**内部最优**，且该最优对口径扰动稳健 | 在 4 个**网格口径**上各跑一遍判据曲线，看 argmin 是否落在阶梯内部、位置是否随口径变 |
| **C-4 口径不变量** | 在 4 种网格口径上重做，原生方法的**不变读数显著多于**矩阵方法 | 逐读数比较 4 个网格口径上的取值；**只数非退化项**（端点最优、平凡常数不算） |

- `contract.json`：契约，跑之前冻结（sha256 记在维护记录里）。
- `run_caliber.py`：唯一入口。只读 `/home/ubuntu/climatetensor-inputs/**` 与
  `~/xue-assimilation/monthly/era5/2026-02/`；写 `archive/caliber-invariance-v1/report.json`（拒绝覆盖）。

## 怎么跑（在服务器上，数据在那边）

```bash
ssh ubuntu@34.200.151.98
cd ~/xue-study/experiments/caliber-invariance
/home/ubuntu/climatetensor-env/bin/python run_caliber.py 2>&1 | tee run.log
```

本机（macOS）没有 numpy，**跑不了**；本机只做编辑与语法检查。

## 相对 E1 的三处修正

E1（`experiments/vocabulary-accounting-e1/`）的判据退化被判为「不能定位最优阶数」。本件把 E1 自己
诊断出的两处缺陷补上，并补上 E1 账里缺的第三项：

1. **单位归一**：每通道除以自身训练期标准差；系数码长改用高斯码长，不再用「每系数 64 位」。
2. **留出项**：选择只用训练＋验证（1979-01…2019-12）；2020 年以后只报不选。
3. **无免费格点**：被域排除的格点按其自身气候态码长计费——没有这一项，判据必然偏向「域越小越好」。

主账（含第 3 项）与副账（不含）**并列报告**，让「这一项加与不加」的差别可见。
