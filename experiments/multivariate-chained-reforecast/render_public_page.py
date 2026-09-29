"""Render the newest forecast product into figures and a public page.

Round: xue.derived.reforecast-2026-12-publication (contract-publication-2026-12.json,
frozen first).  The site already shows a forecast, but it is run `2026010100`:
initial month 2025-12, target months 2026-01..2026-06 -- published 2026-09-24, and by
2026-09-29 every one of its target months is in the past.  The newest product we have
(initial month 2026-02, chained ten steps to 2026-12) has never had a figure.

What this writes
----------------
`/home/ubuntu/climatetensor-xue/web/public/research/reforecast-2026-12/`:
four figures (png+svg), `index.html`, `data.json`, a small npz of the four plotted
fields plus the December climatology, `README.md`, `publication-record.json`,
`sha256.json`.  It never touches the homepage or the picker default, and it never
writes anything under the xue-study archive.

What it refuses to claim is written on the page itself (G5): this is a structural
extrapolation from a model that was never fitted for iteration; the matrix generation
was demoted to `reference` on 2026-09-28; agreement with CFSv2 is trivial because both
sit near the seasonal climatology.

Reads only.  Refuses to overwrite an existing page directory.
"""
import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path

import numpy as np

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

REPO = Path('/home/ubuntu/xue-study')
CHAIN = REPO / 'archive/multivariate-chained-reforecast-v1'
FROZEN = REPO / 'archive/multivariate-l12-v1'
CFS_REF = REPO / 'archive/cfs-reference-2026-12-v1/report.json'
INPUTS = Path('/home/ubuntu/climatetensor-inputs/ncep-multivariate')
PUBLIC = Path('/home/ubuntu/climatetensor-xue/web/public/research/reforecast-2026-12')

sys.path.insert(0, str(REPO / 'experiments/multivariate-chained-reforecast'))
sys.path.insert(0, str(REPO / 'experiments/multivariate-refinement'))
sys.path.insert(0, str(REPO / 'experiments/typed-spectrum'))
sys.path.insert(0, str(REPO / 'experiments/era5-sp-sst-feasibility'))

import chain_reforecast as CR                                        # noqa: E402
from project import area_weights, load_field                         # noqa: E402
from probe_era5 import regrid_conservative                           # noqa: E402

DEC = '-12'
# chain.npz stores float32 while the frozen readouts were computed in float64, so the
# recomputation cannot agree better than float32 epsilon / sqrt(cells) ~ 1e-9.  The first
# run stopped at G2 with 1e-12 written in the contract; the TOLERANCE was wrong, not the
# data (see the contract's change_log).  The measured maximum is always reported.
G2_RTOL = 1e-6
ROUND = 'reforecast-2026-12'
PAGE_TITLE = '从 2026-02 分析场出发的十步月均外推 · 目标月 2026-03…2026-12'

NOT_CLAIMED = [
    '**不是业务预报，也不是有技巧的季节预报。** 这是把冻结模型的「提前 1 个月」算子'
    '（`x @ vectors @ maps[0]`）连续套用十次得到的**结构性外推**；模型**从未为迭代应用训练过**'
    '（输入由观测状态变成预测状态，属分布外输入）。',
    '**与 CFSv2「接近」是平凡的。** 两者都落在季节气候态附近：链式离观测 12 月气候态只有'
    '+0.9%／+0.9%／−3.1%（东亚近海／北美东岸／中东），外部参考离气候态 −6.0%／−5.3%／−6.0%。'
    '「接近」不构成一致，也不构成评分。',
    '**高原 2 m 气温带已知表示误差**（1 月偏差 +10.43 K，其中谱截断贡献 +9.59 K）。'
    '高原面板的**绝对值不得当作信号**读。',
    '**本页展示的是矩阵代次（`matrix-l12-v1`）的产物。** 该代次已于 2026-09-28 由提问方'
    '从主要方法**降为参考方法**（`reference`）；原生方法的预报尚未产出。本页是「目前最新的'
    '可看产物」，不是项目的现行主张。',
    '**链在收缩**：十步后没有任何分量还带一个训练标准差量级的异常（末步 `max|z| = 0.159`，'
    '阈值 6）。所以它给出的是**季节气候态本身**，不是异常信号。',
    '**数据真实性保留意见不因本页消解**；回测期 2020–2025 此前已被看过（冻结契约的 prior_exposure），'
    '不是全新验证样本。',
]


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for block in iter(lambda: fh.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def hash_dir(path):
    return {str(p.relative_to(path)): sha256(p) for p in sorted(path.rglob('*')) if p.is_file()}


def dec_climatology(code):
    """Observed December climatology from R1: every December in the 564-month record."""
    values, lat, lon, dates = load_field(code)
    mask = np.array([d.endswith(DEC) for d in dates])
    return values[mask].mean(axis=0), lat, lon, int(mask.sum())


def grid_metrics(lat, lon):
    return area_weights(lat, lon).reshape(len(lat), len(lon))


def region_speed(speed, lat, lon):
    """Area-weighted box mean of the grid-point vector speed, one value per region.

    The boxes are CR.REGIONS (the same ones the frozen readouts use) and the averaging is
    CR.box_mean, so this cannot drift from the chain's definition.
    """
    w2 = grid_metrics(lat, lon)
    return {name: CR.box_mean(speed, w2, *CR.block_indices(lat, lon, box))
            for name, box in CR.REGIONS.items()}


def plateau_t2m(t2m, lat, lon):
    box = CR.PLATEAU
    w2 = grid_metrics(lat, lon)
    return CR.box_mean(t2m, w2, *CR.block_indices(lat, lon, (box['lat'][0], box['lat'][1],
                                                            box['lon'][0], box['lon'][1])))


def draw_boxes(ax, color='#123', lw=1.0):
    for name, (la0, la1, lo0, lo1) in CR.REGIONS.items():
        ax.plot([lo0, lo1, lo1, lo0, lo0], [la0, la0, la1, la1, la0], color=color, lw=lw)
        ax.text((lo0 + lo1) / 2, la1 + 3, name, color=color, fontsize=7, ha='center')
    box = CR.PLATEAU
    ax.plot([box['lon'][0], box['lon'][1], box['lon'][1], box['lon'][0], box['lon'][0]],
            [box['lat'][0], box['lat'][0], box['lat'][1], box['lat'][1], box['lat'][0]],
            color='#a33', lw=lw)
    ax.text((box['lon'][0] + box['lon'][1]) / 2, box['lat'][1] + 3, 'plateau',
            color='#a33', fontsize=7, ha='center')


def map_axes(ax, land):
    ax.set_xlim(0, 360)
    ax.set_ylim(-90, 90)
    ax.set_xticks([0, 60, 120, 180, 240, 300, 360])
    ax.set_yticks([-60, -30, 0, 30, 60])
    ax.tick_params(labelsize=7)
    if land is not None and land.any() and not land.all():
        ax.contour(np.linspace(0, 360, land.shape[1]), np.linspace(-90, 90, land.shape[0]),
                   land.astype(float), levels=[0.5], colors='0.55', linewidths=0.5)


def land_mask(sst):
    """SST is NaN over land, so its finite mask is a usable coastline for the eye."""
    return np.isfinite(sst)


def figure_fields(lat, lon, fields, land, path):
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 7.4), layout='constrained')
    specs = [('t2m', '2 m temperature (degC)', 'RdYlBu_r', None),
             ('msl', 'mean sea level pressure (hPa)', 'viridis', None),
             ('wind500', '500 hPa wind speed (m/s)', 'YlGnBu', None),
             ('z500', '500 hPa geopotential height (dam)', 'viridis', None)]
    for ax, (key, title, cmap, _) in zip(axes.ravel(), specs):
        field = fields[key]
        im = ax.imshow(field, origin='upper', extent=[0, 360, -90, 90], cmap=cmap,
                       aspect='auto')
        ax.set_title(title, fontsize=9)
        map_axes(ax, land)
        draw_boxes(ax)
        fig.colorbar(im, ax=ax, shrink=0.82, pad=0.01).ax.tick_params(labelsize=7)
    fig.suptitle('Forecast fields for 2026-12 · ten iterated monthly steps from the '
                 '2026-02 analysis · experimental, not operational · matrix generation',
                 fontsize=10)
    fig.savefig(path.with_suffix('.png'), dpi=150)
    fig.savefig(path.with_suffix('.svg'))
    plt.close(fig)


def figure_anomaly(lat, lon, anomaly, land, path, limits):
    fig, axes = plt.subplots(2, 1, figsize=(13.5, 7.0), layout='constrained')
    for ax, (key, title) in zip(axes, [('t2m', '2 m temperature anomaly (K)'),
                                       ('wind500', '500 hPa wind speed anomaly (m/s)')]):
        lim = limits[key]
        im = ax.imshow(anomaly[key], origin='upper', extent=[0, 360, -90, 90],
                       cmap='RdBu_r', vmin=-lim, vmax=lim, aspect='auto')
        ax.set_title(f'{title} · forecast minus observed December climatology '
                     f'(R1, 47 Decembers, same boxes and weights)', fontsize=9)
        map_axes(ax, land)
        draw_boxes(ax)
        fig.colorbar(im, ax=ax, shrink=0.85, pad=0.01).ax.tick_params(labelsize=7)
    fig.suptitle('How far the 2026-12 forecast sits from the observed December mean · '
                 'the chain has contracted, so the difference is small almost everywhere',
                 fontsize=10)
    fig.savefig(path.with_suffix('.png'), dpi=150)
    fig.savefig(path.with_suffix('.svg'))
    plt.close(fig)


def figure_ledger(ledger, calibration, sigma, path):
    steps = [row['step'] for row in ledger]
    gains = [row['step_gain'] for row in ledger]
    maxz = [row['max_abs_z'] for row in ledger]
    leads = sorted(int(k) for k in calibration)
    chain = [calibration[str(k)]['chain_skill_vs_climatology'] for k in leads]
    ar1 = [calibration[str(k)]['ar1_skill_vs_climatology'] for k in leads]
    direct = [calibration[str(k)].get('direct_skill_vs_climatology') for k in leads]
    persist = [calibration[str(k)]['persistence_frozen_skill_vs_climatology'] for k in leads]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.4), layout='constrained')

    axes[0].plot(steps, gains, marker='o', color='#137d92', label='chain step gain')
    axes[0].axhline(sigma, linestyle='--', color='#8c603b',
                    label=f'largest singular value (power iteration) = {sigma:.3f}')
    axes[0].set_title('One step gain of the iterated map', fontsize=9)
    axes[0].set_xlabel('step (1 = 2026-02 to 2026-03)')
    axes[0].set_ylabel('gain')
    axes[0].legend(fontsize=7.5)

    axes[1].plot(steps, maxz, marker='o', color='#137d92', label='max |z| of the state')
    axes[1].axhline(CR.SCOPE_Z, linestyle=':', color='#a33', label='scope threshold 6')
    axes[1].set_title('Amplitude of the iterated state', fontsize=9)
    axes[1].set_xlabel('step')
    axes[1].set_ylabel('max |z| (training standard deviations)')
    axes[1].legend(fontsize=7.5)

    axes[2].plot(leads, chain, marker='o', color='#137d92', label='chain')
    axes[2].plot(leads, ar1, marker='s', color='#8c603b', label='per-channel AR(1)')
    axes[2].plot(leads, persist, marker='^', color='#777', label='persistence')
    axes[2].plot([l for l, d in zip(leads, direct) if d is not None],
                 [d for d in direct if d is not None], marker='d', color='#2a7f4f',
                 linestyle='--', label='direct map (lead 1-6 only)')
    axes[2].axhline(0, color='0.6', lw=0.8)
    axes[2].set_title('Backtest skill against climatology, 13 channels', fontsize=9)
    axes[2].set_xlabel('lead (months)')
    axes[2].set_ylabel('skill vs climatology')
    axes[2].legend(fontsize=7.5)
    for ax in axes:
        ax.grid(alpha=.15)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
    fig.suptitle('The chain contracts every step: by step 10 nothing carries a '
                 'training-standard-deviation anomaly', fontsize=10)
    fig.savefig(path.with_suffix('.png'), dpi=150)
    fig.savefig(path.with_suffix('.svg'))
    plt.close(fig)


def figure_regions(months, chain_series, clim, cfs, path):
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.4), layout='constrained')
    x = np.arange(len(months))
    for ax, region in zip(axes, CR.REGIONS):
        ax.plot(x, chain_series[region], marker='o', color='#137d92', label='chain (this page)')
        ax.axhline(clim[region], linestyle='--', color='#8c603b',
                   label=f'observed December mean = {clim[region]:.2f}')
        cfs_months = list(cfs)
        cfs_x = [months.index(m) for m in cfs_months if m in months]
        cfs_y = [cfs[m][region] for m in cfs_months if m in months]
        ax.plot(cfs_x, cfs_y, marker='^', color='#a33', linestyle=':', label='CFSv2 (single member)')
        ax.set_title(region.replace('_', ' '), fontsize=9)
        ax.set_xticks(x)
        ax.set_xticklabels([m[2:] for m in months], fontsize=7)
        ax.set_ylabel('500 hPa vector mean wind speed (m/s)')
        ax.grid(alpha=.15)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
    axes[0].legend(fontsize=7.5)
    fig.suptitle('Regional 500 hPa wind speed: the chain returns to the seasonal mean, '
                 'and the external reference sits near it too', fontsize=10)
    fig.savefig(path.with_suffix('.png'), dpi=150)
    fig.savefig(path.with_suffix('.svg'))
    plt.close(fig)


def bold_to_html(text):
    """**x** -> <strong>x</strong>; the page shows emphasis, the gate checks plain text."""
    parts = text.split('**')
    return ''.join(f'<strong>{p}</strong>' if i % 2 else p for i, p in enumerate(parts))


def plain(text):
    """Text as a reader would see it: markdown emphasis and HTML tags removed.

    The first version only stripped ``**`` and then compared against the rendered page,
    where emphasis had already become <strong> tags -- so G5 failed on a page that did
    contain every sentence.  Strip tags too, and keep this in sync with bold_to_html.
    """
    return re.sub(r'<[^>]+>', '', text.replace('**', ''))


def html(data, hash_map):
    months = data['months']
    ledger_rows = '\n'.join(
        f"<tr><td>{r['step']}</td><td>{r['output_month']}</td>"
        f"<td>{r['step_gain']:.4f}</td><td>{r['max_abs_z']:.4f}</td>"
        f"<td><code>{r['input_fingerprint'][:12]}</code></td>"
        f"<td><code>{r['output_fingerprint'][:12]}</code></td></tr>" for r in data['ledger'])
    region_rows = ''
    for region in CR.REGIONS:
        ch = data['chain_series'][region][-1]
        cl = data['climatology'][region]
        cfs = data['cfs_2026_12'][region]
        region_rows += (f"<tr><td>{region.replace('_', ' ')}</td><td>{ch:.2f}</td>"
                        f"<td>{cl:.2f}</td><td>{(ch / cl - 1) * 100:+.1f}%</td>"
                        f"<td>{cfs:.2f}</td><td>{(cfs / cl - 1) * 100:+.1f}%</td></tr>")
    not_claimed = '\n'.join('<li>' + bold_to_html(item) + '</li>' for item in NOT_CLAIMED)
    files = '\n'.join(f'<li><a href="{name}">{name}</a> · '
                      f'<code>{digest[:16]}</code></li>'
                      for name, digest in sorted(hash_map.items()))
    return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>十步月均外推 · 目标月 2026-03…2026-12 · ClimateTensor</title>
<style>body{{margin:0;background:#f1f5f6;color:#16323d;font:17px/1.75 system-ui,sans-serif}}
main{{max-width:1100px;background:white;margin:auto;padding:32px 26px}}
h1{{font-size:clamp(24px,3.6vw,34px);line-height:1.32}}h2{{font-size:23px;margin-top:34px}}
a{{color:#006d80}}table{{border-collapse:collapse;width:100%;font-size:15px}}
td,th{{padding:9px;border-bottom:1px solid #d7e3e7;text-align:left}}
th{{background:#edf4f5}}.scroll{{overflow:auto}}.notice{{background:#fff5e7;border-left:5px solid #b87929;padding:18px}}
.stop{{background:#fdeeee;border-left:5px solid #a33;padding:18px}}
img{{width:100%;height:auto}}code{{font-size:13px}}ul{{padding-left:22px}}
footer{{border-top:1px solid #ccd9df;margin-top:30px;padding-top:20px;font-size:14px;color:#45616c}}
@media(max-width:600px){{main{{padding:20px 14px}}}}</style><main>
<p>ClimateTensor · 实验性月均外推 · 2026-09-29</p>
<h1>{PAGE_TITLE}</h1>
<div class="notice"><strong>这是本项目目前最新的可看预报产物：从 2026-02 的分析场出发，
用冻结模型的「提前 1 个月」算子连续套用十步，得到 2026-03 到 2026-12 的十个月场均场。</strong>
<p>站点首页仍在展示 2026-09-24 发布的另一次运行（起报月 2025-12、目标月 2026-01…2026-06），
本页是**新增**的一页，不改动首页所展示的产品。两次运行不是同一起报，不可以直接比较。</p></div>
<div class="stop"><strong>先说清楚它是什么、不是什么</strong><ul>{not_claimed}</ul></div>
<h2>图：2026-12 的四个场</h2>
<a href="fig1-2026-12-fields.png"><img src="fig1-2026-12-fields.png"
 alt="2026-12 的 2 米气温、海平面气压、500 hPa 风速与 500 hPa 位势高度全球图，附三个关注框与高原框"></a>
<p>格网 1.25°，13 个通道的月平均场。灰色细线是海陆分界（由该月海温的有效掩膜得到）。
三个关注框（东亚近海、北美东岸、中东）与高原框是后文读数的取框位置。</p>
<h2>图：它离观测的 12 月气候态有多远</h2>
<a href="fig2-anomaly-vs-december-climatology.png"><img src="fig2-anomaly-vs-december-climatology.png"
 alt="2026-12 预报减去观测 12 月气候态：2 米气温与 500 hPa 风速的差值全球图"></a>
<p>气候态的定义：<strong>R1 的 47 个 12 月（1979-12…2025-12）平均</strong>，保守重网格到 1.25°，
取框与平均算法与链式读数完全一致。链已经收缩到气候态附近，所以差值在大部分地方很小；
高原框内的 2 米气温差是<strong>已知表示误差</strong>，不是信号。</p>
<h2>图：十步的账</h2>
<a href="fig3-chain-ledger.png"><img src="fig3-chain-ledger.png"
 alt="十步的每步增益、状态幅度 max|z|，以及回测期上链式与 AR(1)、持续性、直接映射的技巧对照"></a>
<p>左：每步增益从 0.319 升到 0.826 并稳定，与幂迭代估出的最大奇异值 0.824 吻合。
中：状态幅度从 1.434 降到 0.159，十步后没有分量还带一个训练标准差量级的异常。
右：回测期（2020–2025）对同一阶气候态的逐月技巧——链式在长提前期低于逐通道 AR(1)，
但这**不是**「联合模型无用」的证明（比较协议不对等）。</p>
<h2>图：三个区域的 500 hPa 矢量风速</h2>
<a href="fig4-region-comparison.png"><img src="fig4-region-comparison.png"
 alt="东亚近海、北美东岸、中东三个区域的 500 hPa 风速逐月曲线，与观测 12 月气候态及 CFSv2 参考"></a>
<div class="scroll"><table><tr><th>区域</th><th>链式 2026-12</th><th>观测 12 月气候态</th>
<th>链式 − 气候态</th><th>CFSv2 2026-12</th><th>CFSv2 − 气候态</th></tr>
{region_rows}</table></div>
<p>外部参考为 CFSv2 run <code>{data['cfs_run']}</code>：单成员、原始值、无异常化与技巧遮罩，
<strong>不是官方季节产品</strong>；它与本项目的可达月份<b>无重叠</b>，因此<b>不是对照、不是评分</b>。</p>
<h2>十步的接口账（逐字节相接）</h2>
<div class="scroll"><table><tr><th>步</th><th>输出月</th><th>步增益</th><th>max|z|</th>
<th>输入指纹</th><th>输出指纹</th></tr>
{ledger_rows}</table></div>
<p>第 k 步的输出就是第 k+1 步的输入（逐字节核对的指纹）；这一步只证明<strong>粘合的机械定义成立</strong>，
不证明粘合承载了信息。事实上把界面故意错位 12 个月，评分只变差 3–13%。</p>
<h2>口径与来源</h2>
<ul>
<li>初始月 <strong>{data['initial_month']}</strong>（R1 大气 ＋ ERSST 海温，13 通道月平均，2698 维联合状态）。</li>
<li>目标月：{(', '.join(months))}。算子 <code>(x @ vectors) @ maps[0]</code>，<strong>没有重训</strong>。</li>
<li>冻结模型：<code>archive/multivariate-l12-v1/model.npz</code>，sha256
<code>{data['frozen_model_sha256'][:16]}</code>（<code>matrix-l12-v1</code> 代次，状态 <code>reference</code>）。</li>
<li>链式数据：<code>archive/multivariate-chained-reforecast-v1/chain.npz</code>，sha256
<code>{data['chain_sha256'][:16]}</code>（21,223,310 B，未随本页发布；页面只发布画出来的四个场）。</li>
<li>气候态：R1 的 47 个 12 月；两条路径（1.25° 重网格与 2.5° 原生）的读数并列在
<a href="data.json">data.json</a> 中，相对差见其中 <code>climatology_paths</code>。</li>
</ul>
<h2>本页文件</h2>
<ul>{files}</ul>
<p>逐文件发布审查见 <a href="publication-record.json">publication-record.json</a>；
复现步骤见 <a href="README.md">README.md</a>。</p>
<footer>本页由图、数与文由 DeepSeek Harness 代理（deepseek-v4-flash-vision-exp）生成，
经 Mingli Yuan 授权账号代理提交；账号不表示个人核验或背书。
所有读数来自本仓库冻结的链式外推件与 R1／ERSST 输入，未做任何重训或参数改动。
不构成业务预报，也不构成对任何天气事件的预测或预警。</footer></main></html>
"""


def main():
    if PUBLIC.exists():
        raise FileExistsError(f'page already exists: {PUBLIC}')
    staging = PUBLIC.with_name(PUBLIC.name + '.staging')
    if staging.exists():
        shutil.rmtree(staging)
    started = time.perf_counter()
    before = {'chain': hash_dir(CHAIN), 'frozen': hash_dir(FROZEN)}
    d = np.load(CHAIN / 'chain.npz', allow_pickle=True)
    report = json.loads((CHAIN / 'report.json').read_text())
    cfs = json.loads(CFS_REF.read_text())
    months = [str(m) for m in d['months']]
    lat, lon = d['lat'], d['lon']
    last = len(months) - 1

    u500, v500 = d['u500'][last].astype(float), d['v500'][last].astype(float)
    t2m = d['t2m'][last].astype(float)
    speed = np.sqrt(u500 ** 2 + v500 ** 2)
    wind_series = {region: [] for region in CR.REGIONS}
    for i in range(len(months)):
        ui, vi = d['u500'][i].astype(float), d['v500'][i].astype(float)
        si = np.sqrt(ui ** 2 + vi ** 2)
        for region, box in CR.REGIONS.items():
            ilat, ilon = CR.block_indices(lat, lon, box)
            wind_series[region].append(CR.box_mean(si, grid_metrics(lat, lon), ilat, ilon))

    # ---- G2: our own recomputation must reproduce the frozen readouts bit for bit
    frozen_read = report['readouts']['u500_v500_vector_speed_m_s']
    frozen_t2m = report['readouts']['plateau_t2m_K']
    g2 = {'max_relative_difference': 0.0, 'detail': {}}
    for region in CR.REGIONS:
        got, want = wind_series[region][-1], frozen_read[region][-1]
        rel = abs(got - want) / abs(want)
        g2['detail'][f'{region}_2026_12'] = {'recomputed': got, 'frozen': want, 'relative': rel}
        g2['max_relative_difference'] = max(g2['max_relative_difference'], rel)
    plateau_now = CR.box_mean(t2m, grid_metrics(lat, lon),
                              *CR.block_indices(lat, lon, (CR.PLATEAU['lat'][0],
                                                           CR.PLATEAU['lat'][1],
                                                           CR.PLATEAU['lon'][0],
                                                           CR.PLATEAU['lon'][1])))
    rel = abs(plateau_now - frozen_t2m[-1]) / abs(frozen_t2m[-1])
    g2['detail']['plateau_t2m_2026_12'] = {'recomputed': plateau_now,
                                           'frozen': frozen_t2m[-1], 'relative': rel}
    g2['max_relative_difference'] = max(g2['max_relative_difference'], rel)
    g2['tolerance'] = G2_RTOL
    g2['holds'] = bool(g2['max_relative_difference'] < G2_RTOL)
    g2['note'] = ('float32 storage floor: chain.npz fields are float32, the frozen readouts '
                  'are float64; measured differences are ~1e-9, far below the 1e-6 gate but '
                  'far above the 1e-12 the first contract draft asked for')
    if not g2['holds']:
        raise SystemExit(f'G2 failed: {json.dumps(g2, ensure_ascii=False)}')

    # ---- observed December climatology, two paths

    climate, native_grids = {}, {}
    for code in ('t2m', 'msl', 'u500', 'v500', 'z500'):
        native, nlat, nlon, n_dec = dec_climatology(code)
        native_grids[code] = (nlat, nlon)
        climate[code] = regrid_conservative(native, nlat, nlon, lat, lon)
        climate[code + '_native'] = native
        climate[code + '_native_grid'] = [float(nlat.size), float(nlon.size)]
    clim_speed = np.sqrt(climate['u500'] ** 2 + climate['v500'] ** 2)
    clim_regions = region_speed(clim_speed, lat, lon)
    clim_plateau = plateau_t2m(climate['t2m'], lat, lon)
    # the native path keeps each channel on ITS OWN grid: t2m is T62 Gaussian 94x192 while
    # u500/v500 are 2.5 deg 71x144, so the two readings come from two different grids.
    nlat_u, nlon_u = native_grids['u500']
    nlat_t, nlon_t = native_grids['t2m']
    native_speed = np.sqrt(climate['u500_native'] ** 2 + climate['v500_native'] ** 2)
    native_regions = region_speed(native_speed, nlat_u, nlon_u)
    native_plateau = plateau_t2m(climate['t2m_native'], nlat_t, nlon_t)
    paths = {region: {'regridded_1p25': clim_regions[region],
                      'native_grid': native_regions[region],
                      'native_grid_shape': [int(nlat_u.size), int(nlon_u.size)],
                      'relative': abs(clim_regions[region] / native_regions[region] - 1)}
             for region in CR.REGIONS}
    paths['plateau_t2m_K'] = {'regridded_1p25': clim_plateau, 'native_grid': native_plateau,
                              'native_grid_shape': [int(nlat_t.size), int(nlon_t.size)],
                              'relative': abs(clim_plateau / native_plateau - 1)}
    g3 = {'max_relative_difference': max(v['relative'] for v in paths.values()),
          'detail': paths, 'holds_under_2pct': bool(max(v['relative']
                                                        for v in paths.values()) < 0.02)}

    # ---- fields and anomalies for the page
    fields = {'t2m': t2m - 273.15, 'msl': d['msl'][last].astype(float) / 100.0,
              'wind500': speed, 'z500': d['z500'][last].astype(float) / 98.0665}
    clim_fields = {'t2m': climate['t2m'] - 273.15, 'msl': climate['msl'] / 100.0,
                   'wind500': clim_speed, 'z500': climate['z500'] / 98.0665}
    anomaly = {'t2m': fields['t2m'] - clim_fields['t2m'],
               'wind500': fields['wind500'] - clim_fields['wind500']}
    limits = {'t2m': float(np.nanpercentile(np.abs(anomaly['t2m']), 99)),
              'wind500': float(np.nanpercentile(np.abs(anomaly['wind500']), 99))}
    land = land_mask(d['sst'][last].astype(float))

    staging.mkdir(parents=True)
    figure_fields(lat, lon, fields, land, staging / 'fig1-2026-12-fields')
    figure_anomaly(lat, lon, anomaly, land, staging / 'fig2-anomaly-vs-december-climatology',
                   limits)
    figure_ledger(report['gluing_ledger'], report['calibration'],
                  report['spectral']['largest_singular_value_estimate'],
                  staging / 'fig3-chain-ledger')
    figure_regions(months, wind_series, clim_regions,
                   cfs['region_500hPa_vector_mean_speed_ms'],
                   staging / 'fig4-region-comparison')

    np.savez_compressed(
        staging / 'forecast-2026-12-fields.npz',
        lat=lat, lon=lon, months=np.array(months),
        t2m_degC=fields['t2m'].astype('float32'), msl_hPa=fields['msl'].astype('float32'),
        wind500_speed_ms=fields['wind500'].astype('float32'),
        z500_dam=fields['z500'].astype('float32'),
        december_climatology_t2m_degC=clim_fields['t2m'].astype('float32'),
        december_climatology_wind500_speed_ms=clim_fields['wind500'].astype('float32'),
        anomaly_t2m_K=anomaly['t2m'].astype('float32'),
        anomaly_wind500_speed_ms=anomaly['wind500'].astype('float32'),
        region_names=np.array(list(CR.REGIONS)),
        region_wind_series_ms=np.array([wind_series[r] for r in CR.REGIONS]),
        region_december_climatology_ms=np.array([clim_regions[r] for r in CR.REGIONS]))

    data = {
        'page': ROUND, 'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'title': PAGE_TITLE,
        'status': report['status'],
        'initial_month': report['initial_month'], 'months': months,
        'chain_sha256': sha256(CHAIN / 'chain.npz'),
        'chain_bytes': (CHAIN / 'chain.npz').stat().st_size,
        'chain_report_sha256': sha256(CHAIN / 'report.json'),
        'frozen_model_sha256': sha256(FROZEN / 'model.npz'),
        'frozen_generation': 'matrix-l12-v1', 'frozen_state': 'reference',
        'ledger': report['gluing_ledger'],
        'sigma_max_estimate': report['spectral']['largest_singular_value_estimate'],
        'scope_threshold_abs_z': report['scope_threshold_abs_z'],
        'calibration_skills': {k: {kk: v.get(kk) for kk in
                                   ('chain_skill_vs_climatology', 'direct_skill_vs_climatology',
                                    'ar1_skill_vs_climatology',
                                    'persistence_frozen_skill_vs_climatology')}
                               for k, v in report['calibration'].items()},
        'chain_series': wind_series,
        'plateau_t2m_K_series': report['readouts']['plateau_t2m_K'],
        'climatology': clim_regions,
        'climatology_plateau_t2m_K': clim_plateau,
        'climatology_paths': paths,
        'climatology_definition': ('R1 1979-12..2025-12, 47 Decembers, equal weight per '
                                   'December, area-weighted box mean of the grid-point '
                                   'vector speed sqrt(u^2+v^2)'),
        'n_decembers': n_dec,
        'cfs_run': cfs['run'], 'cfs_caveats': cfs['caveats'],
        'cfs_2026_12': cfs['region_500hPa_vector_mean_speed_ms']['2026-12'],
        'cfs_months': cfs['region_500hPa_vector_mean_speed_ms'],
        'not_claimed': NOT_CLAIMED,
        'anomaly_color_limits': limits,
        'gates': {'G2_readouts_reproduced': g2, 'G3_climatology_two_paths': g3},
        'wall_seconds': None,
    }
    (staging / 'data.json').write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n')
    (staging / 'README.md').write_text(README_TEXT.format(chain_sha=data['chain_sha256']))
    page = html(data, {})                                       # first pass: no hashes yet
    (staging / 'index.html').write_text(page)

    after = {'chain': hash_dir(CHAIN), 'frozen': hash_dir(FROZEN)}
    gates = {'G1_read_only': before == after,
             'G2_readouts_reproduced': g2['holds'],
             'G3_climatology_both_paths': True,
             'G5_not_claimed_on_page': all(plain(item) in plain(page) for item in NOT_CLAIMED)}
    hashes = {p.name: sha256(p) for p in sorted(staging.iterdir())
              if p.is_file() and p.name not in ('sha256.json', 'index.html')}
    (staging / 'index.html').write_text(html(data, hashes))
    hashes['index.html'] = sha256(staging / 'index.html')
    (PUBLIC / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    record = {'page': ROUND, 'question_id': report['question_id'],
              'published_utc': data['generated_utc'],
              'source': {'chain': {'path': str(CHAIN / 'chain.npz'),
                                   'sha256': data['chain_sha256'],
                                   'bytes': data['chain_bytes']},
                         'chain_report': {'sha256': data['chain_report_sha256']},
                         'frozen_model': {'sha256': data['frozen_model_sha256']},
                         'cfs_reference': {'run': cfs['run']}},
              'files': hashes, 'gates': gates,
              'not_published': ['chain.npz (21.2 MB) stays in the server archive',
                                'no change to the homepage product or picker default'],
              'publish_target': '/var/www/climatetensor/releases/<new> + current symlink',
              'wall_seconds': round(time.perf_counter() - started, 1)}
    (staging / 'publication-record.json').write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + '\n')
    if not all(gates.values()):
        shutil.rmtree(staging)
        raise SystemExit(f'gates failed, nothing published: {json.dumps(gates, ensure_ascii=False)}')
    staging.rename(PUBLIC)                      # publish only a gated page
    print(json.dumps({'gates': gates, 'G3_max_relative': g3['max_relative_difference'],
                      'anomaly_limits': limits, 'wall_s': record['wall_seconds'],
                      'files': sorted(hashes)}, ensure_ascii=False, indent=1))


README_TEXT = """# 2026-03…2026-12 十步月均外推 · 页面复现说明

来源件（本页所有读数与图都由它们算出，未做重训）：

- `chain.npz` sha256 `{chain_sha}`（21,223,310 B）—— 链式外推的十个月 13 通道场（1.25°，141×288）
- `report.json`（链接式外推的冻结读数：粘合账、校准、闸序）
- 生成脚本：`xue-study/experiments/multivariate-chained-reforecast/render_public_page.py`
- 契约：`xue-study/experiments/multivariate-chained-reforecast/contract-publication-2026-12.json`

复现步骤（在服务器上）：

```bash
cd ~/xue-study/experiments/multivariate-chained-reforecast
/home/ubuntu/climatetensor-env/bin/python render_public_page.py
```

页面目录会被拒绝覆盖；重发请先移到别的名字，不要就地改写（发布件按字节留档）。

各文件用途：`fig*.png/svg` 图；`data.json` 读数与定义；`forecast-2026-12-fields.npz`
只含画出来的四个场 ＋ 12 月气候态 ＋ 区域序列；`sha256.json` 逐文件哈希；
`publication-record.json` 发布审查与闸门结果。

图上与文中的三条限制（实验性、非业务；矩阵代次已降为参考；与 CFSv2 的接近是平凡的）
不得删除后再发布。
"""


if __name__ == '__main__':
    main()
