"""Does xue's own colour ramp actually colour the fields it is given?

WHY THIS IS NOT COSMETIC
------------------------
The report's §576 records a browser screenshot of the THETAE850 layer and reads
it as evidence: "the plateau is one solid slab of the ramp's topmost dark red,
visibly more extreme than the tropical warm pool".  That reading assumes the
ramp RESOLVES the field -- that two different values get two different colours.

The ramp does not.  `web/src/palettes.ts` holds TEMPERATURE_STOPS in degrees
Celsius, from -60 to 50, and `buildPalette` looks a code's decoded VALUE up in
that table.  The archived thetae850 codebook is

    value = 230 + 0.5 * code,  code <= 254   ->   230 K .. 357 K

Every one of those codes is past the ramp's 50 degC top stop, so the lookup
returns the same colour 255 times.  A constant field cannot show a plateau that
is "more extreme" than the warm pool: it shows no plateau at all.

WHAT THIS DOES AND DOES NOT SETTLE
----------------------------------
It settles what xue's palette code in THIS checkout does with THIS codebook.
The script runs the real module -- it bundles `web/src/palettes.ts` with the
repository's own esbuild and calls the real `buildPalette` -- rather than
re-implementing it, because a re-implementation would only prove that two
copies of my own misunderstanding agree.

It does NOT settle what the deployed site renders.  `thetae850` does not appear
anywhere in this checkout's `web/src`, so the layer the screenshot shows was
built by a copy that had a variable this checkout does not, and that copy is
gone.  The screenshot therefore cannot be used either to support or to refute
the constant-colour result, and this figure says so rather than picking a side.

WHY tmp2m AND hgt500 ARE HERE
-----------------------------
A test that can only fail is not a test.  tmp2m's codebook (-60..50 degC) lines
up with the ramp exactly, and the pressure family gets its own ramp rescaled
onto the codebook range.  Both must come back with a full spread of colours.  If
all three were degenerate, the fault would be in this check, not in the ramp.

Usage:
  uv run --with numpy --with matplotlib python scripts/fig_palette_reach.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt                                      # noqa: E402

import figstyle                                                      # noqa: E402
from poster_field import load, runs_with                              # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
figstyle.use()
XUE = Path("/Users/mingli/Climate/xue")

# The variables to test, with the codebooks the ARCHIVE actually carries.  The
# quantizations are read from the archived manifests, not written in here.
TARGETS = ("thetae850", "tmp850", "tmp2m", "tmp500")

DRIVER = """
import {{ buildPalette }} from "{bundle}";
const targets = {targets};
const out = {{}};
for (const [id, q] of Object.entries(targets)) {{
  const pal = buildPalette({{ id, unit: "", quantization: q }});
  const seen = new Set();
  const codes = [];
  for (let c = 0; c <= q.maximumCode; c += 1) {{
    const key = [pal[c*4], pal[c*4+1], pal[c*4+2], pal[c*4+3]].join(",");
    seen.add(key);
    codes.push(key);
  }}
  out[id] = {{ distinct: seen.size, n_codes: q.maximumCode + 1,
               first: codes[0], last: codes[codes.length - 1] }};
}}
console.log(JSON.stringify(out));
"""


def run_real_palette(codebooks: dict[str, dict]) -> dict:
    """Call xue's own buildPalette through its own toolchain."""
    esbuild = XUE / "node_modules" / ".bin" / "esbuild"
    if not esbuild.exists():
        raise SystemExit(f"找不到 {esbuild} —— 拒绝用自己重写的色标代替真代码出图")
    with tempfile.TemporaryDirectory() as td:
        bundle = Path(td) / "palettes-bundle.mjs"
        subprocess.run([str(esbuild), str(XUE / "web/src/palettes.ts"),
                        "--bundle", "--format=esm", f"--outfile={bundle}",
                        "--log-level=warning"], check=True)
        driver = Path(td) / "driver.mjs"
        driver.write_text(DRIVER.format(bundle=bundle.as_uri(),
                                        targets=json.dumps(codebooks)))
        res = subprocess.run(["node", str(driver)], check=True,
                             capture_output=True, text=True)
    return json.loads(res.stdout)


def ramp_colors(codebooks: dict[str, dict], result: dict) -> dict[str, np.ndarray]:
    """Recover the actual RGB of every code, so the figure can draw the ramp."""
    with tempfile.TemporaryDirectory() as td:
        bundle = Path(td) / "palettes-bundle.mjs"
        subprocess.run([str(XUE / "node_modules/.bin/esbuild"),
                        str(XUE / "web/src/palettes.ts"), "--bundle",
                        "--format=esm", f"--outfile={bundle}",
                        "--log-level=warning"], check=True)
        driver = Path(td) / "pal.mjs"
        driver.write_text(f"""
import {{ buildPalette }} from "{bundle.as_uri()}";
const targets = {json.dumps(codebooks)};
const out = {{}};
for (const [id, q] of Object.entries(targets)) {{
  const pal = buildPalette({{ id, unit: "", quantization: q }});
  out[id] = Array.from(pal.slice(0, (q.maximumCode + 1) * 4));
}}
console.log(JSON.stringify(out));
""")
        res = subprocess.run(["node", str(driver)], check=True,
                             capture_output=True, text=True)
    raw = json.loads(res.stdout)
    return {k: np.array(v, dtype=np.uint8).reshape(-1, 4) for k, v in raw.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default=str(ROOT / "archive"))
    ap.add_argument("--out", default=str(ROOT / "figures" / "palette-reach.png"))
    ap.add_argument("--json", default=str(ROOT / "figures" / "palette-reach.json"))
    args = ap.parse_args()
    archive = Path(args.archive)

    codebooks, ceiling = {}, {}
    for var in TARGETS:
        items = runs_with(archive, "gfs", var)
        if not items:
            continue
        p = load(archive, "gfs", items[-1], var)
        codebooks[var] = p.q
        ceiling[var] = p.ceiling

    if "thetae850" not in codebooks:
        print("归档里没有 thetae850 —— 不作图")
        return 1

    result = run_real_palette(codebooks)
    rgb = ramp_colors(codebooks, result)

    print("xue 自己的 buildPalette，对归档里真实的量化：\n")
    print(f"{'变量':<11}{'码位数':>7}{'不同颜色数':>11}{'取值域':>22}  首码/末码颜色")
    for var in TARGETS:
        if var not in result:
            continue
        r = result[var]
        q = codebooks[var]
        lo = q["offset"]
        hi = q["offset"] + q["scale"] * q["maximumCode"]
        unit = "K" if var == "thetae850" else "°C"
        print(f"{var:<11}{r['n_codes']:>7}{r['distinct']:>11}"
              f"{f'{lo:g}..{hi:g} {unit}':>22}  {r['first']} / {r['last']}")

    th = result["thetae850"]
    print(f"\n判据一 · θe850 是否退化：{th['distinct']} 种颜色 / {th['n_codes']} 个码位"
          f"  → {'退化：整层是一个常数色' if th['distinct'] == 1 else '未退化'}")
    controls = {k: v["distinct"] for k, v in result.items() if k != "thetae850"}
    print("判据二 · 同样的函数在别的变量上："
          + "  ".join(f"{k} {v} 色" for k, v in controls.items())
          + f"  → {'对照通过：函数本身没有坏' if max(controls.values()) > 10 else '对照失败：这个检查不成立'}")
    if th["distinct"] != 1 or max(controls.values()) <= 10:
        print("\n  检查不成立或结论未复现 —— 不出图")
        return 1

    # ---- figure ------------------------------------------------------------
    fig = plt.figure(figsize=(13.0, 6.6), dpi=140)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.0, 1.25], wspace=0.16,
                          left=0.055, right=0.985, top=0.80, bottom=0.16)

    ax = fig.add_subplot(gs[0, 0])
    order = [v for v in TARGETS if v in result]
    y = np.arange(len(order))[::-1]
    counts = [result[v]["distinct"] for v in order]
    cols = [figstyle.BAD if v == "thetae850" else figstyle.OK for v in order]
    ax.barh(y, counts, color=cols, height=0.55, zorder=3)
    for yi, v, c in zip(y, order, counts):
        ax.text(c + 4, yi, f"{c} / {result[v]['n_codes']}", va="center",
                fontsize=10, color=figstyle.INK, fontweight="bold")
    ax.set_yticks(y)
    ax.set_yticklabels([f"{v}\n{codebooks[v]['offset']:g}"
                        f"＋{codebooks[v]['scale']:g}×code" for v in order],
                       fontsize=9)
    ax.set_xlim(0, 265)
    ax.set_xlabel("xue 的 buildPalette 产出的不同颜色数", fontsize=10)
    ax.set_title("同一个色标函数，四个真实量化", fontsize=11.5)
    figstyle.tidy(ax, "x")

    ax2 = fig.add_subplot(gs[0, 1])
    width = 42
    for row, v in enumerate(order):
        strip = rgb[v]
        if len(strip) < 255:
            strip = np.vstack([strip, np.zeros((255 - len(strip), 4), np.uint8)])
        img = np.repeat(strip[:255][None, :, :], width, axis=0)
        yy = len(order) - 1 - row
        ax2.imshow(img, extent=(0, 255, yy, yy + 1), aspect="auto",
                   interpolation="nearest")
        ax2.text(-4, yy + 0.5, v, ha="right", va="center", fontsize=9.5)
        if result[v]["distinct"] == 1:
            ax2.text(127, yy + 0.5, "  整条色标只有一个颜色  ",
                     ha="center", va="center", fontsize=9.5, color="white",
                     fontweight="bold",
                     bbox=dict(facecolor=figstyle.INK, alpha=0.75,
                               edgecolor="none", pad=3))
    ax2.set_xlim(-52, 255)
    ax2.set_ylim(0, len(order))
    ax2.set_yticks([])
    ax2.set_xticks([0, 51, 102, 153, 204, 254])
    ax2.set_xticklabels(["code 0", "51", "102", "153", "204", "254"], fontsize=9)
    ax2.set_xlabel("量化码位 →", fontsize=10)
    ax2.set_title("色标本身（每个码位一格）", fontsize=11.5)
    for s in ax2.spines.values():
        s.set_visible(False)

    figstyle.title(
        fig, "色标到不了 θe850 所在的温度区间",
        "xue 的 TEMPERATURE_STOPS 是摄氏 −60…50。θe850 的量化是 230＋0.5×code，"
        "也就是 230–357 K —— 全部落在色标顶端之外，于是 255 个码位得到同一个颜色。")
    figstyle.footer(
        fig, "本图直接运行 xue 自己的 web/src/palettes.ts（用该仓库自带的 esbuild 打包后调用真 buildPalette），"
             "不是重写一遍。边界：代码量化取自 archive/ 的 manifest，而 thetae850 在本机 xue 检出里"
             "根本不存在于 web/src —— 那张唯一的浏览器截图来自另一份已不存在的构建，"
             "故本图既不能证实也不能否证线上页面今天渲染成什么样。")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    Path(args.json).write_text(json.dumps(
        {"result": result, "codebooks": codebooks}, indent=1, ensure_ascii=False))
    print(f"\n  写入 {out} 和 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
