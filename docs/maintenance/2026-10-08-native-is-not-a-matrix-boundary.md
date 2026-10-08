# 2026-10-08 · 我们的矩阵工作是否在「native 不是矩阵」这条禁止线内

**件**：`experiments/sphaera-ablation/README.md`（本仓库）；依据件为
`mountain/adva-machine@a0b710a2517f06f2fe03cc463e855548adf418ac:spec/framework/repository-exchange-registration-v0.1.md`。

**提问**：我们是否已经在 adva 与 process-geometry 反复强调的
「native 构造不是矩阵」这个禁止线内工作？同时 native 构造上也有链式法则。

**答**：**不在禁止线内，但有两处具体不合规。** 而第二问正是要害 —— 而且它指出了一处
我们一直在悄悄等同的东西。

---

## 1. 禁止线的准确措辞（三处原文，均取自 `~/Adva/adva` @ `3a6ba55`）

```
docs/NEXT_PHASE_PROGRAM_SLICES.md §3「不得静默重开的基本事实」
  · The native object is an open finite program, not a value or matrix.
  · Current matrix-like and expression-valued backward constructions are
    bounded research witnesses, not stable ontology.

AGENTS.md
  · process-geometry supplies theory and independent regression oracles.
    Do not silently copy its experimental claims into the stable API.

docs/adr/0006（Program process before values and compiled projections）
  · Scalar evaluation is a certified projection of this DAG.
  · Process exponentials, resolvents, ..., matrices, spectra ... remain
    DERIVED RESEARCH CONSTRUCTIONS.
  · Matrix and spectral experiments MUST BEGIN FROM CHECKED CUT TRANSPORT
    and retain an explicit residual.
  · Equality of values, frontiers, or schedule endpoints still does not
    identify program histories.

docs/adr/0004（Frontier before compiled presentations）
  · frontier 只是「有序的类型化开放边界」，不主张 tensor / matrix 语义。
  · 矩阵类对象 = 「相对于【声明的基】的 action 或 transport 呈现」，
    且在【挣得】之后作为【单独的编译产物】进入。
  · Polynomial 与 action 呈现【不得静默成为本体，也不得成为默认数值求值器】。
```

而且 process-geometry 把这条**编码成了可执行的测试**
（`~/research-inputs/process-geometry-reference-20260924`）：

```python
def test_native_process_evaluator_does_not_compile_a_series_or_matrix():
    forbidden_names = ("interaction_log_coefficients",
                       "build_substitution_matrix",
                       "substitution_coefficient")
    # 把这三个函数猴子补丁成抛异常，再跑 native 求值器
    def forbidden(*_a, **_k):
        raise AssertionError("the native evaluator called the coefficient compiler")
    ...
    result = module.evaluate_escape_process(...)   # 必须跑得通
```

**⇒ 禁止的不是「用矩阵」，而是「native 求值器经过系数／矩阵编译器」。**
两条代码路径，矩阵编译器是从 native 过程**派生**出去的**独立产物**，永不**进入**它。

---

## 2. 它实际禁止的六件事

| # | 禁止 | 出处 |
|---|---|---|
| 1 | native 对象是值或矩阵 | NEXT_PHASE §3、ADR 0006 |
| 2 | **native 求值器经由系数／矩阵编译器** | process-geometry 的可执行测试 |
| 3 | 矩阵呈现**静默成为本体或默认数值求值器** | ADR 0004 |
| 4 | 把 process-geometry 的实验主张**静默复制进稳定 API** | AGENTS.md |
| 5 | 矩阵实验**不始于 checked cut transport** | ADR 0006 |
| 6 | 矩阵实验**不保留显式残差** | ADR 0006 |

---

## 3. 我们的东西是什么

链式外推的算子是 `x @ vectors @ maps[0]` —— **在声明的 EOF 基上的岭回归映射**。

按 ADR 0004 的分类，这**正是** `ActionPresentation`：
> 「相对于**声明的基**的 action 或 transport 呈现，常用于离线编译与重放」。

**⇒ 它【被允许】，前提是作为【挣得的编译产物】进入，并声明 ADR 0004 要求的那组字段。**

**⇒ 所以：不在禁止线内。**

---

## 4. 但有两处具体不合规（这是本条真正的交付）

### 不合规之一：我们没有 checked cut transport

ADR 0006 原文：矩阵与谱实验**必须始于 checked cut transport**。

```
xue-study 里：
  SharedProgramDiagram   无
  CausalCut              无
  graft / ProgramTerm    无（sphaera 之外）
```

我们的矩阵是**在 NetCDF 场上做岭回归拟合**得来的，**不源自任何已检查的图**。

> **这不只是「没有声明」，是「起点不同」**：adva 的呈现从已检查的图**派生**，
> 我们的矩阵从数据**拟合**。这条不是补几句声明能补上的。

### 不合规之二：ADR 0004 要求的呈现字段缺四条

`ActionPresentation` 必须声明：source presentation、**basis**、action/transport table、
**composition law**、**decoder**、**replay certificate**。

核对我们的契约：

```
basis            —           ← 缺
composition law  —           ← 缺
decoder          —           ← 缺
certificate      —           ← 缺
replay           有（G2a/G2b 逐位相同）
residual         有（报告里有）
```

**六条里有两條，缺四条。**

---

## 5. 第二问是要害：native 的链式法则不是我们的那一条

**native 的链式法则**（ADR 0006）：

```
ProgramTerm::Call = PSC0 的有界同时替换
  · 实参程序对【被调方的边界】做检查后被 graft，不带隐式共享
  · 载体是 SharedProgramDiagram（已检查的出现 DAG）
  · 返回证书；【不产生值、方程、来源身份或出现身份】
  · 逐次应用在实现层就是【开孔 ＋ 粘合】
```

**我们的「链」**：同一个矩阵 `maps[0]` 反复作用 —— **矩阵复合**。

而 adva 明确禁止把两者悄悄等同：

```
0036 §2.5        「应用与替换不得被悄悄等同」
ADR 0006         「Equality of values, frontiers, or schedule endpoints
                  still does not identify program histories.」
```

**⇒ 我们把它叫「链式外推」时，用的是它在【呈现层】的含义。**
它与 native 的 graft 链式法则**不是同一个操作**，而我们从未在记录里把这条线画出来。

---

## 6. 一处漂亮的呼应：我们昨天量到的那件事，正是这个分层的症状

链式外推里，**「粘合」形式上成立、内容上几乎不承载信息**：
把界面故意错位 12 个月，resolved 误差只变大 **3–13%**。

**在 ADR 0004/0006 的语言里，这正是应该的：**

> 我们的 `gluing_ledger` 粘的是**归一化异常系数向量**（呈现层的界面）。
> native 的粘合粘的是**空洞（holes）与出现（occurrences）**，载体是出现 DAG。
>
> **⇒「粘合是形式而不是信息通道」不是经验上的巧合 ——
> 它是「比粘合被定义的那一层低了一层」的症状。**

这一条把我们自己的经验发现与 adva 的架构判据接上了，而且**两边都不知道对方**。

---

## 7. 那么该怎么办（四条，按代价从小到大）

1. **改名与补声明**：把那条叫 `ActionPresentation`，补齐 basis / composition law /
   decoder / 证书四项。**不再用「链」不加限定** —— 至少写成「呈现层的矩阵复合」。
2. **把不合规之一如实登记**：我们的矩阵**不源自 checked cut transport**，
   而是数据拟合的呈现。这不是可以补声明的缺口，**要写成一条已知的不合规**。
3. **ensemble 不得建在呈现层而不声明**。ADR 0004：呈现**不得静默成为本体**。
   一个建在矩阵呈现上的集合，**继承呈现层的全部限制** ——
   包括「它的界面不承载 native 结构」这一条。
4. **要走 native 路线，从 `sphaera-frame` 开始，不是从头。**
   本仓库**已经有**一个真正的 native 层实验：

```
experiments/sphaera-frame/
  · 生成的 .adva 程序由真正的 adva-lisp crate 解析、链接、编译、验证、求值
  · 48 个编译器生成的 GraftFrame，身份／有序空洞／调用历史／显式 copy 出现／
    编译-graft-导入证书全部保留在 native.json
  · 自述：「它不把 Python 对象改标签冒充 native frame」
  · 「Python 提供有限源程序与有理输入；它【不】分配 native 语义身份，
     也【不】求值 Adva 程序」
```

**那条路已经铺好了。**

---

## 8. 不得据此写的

- **不得**写「我们的矩阵工作违反了 adva 的禁止线」。**它没有被违反** ——
  禁止的是 native 对象是矩阵、以及 native 求值器经过矩阵编译器，我们两者都不是。
- **不得**写「我们的链就是 native 的链式法则」。**不是**，两者是不同层的不同操作。
- **不得**把第 6 节那条呼应写成「我们证明了 adva 的架构判据」——
  那是**我们的读数与它的判据相合**，不是我们验证了它。
- **不得**因为「这是研究不是稳定 API」就把两处不合规当成不需要登记。
  ADR 0006 那句话（始于 checked cut transport）**没有限定在稳定层**。
