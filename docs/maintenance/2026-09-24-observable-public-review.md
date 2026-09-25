# 2026-09-24 Observable 公开笔记本核查

发布说明更新于 `experiments/observable-seasonal/README.md`，恢复点更新于 `CONTINUE.md`。
用户提供 https://observablehq.com/@climatetensor/annual-spectrum-1 后进行只读核查。

公开文档 API 返回 public、版本 27、发布时间 2026-09-24T06:54:04.490Z，
创建者 mountain，所有者 climatetensor 团队。9 个单元与此前生成的本地 v2 源文件
逐项一致，仅忽略首尾空白。保留了合成实验的限定、四年调制与三类机制、区间周期定理
的适用条件，以及尚未训练新气象模型的说明。

公开源码有 annual-check.json 的新版 file resolution，旧 files 列表为空不等于没附件。
从该引用拼接旧 CDN 地址返回 403，无法用此判定实际附件不可用。
网页与自动 Chromium 都未能取得正常页面，Chromium 返回 429 / Vercel Security Checkpoint。
已请用户确认在线校验是否显示 samples: 384 与 trainingOnlyFit: true。

另观察到旧版 JavaScript v4 导出只有 5 个单元定义、遗漏新版声明。
不将这一兼容性现象误报为用户网页丢失代码；自托管继续使用已验证的新格式源文件。
完整记录在 archive/observable-public-review-20260924/review.json；原始响应留在仓库外
/home/ubuntu/research-inputs/observable-annual-review-20260924/。
本轮未登录用户账号、未写入 Observable、未修改冻结的 v2 下载包。

用户随后回复没看到校验结果，但确认下拉框及两张图正常。把诊断范围缩小到校验单元；
没有将“没看到”直接归因为附件丢失。原实现通过对象查看器显示，交互提示不够清楚。
本地 v3 用一个独立可见区域先显示读取状态，再显示四行数值表格；读取或格式失败时
显示实际错误。只替换原第 8 单元，`calibration-cell.js` 可直接复制。
新版整页构建与桌面/手机交互通过，另用同一单元源码检查有效 JSON、缺失文件、网络失败、
JSON 解析失败、缺字段五种状态，错误均不能误显为读取成功。
v3 是待用户替换的本地修订，未声称已在 Observable 部署。

用户一度把 calibration-cell.js 当数据模块 import；已给出可直接粘贴的完整简明单元。
再次核查链接：公开版本 43、publish_version 43，id 11 正确使用 FileAttachment JSON，
通过 Inputs.table 显示四项结果，并 catch 显示实际错误；错误 import 不再存在。
与版本 27 比较只有该单元改变，其余 8 单元内容一致。
这是源码核对结果；未把本地试验或用户确认的图表交互等同于实际在线附件内容已读取。
新核查记录为 archive/observable-public-review-20260924/review-v43.json。

最终用户贴出在线表格：samples 384、trainingOnlyFit true、季节拟合最大误差 8.882e-16、
年度传播倍率 0.7788007831。与本地 annual-check.json 按相同显示精度逐项核对一致。
结合用户先前的控件/双图确认，本轮发布检查完成；运行证据明确记为用户反馈，
没有声称助手直接访问成功，也没有验证远程附件所有字节或真实气象技巧。
记录：archive/observable-public-review-20260924/user-runtime-confirmation.json。
