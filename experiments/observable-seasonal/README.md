# Observable 首篇研究笔记发布候选

2026-09-24。主题：球面模态的年周期、独立扰动、调幅与调相。
用户现已发布到 [@climatetensor/annual-spectrum-1](https://observablehq.com/@climatetensor/annual-spectrum-1)。
2026-09-24 通过公开文档 API 确认版本 27 为 public，所有 9 个单元与本地 v2 源码一致
（仅忽略首尾空白）；创建者为 mountain，所有者为 climatetensor 团队。
网页自动浏览被站点验证页阻断，附件存在新版解析引用。
用户确认下拉框和两张图正常，但没看到校验数字；线上附件运行结果尚未确认。
核查记录在 `../../archive/observable-public-review-20260924/review.json`。
旧 ZIP 中“未发布”是生成时的历史状态；本轮由用户在网页发布，助手没有写入账号。

后续用户已将校验单元替换为简明表格代码，公开版本 **43**：直接读取 JSON，显示四项结果，
失败时显示错误。只有该单元改变，其余 8 单元与版本 27 一致。用户已确认图表和控件正常。
随后用户贴出在线表格：384、true、8.882e-16、0.7788007831，全部与本地附件按显示精度一致，
本轮发布检查完成。在线运行证据来自用户反馈，助手未直接观察网页。
见 `../../archive/observable-public-review-20260924/review-v43.json` 和
`../../archive/observable-public-review-20260924/user-runtime-confirmation.json`。

## 文件

- `docs/annual-spectrum.html`：Observable Notebooks 2.0 开放格式的源文件，9 个单元。
- `docs/annual-check.json`：有限 Python 检验结果，含训练期隔离、频谱和标量 Floquet 例子。
- `cells.md`：按顺序复制到网页笔记本的单元文本，避开未确认的整文件上传入口。
- `package.json` / `package-lock.json`：本地构建依赖，Notebook Kit 固定为 2.6.4。
- 派生包：`../../archive/observable-seasonal-v3/`，含 ZIP、数据 CSV 和浏览器检验记录。
- `calibration-cell.js`：仅替换第 8 个单元的内容，显示明确的状态、数值表格或附件错误。

v1 是本地初稿，手机公式过宽；v2 改为两行公式，是当前线上版本的源。
v3 只改校验显示：先显示读取状态，再显示展开的数值表格；失败时展示真实错误。
v3 已在本地构建与浏览器检验；线上版本 43 采用随后提供的较简短表格代码，
功能目的相同但不与 v3 逐字一致。用户无需重导整篇笔记本。

源 HTML 是笔记本格式；直接双击不等于执行笔记本。用下列构建/预览命令，或迁移单元。

```sh
npm ci --no-audit --no-fund
npm run build
npm run preview
```

Notebook Kit 文档支持本地构建为静态站点，也支持下载已有在线笔记本。
本轮未找到其官方命令行工具将本地文件直接写入账号的已文档化发布命令。
因此不能将本地 `build` 的成功称作已经发布到 Observable。

## 网页迁移步骤

1. 登录自己的 Observable，创建一个 Notebooks 2.0 笔记本。
2. 按 `cells.md` 的顺序创建 Markdown、TeX 和 JavaScript 单元，粘贴对应内容。
3. 将 `annual-check.json` 加为文件附件，保持同名；第 8 单元用 `FileAttachment` 读取。
4. 检查三种扰动、周期和幅度控件，然后在该账号中选择公开发布。

这条路径使用笔记本单元和附件，不依赖未文档化写入 API。
具体网页按钮可能随新版变化；本机匿名浏览器被站点验证页挡住，未能实测登录后的菜单。
工具目录搜索没有找到 Observable 连接；返回的 Datadog 无关，未建议或安装。
本轮使用了 plugin-management 技能进行连接发现，没有使用该技能发送消息或发布内容。

## 我们的资料怎样组织

论文式说明、公式、可修改的轻量实验放在笔记本；冻结检验结果、CSV/JSON 小型数据可以作为附件。
大体积原始气象场、训练归档和完整模型继续保存在自己的数据服务，笔记本可读取选定切片。
跨域读取需要该数据服务正确设置 CORS；当前发布候选使用本地附件，不依赖新增服务端配置。
真实样本图必须保留来源、时间、单位和掩膜；拟合误差不写成预报技巧。

## 核查来源

- [Notebook Kit 的文件格式及 CLI](https://observablehq.github.io/notebook-kit/kit)：四种命令为 preview/build/download/query。
- [新 Observable 公告](https://observablehq.com/@observablehq/a-new-observable)：2026-09-01 的新版入口。
- [新版标准库与单元说明](https://observablehq.github.io/notebook-kit/system-guide)。
- [附件文档](https://observablehq.github.io/documentation/data/files/file-attachments)：附件引用及发布；部分页面保留旧界面说明。

本轮没有核实该账号配额或付费计划，没有要求密码、Cookie 或令牌。

## 已发布版本的读取边界

Notebook Kit 使用的公开文档 API 可读取这篇笔记本，适合核对单元源代码。
旧版 `api.observablehq.com/...js?v=4` 返回的模块只有 5 个定义，遗漏现代单元，
不能据此断言新版网页缺失代码，也不能把该模块当作完整自托管导出。
继续自托管应使用本目录已经验证的新版 Notebook Kit 源文件与附件。
