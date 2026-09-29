# 2026-03…2026-12 十步月均外推 · 页面复现说明

来源件（本页所有读数与图都由它们算出，未做重训）：

- `chain.npz` sha256 `92e2e8512eb9662159f305e7cda4c5f8b9f18ff9e791b0553ee3002082477531`（21,223,310 B）—— 链式外推的十个月 13 通道场（1.25°，141×288）
- `report.json`（链接式外推的冻结读数：粘合账、校准、闸序）
- 生成脚本：`xue-study/experiments/multivariate-chained-reforecast/render_public_page.py`
- 契约：`xue-study/experiments/multivariate-chained-reforecast/contract-publication-2026-12.json`

复现步骤（在服务器上）：

```bash
cd ~/xue-study/experiments/multivariate-chained-reforecast
/home/ubuntu/climatetensor-env/bin/python render_public_page.py
```

页面目录会被拒绝覆盖；重发请先移到别的名字，不要就地改写（发布件按字节留档）。

各文件用途：`fig*.png/svg` 图；`data.json` 读数与定义；`forecast-2026-12-fields.npz`
只含画出来的四个场 ＋ 12 月气候态 ＋ 区域序列；`sha256.json` 逐文件哈希；
`publication-record.json` 发布审查与闸门结果。

图上与文中的三条限制（实验性、非业务；矩阵代次已降为参考；与 CFSv2 的接近是平凡的）
不得删除后再发布。
