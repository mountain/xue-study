# 2026-10-08 · 我们的 native 方法在 adva 几何谱系里的位置

**件**：`experiments/sphaera-ablation/README.md`（本仓库的方法与读数）。
**引用件**（外部，按坐标）：
`mountain/adva@3a6ba5571491342d0e211a56590a29b2407e284c:docs/research/0243-the-geometry-foundation-shared-items-the-corrected-pairing-and-the-spacetime-group-clause.md`
`mountain/adva@3a6ba5571491342d0e211a56590a29b2407e284c:experiments/geometry_foundation_v1/contract.json`
`mountain/adva@3a6ba5571491342d0e211a56590a29b2407e284c:docs/terminology/geometry-boundaries-v0.json`

---

## 1. 起因

提问方问：我们的 native 方法是否比 sphaera 的涡旋方法更广；adva 线有没有对球几何的论述。

**有，而且它明写了「更广之处在哪」。**

---

## 2. adva 的论述（**这是引文，不是我的推断**）

`…:docs/research/0243-…md` 的 supplement 第一条更正：

```
① 非手性阿基米德多面体的【完整】点群（T_d 24、O_h 48）含 12／24 个非正常元素，
   【不在 SO(3) 里】，只在旋转部分上成立。所以与相对论时空匹配的是
   O(3)（旋转 ＋ 宇称）⊂ O(3,1)
```

同件 §84–86 原话：

> the constellation's side is **O(3) — rotations together with parity** — embedded in the full …
> contain improper elements; **parity is exactly the element that pairs antipodal platforms**

以及第二条更正：

```
② 「地面图案继承点群」是【错的对象】—— 时空对称性才该声明
```

**⇒ adva 的主张是：该声明的对象是【对称性】（O(3) 及其在 O(3,1) 中的嵌入），
不是图案、不是基。**

---

## 3. 我们的方法落在哪一层（**这一段的分层是我的连接，不是引文**）

```
最一般   O(3) ⊂ O(3,1) 的对称性论述              ← adva 0243 / geometry_foundation_v1
         （星座＋排程）在「空间操作＋时间平移」下不变 ⇒ 净输运恰为 0
中间     宇称分解：E 取奇部、O 取偶部              ← 我们的方法在这一层
         证据：E 的权重 sign(z)/N 在 z→−z 下【奇】
               O 的权重 |z|/N   在 z→−z 下【偶】
最具体   涡度球谐的 β_l / γ_l 判据                 ← sphaera 的涡旋方法
```

**「更广」之处在于：我们的 E/O 不预设任何基。** 它是**采样的宇称分解**，
属于**对称群 O(3) 的性质**，不属于任何特定的球谐展开；而涡旋方法预设了涡度的球谐基。

**而 0243 说「parity 正是把对径平台配成对的那个元素」** ——
我们的 **±3/5、±4/5 两条 z 环正是把节点按对径配起来**。
**这不是巧合，是让宇称分解干净的前提。**

---

## 4. 这一分层解释了本轮两条实测结果

| 实测 | 在分层下的读法 |
|---|---|
| **换区域有效**（中纬几何 → 热带几何，O 的增量由负转正，四组切分全过） | 换 z **保住了宇称配对**（±5/13、±3/5 仍成对），故中间层的结构不变而采样位置变了 |
| **加密方位无效**（4 方位 → 8 方位，M4−M3 由 +0.0050 降到 +0.0023、RMSE 反向） | 加密**没有改变宇称结构** —— 四个基本方位与四个勾股对角都在同一 z 环上，宇称归属不变 |
| **换层次非决定性**（250/500/850 三层次同向） | 层次不改变星座的对称性 |

**⇒ 一个可检验的推论**：若把节点**改得不按对径配对**（例如只取北半球），
宇称分解就失去意义，E 与 O 的区分应当**退化**。**这是中间层的一个证伪点，本件未做。**

> **已执行（2026-10-08）**：见 `docs/maintenance/2026-10-08-parity-falsification-north-only-nodes.md`。撤掉对径配对后，去季节 corr(E,O) 由 **−0.0208** 升至 **+0.7962**，M2−M1 由 **−0.0301/−0.0177** 变为 **+0.0012/+0.0009**（k=1/2）。**预测命中，该证伪点未能证伪本件的中层论述。** 但差异混着 z 取值集合的变化，**南半球 only 的对照仍未做**。

---

## 5. 必须标清的边界

1. **`0243` 是 `PROPOSAL ONLY`**，自述「authorizes nothing, decides nothing, asserts no physical
   effect, gives no magnitude for any physical quantity and uses no data」。
   它给我们的是**对象与对称性的语言**，不是可用的数。
2. **O(3) 与我们 E/O 的对应是我做的连接，不是 0243 的陈述。**
   0243 讲的是星座的对称群与时空嵌入；把它读到「宇称分解 ⇒ 两个通道」是我的推断。
   **证据很直接（权重函数的奇偶性），但它仍是推断，应如此标注。**
3. `…:docs/terminology/geometry-boundaries-v0.json` 的状态是 `status = Proposed`、
   `native_admission = NotGranted`、`semantic_identity_allocation = False`
   —— **术语层的提案，不是已准入的语义**。
4. **我量出的两条硬边界（有理算术 ⇒ 纬度 ≥22.62°、经度只能勾股角）是关于
   「哪些有限点集能被精确写出」的限制，不是关于对称性的限制。**
   ⇒ **对称性论述比我们的有限实现更广**；16 节点只是它的一个可精确写出的实例。
5. 本件**没有**做第 4 节那个证伪点；**没有**验证 O(3) 的完整群在任何一层被实际用到
   —— 我们的实现只用到宇称与 90° 旋转这一小部分。
