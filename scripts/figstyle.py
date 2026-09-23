"""House style for this repository's figures.  One place, so no figure can
silently end up in a different font, palette or footer convention.

THE FONT IS NOT COSMETIC
------------------------
These figures are labelled in Chinese.  Matplotlib has no CJK face by default,
so every Chinese string silently becomes a row of empty boxes -- a figure that
renders, saves, opens, and says nothing.  That is the worst possible failure
mode for a deliverable whose entire job is to be read, and it does not raise an
exception.

So `use()` resolves a CJK font and REFUSES TO CONTINUE if it cannot find one.
A figure that fails to draw is recoverable; a figure full of tofu that gets
committed and cited is not.

THE FOOTER IS PART OF THE FIGURE
--------------------------------
Every figure in this repository states its own boundary on its own face: what
it measured, what it did not, and which numbers are RECORDED from elsewhere
rather than observed here.  A number that crosses into a picture stops carrying
its caveats unless the picture carries them.
"""

from __future__ import annotations

import matplotlib
from matplotlib import font_manager

matplotlib.use("Agg")
import matplotlib.pyplot as plt                                       # noqa: E402

# Faces tried in order.  The first that exists AND parses wins.
CJK_CANDIDATES = (
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
)

INK = "#16181b"
DIM = "#5f6368"
FAINT = "#9aa0a6"
OK = "#2ca02c"
BAD = "#d62728"
WARN = "#e39b02"
NEUTRAL = "#4c78a8"
GRID = "#d8dade"


def use() -> str:
    """Register a CJK font and return the family name.  Raises if none works."""
    for path in CJK_CANDIDATES:
        try:
            font_manager.fontManager.addfont(path)
            name = font_manager.FontProperties(fname=path).get_name()
        except Exception:                                          # noqa: BLE001
            continue
        plt.rcParams["font.family"] = [name, "DejaVu Sans"]
        # A missing glyph must not be papered over by a minus-sign substitution.
        plt.rcParams["axes.unicode_minus"] = False
        plt.rcParams["figure.facecolor"] = "white"
        plt.rcParams["axes.facecolor"] = "white"
        plt.rcParams["axes.edgecolor"] = "#bbbfc4"
        plt.rcParams["axes.labelcolor"] = INK
        plt.rcParams["text.color"] = INK
        plt.rcParams["xtick.color"] = DIM
        plt.rcParams["ytick.color"] = DIM
        plt.rcParams["axes.titlesize"] = 11
        plt.rcParams["axes.titleweight"] = "bold"
        plt.rcParams["savefig.facecolor"] = "white"
        return name
    raise SystemExit(
        "找不到可用的中文字体 —— 拒绝出图。\n"
        "缺字体的图会渲染成一片空方框，而且不会报错，"
        "比没有图更糟。请安装中文字体或改用英文标注。\n"
        f"试过：{', '.join(CJK_CANDIDATES)}")


def title(fig, main: str, sub: str = "", y: float = 0.975):
    """The figure's own title block, above the axes rather than inside them."""
    fig.text(0.055, y, main, fontsize=15.5, fontweight="bold", color=INK,
             va="top", ha="left")
    if sub:
        fig.text(0.055, y - 0.045, sub, fontsize=9.2, color=DIM, va="top",
                 ha="left", wrap=True)


def footer(fig, text: str):
    """The boundary statement.  Not optional, and not in the caption."""
    fig.text(0.055, 0.014, text, fontsize=7.8, color=FAINT, va="bottom",
             ha="left", wrap=True)


def provenance(ax, text: str, x: float = 0.005, y: float = 0.98):
    """Mark WHICH numbers on this axes are recorded rather than measured."""
    ax.text(x, y, text, transform=ax.transAxes, fontsize=7.8, color=FAINT,
            va="top", ha="left")


def tidy(ax, grid_axis: str = "y"):
    ax.grid(axis=grid_axis, color=GRID, alpha=0.9, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
