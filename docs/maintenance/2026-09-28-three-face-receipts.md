# 2026-09-28 · E2：三面收据可区分性（时／空／构）

**性质**：一次有限、可复核的自审，**不是**对自然的发现。问题卡：`docs/problem-cards/three-face-receipts.json`。
**契约（先冻结）**：`experiments/three-face-receipts/contract.json`，sha256 `5f2972d0aee8e232547e0b624af4266c8d0c4f0c0fa86503640ac3e8fa5b2a29`。
**结果**：`experiments/three-face-receipts/{report.json,run.log}`（副本 `archive/three-face-receipts-v1/`）。

---

## 1. 问的是什么

载体已由提问方声明（多年尺度地球系统演化过程），三面（时 T／空 X／构 K）不再是无从定义的并列机制。
剩下一个具体的疑点，是 `0036` §4.1 的红队句：**三角形也许只是改名**。
本件把它变成一次可执行的检验：三面各出一张收据（`atlas` §13 的 12 字段）＋ 四个模板格
（局部单元／重叠／相容条件／粘合产物），要求**每个取值都有见证、每个模板格都有实例**。

判据按读法记录（`docs/adva-triangle-one-rule-three-localities.md`）**§7 的对照 A′**：
**模板格要实例，不要名字**——「能写下『重叠＝相邻界面』这句话」不等于「指得出一个真实的相邻对」。

---

## 2. 判定

| 项 | 实测 |
|---|---|
| `tool_status` | **ok** |
| 条件一（11 个受计字段中 ≥4 个三面两两不同） | **成立**：`distinguishing_fields = 11` |
| 条件二（12 个模板格全部 `present`） | **不成立**：只有 **7/12** |
| 判定 | **`partial_frontier`（不是三面）** |
| 预测（契约里先写死 13 条） | **13/13 命中** |
| 负对照 C1（6 种面标号置换 ＋ 标号不内嵌） | 通过 |
| 负对照 C2（复制同一张 ⇒ 区分度必须归零） | 通过（归零，判定降级为 `relabel_risk`） |

**不成立的五个模板格**：

| 面 | 格 | 状态 | 理由 |
|---|---|---|---|
| 时 T | 重叠 | **absent** | 6 支箭头**共源**（都从同一初始月 `x[-1]` 出发）⇒ 无「上一支输出＝下一支输入」的相邻对 |
| 时 T | 相容条件 | **absent** | 无重叠 ⇒ 无界面可验；lead 之间从不做相容检验 |
| 时 T | 粘合产物 | **absent** | 6 个 lead 是 `np.stack` 的**并列**，不是依次复合 `f₁;…;f₆` |
| 空 X | 重叠 | **degenerate** | 交集＝域本身（平凡覆盖）；同域月份共享同一 Gram |
| 空 X | 粘合产物 | **absent** | 不同域之间无并集粘合；系数是 `np.concatenate` 的**并列** |

**⇒ 本载体上完整的三段式只有「构 K」一面**：作用域（契约的 reads／writes／prohibited）＋真实共享
（`archive/multivariate-l12-v1/` 的冻结件同被两个实验读）＋在共享件上真的做了相容检验（逐件 sha256 全等、
结果目录拒绝覆盖）＋真的粘出了整体项（问题卡 C1–C10 与维护记录的 append-only 台账）。

---

## 3. 最要紧的一条后果（以及它不是新原因）

T 面缺重叠／相容／粘合，说的就是：**冻结模型是「同一初始月的并列直映」，没有依次应用**。
这与 `experiments/multivariate-reforecast/contract.json` 的 `reachability_rule`
（`target T needs initial M with 0 < T-M <= 6`）**是同一件事的两种说法**——
一个用数据可达性说，一个用框架语言说。**不是两个原因，也不构成新的阻塞。**

差别在于它能指向下一步：要在框架语言里补 T 面，就得把「并列直映」改成
**有界递推 ＋ 逐界面相容检验**，并逐回路记 `τ` 做了什么（生日／覆盖层／构造深度／精确残差）。
这正是 **E3** 的内容，因此 E3 的入口从「回路学到了什么」变成了更具体的一句：
**把 T 面从 1/4 补到 4/4，并把 E2 的收据重跑一遍看它是否真的变了**——那是一句可证伪的话。

---

## 4. 本轮工具自身的一次失败（保留，未抹）

首轮 `python3 check_receipts.py` 报 `tool_status = failure`：

```
C1 failed: counted value embeds a face label:
['k/object_type=digest_record', 'k/arithmetic_domain=exact_integer_and_digest',
 't/embedding=eof_coefficient_vector', 't/expression_or_word=single_matrix_product',
 'x/expression_or_word=mask_then_gram_solve', 't/evaluation_order=single_shot_per_lead',
 'x/evaluation_order=restrict_then_project_per_month', 't/fuel_used=six_matrix_products']
```

**这是检查器的假阳性，不是收据的问题**：裸子串 `t_`／`x_`／`k_` 会命中的
`digest_record`／`six_matrix_products`／`mask_then_gram_solve` 等普通取值。
两件事值得记下来：

1. **失败语义按设计生效**：按契约，闸门不成立即工具失败、**不得报出判定**——首轮确实没有报判定
   （`report.json` 里 `verdict` 被扣下，只留 `failures`）。这是 fail-closed 第一次在本项目里真的咬住。
2. **负对照先咬了自己的工具**：C1 的本意是防「判定来自名字而不是结构」，它先抓到的是我写的匹配规则。
   改为「面标号只算取值**前缀**或**非字母数字边界**」（`(?<![0-9A-Za-z_])(?:t_|x_|k_|时_|空_|构_)`）后通过。
   这段留痕写在 `check_receipts.py` 的注释里（Revision 2）。

---

## 5. 残差（未消除，逐条列出）

1. **检查器只核对见证物存在且含指定子串、取值属于闭词表、计数按写死规则算出**；
   它**不核对** `value` 的措辞与见证物的含义相符——这一层由填写者负责。
2. **三面由同一条流水线执行** ⇒ 本件**不能**支持「三面相互独立」，也**不能**支持三计算校准
   （`0155` §6.2：多数票不构成三计算）。
3. **条件一的证明力低**：闭词表由填写者设计，只要给三面各留一个不同元素，计数就自动 ≥4。
   契约的 `self_disclosure` 已把这条写在填收据**之前**，以免事后把它当成功劳。
4. **「实例」的指认仍由填写者作出**：第三方能复核见证物存在与取值合法，复核不了「这个实例算不算重叠」。
5. **未做**：把 T 面的重叠与粘合真的做出来再看收据是否变 4/4（属 E3）。

---

## 6. 不得据此写进报告层的

- **不得**写「三面已建立」。只能写「三面读法已定义，其中**构**面在本载体上完整」。
- **不得**把 11/11 当作三面不同的证据。
- **不得**把 `degenerate` 记成 `present`。
- **不得**在填收据之后修改契约（改则另立 v2；收据里的 `contract_sha256` 会使旧收据失效）。

---

## 7. 本轮的附带修复：仓库本地与远端不同步

核对见证物时发现 `experiments/multivariate-reforecast/{contract.json,extend_inputs.py,reforecast.py,cfs_reference.py,extend.log,reforecast.log}`
与 `experiments/vocabulary-accounting-e1/run.log` **只在远端仓库存在**，本地缺失（早前的写法是先在
`work/common` 暂存目录写、再传到远端跑，本地仓库副本没有回填）。本件已把这 7 个文件取回本地，
并把本地的 C10 更正、读法记录、E2 全部文件同步到远端，两侧一致。

---

## 8. 附记：**跨机复跑**（同日，事后补记）

E2 的结果在**两台机器**上各跑过一次检查器（本机 macOS ／ 远端 Linux／python 3.14＋numpy 2.4.6）：

| 项 | 实测 |
|---|---|
| 两份 `report.json` 的字段数 | 20 |
| **不相同的字段** | **只有 `checked_at_utc`**（检查时刻，`17:17:28Z` 对 `17:18:24Z`） |
| 其余 19 个字段（判定、计数、`slot_state`、两组对照、13 条预测） | **逐项相同** |

⇒ 判据与计数**与机器无关**；唯一不可复制的量是"什么时候检查的"。
两份报告已统一为本机那份（逐字节相同），以免同一轮留下两个版本。
