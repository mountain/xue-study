# 2026-10-08 · 走 native 路线：从 `sphaera-frame` 起步，已可复现

**起自**：上一件判定「我们的矩阵工作不在禁止线内，但两处不合规」，
并指出本仓库**已经有一个真正的 native 层实验**（`experiments/sphaera-frame`）。
本件是**从那里开始走**的第一步：把那条路打通并验证可复现。

---

## 1. 这条路线为什么是本仓库已有的

`sphaera-frame` 不是「用 Python 模拟 native」，它明写并做到：

```
· 生成的 .adva 程序由真正的 adva-lisp crate
  解析 → 链接 → 编译 → 序列化 → 经校验导入 → 求值
· 该次编译含 48 个编译器生成的 GraftFrame
  身份 / 有序空洞 / 调用历史 / 显式 copy 出现 / 编译-graft-导入证书全部保留
· 「它不把 Python 对象改标签冒充 native frame」
· 「Python 提供有限源程序与有理输入；它【不】分配 native 语义身份，也【不】求值 Adva 程序」
```

`turn-i` 的 native 定义很短，但正是要点：

```lisp
(def turn-i
  (fn ((e Real) (o Real)) (outputs Real Real)
    (frontier (neg (use o)) (id (use e)))))
```

**「编译器保留两个来源；数值相等永不合并它们。」** —— 这就是 native 层与呈现层的分界，
写成了一行程序。

---

## 2. 打通了什么（本件实际做的）

### 前置一度看似不满足，实为满足

```
契约要求 machine_revision = 3043be35ff1186d502d091baa8bb96581449595c
本机 ~/Adva/adva-machine  HEAD = a0b710a2517f06f2fe03cc463e855548adf418ac   ← 不匹配
```

**但 `3043be35` 是本机历史的祖先**（2026-09-22，`fix: mirror the terminology-home version rule`）。
故用 **worktree** 检出于 `Cargo.toml` 期望的路径，**不动 `~/Adva/adva-machine` 的未提交改动**：

```sh
git -C ~/Adva/adva-machine worktree add /Users/mingli/Climate/adva-machine \
    3043be35ff1186d502d091baa8bb96581449595c --detach
```

`Cargo.toml` 写的是 `adva-lisp = { path = "../../../adva-machine/crates/adva-lisp" }`，
从 `experiments/sphaera-frame/` 出发即 `Climate/adva-machine`，与上面一致。

**依赖不必联网**：`Cargo.lock` 的 13 个外部包（`serde` 1.0.229、`syn` 3.0.5、
`thiserror` 2.0.20、`zmij` 1.0.23 等）**在本机 cargo 缓存里都有精确版本**
（首次核对时我用只取首个匹配的 glob，误判为「版本对不上」；逐版本核对后全中）。

```sh
cd experiments/sphaera-frame
cargo build --offline --locked      # 8.87 s，编译 adva-ir 与 adva-lisp 自 pin 上的 worktree
```

---

## 3. 一处平台限制（必须与结论同时说）

**契约检查器在本机跑不了**：

```
check.py 用 preexec_fn=native_limits，其中
  resource.setrlimit(RLIMIT_AS, 2048 MB)
  resource.setrlimit(RLIMIT_CPU, 40 s)
  resource.setrlimit(RLIMIT_FSIZE, 16 MB)
在 macOS 上抛 subprocess.SubprocessError: Exception occurred in preexec_fn
```

⇒ **`RLIMIT_AS` 在 macOS 上不经这条路径生效。** 而契约把这三条限制写死了，
**去掉限制去跑等于改契约**，所以本机**不能产出证据**。

**分工（实测）：**

| | 构建 | 契约检查器 | 说明 |
|---|---|---|---|
| 本机 macOS | ✓ 8.87 s | ✗ | `RLIMIT_AS` 不经 `preexec_fn` 生效 |
| 远端 Linux `ubuntu@34.200.151.98` | ✓ | ✓ | 且 `~/adva-machine` **恰在 pin 上** |

远端复现：

```sh
ssh -i ~/.ssh/mingli-us.pem ubuntu@34.200.151.98
cd ~/xue-study/experiments/sphaera-frame && python3 check.py --out runs/run-002
```

---

## 4. 复现结果：**原生路径逐位可复现**

`runs/run-002`（远端新跑）对 `runs/run-001`（2026-09-24 的原跑）：

```
native.json    a352e561fa92c91a  a352e561fa92c91a   逐位相同 ✓   ← 1,223,225 B，含 48 个 GraftFrame 与证书
request.json   95b169b2a2b72622  95b169b2a2b72622   逐位相同 ✓
spectrum.adva  5540b54c60403f0a  5540b54c60403f0a   逐位相同 ✓
frame.json     7d43a177229866c8  7d43a177229866c8   逐位相同 ✓
evidence.json  6a34e631e60a7e15  05299da53ab901c9   不同
```

**`evidence.json` 的唯一差异是 `elapsed_seconds`（0.4302060970076127 对 0.5665729390020715），
其余键逐位相同**；`native_evaluations = 283` 两次相同。

> **⇒ 唯一不可复制的量是墙上时间。原生路径（含全部身份与证书）逐位可复现。**

本机直接跑二进制（**不带 rlimit，故非证据，仅用于开发迭代**）也给出
逐位相同的 `native.json`（`a352e561fa92c91a`）。

---

## 5. 路线已通，下一步是它自己写下的那一问

`sphaera-frame` 的 README 末尾原话：

> **The next question is whether the added channel carries information about a specified
> future monthly/seasonal target after conditioning on the original channel, season and
> slow-variable baselines. The old and new observers should remain available as an
> **ablation pair** for that comparison.**

**⇒ 这正是把「native 构造」接到「季节预报」上的那一问，而且它自带消融对（旧观测 vs 新观测）。**

---

## 6. 边界与操作事实

- **不得**把本机不带 rlimit 的运行当作证据 —— 契约固定了三条资源上限，去掉就不是同一次运行。
- **远端 `~/xue-study` 有未提交改动**（`docs/maintenance/2026-09-28-era5-sp-sst-feasibility.md`、
  `evidence/MANIFEST.jsonl`、`experiments/continuous-assimilation/*`，
  以及未跟踪的 `2026-10-07-era5-september-complete.md` 等）。
  **那是另一个 agent 正在做的工作，本件只读、只新建 `runs/run-002`，未触碰它们。**
- 远端 `~/xue-study` HEAD 是 `87696b0`，落后本机（`49bb4d3`）。**本件没有在远端 pull** ——
  在工作区有未提交改动时 pull 是不安全的。
- `sphaera-frame` 是**有限算术校准**，不是预报技巧。契约的 `residuals` 明列
  「no empirical forecasting model」「quadrature evidence is not forecast skill」。
