#!/usr/bin/env python3
"""换正经海陆掩膜，并用数据内的物理判别量独立交叉核对。

掩膜来源（出处记下来，本项目对上游引用要求可核）：
  https://psl.noaa.gov/thredds/fileServer/Datasets/ncep.reanalysis/surface_gauss/land.sfc.gauss.nc
  NCEP-NCAR Reanalysis 1，变量 `land`（0=海 1=陆），T62 高斯网格 94×192，25 KB。

独立核对：**t2m 的季节振幅**。陆地热容量小 ⇒ 季节振幅大；海洋热容量大 ⇒ 振幅小。
这是一个【数据内】的物理判别量，与官方掩膜来源完全独立（一个来自制图，一个来自能量收支）。
若两者高度一致，我们就有资格在这个网格上说「海陆」。

这也是本项目对「月平均」这条时间尺度的一贯态度：季节振幅正是月平均能看见的那个量。
"""
import hashlib
import shutil
from pathlib import Path

import numpy as np
import xarray as xr

# 原始 nc 在 ncep-multivariate/ 子目录下；land 掩膜我放在 climatetensor-inputs/ 根，
# 两处都要写对 —— 上一版把 nc 的路径少写了一层，于是「文件不存在」。
SRC = Path.home() / "climatetensor-inputs/ncep-multivariate"
MASK_NC = Path.home() / "climatetensor-inputs/land.sfc.gauss.nc"
DEST = Path("data")
DEST.mkdir(exist_ok=True)


def main() -> int:
    # 把掩膜存到持久位置并记录出处
    if not MASK_NC.exists():
        shutil.copy("/tmp/land.nc", MASK_NC)
    sha = hashlib.sha256(MASK_NC.read_bytes()).hexdigest()
    shutil.copy(MASK_NC, DEST / "land.sfc.gauss.nc")
    (DEST / "land.sfc.gauss.nc.provenance.txt").write_text(
        "source: https://psl.noaa.gov/thredds/fileServer/Datasets/ncep.reanalysis/"
        "surface_gauss/land.sfc.gauss.nc\n"
        "dataset: NCEP-NCAR Reanalysis 1, variable `land` (0=sea, 1=land)\n"
        f"grid: T62 gaussian, lat 94 x lon 192\nsha256: {sha}\n")
    print(f"  掩膜已存 data/land.sfc.gauss.nc  sha256 {sha[:24]}…")

    ds = xr.open_dataset(MASK_NC)
    land = ds["land"].isel(time=0).values.astype(float)
    mlat, mlon = ds["lat"].values.astype(float), ds["lon"].values.astype(float)
    print(f"  掩膜网格 lat {mlat[0]:.2f}→{mlat[-1]:.2f} ({mlat.size})  "
          f"lon {mlon[0]:.1f}→{mlon[-1]:.1f} ({mlon.size})")
    print(f"  陆地格点 {(land > 0.5).sum()} / {land.size} = {(land > 0.5).mean():.1%}")

    def is_land(la, lo):
        i = int(np.argmin(np.abs(mlat - la)))
        j = int(np.argmin(np.abs(((mlon - (lo % 360.0)) + 180) % 360 - 180)))
        return bool(land[i, j] > 0.5)

    # ---- 独立核对：t2m 季节振幅 ----
    t = xr.open_dataset(SRC / "ncep.reanalysis.derived__surface_gauss__air.2m.mon.mean.nc")
    var = [v for v in t.data_vars if "air" in v.lower()][0]
    tas = t[var].values.astype(float)                     # (time, lat, lon)
    tlat = t["lat"].values.astype(float)
    tlon = t["lon"].values.astype(float)
    tm = t["time"].dt.month.values
    clim = np.stack([np.nanmean(tas[tm == m], axis=0) for m in range(1, 13)])   # (12, lat, lon)
    amp = np.nanmax(clim, axis=0) - np.nanmin(clim, axis=0)
    # air.2m 也是 surface_gauss ⇒ 与 land 掩膜【同一网格】94×192，不需要插值。
    # 上一版构造了一套最近邻索引去插值，纯属多余，而且那是一类易错的写法。
    assert amp.shape == land.shape, f"网格不同: amp {amp.shape} vs land {land.shape}"
    assert np.allclose(tlat, mlat) and np.allclose(tlon, mlon), "同网格但坐标不一致"
    amp_on_mask = amp
    isl = land > 0.5
    print()
    print("  === 独立核对：t2m 季节振幅 vs 官方 land 掩膜 ===")
    print(f"    陆上格点 振幅中位数 {np.nanmedian(amp_on_mask[isl]):6.2f} K  "
          f"（{isl.sum()} 格）")
    print(f"    海上格点 振幅中位数 {np.nanmedian(amp_on_mask[~isl]):6.2f} K  "
          f"（{(~isl).sum()} 格）")
    for thr in (3, 5, 8, 10):
        pred = amp_on_mask > thr
        agree = (pred == isl).mean()
        print(f"    阈值 {thr:2d} K：与官方掩膜一致率 {agree:.1%}"
              f"（把 {int((pred & ~isl).sum())} 个海格误判为陆，"
              f"漏掉 {int((~pred & isl).sum())} 个陆格）")

    # ---- 我们实际采样的那些节点 ----
    print()
    print("  === 我们实际采样的节点（tropical，|z|=5/13,3/5） ===")
    for zname, z in (("5/13", 5/13), ("3/5", 3/5)):
        rad = float(np.sqrt(1 - z * z))
        la = float(np.degrees(np.arcsin(z)))
        for lo in (0.0, 90.0, 180.0, 270.0):
            n_land = is_land(la, lo)
            s_land = is_land(-la, lo)
            print(f"    |z|={zname:5s} 经度 {lo:5.1f}°  北 {la:+6.2f}°={'陆' if n_land else '海'}  "
                  f"南 {-la:+6.2f}°={'陆' if s_land else '海'}   → "
                  f"{'陆' if n_land else '海'}-{'陆' if s_land else '海'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
