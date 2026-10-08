"""追加「对径配对是 E/O 区分的来源」这条 claim，写入前用 tomllib 验证。

历史教训：TOML 已被写坏 3 次。故本脚本先构造文本、再 tomllib.loads 解析、
确认 11 个字段齐全且 claim 数从 17 → 18，最后才落盘。
"""
import json
import pathlib
import tomllib

CLAIMS = pathlib.Path("docs/claims.toml")

FIELDS = [
    ("claim_id", "xue.native.antipodal-pairing-is-the-source-of-the-eo-split.v0"),
    ("canonical_name",
     "对径配对是 E/O 区分的来源：撤掉它，宇称分解退化，O 在 E 之上的增量随之消失"),
    ("code_symbol",
     "experiments/sphaera-ablation/runs/north/spectrum-north.adva; "
     "experiments/sphaera-ablation/runs/north/eo.npz"),
    ("dimension", "native 构造的对称性内容 / 宇称分解的可证伪性"),
    ("status", "bounded-measurement"),
    ("scope",
     "**证伪设计（事先写下，见 `docs/maintenance/2026-10-08-our-method-in-the-adva-geometry-lineage.md` §4）**："
     "把节点改成**不按对径配对**——四个环全取北半球，z = 5/13, 12/13, 3/5, 4/5（半径 12/13, 5/13, 4/5, 3/5，"
     "全是勾股合法值），每环四个基本方位，共 16 节点。**预测**：若 E/O 之分源于宇称，去掉对径配对应让它退化。\n"
     "**程序层核对**（不是假设）：生成的 `.adva` 中 `(scale 1/16 (use e))` 出现，"
     "`(scale -1/16 (use e))` 出现 **0 次** ⇒ 编译后的程序里 `sign(z)` 恒为 +1。\n"
     "**E/O 相关性**（564 个月，按日历月去季节）：对径配对（tropical）原始 **+0.7190**，去季节 **−0.0208**；"
     "无对径配对（north）原始 **+0.9915**，去季节 **+0.7962**。\n"
     "**通道尺度**：E 的 sd 由 3.9378 降到 2.5743，O 的 sd 由 0.6435 升到 1.2345 —— 两者量级趋于相当。\n"
     "**主判据 M2−M1（RMSE Δ，负=O 有增量）**，k=1/2/4/6：\n"
     "  对径配对：**−0.0301 / −0.0177 / −0.0059 / −0.0008**（四个 lead 全为负，且随 lead 单调衰减）\n"
     "  无对径配对：**+0.0012 / +0.0009 / −0.0010 / −0.0003**（前两个 lead 为正，即 O 反而有害）\n"
     "**结论**：撤掉对径配对后，O 在 E 之上的增量在**它原本最强的两个 lead 上消失了**，"
     "预测命中，**本证伪点未能证伪该理论**。"),
    ("assumptions",
     "两侧用的目标、窗口、训练/测试划分、消融代码完全相同，只换几何。\n"
     "「north 的 E 是水平项、O 是 z 加权水平项」是从程序里 `sign(z)` 的系数**读出来的**，不是推断的。\n"
     "**north 的 z 取值集合与 tropical 不同**（north 少了 ±3/5 与 ±5/13 里南半球的那一半，多出 12/13 与 4/5），"
     "故这不是「同一几何去掉一半」，而是**一个不同的节点集**；两组差异不能全部归给对径配对。"),
    ("dependencies", ["xue.native.sampling-region-is-decisive.v0",
                      "xue.native.rational-arithmetic-sampling-boundaries.v0"]),
    ("proof_or_certificate",
     "`runs/north/spectrum-north.adva`、`runs/north/req.json`（564 case × 48 输入）、"
     "`runs/north/nat.json`（原生求值 564 次，`native functions=12, evaluations=564, bytes=3253333`）、"
     "`runs/north/eo.npz` 全部留存，可重跑。\n"
     "对径配对的对照为 `runs/tropical/eo-500.npz` 与同一 `ablate.py --lead k`。"),
    ("counterexample_boundary",
     "**不**主张「宇称分解已被证实为 E/O 区分的唯一来源」——本件只证明**撤掉对径配对会让它退化**，"
     "这是必要条件方向上的一步，不是充分性证明。\n"
     "**次判据 M4−M3 在本对照上不区分**：对径配对 −0.0028/−0.0047/−0.0011/+0.0007，"
     "无对径配对 −0.0019/−0.0032/−0.0023/+0.0009，两者同量级同符号。故本件结论**只建立在 M2−M1 上**，"
     "不得说「两条判据都支持」。\n"
     "**E 单通道反而更强**：north 的 M1 test corr 0.2378 高于 tropical 的 0.1116 —— "
     "水平项携带更多原始信号但不携带宇称信息，故「north 的 M1 更好」**不**说明该几何更好。\n"
     "**不**据此推断南半球节点无用 —— 本件没有做「南半球only」的对称对照。"),
    ("forbidden_conflations",
     "不得把本条写成「宇称对称性是 E/O 区分的原因」这一**因果确证** —— 本件做的是单侧撤除，"
     "差异还混着 z 取值集合的变化（见 assumptions）。\n"
     "不得引用 M2−M1 的增量而省略 M4−M3 不区分这一事实 —— 那会把一条判据的读数说成两条。\n"
     "不得把 north 几何的 M1 更强读成「北半球更好」—— 那是水平项信号量的问题，不是位置优劣的问题。\n"
     "不得写「证实了 adva 0243 关于 parity 的论述」—— 本件测的是**我们构造里**的 E/O 行为，"
     "与 0243 的 O(3) 论证是记录层与观测层两件事。"),
]


def render(fields) -> str:
    out = ["\n[[claim]]\n"]
    for key, val in fields:
        out.append(f"{key} = {json.dumps(val, ensure_ascii=False)}\n")
    return "".join(out)


def main() -> int:
    assert [k for k, _ in FIELDS] == [
        "claim_id", "canonical_name", "code_symbol", "dimension", "status",
        "scope", "assumptions", "dependencies", "proof_or_certificate",
        "counterexample_boundary", "forbidden_conflations",
    ], "字段顺序/名称不符"
    assert len(FIELDS) == 11, f"字段数 {len(FIELDS)}"

    old = CLAIMS.read_text()
    before = tomllib.loads(old)
    n0 = len(before["claim"])
    ids0 = {c["claim_id"] for c in before["claim"]}
    assert FIELDS[0][1] not in ids0, "claim_id 已存在，不覆盖"

    new = old.rstrip("\n") + "\n" + render(FIELDS)

    parsed = tomllib.loads(new)              # 先验证，后落盘
    n1 = len(parsed["claim"])
    assert n1 == n0 + 1, f"claim 数 {n0} → {n1}"
    last = parsed["claim"][-1]
    missing = [k for k, _ in FIELDS if k not in last]
    assert not missing, f"缺字段 {missing}"
    assert len(last) == 11, f"末尾 claim 有 {len(last)} 个字段"
    for c in parsed["claim"]:
        assert len(c) == 11, f"{c['claim_id']} 有 {len(c)} 个字段"

    CLAIMS.write_text(new)
    print(f"  TOML 验证通过：claim {n0} → {n1}，每条 11 字段")
    print(f"  新增 {last['claim_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
