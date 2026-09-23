"""Build the board that shows every figure this repository can currently draw.

WHY A BOARD AND NOT A DIRECTORY OF PNGs
---------------------------------------
A figure without its boundary travels badly.  Someone opens the PNG, sees a
number, and quotes it -- and the sentence that said what the figure does NOT
establish was in a caption in a report nobody opened.  This repository has been
bitten by exactly that, which is why every figure script here carries its own
footer.

The board closes the loop: each figure is shown together with what it claims,
what it does not, which numbers were recomputed in this repository and which
were recorded from elsewhere, and the command that regenerates it.  It is a
snapshot, like the block page, and it says when it was generated.

Usage:
  python3 scripts/fig_board.py            # writes figures/index.html
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIGDIR = ROOT / "figures"

# One entry per figure.  `claim` is what the picture asserts; `boundary` is what
# it must not be read as asserting; `note` carries anything that changed while
# making it.  Kept next to the board rather than inside each script so that a
# figure and its reading can be compared side by side -- which is the only way
# the boundary ever gets checked against the picture.
FIGURES = [
    {
        "file": "level-problem.png",
        "script": "scripts/fig_level_problem.py",
        "title": "高原的地面在 850 hPa 之下",
        "kind": "实测",
        "claim": "ERA5 自己报的地面气压显示：高原框内大部分格点上 850 hPa 位于地下；"
                 "500 hPa 则几乎所有格点都在地面之上。右侧面板给了不依赖阈值的说法（位势差）。",
        "boundary": "这是 ERA5 的地形，不是真实地形；1.5° 格点装不下高原的真实起伏。"
                    "所以这些比例是关于「ERA5 怎么表示高原」的陈述 —— 而这正是向 ERA5 "
                    "或同量级网格提问时该用的那一句。",
        "why": "整份研究都建立在这一条几何事实之上，而它此前只是一个记录来的数（582.6 hPa）。",
    },
    {
        "file": "plane-ceiling.png",
        "script": "scripts/fig_plane_ceiling.py",
        "title": "「顶在上限」是读数，不是天气",
        "kind": "实测",
        "claim": "9 次归档运行、三个模式：GFS 的高原框有 51–58% 的格点顶在编码上限 357 K，"
                 "ECMWF 0–2.5%、AIFS 全为 0；两个对照区（含真正最暖的暖池）都不到 1%；"
                 "换到 500 hPa，饱和完全消失。",
        "boundary": "只用 poster（0.5° 降采样网格），未做重采样对齐；"
                    "「饱和」的阈值 = 上限 − 2 K 是选定的，不是从数据推出来的。",
        "why": "三条判据各自都能失败：跨运行不稳定 → 是天气；对照区也顶到 → 是真实高温；"
               "500 hPa 也顶到 → 层次解释不成立。三条都过了。",
    },
    {
        "file": "high-asia-fields.png",
        "script": "scripts/fig_high_asia_fields.py",
        "title": "同一个模式、同一个地方、两个层次：一个被削平，一个没有",
        "kind": "实测",
        "claim": "把场画出来：GFS 的 θe850 在高原框内一半以上落进「离上限 2 K 以内」的斜纹区，"
                 "框内中位 356.5 K；ECMWF 同一层次、同一框、同一量化，一格都没有，中位 325.0 K，"
                 "差 31.5 K。500 hPa 上一个都没有。",
        "boundary": "poster 是 0.5° 降采样网格，不是全分辨率 store。"
                    "色标用的是 xue 的颜色顺序、但按各变量自身的码位区间重标定 —— 这一处不是照抄，"
                    "是本图的改动，理由见下一张图。地图上没有任何外部底图："
                    "Natural Earth 两次下载都被截断，改用标注坐标。",
        "why": "p / a 的算术能说明报告里那些数，但说明不了「读这个产品的人看到的是什么」。",
    },
    {
        "file": "palette-reach.png",
        "script": "scripts/fig_palette_reach.py",
        "title": "色标到不了 θe850 所在的温度区间",
        "kind": "实测（在 xue 自己的代码上）",
        "claim": "xue 的 TEMPERATURE_STOPS 是摄氏 −60…50；θe850 的量化是 230＋0.5×code，"
                 "即 230–357 K。把归档里真实的量化喂进 xue 自己的 buildPalette，"
                 "255 个码位只得到 1 种颜色。同样这个函数对 tmp850/tmp2m/tmp500 分别给出 "
                 "211/221/151 种颜色。",
        "boundary": "这一条说的是本机 xue 检出里的调色板代码，不是线上页面。"
                    "thetae850 在本机 web/src 里根本不存在 —— 那张唯一的浏览器截图来自另一份"
                    "已不存在的构建，所以本图既不能证实也不能否证线上今天渲染成什么样。",
        "why": "报告 §576 曾用那张截图当作「高原在图上更亮」的证据。"
               "若色标本就不能分辨，那条证据的形状需要重新检查 —— 这一步只把边界说清楚，不替它下结论。",
    },
    {
        "file": "conventions.png",
        "script": "scripts/fig_conventions.py",
        "title": "问一个观测上没有定义的量，就会得到三种约定",
        "kind": "实测 + 记录",
        "claim": "同一三次归档运行，只换区域：高原框三模式中位极差 31.50 K，"
                 "暖池极差 1.50 K。ERA5 贴地给值、GFS 外推后被上限削平、MERRA-2 屏蔽 65.1%。",
        "boundary": "两处不可比性必须自己踩住：(1) MERRA-2 的有效子集均值是对「850 hPa 在地面之上」"
                    "的那 34.86% 格点求的，ERA5 是对整框求的，并排放会读成「MERRA-2 居中」；"
                    "(2) ERA5 是 63 年九月中位，其余是一次分析。另外，归档 poster 的暖池中位比记录来的 "
                    "ERA5/MERRA-2 暖池值高约 3.8 K，本图把它们分开谈，没有并进对照。",
        "why": "这是 CONTINUE.md 第四节说「最可能真正救人」的那一条："
               "任何建立在高原 850 hPa 上的风险指数都继承这套约定。",
    },
    {
        "file": "discrimination-ceiling.png",
        "script": "scripts/fig_discrimination_ceiling.py",
        "title": "精确率的上限由基率封顶",
        "kind": "代数 + 实测",
        "claim": "完美排序下 precision = p / a，与大气物理无关。"
                 "两个实测探测器的报警率在更正口径下是基率的 30–42 倍，在撤回口径下是 5,646 倍。",
        "boundary": "代数成立，数量级不成立：要定出「站年」必须先有冰川边界（RGI/GLIMS），"
                    "本仓库至今未取到。已被撤回的 6,204 与修正后的 33–44 都画在图上。"
                    "另记一处会踩的坑：scripts/discrimination_ceiling.py 的 POPULATIONS 里"
                    "仍写着已撤回的 564×11，更正只存在于 claims.toml 与报告 §3108 —— "
                    "本步没有改那个脚本，但在图面和 stdout 都标了出来。",
        "why": "「再找一个更好的特征」不会修好它 —— 这一条把问题从「找特征」转成「缩小总体」。",
    },
    {
        "file": "error-budget.png",
        "script": "scripts/fig_error_budget.py",
        "title": "判决取决于误差标准，不取决于数据",
        "kind": "实测",
        "claim": "同一次比对、同一个观测，一致性可以是 36.2% 或 94.5%。"
                 "重算把这一条推得更远：把记录的 7 时效（中位 −0.30 K、sd 2.13 K）当作一条正态，"
                 "两个判决被预测到 35.8% 与 95.2% —— 差 0.4 与 0.7 个百分点。"
                 "所以这个摆动不携带关于模式的信息，两个数完全由阈值决定。"
                 "用本步实测的代表性误差（0.94 K）作第二档标准，同一次比对读作 67.8%。",
        "boundary": "代表性误差是下限不是真值（机场集中在城市，同格点两站不横跨整个格点）。"
                    "按海拔分层时，2000 m 以上只有 2 组独立测站对（17 条配对观测），"
                    "这个方法对高原与喜马拉雅在结构上无法作答。"
                    "archive/ 已比 §3449 写它时大了约十九倍（观测 16,347 → 304,922 条，"
                    "测站对 478 → 4,261），所以报告里那个「478 对」是会过期的数，引用它必须带上数据量。"
                    "36.2%/94.5% 这次复算不了：三个归档 gfs 的 0.25° store 上游已 404，故标为 RECORDED。",
        "why": "与 ITS_LIVE 对岩体失明、PDD 91% 饱和同属一类："
               "限制不在数据量，而在观测所在的位置。",
    },
]


def read_json(name: str):
    p = FIGDIR / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:                                                 # noqa: BLE001
        return None


def key_numbers(entry: dict, data) -> list[str]:
    """The numbers this board is willing to repeat, taken from the JSON the
    figure itself wrote -- never retyped from the prose."""
    out = []
    if data is None:
        return out
    if entry["file"] == "plane-ceiling.png":
        for m in ("gfs", "ecmwf", "aifs"):
            v = [r["saturated_frac"] * 100 for r in data["thetae850"]
                 if r["model"] == m and r["region"].startswith("高原") and r["n"]]
            if v:
                out.append(f"{m} 高原饱和 {min(v):.2f}–{max(v):.2f}%")
        v = [r["saturated_frac"] * 100 for r in data["thetae850"]
             if r["region"].startswith("暖池") and r["n"]]
        out.append(f"暖池最大 {max(v):.2f}%")
    elif entry["file"] == "conventions.png":
        h = data["here"]
        pl = [h[c]["plateau_median"] for c in h]
        wp = [h[c]["warmpool_median"] for c in h]
        out.append(f"高原框三模式中位极差 {max(pl) - min(pl):.2f} K")
        out.append(f"暖池三模式中位极差 {max(wp) - min(wp):.2f} K")
        out.append(f"GFS 高原中位 {h['gfs']['plateau_median']:.1f} K，饱和 "
                   f"{h['gfs']['plateau_sat'] * 100:.1f}%")
    elif entry["file"] == "palette-reach.png":
        r = data["result"]
        out.append("θe850 " + str(r["thetae850"]["distinct"]) + " 色 / "
                   + str(r["thetae850"]["n_codes"]) + " 码位")
        out.append("对照 " + "，".join(f"{k} {v['distinct']} 色"
                                      for k, v in r.items() if k != "thetae850"))
    elif entry["file"] == "high-asia-fields.png":
        for k, st in data.items():
            if st.get("n"):
                out.append(f"{k} 中位 {st['median']:.1f}，饱和 "
                           f"{st['saturated_frac'] * 100:.2f}%")
    elif entry["file"] == "level-problem.png":
        out.append(f"高原框地面气压中位 {data['surface_pressure_median_hpa']:.1f} hPa")
        out.append("850 hPa 在地下 "
                   + f"{data['underground_frac']['850'] * 100:.1f}%")
        out.append("500 hPa 在地下 "
                   + f"{data['underground_frac']['500'] * 100:.1f}%")
        h = data["level_height_above_ground_m"]
        out.append(f"850 hPa 距地面中位 {h['850']['median']:+.0f} m")
        out.append(f"对照暖池 850 在地下 "
                   f"{data['warmpool_underground_frac_850'] * 100:.2f}%")
    elif entry["file"] == "error-budget.png":
        # Pull the numbers the card is allowed to repeat, and format them --
        # a raw JSON dump on the board is unreadable and gets skipped, which
        # defeats the point of showing the numbers at all.
        r = data.get("recomputed_here", {}).get("representativeness_0p25", {})
        if r:
            out.append(f"0.25° 现场重算：观测 {r.get('n_obs', 0):,} 条，"
                       f"同格同刻测站对 n={r.get('n_pairs', 0):,}，"
                       f"代表性 {r.get('repr_k', float('nan')):.2f} K")
        b = data.get("recomputed_here", {}).get("budget_shares_pct")
        if b:
            out.append("方差份额：" + "，".join(f"{k} {v:.1f}%"
                                            for k, v in b.items()))
        v = data.get("verdict_standards", {})
        if v.get("recorded_pct"):
            rec = [x for x in v["recorded_pct"] if x is not None]
            out.append("记录的两个判决：" + " / ".join(f"{x}%" for x in rec)
                       + "（同一分布读在两处阈值）")
        if v.get("normal_prediction_pct"):
            out.append("正态预测：" + " / ".join(
                f"{x:.1f}%" if isinstance(x, (int, float)) else "—"
                for x in v["normal_prediction_pct"]))
        for k, lab in (("elevation_bands_0p25", "海拔分层 0.25°"),
                       ("elevation_bands_0p5", "海拔分层 0.5°")):
            bands = data.get("recomputed_here", {}).get(k)
            if bands:
                out.append(lab + "：" + "，".join(
                    f"{b.get('band', b.get('label', '?'))} "
                    f"{b.get('repr_k', float('nan')):.2f} K"
                    if b.get("repr_k") is not None else
                    f"{b.get('band', b.get('label', '?'))} 样本不足"
                    for b in bands))
    elif entry["file"] == "discrimination-ceiling.png":
        pc = data.get("population_corrected_site_years")
        pw = data.get("population_withdrawn_site_years")
        if pc:
            out.append(f"更正的总体：{pc[0]}–{pc[1]} 站年"
                       f"（p = {data['base_rate_corrected'][0]:.2e}–"
                       f"{data['base_rate_corrected'][1]:.2e}）")
            out.append(f"已撤回的总体：{pw:,} 站年（p = {data['base_rate_withdrawn']:.2e}）")
        for name, d in (data.get("detectors") or {}).items():
            xc, xw = d.get("x_corrected_n"), d.get("x_withdrawn_n")
            if isinstance(xc, list):
                out.append(f"{name}：报警率 {d['alarm_rate']:.0%}，"
                           f"是基率的 {xc[0]:.0f}–{xc[1]:.0f} 倍（更正口径）"
                           f"／{xw:,.0f} 倍（撤回口径）")
        for name, d in (data.get("ceiling_pct") or {}).items():
            out.append(f"{name} 的精确率上限：{json.dumps(d, ensure_ascii=False)}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(FIGDIR / "index.html"))
    args = ap.parse_args()

    cards = []
    for i, e in enumerate(FIGURES, 1):
        png = FIGDIR / e["file"]
        data = read_json(e["file"].replace(".png", ".json"))
        nums = key_numbers(e, data)
        missing = "" if png.exists() else (
            '<div class="bad">这张图不在磁盘上 —— 尚未生成或已删除。'
            f'先跑 <code>{e["script"]}</code>。</div>')
        cards.append(f"""
<section class="card{' pending' if not png.exists() else ''}">
  <div class="head">
    <span class="num">{i:02d}</span>
    <h2>{e['title']}</h2>
    <span class="kind">{e['kind']}</span>
  </div>
  {missing}
  <a href="{e['file']}"><img src="{e['file']}" alt="{e['title']}"></a>
  <dl>
    <dt>它主张什么</dt><dd>{e['claim']}</dd>
    <dt>它不主张什么</dt><dd class="b">{e['boundary']}</dd>
    <dt>为什么要画</dt><dd>{e['why']}</dd>
    <dt>数字（本仓库现场重算）</dt>
    <dd class="nums">{'<br>'.join(nums) if nums else '—（本图未写 JSON，或尚未生成）'}</dd>
    <dt>重跑</dt><dd><code>{e['script']}</code></dd>
  </dl>
</section>""")

    gen = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    html = f"""<!doctype html>
<html lang="zh">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>可视化 · figures</title>
<style>
 :root {{ color-scheme: dark; --fg:#e8eaed; --dim:#9aa0a6; --line:#2b2f33;
          --ok:#57d9a3; --warn:#f5c26b; --bad:#ff7b72; --bg:#16181b;
          --card:#1c1f23; }}
 * {{ box-sizing:border-box; }}
 body {{ margin:0; padding:32px 28px 80px; background:var(--bg); color:var(--fg);
         font:14px/1.62 -apple-system,"Helvetica Neue","PingFang SC",
              ui-sans-serif,sans-serif; }}
 h1 {{ font-size:20px; margin:0 0 6px; font-weight:650; letter-spacing:.01em; }}
 .sub {{ color:var(--dim); font-size:12.5px; margin-bottom:8px; }}
 .rules {{ color:var(--dim); font-size:12.5px; max-width:980px;
           border-left:2px solid var(--line); padding-left:12px; margin:16px 0 30px; }}
 .rules b {{ color:var(--fg); font-weight:600; }}
 .card {{ background:var(--card); border:1px solid var(--line); border-radius:8px;
          padding:20px 22px 22px; margin:0 0 26px; max-width:1180px; }}
 .card.pending {{ opacity:.62; }}
 .head {{ display:flex; align-items:baseline; gap:12px; margin-bottom:14px; }}
 .head h2 {{ font-size:16.5px; margin:0; font-weight:640; flex:1; }}
 .num {{ color:var(--dim); font-variant-numeric:tabular-nums; font-size:13px;
         border:1px solid var(--line); border-radius:4px; padding:1px 7px; }}
 .kind {{ color:var(--ok); font-size:11.5px; border:1px solid var(--line);
          border-radius:999px; padding:2px 10px; white-space:nowrap; }}
 img {{ width:100%; display:block; border-radius:5px; background:#fff; }}
 dl {{ display:grid; grid-template-columns:148px 1fr; gap:5px 16px;
       margin:16px 0 0; }}
 dt {{ color:var(--dim); font-size:12.5px; }}
 dd {{ margin:0; font-size:13.5px; }}
 dd.b {{ color:var(--warn); }}
 dd.nums {{ font:12.5px/1.75 ui-monospace,SFMono-Regular,Menlo,monospace;
            color:var(--ok); }}
 code {{ font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace;
         color:var(--ok); }}
 .bad {{ color:var(--bad); font-size:13px; margin-bottom:12px; }}
 a {{ color:inherit; }}
 footer {{ color:var(--dim); font-size:12px; max-width:980px; }}
 @media (max-width:820px) {{ dl {{ grid-template-columns:1fr; }}
   dt {{ margin-top:8px; }} }}
</style>
<h1>目前能做的可视化</h1>
<div class="sub">生成于 {gen} · 这是<strong>快照</strong>，不是实时页 ·
 {sum(1 for e in FIGURES if (FIGDIR / e['file']).exists())}/{len(FIGURES)} 张在盘上 ·
 每一张都可以用卡片里给出的命令重跑</div>
<div class="rules">
 本页遵守本仓库的纪律，逐条写在卡片里：<br>
 <b>RECORDED 与 OBSERVED HERE 分开</b> —— 从论文或报告读来的数不是本仓库的测量，
 每张图都标了哪些是现场重算的；<br>
 <b>区分「未建立」与「无技巧」</b> —— 样本不足不是结论；
 <b>数字只从图自己写的 JSON 里抄</b>，不从散文里重打一遍；<br>
 <b>每张图都在自己的页脚写明边界</b> —— 一张没有边界的图会被引用成它没有主张的东西。
</div>
{''.join(cards)}
<footer>
 图与脚本都在 <code>xue-study/figures/</code> 与 <code>xue-study/scripts/</code>。
 本页由 <code>scripts/fig_board.py</code> 生成；它只读 <code>figures/*.json</code>，
 不参与任何计算 —— 图的数字由各自的脚本负责。
</footer>
</html>
"""
    Path(args.out).write_text(html, encoding="utf-8")
    n = sum(1 for e in FIGURES if (FIGDIR / e["file"]).exists())
    print(f"  写入 {args.out}（{n}/{len(FIGURES)} 张图在盘上）")
    for e in FIGURES:
        if not (FIGDIR / e["file"]).exists():
            print(f"    缺：{e['file']}  ← {e['script']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
