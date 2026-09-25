# 2026-09-24：500 hPa 数值谱学习原型与独立 Xue 发布

用户明确选择先做 500 hPa 风场谱学习与实验预报，并要求发布测试通过后共同研究同化。

实际实现与范围见 `experiments/wind500-seasonal/README.md`。这一轮补上了真实历史月均资料上的拟合、独立时间段选参与测试，然后把自行生成的数值转换为 Xue 的 bundle 与 Zarr。

本轮必须保留的区分：

1. 本轮训练的是新建数值原型，不是已经迁入 Adva 原生工具链的学习器。
2. 公开月均资料目前更新到 2026-02；这批明确为 2025-12 初始、2026-01—06 目标的历史起报实验，实际生成于 2026-09-24。没有重建历史实时可用性，也没有今天起报的实时预报声明。
3. full 与 even 均保留完整季节气候态；even 仅保留偶阶旋转异常。它不是把所有奇阶从总风场中删除。
4. 留出低阶投影的一个月 MSE 改善约 9.05%，三至六月很弱。数值回读或网页测试通过不证明预报技巧，更不证明长期业务能力。
5. 未实施同化。后续首先需要统一观测与预测状态的时间窗口，并明示误差。

已观察并修复两个发布问题：

- 浏览器把已取消的一字节 Range 探测缓存成后续完整 JSON，导致 JSON 解析失败。`supportsRangeRequests` 增加 `cache: no-store`；实际浏览器复测完整元数据与两组全部月份正常。
- 实验说明浮层遮挡模型选择面板，手机上又遮住色标。降低说明层级并将手机色标下移；实际点击切换和布局边界检查均通过。

工程验证证据在 `archive/wind500-seasonal-v1/`。科学检查 4 项、前端 118 项、两组各 6 帧原生回读、标准 Zarr 读取、真实浏览器两模型/点位曲线/手机检查。方法纪律检查输出 7/7，其中 card 校验仍受原有工具可用性限制，详见日志；不能将其描述为新增科学结论的全面证明。

Xue 独立工作树：`/home/ubuntu/climatetensor-xue`，分支 `climatetensor-publish`。
公开站点：https://climatetensor.io/?lang=zh
方法与下载：https://climatetensor.io/experiment.html
静态版本：`/var/www/climatetensor/releases/wind500-v1-20260924`。
Caddy 从 `/var/www/climatetensor/current` 提供服务。
原始 `/home/ubuntu/xue` 工作树未修改，也未向上游仓库或外部数据桶推送。
