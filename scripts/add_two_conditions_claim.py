"""追加「宇称通道需要两个条件同时成立」这条 claim，并给上一条打一个追加式更正。

上一条（`xue.native.antipodal-pairing-not-the-z-set-drives-the-eo-split.v0`）写了
「|corr| 双峰，中间是空的」。`declared` 的 0.2265 落进了那道空隙 ⇒ 该说法被削弱。
按 append-only：改边界描述并留下更正痕迹，不删原句、不改历史读数。
"""
import json
import pathlib
import tomllib

CLAIMS = pathlib.Path("docs/claims.toml")

FIELDS = [
    ("claim_id", "xue.native.parity-channel-needs-pairing-and-equatorward-reach.v0"),
    ("canonical_name",
     "O 的增量需要两个条件同时成立：有对径配对，且节点下探到 |z|=5/13；"
     "配对必要但不充分（declared 有配对却无增量）"),
    ("code_symbol",
     "experiments/sphaera-ablation/gen_controls.py; "
     "experiments/sphaera-ablation/parity_report.py; "
     "experiments/sphaera-ablation/runs/north32/spectrum-north32.adva; "
     "experiments/sphaera-ablation/runs/northhi/spectrum-northhi.adva"),
    ("dimension", "native 构造的对称性内容 / 2×2 合取条件 / 环数混淆的收口"),
    ("status", "bounded-measurement"),
    ("scope",
     "八几何总表（564 月，去季节按日历月；M2−M1 为 RMSE Δ，负 = O 在 E 之上有增量）：\n\n"
     "  `tropical` 16 节点 有配对 最低|z|=5/13  去季节corr −0.0208  M2−M1 −0.0301/−0.0177\n"
     "  `dense`    32 节点 有配对 最低|z|=5/13  去季节corr −0.0133  M2−M1 −0.0212/−0.0158\n"
     "  `paired8`  32 节点 有配对 最低|z|=5/13  去季节corr −0.1651  M2−M1 −0.0552/−0.0346\n"
     "  `declared` 16 节点 有配对 最低|z|=**3/5**  去季节corr **+0.2265**  M2−M1 **+0.0088/+0.0069**\n"
     "  `north`    16 节点 无配对 最低|z|=5/13  去季节corr +0.7962  M2−M1 +0.0012/+0.0009\n"
     "  `south`    16 节点 无配对 最低|z|=5/13  去季节corr −0.8187  M2−M1 −0.0051/−0.0093\n"
     "  `north32`  32 节点 无配对 最低|z|=5/13  去季节corr +0.8553  M2−M1 −0.0062/−0.0021\n"
     "  `northhi`  16 节点 无配对 最低|z|=**3/5**  去季节corr **+0.9627**  M2−M1 −0.0004/+0.0002\n\n"
     "**反例**：`declared` 是标准对径配对（z = ±3/5, ±4/5），却**没有** O 增量。"
     "这推翻了「配对就是那个开关」的简单读法。\n\n"
     "**两个新的单变量对照（都在系数层断言）**：\n"
     "`north32` vs `paired8`：节点数同为 32，**|z| 多重集逐值逐重数相同**（5/13、12/13、3/5、4/5 各 8 次），"
     "E 系数 `north32` 全 +1/32、`paired8` 为 ±1/32 ⇒ **只差配对**。M2−M1 **−0.0062 → −0.0552**。\n"
     "`northhi` vs `declared`：节点数同为 16，|z| 多重集相同（3/5、4/5 各 8 次），"
     "**两者都不下探到 5/13** ⇒ 只差配对。M2−M1 **−0.0004 → +0.0088**，即**有配对也不出增量**。\n\n"
     "**结论一（环数混淆收口）**：节点数在两套配对状态里各被独立翻倍一次，都不改变结论 —— "
     "`tropical`→`dense`（配对与|z|固定，16→32）−0.0301→−0.0212；"
     "`north`→`north32`（无配对，16→32）+0.0012→−0.0062。\n"
     "**结论二**：两个条件都是必要的。配对必要（三个无配对几何全近零）；"
     "下探到 |z|=5/13 也必要（`declared` 有配对但不下探，增量 +0.0088，"
     "其 corr +0.2265 与 O/E 0.560 **都退回到无配对那一档**）。\n"
     "**结论三**：两个条件都失败时退化最彻底 —— `northhi` 的 |corr| = **+0.9627**，八者中最高。\n"
     "**结论四**：`paired8` 强于 `tropical` 不是节点数造成的（翻倍反而略减弱），"
     "剩下的差别是 |z| 跨度（铺到 12/13 = 67.4° vs 只到 3/5 = 53.1°）—— **两个数据点上的线索，不是结论**。"),
    ("assumptions",
     "八几何的目标、窗口、训练/测试划分、消融代码完全相同，只换几何。\n"
     "所有「只差一个变量」的说法都来自**解析 `.adva` 系数后的比对**，不是几何描述上的相似。\n"
     "`declared` 的配对与节点数是从 `extract_nodes.py` 的预设表读的，**不是从程序读的** —— "
     "那批 run（`runs/l500/`）没有留存 `.adva`。输出里已标 `[预设表(无.adva)]`。\n"
     "「下探到 5/13」在本实验里天然被钉在 5/13，因为 **5/13 是有理算术允许的最低 |z|**（22.62°）。"),
    ("dependencies", ["xue.native.antipodal-pairing-is-the-source-of-the-eo-split.v0",
                      "xue.native.antipodal-pairing-not-the-z-set-drives-the-eo-split.v0",
                      "xue.native.sampling-region-is-decisive.v0"]),
    ("proof_or_certificate",
     "`gen_controls.py` 可重跑，它在生成后**解析 `.adva` 系数并断言**三个单变量对照成立；"
     "`parity_report.py` 一张表算完八个几何的统计与消融，节点数/配对**从 `.adva` 读**（`declared` 除外，已标）。\n"
     "`check_arity.py` 核对每个几何的 request 真的给足输入（`north32`/`paired8` 96，其余 48，缺 0 个键）。\n"
     "四个新几何的程序文件已入版本控制；读数件（`eo.npz`/`nat.json`/`req.json`）在计算主机上留存，"
     "各 564 次原生求值，`native functions=12, evaluations=564`。"),
    ("counterexample_boundary",
     "**不**主张配对是充分条件 —— `declared` 就是配对而不出增量的反例，这正是本件的起点。\n"
     "**不**主张「下探到 5/13」是单变量结论 —— `declared` 与 `northhi` 的对照只能证明"
     "**在高纬这一档里配对也不够**；要证「5/13 是关键纬度」需要下探到 5/13 的有配对几何与 `declared` "
     "在其余条件上对齐，**未做**。\n"
     "**不**主张 22.62° 是物理上的关键纬度 —— 5/13 只是**有理算术允许的最低值**，"
     "「能下探多低」是被算术钉死的，不是被物理钉死的。\n"
     "**次判据 M4−M3 在八个几何上仍不区分**（k=1 全部在 ±0.004 内）⇒ 结论**只建立在 M2−M1 上**。\n"
     "**不**把结论四当作结论 —— 那是两个数据点。"),
    ("forbidden_conflations",
     "**不得**把本条读成「配对充足」—— `declared` 是该读法的直接反例。\n"
     "**不得**把 `declared` 与 `northhi` 的对照说成「证明了下探到 5/13 必要」—— "
     "那个对照固定的是「不下探」这一档，两侧都不下探。\n"
     "**不得**把 `declared` 与 `tropical` 的差异单独归给配对或单独归给纬度 —— 两者在 |z| 集合上不同，"
     "是**跨几何比较**。\n"
     "不得引用 `northhi` 的 |corr| = 0.9627 作为「无配对一定更相关」的证据 —— "
     "另有 `south` 的 −0.8187 说明符号随半球翻转（代数后果），有意义的是 |corr|。\n"
     "不得引用「48 个输入」这类硬编码标签 —— 该标签曾在 `extract_nodes.py:138` 写死，对 32 节点也印 48。"),
]


def render(fields) -> str:
    return "\n[[claim]]\n" + "".join(
        f"{k} = {json.dumps(v, ensure_ascii=False)}\n" for k, v in fields)


def main() -> int:
    assert len(FIELDS) == 11, f"字段数 {len(FIELDS)}"
    old = CLAIMS.read_text()
    before = tomllib.loads(old)
    n0 = len(before["claim"])
    assert FIELDS[0][1] not in {c["claim_id"] for c in before["claim"]}, "claim_id 已存在"

    new = old.rstrip("\n") + "\n" + render(FIELDS)

    # 给上一条打追加式更正：双峰说法被 declared 削弱。
    # 注意 \\n 必须转义成两个字面字符，否则会往单行 TOML 字符串里塞一个真实换行 ——
    # tomllib 会拒绝（这正是 repin_contract.py 文档里记的 2026-09-17 那个事故）。
    # 同样更正 claim 正文里的 forbidden_conflations 表述
    new = new.replace(
        "**不得**把 north(+0.796) 与 south(−0.818) 的符号相反读成半球动力学相反",
        "**追加更正（2026-10-08）**：本条写的「有配对 0.02/0.17、无配对 0.80/0.82、中间是空的」"
        "已被 `declared`（配对，corr +0.2265）削弱；且 `declared` 说明**配对必要但不充分**。"
        "现行结论见 `xue.native.parity-channel-needs-pairing-and-equatorward-reach.v0`。\\n"
        "**不得**把 north(+0.796) 与 south(−0.818) 的符号相反读成半球动力学相反", 1)

    parsed = tomllib.loads(new)
    assert len(parsed["claim"]) == n0 + 1, f"claim 数 {n0} → {len(parsed['claim'])}"
    for c in parsed["claim"]:
        assert len(c) == 11, f"{c['claim_id']} 有 {len(c)} 个字段"
    CLAIMS.write_text(new)
    print(f"  TOML 验证通过：claim {n0} → {len(parsed['claim'])}，每条 11 字段")
    print("  已给上一条打追加式更正（双峰说法被 declared 削弱）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
