#!/usr/bin/env python3
"""定位：为什么 mine 与 stored 对不上。打印分布与离群位置，不推理。"""
from pathlib import Path
import numpy as np

ARCH = Path.home() / "xue-study/archive/multivariate-l12-v1"
m = np.load(ARCH / "model.npz", allow_pickle=True)
coef = m["coefficients"].astype(float); vec = m["vectors"].astype(float)
maps = m["maps"].astype(float); clim = m["climatology"].astype(float)
scale = m["scale"].astype(float); dates = m["dates"].astype(str)
bt = np.load(ARCH / "backtest.npz", allow_pickle=True)
stored = bt["joint"].astype(float)
print("  backtest.npz 全部键与其形状：")
for k in bt.files:
    print(f"    {k:22s} {bt[k].shape}")
print(f"  target_months 前 3 个: {bt['target_months'][:3]}  后 3 个: {bt['target_months'][-3:]}")
print()

mint = np.array([int(s[5:7]) for s in dates]) - 1
x_enc = (coef - clim[mint]) / scale
test = np.where(dates >= "2020-01")[0]
print(f"  test 索引 {test[0]}..{test[-1]}  共 {len(test)}")
print(f"  x_enc[test] 分位数 {np.percentile(x_enc[test], [0,1,50,99,100]).round(4)}")
print(f"  stored[0]   分位数 {np.percentile(stored[0], [0,1,50,99,100]).round(4)}")
print()
mine = np.stack([(x_enc[i - 1] @ vec) @ maps[0] for i in test])
print(f"  mine        分位数 {np.percentile(mine, [0,1,50,99,100]).round(4)}")
d = np.abs(mine - stored[0])
print(f"  |Δ|         分位数 {np.percentile(d, [50,90,99,100]).round(4)}")
j = np.unravel_index(np.argmax(d), d.shape)
print(f"  最大差在 (月 {j[0]}, 格点 {j[1]})  mine={mine[j]:.4g} stored={stored[0][j]:.4g}")
# 哪个通道？格点索引到通道的映射
ch = __import__("json").loads(str(m["channels_json"]))
print(f"  channels_json 类型 {type(ch).__name__}  长度 {len(ch)}")
print(f"  前 2 项: {str(ch[:2])[:300]}")
