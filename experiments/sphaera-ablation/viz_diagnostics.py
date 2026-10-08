#!/usr/bin/env python3
"""诊断可视化：做出【能看出不足】的图，不是好看的图。

五张图，每一张都对着一个具体的不足：

  fig1 采样几何 —— 我们的节点到底落在世界的哪里？四条子午线的混叠、海陆分层怎么选的、
       对径对跨过什么。这一张是整条线最该看的，因为反复出问题的都是采样几何。
  fig2 通道时间序列 —— E/O 长什么样、去季节后还剩什么、与 Niño3.4 的关系。
  fig3 宇称诊断 —— 所有几何的 |corr(E,O)| 与增量。看「双峰」到底成不成立。
  fig4 消融随 lead —— 增量怎么随预报时效衰减。看强配置与弱配置的分野。
  fig5 冗余与残差 —— 模型状态装下了 E/O 多少；残差修正在样本外怎么失败。

纪律：
  - 后端固定 Agg（无显示环境）。
  - 每张图落盘后断言文件存在且 > 20 KB —— 空白图也是合法 PNG，不检查就发现不了。
  - 数据缺失的图【跳过并打印原因】，不用假数据填。
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

sys.path.insert(0, ".")
import parity_report                                    # noqa: E402

plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
OUT = Path("figures")
OUT.mkdir(exist_ok=True)

GEOMS = {
    "ls_oo": ("runs/ls_oo/eo.npz", "海-海（64 节点）"),
    "ls_lo": ("runs/ls_lo/eo.npz", "陆-海（64 节点）"),
    "tropical": ("runs/tropical/eo-500.npz", "tropical（16）"),
    "declared": ("runs/declared/eo.npz", "declared（16）"),
    "paired8": ("runs/paired8/eo.npz", "paired8（32）"),
    "north": ("runs/north/eo.npz", "north（16，无配对）"),
    "northhi": ("runs/northhi/eo.npz", "northhi（16，无配对）"),
    "cross": ("runs/cross/eo.npz", "cross（16）"),
}


def load_mask():
    ds = xr.open_dataset(Path("data/land.sfc.gauss.nc"))
    return (ds["land"].isel(time=0).values.astype(float),
            ds["lat"].values.astype(float), ds["lon"].values.astype(float))


def xyz_to_latlon(nodes):
    n = np.asarray(nodes, float)
    lat = np.degrees(np.arcsin(np.clip(n[:, 2], -1, 1)))
    lon = np.degrees(np.arctan2(n[:, 1], n[:, 0])) % 360.0
    return lat, lon


def save(fig, name):
    p = OUT / name
    fig.savefig(p, dpi=130, bbox_inches="tight")
    plt.close(fig)
    sz = p.stat().st_size
    assert sz > 20000, f"{name} 只有 {sz} 字节 —— 可能是空白图"
    print(f"  ✓ {p}  {sz/1024:.0f} KB")
    return p


# ---------------- fig1 采样几何 ----------------
PYTH = ((1, 0, 1), (0, 1, 1), (3, 4, 5), (4, 3, 5), (5, 12, 13), (12, 5, 13),
        (8, 15, 17), (15, 8, 17), (7, 24, 25), (24, 7, 25), (20, 21, 29), (21, 20, 29))


def pool_nodes():
    """重现 sweep_landsea 的池：44 个勾股方位 × 2 个 |z|，每个方位南北各一节点。"""
    from fractions import Fraction as F
    az = []
    for c, sq, d in PYTH:
        for sc in (1, -1):
            for ss in (1, -1):
                v = (F(sc * c, d), F(ss * sq, d))
                if v not in az:
                    az.append(v)
    out = []
    for z, rad in ((F(5, 13), F(12, 13)), (F(3, 5), F(4, 5))):
        for c, sq in az:
            for sgn in (1, -1):
                out.append([float(rad * c), float(rad * sq), float(sgn * z)])
    return out


def _nodes_for(path, preset):
    p = Path(path)
    if p.exists() and p.name == "nodes.json":
        return json.loads(p.read_text())
    import extract_nodes as E
    return [list(v) for v in E.nodes(preset)]


def fig_sampling():
    land, mlat, mlon = load_mask()
    sets = [("runs/ls_oo/nodes.json", "ls_oo", "海-海配对 32 对"),
            ("runs/ls_lo/nodes.json", "ls_lo", "陆-海配对 32 对"),
            ("runs/paired8/nodes.json", "paired8", "paired8（4 环配对）"),
            ("runs/tropical/req.json", "tropical", "tropical（2 环配对）"),
            ("runs/north/eo.npz", "north", "north（无配对，对照）"),
            (None, None, "池：44 勾股方位 × 2 个 |z| = 176 对")]
    fig, axes = plt.subplots(2, 3, figsize=(19, 8))
    for ax, (path, preset, title) in zip(axes.ravel(), sets):
        ax.contour(mlon, mlat, land, levels=[0.5], colors="0.6", linewidths=0.5)
        if path is None:
            nodes = pool_nodes()
            note = "（全部候选，未分层）"
        else:
            try:
                nodes = _nodes_for(path, preset)
                note = ""
            except Exception as e:
                ax.text(0.5, 0.5, f"取不到 {preset}: {e}", ha="center", va="center")
                ax.set_axis_off()
                continue
        lat, lon = xyz_to_latlon(nodes)
        for i in range(0, len(lat) - 1, 2):
            d = ((lon[i + 1] - lon[i] + 180) % 360) - 180
            ax.plot([lon[i], lon[i] + d], [lat[i], lat[i + 1]],
                    "-", color="0.78", lw=0.5, zorder=1)
        north = lat > 0
        ax.scatter(lon[north], lat[north], s=18, c="#c0392b", marker="o",
                   edgecolors="k", linewidths=0.3, zorder=3)
        ax.scatter(lon[~north], lat[~north], s=18, c="#2471a3", marker="^",
                   edgecolors="k", linewidths=0.3, zorder=3)
        ax.set_xlim(0, 360); ax.set_ylim(-90, 90)
        ax.set_xticks([0, 90, 180, 270, 360]); ax.set_yticks([-60, -30, 0, 30, 60])
        ax.grid(alpha=0.25, lw=0.4)
        ax.set_title(f"{title}   {len(lat)} 节点{note}", fontsize=9)
    fig.suptitle("采样几何：红=北半球节点，蓝=南半球节点，灰线=对径对。"
                 "看『陆-海』的北半球节点压在北美/欧亚大陆，『海-海』的压在大西洋/太平洋"
                 "—— 这就是位置混杂", fontsize=11)
    fig.tight_layout()
    return save(fig, "fig1_sampling_geometry.png")


# ---------------- fig2 通道时间序列 ----------------
def fig_timeseries():
    s = np.load(Path.home() / "climatetensor-inputs/ncep-multivariate/sst.npz")
    sst, lat, lon = s["values"].astype(float), s["lat"].astype(float), s["lon"].astype(float)
    mla, mlo = (lat >= -5) & (lat <= 5), (lon >= 190) & (lon <= 240)
    box = sst[:, mla][:, :, mlo]
    n34 = np.nanmean(box.reshape(box.shape[0], -1), axis=1)

    fig, axes = plt.subplots(3, 1, figsize=(13, 9), sharex=True)
    for tag in ("ls_oo", "ls_lo"):
        z = np.load(GEOMS[tag][0])
        E, O, m = z["E"], z["O"], z["months"].astype(str)
        mon = np.array([x[5:7] for x in m])
        years = np.array([float(x[:4]) + (int(x[5:7]) - 1) / 12 for x in m])
        for ax, (v, nm) in zip(axes, ((E, "E（南北之差）"), (O, "O（|z| 加权和）"))):
            ax.plot(years, v, lw=0.8, label=f"{GEOMS[tag][1]} 原始", alpha=0.75)
            d = v.astype(float).copy()
            for mm in set(mon):
                k = mon == mm
                d[k] -= v[k].mean()
            ax.plot(years, d, lw=0.7, alpha=0.9, label=f"{GEOMS[tag][1]} 去季节")
            ax.set_ylabel(nm, fontsize=9)
            ax.grid(alpha=0.25, lw=0.4)
            ax.legend(fontsize=7, ncol=2)
    Na = n34.copy()
    for mm in set(np.array([x[5:7] for x in m])):
        pass
    axes[2].plot(years, n34, lw=0.9, color="k", label="Niño3.4 原始")
    axes[2].set_ylabel("Niño3.4 (°C)", fontsize=9)
    axes[2].grid(alpha=0.25, lw=0.4)
    axes[2].legend(fontsize=7)
    axes[2].set_xlabel("年")
    fig.suptitle("通道时间序列：最强配置（海-海）与最弱配置（陆-海）的 E、O", fontsize=12)
    fig.tight_layout()
    return save(fig, "fig2_parity_timeseries.png")


# ---------------- fig3 宇称诊断 ----------------
def fig_diag():
    tags, corrs, d1, cls = [], [], [], []
    for tag in GEOMS:
        p = Path(GEOMS[tag][0])
        if not p.exists():
            continue
        z = np.load(p)
        E, O, m = z["E"], z["O"], z["months"].astype(str)
        mon = np.array([x[5:7] for x in m])
        a, b = E.astype(float).copy(), O.astype(float).copy()
        for mm in set(mon):
            k = mon == mm
            a[k] -= E[k].mean()
            b[k] -= O[k].mean()
        tags.append(GEOMS[tag][1])
        corrs.append(float(np.corrcoef(a, b)[0, 1]))
        d1.append(parity_report.ablation(GEOMS[tag][0], 1)[0])
        cls.append("无配对" if "无配对" in GEOMS[tag][1] else "有配对")
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    order = np.argsort([abs(c) for c in corrs])
    cols = ["#c0392b" if c == "无配对" else "#2471a3" for c in cls]
    axes[0].barh([tags[i] for i in order], [abs(corrs[i]) for i in order],
                 color=[cols[i] for i in order])
    axes[0].set_xlabel("|去季节 corr(E, O)|")
    axes[0].set_title("双峰在不在？—— 红=无配对，蓝=有配对", fontsize=10)
    axes[0].grid(alpha=0.25, axis="x", lw=0.4)
    axes[1].barh([tags[i] for i in order],
                 [np.nan if d1[i] is None else d1[i] for i in order],
                 color=[cols[i] for i in order])
    axes[1].axvline(0, color="k", lw=0.8)
    axes[1].set_xlabel("M2−M1（RMSE Δ；负 = O 有增量）")
    axes[1].set_title("增量：负才好", fontsize=10)
    axes[1].grid(alpha=0.25, axis="x", lw=0.4)
    fig.suptitle("宇称诊断：配对与增量", fontsize=12)
    fig.tight_layout()
    return save(fig, "fig3_parity_diagnostic.png")


# ---------------- fig4 消融随 lead ----------------
def fig_leads():
    leads = (1, 2, 3, 4, 5, 6)
    fig, ax = plt.subplots(figsize=(10, 6))
    for tag, (path, label) in GEOMS.items():
        if not Path(path).exists():
            continue
        ys = [parity_report.ablation(path, k)[0] for k in leads]
        if any(y is None for y in ys):
            continue
        ax.plot(leads, ys, "o-", lw=1.4, ms=4, label=label)
    ax.axhline(0, color="k", lw=0.9)
    ax.set_xlabel("预报时效 k（月）")
    ax.set_ylabel("M2−M1（RMSE Δ）")
    ax.set_title("增量随预报时效衰减 —— 负=O 在 E 之上有增量", fontsize=11)
    ax.grid(alpha=0.3, lw=0.4)
    ax.legend(fontsize=8)
    fig.tight_layout()
    return save(fig, "fig4_ablation_leads.png")


# ---------------- fig5 冗余与残差 ----------------
def fig_redundancy():
    arch = Path.home() / "xue-study/archive/multivariate-l12-v1"
    if not (arch / "model.npz").exists():
        print("  跳过 fig5：缺 L12 归档")
        return None
    m = np.load(arch / "model.npz", allow_pickle=True)
    coef = m["coefficients"].astype(float); vec = m["vectors"].astype(float)
    clim = m["climatology"].astype(float); scale = m["scale"].astype(float)
    dates = m["dates"].astype(str)
    mint = np.array([int(s[5:7]) for s in dates]) - 1
    x_enc = (coef - clim[mint]) / scale
    S = x_enc @ vec
    z = np.load("runs/ls_oo/eo.npz")
    E, O, em = z["E"], z["O"], z["months"].astype(str)
    assert (em == dates).all()
    mon = np.array([s[5:7] for s in dates])

    def de(v):
        o = v.astype(float).copy()
        for mm in set(mon):
            k = mon == mm
            o[k] -= v[k].mean(axis=0) if v.ndim > 1 else v[k].mean()
        return o
    Sa, Ea, Oa = de(S), de(E), de(O)
    tr = dates <= "2014-12"; bt = dates >= "2020-01"

    fig, axes = plt.subplots(1, 3, figsize=(16, 5.2))
    # (a)(b) 冗余散点
    for ax, (y, nm) in zip(axes[:2], ((Ea, "E"), (Oa, "O"))):
        X = np.column_stack([Sa[tr], np.ones(tr.sum())])
        b, *_ = np.linalg.lstsq(X, y[tr], rcond=None)
        pred = np.column_stack([Sa[bt], np.ones(bt.sum())]) @ b
        r2 = 1 - ((y[bt] - pred) ** 2).sum() / ((y[bt] - y[tr].mean()) ** 2).sum()
        ax.scatter(y[bt], pred, s=12, alpha=0.6)
        lim = [min(y[bt].min(), pred.min()), max(y[bt].max(), pred.max())]
        ax.plot(lim, lim, "k--", lw=0.9)
        ax.set_xlabel(f"{nm} 实测（去季节）")
        ax.set_ylabel(f"模型 64 维状态预测的 {nm}")
        ax.set_title(f"{nm}：回测期 R² = {r2:.3f}", fontsize=10)
        ax.grid(alpha=0.25, lw=0.4)
    # (c) 残差修正的技巧变化
    leads = (1, 2, 4, 6)
    base, aug = [], []
    for k in leads:
        bt_idx = np.where(bt)[0]
        enc = np.stack([(x_enc[i - k] @ vec) @ m["maps"][k - 1] for i in bt_idx])
        y = x_enc[bt_idx]
        base.append(1 - ((y - enc) ** 2).sum() / (y ** 2).sum())
        tr_idx = np.where(tr)[0]; tr_idx = tr_idx[tr_idx + k < len(dates)]
        err = x_enc[tr_idx + k] - np.stack([(x_enc[i] @ vec) @ m["maps"][k - 1] for i in tr_idx])
        res = {}
        for nm2, v in (("E", Ea), ("O", Oa)):
            b, *_ = np.linalg.lstsq(np.column_stack([de(v)[tr_idx], np.ones(len(tr_idx))]),
                                    err, rcond=None)
            res[nm2] = b
        corr = enc + sum(np.column_stack([de(v)[bt_idx - k], np.ones(len(bt_idx))]) @ res[nm2]
                         for nm2, v in (("E", Ea), ("O", Oa)))
        aug.append(1 - ((y - corr) ** 2).sum() / (y ** 2).sum())
    xs = np.arange(len(leads))
    axes[2].bar(xs - 0.2, base, 0.4, label="基线（模型自身）", color="#2471a3")
    axes[2].bar(xs + 0.2, aug, 0.4, label="+E/O 残差修正", color="#c0392b")
    axes[2].set_xticks(xs); axes[2].set_xticklabels([f"k={k}" for k in leads])
    axes[2].set_ylabel("技巧（1 − MSE/MSE_气候态）")
    axes[2].set_title("残差修正：四个时效全部劣化", fontsize=10)
    axes[2].legend(fontsize=8); axes[2].grid(alpha=0.25, axis="y", lw=0.4)
    fig.suptitle("冗余与残差：模型状态已装下大部分 E/O，残差样本外失效", fontsize=12)
    fig.tight_layout()
    return save(fig, "fig5_redundancy_residual.png")


def main() -> int:
    made = []
    for fn in (fig_sampling, fig_timeseries, fig_diag, fig_leads, fig_redundancy):
        try:
            r = fn()
            if r:
                made.append(r)
        except Exception as e:
            print(f"  ✗ {fn.__name__} 失败: {type(e).__name__}: {e}")
    print(f"\n  共 {len(made)} 张图落在 {OUT}/")
    return 0 if made else 1


if __name__ == "__main__":
    raise SystemExit(main())
