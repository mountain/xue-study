const calibrationStatus = html`<section data-calibration-status style="overflow-wrap:anywhere">
  <p>校验附件：读取中…</p>
</section>`;
display(calibrationStatus);
try {
  const calibration = await FileAttachment("annual-check.json").json();
  if (!Number.isInteger(calibration.sample_count) ||
      typeof calibration.heldout_poison_does_not_change_fit !== "boolean" ||
      !Number.isFinite(calibration.seasonal_fit_max_error) ||
      !Number.isFinite(calibration.scalar_floquet?.annual_multiplier)) {
    throw new Error("附件缺少所需校验字段，请核对 annual-check.json 的内容。");
  }
  calibrationStatus.replaceChildren(html`<h3>合成实验校验：附件已读取</h3>`, html`<table>
    <tbody>
      <tr><th>样本数 samples</th><td>${calibration.sample_count}</td></tr>
      <tr><th>训练期隔离 trainingOnlyFit</th><td>${String(calibration.heldout_poison_does_not_change_fit)}</td></tr>
      <tr><th>季节拟合最大误差</th><td>${calibration.seasonal_fit_max_error.toExponential(3)}</td></tr>
      <tr><th>年度传播倍率</th><td>${calibration.scalar_floquet.annual_multiplier.toFixed(10)}</td></tr>
    </tbody>
  </table>`);
} catch (error) {
  calibrationStatus.replaceChildren(html`<p>校验附件读取失败：${String(error)}</p>`);
}
