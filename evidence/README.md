# `evidence/`：要版本化的字节级证据

`archive/` 被 `.gitignore` 排除，理由成立（受限再分发的第三方数据 ＋ 可重建的大数组）。
但它同时也装着**我们自己生成的、体积很小的文本结果**——`report.json` / `run.log`——
而那些是**字节级证据**：闸门、对照、留痕的失败、以及各文档逐条引用的 sha256 都在里面。
把它们留在版本控制之外，等于**服务器一丢，证据就没了，而引用它们的文字还在 git 里**。

所以本目录把那一层单独拿出来跟踪。

## 规矩（由 `scripts/evidence_sync.py` 机械执行）

| | |
|---|---|
| **纳入** | `archive/*/report.json`、`archive/*/run.log`，以及 `archive/*/*.json` 中**小于 1 MB** 的 |
| **排除** | 数组与图（`.npz .npy .png .svg .gif .jpg .nc .h5 .zarr .zip .gz .pkl .pt .bin`）与超限文件 |
| **也排除** | `package.json` / `package-lock.json` / `yarn.lock` / `pnpm-lock.yaml`——那是依赖元数据，不是结果证据；且其来源 `experiments/observable-seasonal/` 已被本仓库跟踪，复制过来只是重复 |
| **只追加** | 已存在的证据文件**永不覆盖**：字节相同 ⇒ 跳过；字节不同 ⇒ **拒绝并报错**（非零退出）。证据真的变了，说明归档件被改写过，那本身是值得人看一眼的事 |
| **可核对** | 每件在 `MANIFEST.jsonl` 里记 `source`／`evidence`／`sha256`／`bytes`／`copied_utc` |

**怎么核对**（复制件与归档原件是否同一批字节）：

```bash
python scripts/evidence_sync.py --check      # 只报告，不写
python scripts/evidence_sync.py              # 幂等：已存在的跳过，冲突的拒绝
```

2026-09-28 首次导入实测：**103 件、1,113,553 字节**（`evidence/` 占 1.5 MB），
逐件与 `archive/` 原件比对 **103/103 一致、0 不一致**。

## 首次导入的一次范围更正（留痕）

首次扫描把 6 个包元数据文件（`observable-seasonal-v{1,2,3}` 的 `package.json` 与 `package-lock.json`）
也拉了进来。它们与已跟踪的 `experiments/observable-seasonal/` 重复，且不属于结果证据 ⇒
**已剔除**，`MANIFEST.jsonl` 相应从 103 条修剪为 97 条。
该更正发生在**首次提交之前**，属范围修正，故直接改写 MANIFEST 而不是追加一条更正——
**此后的任何变化都必须是追加**。

另外做了一次公开前的安全扫描（`password|secret|api_key|token|bearer|private_key` 等）：
命中的 5 个文件全部是**词形误报**——一处是我自己在 E2 检查器里写的字段名
`face_label_tokens_in_values`，其余是 npm 包名（如 `js-tokens`）。
**无凭据、无邮箱、无私钥。** 扫描结果见提交信息。

## 明确**不在**这里的，以及它带来的风险

| 不在其中 | 体积 | 后果 |
|---|---|---|
| `archive/multivariate-l12-v1/model.npz` | **28 MB** | **共享底座**：所有预报／链式／验证都作用在它的 `vectors`／`maps` 上 |
| `archive/multivariate-l12-v1/projection-L12.npz` | **29 MB** | 观测域、Gram 库、每月残差 |
| `archive/multivariate-l12-v1/forecast.npz` | 13 MB | 冻结预报（G2 复刻闸门的对照物） |
| `archive/multivariate-l12-v1/backtest.npz` | 45 MB | 开发回测的四组预测 |

⇒ **这 115 MB 的 npz 不在 git 里。** 服务器若丢失，**同一批字节就没了**：
模型可以按契约重训，但重训出来的是**不同的字节、不同的 sha256**，
而多份文档（`R4` 的 G5 对账、各轮维护记录、验证器的硬闸门）都按 sha256 引用它们。

**这是本目录刻意留下的一个缺口，不是疏忽。** 它需要另一个机制（对象存储或异地备份），
不在 git 的适用范围里；要不要做、怎么做，是一个决定。

## 与 `archive/` 的关系

`archive/` 里的原件**是主件**，`evidence/` 是它的**版本化副本**。
两者都改动时以 `archive/` 为准，并用 `MANIFEST.jsonl` 的 `sha256` 判定它们是否还是同一批字节。
本目录**不参与任何计算**：没有一段代码从 `evidence/` 读数据。

---

## 异地备份：S3（2026-09-28 建立并已验证）

| | |
|---|---|
| 桶 | **`s3://xue-study-evidence-459231717818-us-east-1-an`**（区域 `us-east-1`，由账号持有人创建） |
| 桶配置 | **版本化：已开**（我开的）／默认 AES256 加密／禁止公开访问／关闭 ACL（BucketOwnerEnforced） |
| 前缀 | **`frozen/`** 17 件 118 MB（冻结底座，可引用性）／**`inputs/`** 97 件 2.83 GB（**不可复得的那一半**） |
| 现存对象 | **114 件，2,946,089,008 字节**（2.95 GB） |
| 授权方式 | 实例角色 `instanceRole`（`arn:aws:iam::459231717818:instance-profile/instanceRole`）⇒ **机器上没有任何长期密钥** |

**验证结果（同日实测）**

| 路径 | 做了什么 | 结果 |
|---|---|---|
| `verify`（廉价） | 逐件比对尺寸 ＋ **我们上传时记录的摘要**（对象 metadata） | **114/114**，`mismatched=0` |
| `deep`（决定性） | 把每一件**下载回来重算 sha256** | **114/114 逐字节一致** |

**一条必须说清的限度**：S3 对这些对象**没有存 `ChecksumSHA256`**——`s3 cp --checksum-algorithm SHA256` 与 `s3api put-object --checksum-sha256` 都试过，对象上只有 multipart ETag（实测 aws-cli 2.37.4）。所以：

- `verify` 通过的含义是「**这是我们上传的那个对象，且本地文件没有漂移**」——**不是**「S3 里的字节完好」；
- 「S3 里的字节完好」由 **`deep`** 证明（下载＋重算），并在此之上叠加 S3 自身的写入/读取校验。

**用量与成本**：开了版本化、且第一次上传没带元数据所以重传过一次 ⇒ 现有 **228 个版本 / 5.89 GB**（两代）。标准存储约 **$0.14/月**；同区域下载不计流量费（`deep` 因此是免费的）。`sync` 已改为**增量**：记录的摘要与本地一致即跳过，不会再出现整批重传。

**复现命令**（在实例上）：

```bash
export PATH=$HOME/bin:$PATH
B=xue-study-evidence-459231717818-us-east-1-an
python scripts/backup_to_s3.py plan                     # 逐件哈希，写 evidence/BACKUP_PLAN.json
python scripts/backup_to_s3.py sync   --bucket $B       # 增量上传（自描述元数据）
python scripts/backup_to_s3.py verify --bucket $B       # 廉价校验
python scripts/backup_to_s3.py deep   --bucket $B       # 决定性校验（免费）
```

每次校验都会往 `evidence/BACKUP_MANIFEST.jsonl` 追加一条记录（只追加）。
