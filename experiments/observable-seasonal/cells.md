# 网页迁移：按顺序创建以下 9 个单元

适用 Observable Notebooks 2.0。先附加同名 `annual-check.json`，然后按各节注明的单元类型粘贴。下面是单元内容，不要把整个 Markdown 文件粘进一个 JavaScript 单元。

## 单元 1：Markdown

```markdown
# 球面模态的年周期与扰动

一个分布在球上的物理量，可以先分解成空间模态，再观察每个模态怎样随季节变化。这里展示一个模态的系数：年周期是基线，扰动可以独立相加，也可以改变年周期的强度或相位。

**这是可复算的合成实验，扰动周期由我们指定；尚未从气象资料中识别，也不是新增天气预报。** 本地 Python 已分别检验球面表示、时间频率与下面的调制关系。
```

## 单元 2：TeX

```tex
\begin{aligned}S(a,t)&=\bar S(a,\theta(t))+\eta(a,t),\\\bar S(a,\theta+2\pi)&=\bar S(a,\theta).\end{aligned}
```

## 单元 3：JavaScript

```javascript
const mechanism = view(Inputs.select(new Map([
  ["独立周期相加", "additive"], ["改变年周期强度", "amplitude"], ["改变年周期相位", "phase"]
]), {label: "扰动方式", value: "additive"}));
const period = view(Inputs.select([4, 2, 8], {label: "扰动周期（年）", value: 4}));
const epsilon = view(Inputs.range([0, 0.6], {label: "扰动幅度", value: 0.2, step: 0.01}));
```

## 单元 4：JavaScript

```javascript
const tau = 2 * Math.PI;
function baseline(t) { return Math.cos(tau * t) + 0.3 * Math.sin(2 * tau * t); }
function perturbed(t) {
  const slow = Math.cos(tau * t / period);
  if (mechanism === "additive") return baseline(t) + epsilon * slow;
  if (mechanism === "amplitude") return baseline(t) + epsilon * slow * Math.cos(tau * t);
  return Math.cos(tau * t + epsilon * slow) + 0.3 * Math.sin(2 * tau * t);
}
const curves = Array.from({length: 513}, (_, i) => {
  const year = i / 64;
  return {year, baseline: baseline(year), perturbed: perturbed(year)};
});
const samples = Array.from({length: 384}, (_, i) => perturbed(i / 12) - baseline(i / 12));
const spectrum = Array.from({length: 80}, (_, index) => {
  const k = index + 1;
  let re = 0, im = 0;
  for (let j = 0; j < samples.length; ++j) {
    re += samples[j] * Math.cos(tau * k * j / samples.length) / samples.length;
    im -= samples[j] * Math.sin(tau * k * j / samples.length) / samples.length;
  }
  return {frequency: k / 32, amplitude: 2 * Math.hypot(re, im), phase: Math.atan2(im, re)};
});
const peaks = spectrum.filter(d => d.amplitude > 1e-8).sort((a, b) => b.amplitude - a.amplitude).slice(0, 5);
```

## 单元 5：JavaScript

```javascript
display(Plot.plot({
  width: Math.min(width, 960), height: 280, grid: true,
  x: {label: "时间（理想化年）"}, y: {label: "归一化模态系数", domain: [-2, 2]},
  marks: [Plot.ruleY([0]), Plot.line(curves, {x: "year", y: "baseline", stroke: "#96a4b5"}),
    Plot.line(curves, {x: "year", y: "perturbed", stroke: "#007b88", strokeWidth: 2})]
}));
```

## 单元 6：Markdown

```markdown
灰线是季节基线，青线加入扰动。频谱使用 32 个理想化年、每年 12 个等间隔样本，去除已知基线后计算。下面只展示正频率，计算保留复相位。

对于四年扰动：独立相加产生 0.25 次/年；调幅产生 0.75 和 1.25 次/年。调相的小幅近似也有这两个频率，但复相位不同。只看功率不能充分区分机制。
```

## 单元 7：JavaScript

```javascript
display(Plot.plot({
  width: Math.min(width, 960), height: 260, grid: true,
  x: {label: "频率（次/年）", domain: [0, 2.5]},
  y: {label: "异常正弦幅度", domain: [0, 0.65]},
  marks: [Plot.ruleY([0]), Plot.ruleX(spectrum, {x: "frequency", y1: 0, y2: "amplitude", stroke: "#007b88", strokeWidth: 2})]
}));
display(Inputs.table(peaks, {columns: ["frequency", "amplitude", "phase"],
  header: {frequency: "频率（次/年）", amplitude: "幅度", phase: "相位（弧度）"}}));
```

## 单元 8：JavaScript

```javascript
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
```

## 单元 9：Markdown

```markdown
## 怎样推进到学习器

每个空间模态保留季节相位、复幅度和变量/高度身份。已有 500 hPa 月均风首版使用逐月气候态加全年相同的 AR(1) 异常演化；候选升级是让传播系数也按季节变化，并检验模态之间的耦合。

对周期系数的齐次线性近似，可以研究 Floquet 年度传播倍率：同一季节经过一年，扰动衰减、放大或旋转多少。非线性与随机强迫仍需另外处理。

**时间的三年周期与空间的三阶球谐是不同概念。** Sharkovsky 定理需要实区间上的连续自映射；任意球面场出现三步重复不满足这一条件。一个纯二阶球面场可以按三步等距旋转，完全没有 Li–Yorke 混沌。

真实训练时，气候态与尺度只能由训练年份估计；预报评价还要比较异常、持续性和气候态基线。复现季节变化本身不能证明天气预报技巧。

方法依据：[周期线性系统与 Floquet 分解](https://arxiv.org/abs/0901.3841)、[Sharkovsky 定理及其条件](https://www.math.northwestern.edu/~burns/papers/boris1/SharkovskyISubmitted.pdf)。

项目：[Climatetensor](https://climatetensor.io/)。此笔记本的计算独立运行；没有依赖网站接口或服务器账号。
```
