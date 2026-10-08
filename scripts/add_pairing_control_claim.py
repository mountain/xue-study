"""追加「是对径配对、不是 z 取值集合，决定 E/O 之分」这条 claim。

写入前用 tomllib 验证（TOML 已被写坏 3 次）。同时把上一条证伪 claim 的
counterexample_boundary 里那条「南半球 only 未做」的遗留项，改为指向本件。
"""
import json
import pathlib
import tomllib

CLAIMS = pathlib.Path("docs/claims.toml")

FIELDS = [
    ("claim_id", "xue.native.antipodal-pairing-not-the-z-set-drives-the-eo-split.v0"),
    ("canonical_name",
     "决定 E/O 之分的是对径配对，不是 z 取值集合：|z| 固定时恢复配对，"
     "去季节 corr(E,O) 由 +0.80 落回 −0.17，M2−M1 由 +0.0012 变为 −0.0552"),
    ("code_symbol",
     "experiments/sphaera-ablation/gen_controls.py; "
     "experiments/sphaera-ablation/runs/south/spectrum-south.adva; "
     "experiments/sphaera-ablation/runs/paired8/spectrum-paired8.adva"),
    ("dimension", "native 构造的对称性内容 / 单变量对照 / 证伪件的遗留项收口"),
    ("status", "bounded-measurement"),
    ("scope",
     "上一件（`xue.native.antipodal-pairing-is-the-source-of-the-eo-split.v0`）留了限制 #3："
     "`north` 与 `tropical` 之间**混着两处变化** —— 配对被撤掉，**且 z 取值集合也变了**，"
     "故那次读数不能干净地归给配对。本件造两个**单变量对照**，都把 |z| 集合钉死成与 `north` 相同的 "
     "{5/13, 12/13, 3/5, 4/5}：\n\n"
     "`south`（16 节点）z = −(5/13, 12/13, 3/5, 4/5)：|z|、节点数、方位都与 `north` 相同，"
     "只有**半球**相反，且配对在两者中**都不存在** ⇒ north vs south 只动半球。\n"
     "`paired8`（32 节点）z = ±(5/13, 12/13, 3/5, 4/5)：|z| 集合与 `north` 完全相同，"
     "但把**对径副本加回来** ⇒ 配对恢复 ⇒ north vs paired8 只动配对。\n\n"
     "**「只动一个变量」是程序里的事实，不是说法**：`gen_controls.py` 从生成的 `.adva` 里解析系数并断言 ——"
     "E 系数 = sign(z)/N，O 系数 = |z|/N；`south` 的 **O 系数多重集与 `north` 逐值相同**"
     "（{1/20, 3/52, 3/80, 5/208}），E 系数是 `north` 的**取负**（1/16 → −1/16）。\n\n"
     "**读数（564 月，去季节按日历月；M2−M1 为 RMSE Δ，负 = O 有增量）**：\n"
     "  `tropical`（16 节点，配对有）：去季节 corr **−0.0208**，M2−M1 k=1/2 **−0.0301 / −0.0177**\n"
     "  `north`  （16 节点，配对无）：去季节 corr **+0.7962**，M2−M1 **+0.0012 / +0.0009**\n"
     "  `south`  （16 节点，配对无）：去季节 corr **−0.8187**，M2−M1 **−0.0051 / −0.0093**\n"
     "  `paired8`（32 节点，配对有）：去季节 corr **−0.1651**，M2−M1 **−0.0552 / −0.0346**\n\n"
     "**结论一（收口限制 #3）**：|z| 集合被钉死时，恢复配对把 M2−M1 从 **+0.0012 拉到 −0.0552**（k=1）。"
     "**所以起作用的是配对，不是 z 取值集合。**\n"
     "**结论二**：半球单独不恢复该增量 —— `south` 的 M2−M1（−0.0051 / −0.0093）与 `north` 同量级，"
     "**比 `paired8` 小一个数量级**。\n"
     "**结论三（双峰而非渐变）**：|去季节 corr(E,O)| 在有配对时是 **0.021 / 0.165**，"
     "无配对时是 **0.796 / 0.819** —— 中间是空的。配对是把两个通道分到哪个箱里的那个开关。\n"
     "**结论四**：`paired8` 的 O 增量**超过** `tropical`（−0.0552 vs −0.0301，k=1），即 8 环"
     "（|z| 从 5/13 铺到 12/13）给出的宇称通道比 4 环（5/13 到 3/5）更强。"),
    ("assumptions",
     "四个几何的目标、窗口、训练/测试划分、消融代码完全相同，只换几何与层次无关（层次已另有 claim）。\n"
     "「south 的 O 系数与 north 逐值相同」是从**程序文本**里解析出来比对的结果。\n"
     "`paired8` 唯一的附带变化是节点数 16→32。**注意这不是方位加密**（那是 dense，已被证明无效），"
     "而是**环数加密** —— 两者不同，环数加密本件未单独控制。\n"
     "`south` 的 E 系数是 `north` 的取负，但**取负的是系数不是数据** —— 南北半球的实测风场本就不同，"
     "故 south 与 north 的差异里**混着真实的大气差异**，不只是几何差异。"),
    ("dependencies", ["xue.native.antipodal-pairing-is-the-source-of-the-eo-split.v0",
                      "xue.native.sampling-region-is-decisive.v0"]),
    ("proof_or_certificate",
     "`gen_controls.py` 可重跑，它在生成后**解析 `.adva` 的系数并断言** |z| 被钉死；"
     "`check_arity.py` 核对三个几何的 request 真的给足了程序要的输入"
     "（`north`/`south` 48，`paired8` 96，缺 0 个键，case 564 且 id 唯一）。\n"
     "程序文件：`runs/south/spectrum-south.adva`、`runs/paired8/spectrum-paired8.adva` 已入版本控制；"
     "读数件 `eo.npz`、`nat.json`、`req.json` 在计算主机上留存（各 564 次原生求值，exit 0）。\n"
     "`extract_nodes.py` 四个旧预设的节点表与上一提交**逐节点相同**（回归比对，加分支无副作用）。"),
    ("counterexample_boundary",
     "**不**主张配对是 E/O 之分的**唯一**来源 —— 本件证的是它在 |z| 固定时**决定性**。\n"
     "**次判据 M4−M3 在所有四个几何上都不区分**（`north` −0.0019/−0.0032/−0.0023/+0.0009，"
     "`south` +0.0015/+0.0048/+0.0069/+0.0017，`paired8` +0.0000/−0.0021/−0.0035/−0.0003）⇒ "
     "本件结论**只建立在 M2−M1 上**，不得说「两条判据都支持」。\n"
     "**`paired8` 的节点数翻倍未被单独控制**：方位加密的 16→32 已被证明无效，但**环数**加密的 16→32 没有。"
     "故「paired8 的增量强于 tropical」这条**不得**当作纯粹的配对效应。\n"
     "**不得**把 `south` 的 corr 为负读成「南半球物理相反」——见 forbidden_conflations。\n"
     "**不**主张南半球数据不可用；本件只做了 |corr| 与 M2−M1 的比对。"),
    ("forbidden_conflations",
     "**不得**把 north(+0.796) 与 south(−0.818) 的符号相反读成半球动力学相反 —— "
     "那是**结构性的**：sign(z) 同号时 E 就是 ±（一个水平项），而 O 也是水平项，"
     "故 corr 的符号就是 sign(z) 的符号。符号翻转是 $E = \\mathrm{sign}(z)/N \\sum c$ 的代数后果，"
     "与南北半球的大气差异无关。要读的是 **|corr|**。\n"
     "不得写「证实了对径配对是宇称分解的物理来源」—— 本件测的是我们构造里两通道的**统计关系**，"
     "不是 adva 0243 的 O(3) 论证。那一条是 `RECORDED`，本件是 `OBSERVED HERE`。\n"
     "不得把本条与上一条合并引用而省略 `north`/`south`/`paired8` 三者的几何差别。\n"
     "不得引用「48 个输入」这个数字 —— 它曾是 `extract_nodes.py:138` 的**硬编码字面量**，"
     "对 32 节点的 `paired8` 也印 48，永远无法发现 arity 不匹配。该标签已修，历史读数里的这个数不可信。"),
]


def render(fields) -> str:
    return "\n[[claim]]\n" + "".join(
        f"{k} = {json.dumps(v, ensure_ascii=False)}\n" for k, v in fields)


def main() -> int:
    assert len(FIELDS) == 11, f"字段数 {len(FIELDS)}"
    assert [k for k, _ in FIELDS][0] == "claim_id" and [k for k, _ in FIELDS][-1] == "forbidden_conflations"

    old = CLAIMS.read_text()
    before = tomllib.loads(old)
    n0 = len(before["claim"])
    assert FIELDS[0][1] not in {c["claim_id"] for c in before["claim"]}, "claim_id 已存在"

    new = old.rstrip("\n") + "\n" + render(FIELDS)
    parsed = tomllib.loads(new)
    assert len(parsed["claim"]) == n0 + 1
    for c in parsed["claim"]:
        assert len(c) == 11, f"{c['claim_id']} 有 {len(c)} 个字段"

    # 顺手把上一条的遗留项改成指向本件（append-only：改的是边界描述，不是历史读数）
    marker = "**不**据此推断南半球节点无用 —— 本件没有做「南半球only」的对称对照。"
    if marker in new:
        new = new.replace(
            marker,
            "**不**据此推断南半球节点无用 —— 该限制的对照已由 "
            "`xue.native.antipodal-pairing-not-the-z-set-drives-the-eo-split.v0` 完成"
            "（`south` 与 `north` 同 |z| 集合、同节点数，只差半球）。", 1)
        parsed = tomllib.loads(new)
        assert len(parsed["claim"]) == n0 + 1
        print("  已把上一条的「南半球 only 未做」改为指向本件")

    parsed = tomllib.loads(new)          # 再验一次，然后才落盘
    CLAIMS.write_text(new)
    print(f"  TOML 验证通过：claim {n0} → {len(parsed['claim'])}，每条 11 字段")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
