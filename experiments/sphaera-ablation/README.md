# sphaera-ablation：把旧观测与新观测做成消融对，接上季节预报

**起自** `sphaera-frame` README 末句自己写下的那一问：

> whether the added channel carries information about a specified future
> monthly/seasonal target **after conditioning on the original channel, season
> and slow-variable baselines**. The old and new observers should remain
> available as an **ablation pair**.

**数据**（提问方 2026-10-08 选定 C）：R1 + 月平均，`u/v` 在 250/500/850 hPa，
**1979-01 … 2025-12，564 个月** —— 与链式外推的 `development_backtest` **同一个窗口**。

## 已跑通的链路

```
R1 月平均 u/v (2.5° 网格, 73×144)
  → 双线性插值到 sphaera 的 16 个声明节点
  → 转成笛卡尔切向分量 (u_x, u_y, u_z)
  → request.json（564 case × 48 输入）
  → 【真正的 adva-lisp kernel】求值
  → 每月一个 (E, O)
```

```
native functions=12, evaluations=564, bytes=3254295, exit 0
runs/run-001/{request.json, native.json, eo.npz}
```

## 读数（850 hPa，564 月）

```
E  sd ?            范围 ?
O  均值 +3.3423    sd 0.3788    范围 [+2.4208, +4.2559]
corr(E, O) = +0.5830        ← 相关但不共线 ⇒ 消融不是退化的
```

**两者都有强季节循环：**

```
6–8 月   E 最负 (−2.44 … −2.72)   O 最低 (+2.93 … +3.05)
11–1 月  E 最接近 0 (−0.94 … −0.97)  O 最高 (+3.64 … +3.77)
```

⇒ **季节循环主导**。所以消融**必须去掉季节循环**，或把「季节」作为基线预测子 ——
这正是 `sphaera-frame` 那句「after conditioning on ... season」的意思。

## 两处被契约挡住、已按规矩解决

1. **求值预算**：探针 `main.rs:36` 写死 `cases.len() > 512` 即拒；而契约的
   `evaluations: 512` 与之对应。**564 > 512 ⇒ 被拒**。
   **本实验自带探针与契约**（`src/main.rs` 把上限提到 4096 并写明理由），
   **不改 `sphaera-frame` 已冻结的探针**。
2. **写死的对照要求完整函数集**：探针无条件求值 `compiled["turn-i"]`，
   只声明 `["spectrum"]` 会 panic（`no entry found for key`）。
   ⇒ request 必须声明全部 12 个导出；只有 `spectrum` 带 case。

## 一处**未消解**的几何缺口（必须与读数同时出现）

声明节点纬度是 **asin(3/5)=36.87°** 与 **asin(4/5)=53.13°**，
而 R1 月平均的 2.5° 网格上是 **37.5°** 与 **52.5°**，差 **0.63°**。

**程序里烤死的权重对应 z=±3/5, ±4/5，采样点实际在 z=±0.6088 / ±0.7986 上。**
本件用双线性插值逼近，**但插值不消除这个落差**。经度方向恰好落在网格上（0/90/180/270），无需插值。

## 尚未做

- **消融本身**（目标变量、去季节、时序外样本、E vs E+O 的技巧比较）**未做**。
- 只跑了 850 hPa；250/500 hPa 未跑。
- 未做 ERA5（选项 D）的对比 —— 见下。
