"""Draw the ternary decoding tree of Morse code, with FLOW's walk traced on it.

WHY TERNARY, AND WHY THIS IS NOT A DIFFERENT TREE FROM THE BINARY ONE
---------------------------------------------------------------------
The familiar Morse tree is binary: at each node you either go dot or dash.  But
that tree cannot be *decoded* without a third piece of information -- when does
the letter end -- because Morse is not a prefix code:

    E = .        is a prefix of        F = ..-.

So a decoder standing on a node has exactly THREE moves available:

    滴  go left          (the dot)
    答  go right         (the dash)
    止  stop here        (take the letter at this node)

Draw all three at every node and the binary tree becomes a ternary one, with
every 止 edge ending in a leaf.  That is what this figure draws.  The three
branches are drawn in the order 滴 / 止 / 答 so the letter hangs directly below
the node it belongs to.

WHAT FLOW LOOKS LIKE ON IT
--------------------------
A decoder never walks a continuous path -- after emitting a letter it returns to
the root, because a letter's code does not remember the previous letter's:

    F = ..-.      E -> I -> U -> F, then 止
    L = .-..      E -> A -> R -> L, then 止
    O = ---       T -> M -> O,      then 止
    W = .--       E -> A -> W,      then 止

So FLOW is four separate root-to-node walks, each closed by a 止 edge.  The 止
branch is what turns "the node I am standing on" into "a letter I have read".

WHAT IS DRAWN AND WHAT IS NOT
-----------------------------
Every node that lies on the way to a letter is drawn, and every node carries a
止 leaf: 27 nodes, 27 leaves, covering all 26 letters.  Nodes that no letter
passes through are pruned, because they are the same picture with more empty
space in it.  The one 止 leaf that is NOT a letter is the root's -- marked ✗,
and it is there on purpose: it shows that the third branch exists at every node,
including the ones where taking it is an error.

Usage:
  uv run --with numpy --with matplotlib python scripts/fig_morse_tree.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt                                      # noqa: E402

import figstyle                                                      # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
figstyle.use()

MORSE = {
    'A': '.-', 'B': '-...', 'C': '-.-.', 'D': '-..', 'E': '.', 'F': '..-.',
    'G': '--.', 'H': '....', 'I': '..', 'J': '.---', 'K': '-.-', 'L': '.-..',
    'M': '--', 'N': '-.', 'O': '---', 'P': '.--.', 'Q': '--.-', 'R': '.-.',
    'S': '...', 'T': '-', 'U': '..-', 'V': '...-', 'W': '.--', 'X': '-..-',
    'Y': '-.--', 'Z': '--..',
}
CODE_LETTER = {v: k for k, v in MORSE.items()}
WORD = "FLOW"
LETTER_COLOR = {"F": "#d62728", "L": "#e39b02", "O": "#2ca02c", "W": "#4c78a8"}


def walk(word):
    """The four root-to-node walks, as lists of 'L'/'R' steps."""
    return {ch: ['L' if c == '.' else 'R' for c in MORSE[ch]] for ch in word}


def to_path(code: str) -> str:
    """Morse notation to the tree's own alphabet: dot -> L, dash -> R."""
    return "".join("L" if c == "." else "R" for c in code)


def build():
    """Nodes and their terminal leaves, pruned to the subtrees holding a letter.

    A node exists when it is the root, is a letter, or is a prefix of a letter.
    Its 滴/答 children exist on the same test; its 止 child (a leaf) always does,
    because the third branch is available everywhere -- that is the whole point.

    The prefix set is built in the tree's own L/R alphabet.  The first version
    built it from the dotted notation while testing L/R paths against it, so
    nothing ever matched and the whole tree collapsed to its root.
    """
    prefixes = {""}
    for code in MORSE.values():
        path = to_path(code)
        for i in range(len(path) + 1):
            prefixes.add(path[:i])
    assert to_path("..-.") in prefixes and to_path(".-..") in prefixes

    def kids(path):
        out = []
        if path + "L" in prefixes:
            out.append(path + "L")
        if path + "R" in prefixes:
            out.append(path + "R")
        return out

    # A DFS in child order 滴 / 止 / 答, which is the order the branches are
    # drawn in.  The LEAF ORDER from this walk is what assigns x positions, so
    # it cannot be replaced by a sort: the first version sorted the leaves by
    # (depth, path), which threw the in-order sequence away and left every
    # parent a mean of unrelated positions -- the tree came out folded flat
    # against one corner.
    nodes, leaves = [], []

    def rec(path, depth):
        nodes.append((path, depth))
        if path + "L" in prefixes:
            rec(path + "L", depth + 1)
        leaves.append((path, depth + 1))          # the 止 leaf, in the middle
        if path + "R" in prefixes:
            rec(path + "R", depth + 1)

    rec("", 0)
    return nodes, leaves, prefixes


def layout(nodes, leaves):
    """Leaf-index layout: leaves evenly spaced, each parent the mean of its
    three branches.

    A ternary-INDEX layout (x = index / 3^depth) would push every dot-first path
    into the left margin, because 滴 is the zero of the digit alphabet and
    leading zeros do not move a position.  Spacing by leaf count has no such
    skew.
    """
    paths = {p: d for p, d in nodes}
    xs = {p: float(i) for i, (p, _) in enumerate(leaves)}

    for depth in range(4, -1, -1):
        for path, d in nodes:
            if d != depth:
                continue
            branch = [xs[path]]                      # 止 leaf shares the path
            if path + "L" in paths:
                branch.append(xs[path + "L"])
            if path + "R" in paths:
                branch.append(xs[path + "R"])
            xs[path + "_node"] = sum(branch) / len(branch)
    return xs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "figures" / "morse-tree-flow.png"))
    args = ap.parse_args()

    nodes, leaves, _ = build()
    xs = layout(nodes, leaves)
    depth_of = dict(nodes)
    leaf_depth = dict(leaves)
    paths = set(depth_of)
    walks = walk(WORD)

    n_leaf = len(leaves)
    print(f"节点 {len(nodes)}，止叶 {n_leaf}，覆盖 {len(MORSE)} 个字母")
    print(f"深度分布：", {d: sum(1 for _, dd in nodes if dd == d) for d in range(5)})
    for ch in WORD:
        print(f"  {ch} = {MORSE[ch]:<5} -> "
              + " -> ".join(["root"] + [CODE_LETTER.get("".join('.' if s == 'L' else '-'
                               for s in walks[ch][:i + 1]), "?")
                             for i in range(len(walks[ch]))])
              + "  then 止")

    fig = plt.figure(figsize=(16.5, 10.2), dpi=135)
    ax = fig.add_axes([0.02, 0.285, 0.96, 0.615])
    ax.set_xlim(-1.2, n_leaf + 0.2)
    ax.set_ylim(-5.55, 1.05)
    ax.axis("off")

    # ---- edges -------------------------------------------------------------
    # An edge walked by more than one of FLOW's letters is drawn in ink rather
    # than in a letter's colour: F, L and W all begin with 滴, and L and W both
    # go 滴答.  Colouring a shared edge by whichever letter was looped over last
    # (what the first version did) hides exactly the structure this figure is
    # for -- how much of the walk is shared prefix.
    def walkers(edge):
        return [c for c in WORD
                if len(edge) <= len(walks[c]) and edge == "".join(walks[c][:len(edge)])]

    for path, d in nodes:
        x0, y0 = xs[path + "_node"], -d
        for step in ("L", "R"):
            tgt = path + step
            if tgt not in paths:
                continue
            who = walkers(tgt)
            if len(who) > 1:
                col, lw, z = figstyle.INK, 3.0, 6
            elif who:
                col, lw, z = LETTER_COLOR[who[0]], 2.6, 6
            else:
                col, lw, z = figstyle.DIM, 1.0, 2
            ax.plot([x0, xs[tgt + "_node"]], [y0, -(d + 1)], color=col, lw=lw,
                    zorder=z, solid_capstyle="round")
        who = walkers(path)
        col, lw = (LETTER_COLOR[who[0]], 2.8) if who else (figstyle.INK, 1.0)
        ax.plot([x0, xs[path]], [y0, -(d + 1)], color=col, lw=lw, zorder=6 if who else 2,
                ls="-" if who else (0, (2, 2)))

    # ---- nodes and leaves --------------------------------------------------
    # In a ternary decoding tree the LETTER belongs to the leaf that the 止
    # branch reaches, not to the node it leaves from.  Drawing it in both places
    # (the first version did) shows every letter twice and hides which one is
    # the terminal.  So a node is drawn as a bare state, carrying only its code
    # so a reader can still check a path against the alphabet.
    for path, d in nodes:
        x, y = xs[path + "_node"], -d
        on_path = any(path == "".join(walks[c][:len(path)]) for c in WORD)
        col = figstyle.INK
        for c in WORD:
            if path == "".join(walks[c]):
                col = LETTER_COLOR[c]
        ax.plot([x], [y], marker="o", ms=7.5, color="white", mec=col,
                mew=1.4 if not on_path else 2.6, zorder=8)
        if path:
            ax.text(x + 0.16, y, "".join('.' if t == 'L' else '-' for t in path),
                    fontsize=7.4, color=figstyle.FAINT, ha="left", va="center",
                    zorder=9)

    for path, d in leaves:
        x, y = xs[path], -d
        letter = CODE_LETTER.get("".join('.' if t == 'L' else '-' for t in path))
        hit = [c for c in WORD if path == "".join(walks[c])]
        col = LETTER_COLOR[hit[0]] if hit else ("#8d99ae" if letter else figstyle.BAD)
        ax.text(x, y, letter if letter else "✗", ha="center", va="center",
                fontsize=11.5 if letter else 10, fontweight="bold",
                color="white" if letter else figstyle.BAD,
                bbox=dict(boxstyle="round,pad=0.30",
                          facecolor=col if letter else "white",
                          edgecolor=col, lw=2.8 if hit else 1.2), zorder=9)

    # ---- branch labels at the root -----------------------------------------
    xr = xs["_node"]
    ax.text(0.5 * (xr + xs["L_node"]), -0.42, "滴 (·)", fontsize=11.5,
            ha="center", va="center", color=figstyle.DIM, fontweight="bold")
    ax.text(0.5 * (xr + xs["R_node"]), -0.42, "答 (−)", fontsize=11.5,
            ha="center", va="center", color=figstyle.DIM, fontweight="bold")
    ax.text(xs[""] - 0.30, -0.55, "止", fontsize=11.5, ha="right",
            va="center", color=figstyle.INK, fontweight="bold")
    ax.text(xr, 0.62, "起点（空）", fontsize=11, ha="center",
            color=figstyle.INK, fontweight="bold")

    ax.text(-1.05, 0.86,
            "空心圆 = 一个节点（状态），旁边小字是它累积到的码\n"
            "圆下方的方框 = 第三支「止」所到达的字母 —— 字母住在叶子上，不在节点上\n"
            "✗ = 在此取「止」不合法：根节点还没有字母\n"
            "深色粗边 = FLOW 里不止一个字母走过（F、L、W 都以滴开头；L、W 都是滴答）",
            fontsize=9.8, ha="left", va="top", color=figstyle.DIM)

    # ---- the four walks, as a strip ----------------------------------------
    axs = fig.add_axes([0.055, 0.085, 0.90, 0.175])
    axs.set_xlim(0, 10.6)
    axs.set_ylim(0, len(WORD))
    axs.axis("off")
    for row, ch in enumerate(WORD):
        y = len(WORD) - row - 1 + 0.5
        col = LETTER_COLOR[ch]
        axs.text(0.0, y, f"{ch}", fontsize=15, fontweight="bold", color=col,
                 va="center", ha="left")
        axs.text(0.42, y, MORSE[ch], fontsize=12, color=figstyle.DIM,
                 va="center", ha="left", family="monospace")
        x = 1.45
        for s in walks[ch]:
            axs.text(x, y, "滴" if s == "L" else "答", fontsize=11.5,
                     ha="center", va="center", color="white", fontweight="bold",
                     bbox=dict(boxstyle="round,pad=0.28", facecolor=col,
                               edgecolor="none"))
            x += 0.52
        axs.text(x, y, "止", fontsize=11.5, ha="center", va="center",
                 color=col, fontweight="bold",
                 bbox=dict(boxstyle="round,pad=0.28", facecolor="white",
                           edgecolor=col, lw=1.8))
        x += 0.62
        chain = "起点 → " + " → ".join(
            CODE_LETTER.get("".join('.' if t == 'L' else '-' for t in walks[ch][:i + 1]), "?")
            for i in range(len(walks[ch])))
        axs.text(x, y, chain + f"  →  取出 {ch}", fontsize=10.5, color=figstyle.INK,
                 va="center", ha="left")
    axs.text(0.0, len(WORD) - 0.06,
             "每一步都从【起点】重新开始：一个字母的码不记得上一个字母。",
             fontsize=9.5, color=figstyle.DIM, va="bottom", ha="left")

    figstyle.title(
        fig, "FLOW 的三叉解码树",
        "摩尔斯树本来是二叉的，但它无法解码 —— 因为摩尔斯不是前缀码（E = · 是 F = ··-· 的前缀）。"
        "站在任一节点上，解码器只有三个动作：滴、答、止。把第三支画出来，二叉就变成三叉。")
    figstyle.footer(
        fig, "每一个节点都有「止」这一支，包括还没有字母的根节点（用它标出 ✗：这一支在哪儿都可用，"
             "但在哪儿不都合法）。深度 4 的 16 个位置里有 4 个不对应任何字母（..--、.-.-、---.、----），已剪掉 —— "
             "剪掉的是空节点，不是字母。布局按叶子等距定位、父节点取三支的均值：若按三进制下标排，"
             "所有以「滴」开头的路径都会挤到左边缘，因为滴正是数字字母表里的 0。")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    print(f"\n  写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
