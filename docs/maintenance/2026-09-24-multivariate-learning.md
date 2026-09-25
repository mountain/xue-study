# 2026-09-24：多变量联合学习、开发回测与 Xue 发布

实现入口：`experiments/multivariate-seasonal/README.md`。
训练前协议：`experiments/multivariate-seasonal/contract.json`。

用户要求加入多变量学习并逐步增加时空分辨率。先保持月均和 L6，下载 NOAA PSL NCEP/NCAR R1 + ERSST v5 的真实 1979—2025 月历史，完成 16 变量、13 通道、778 系数的联合 EOF/ridge 模型；不是此前 ERA5 配置或单时次表示的重复验收。

训练/验证/回测为 1979—2014 / 2015—2019 / 2020—2025。最后一段此前已有 wind500 结果暴露，明确为开发回测。只有训练期参与季节拟合、归一化、EOF 和动力映射估计；验证选全局超参数；没有看回测后改参。

选中 rank 32、penalty 0.1。整体归一化系数 MSE 16.9318，优于气候态 20.3693，但逊于逐通道独立学习 16.0666（高 5.39%）。500 hPa 风一月技巧约 6.60%，独立 AR1 约 9.05%。已公开这一负面比较，不以联通或测试通过宣称模型胜出。跨变量系数不是因果证据，未去除长期趋势。

数据的物理单位和域逐项处理：原生网格面积权重、训练期固定有效域、气压层地下掩膜、比湿对数状态。SST 重建仍有低温越界，原始诊断 NPZ 保留且单独披露，不作为地图预报层发布。sp 也留在完整下载中。其余 14 分量组成 11 个 Xue 图层。

Xue 发布代码：`/home/ubuntu/climatetensor-xue/scripts/climatetensor_multi_publish.py`。
研究页面：`https://climatetensor.io/multivariate.html`。
学习产物、数值/回读/浏览器检查：`archive/multivariate-seasonal-v1/`。
全部仍为 2025-12 初始、2026-01—06 目标、2026-09-24 生成的历史月均实验，未同化、非实时、非原生 Adva 学习器。第一版 FULL/EVEN 保留。

下一步仅先做相同月资料下 L12 的受控比较，然后再引入日/周尺度，之后 L24；本轮未实施这些阶段。原始资料在仓库外缓存，不提交原始再分析，也没有上游 push 或自动训练 cron。

发布目录为 `/var/www/climatetensor/releases/multivariate-v1-20260924`，使用原子 symlink 切换 `current`。旧 release 保留，未重写原始风场产物。Caddy 配置先 validate 后 reload，新增研究下载的公开 CORS，供 Observable 等读取公开 JSON；没有账号写入。

已完成四项数值科学检查、119 项相关前端检查、11×6 帧原生 decoder 与 Zarr 标准库逐格回读、140 个 HTTPS 对象逐字节比对、三个发布指针 CRC/缓存头、后缀 Range 206 检查。方法纪律检查仍显示 7/7，其中旧 Adva card validator 不可用而跳过，不能称为原生科学证明。工程凭据为 `https-verification.json`、`encoding-verification.json` 及分批 `browser-local-*.json` / `browser-public-*.json`。

浏览器初始整批检查耗时较长，改为分批并设置显式超时；早期未完成的逐层日志只作部分检查记录，正式完成凭据使用 JSON。手机截图发现旧站两个入口都指向同一实验页并挤占变量标题，隐藏重复入口、将保留的入口指向新研究页；实际手机布局复查通过。

最终线上验收完成：11 个图层、首页默认 MULTI、三模型切换、6/6 点位序列、研究图、手机标题/说明/色标布局，均通过。三份线上浏览器凭据无 page error 或 HTTP error，共观察到 64 次成功 Range 响应。汇总为 `archive/multivariate-seasonal-v1/implementation-verification.json`。临时本地预览已停止，公开 Caddy 服务保持 active。
