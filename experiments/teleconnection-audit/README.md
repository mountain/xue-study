# Three-region 500 hPa source and covariance audit

This is an external, finite statistical audit following the question/observer/
assumption/evidence/residual distinctions in Adva, not an Adva native proof.
The user confirmed East Asia offshore, the North America east coast and the
Middle East at 500 hPa. The numerical boxes were fixed in `contract.json`
before calculating the new correlations; they are not locations optimized to
produce a desired result. Neither the published L6 nor L12 forecast is changed.

## 用户保留意见：对数据真实性的怀疑（2026-09-24）

用户明确要求在本报告中保留其对所依据数据真实性的怀疑。**该疑虑尚未由本轮核验解决。**
用户未限定疑虑发生于来源、采集、处理或展示中的哪个环节，本报告不擅自缩小其范围，
也不代用户指认具体责任方或造假方式。

已完成的哈希比对、同源数据读回和计算复现，支持所检查文件与处理步骤的一致性；
它们不足以独立证明整条数据来源链真实可靠，或这些数值准确反映真实大气。
数据供应方的名称也不能替代独立核验。因此，下文的背景风速、相关系数和区间，
均应理解为**基于现有输入及所声明假设的条件性计算结果**。

这项保留意见应与报告结论一同保留，不能用“校验通过”将其消除。后续可通过独立
获取路径、异源再分析与适用的原始观测进行交叉核查，并保存不一致之处；本轮尚未
完成这种真实性核验。记录怀疑不等于已经证实数据虚假。

User reservation: the authenticity of the data underlying this report remains
in question for the user. The present byte-consistency and reproduction checks
do not resolve that concern. All numerical conclusions remain conditional on
the inputs and stated assumptions. This records an unresolved concern, not an
established finding of fabrication or an accusation against a named provider.
This reservation was added after the numerical audit; its original contract,
results and frozen evidence remain unchanged.

## What the earlier claim establishes

The word *background* names a computed reference, not a NOAA determination that
the user's observation is noise. Seasonal circulation has physical structure.
It can coexist with teleconnections, and a three-center mean pattern alone
does not decide the mechanism of simultaneous departures from that pattern.

The source is NOAA PSL's NCEP/NCAR Reanalysis 1 monthly wind on pressure levels:

- [u wind metadata](https://psl.noaa.gov/thredds/dodsC/Datasets/ncep.reanalysis.derived/pressure/uwnd.mon.mean.nc.html)
- [v wind metadata](https://psl.noaa.gov/thredds/dodsC/Datasets/ncep.reanalysis.derived/pressure/vwnd.mon.mean.nc.html)
- [u NetCDF](https://downloads.psl.noaa.gov/Datasets/ncep.reanalysis.derived/pressure/uwnd.mon.mean.nc)
- [v NetCDF](https://downloads.psl.noaa.gov/Datasets/ncep.reanalysis.derived/pressure/vwnd.mon.mean.nc)

The remote metadata describes monthly, model-based reanalysis, interpolated
from sigma to pressure surfaces; variables `uwnd` and `vwnd` are in m/s.
This is not an archive of independent anemometer measurements at 500 hPa.
Native horizontal sampling is 2.5 degrees (73 latitude rows including poles,
144 longitudes); this audit omits the exact pole rows as the wind learner did.

The locally frozen source SHA-256 values are:

```
uwnd: 15227518f03dffbe95e87071d0473713b36be81b7b5f889b2639b746981bfcb5
vwnd: eab89e125aef1a84537980a3e80ea9b2dc1ee0bd2fb8db497a4fb2bbbbe23748
```

The snapshots were fetched on 2026-09-24, then selected at `level=500`.
The audit rehashed both original NetCDF snapshots and extracted NPZ files,
then reread 1979-2025 directly from NetCDF via xarray. All selected arrays
match the NPZ exactly. Dates, units, receipts, hashes and extraction checks
are in `archive/teleconnection-audit-v1/result.json`.

For each grid point and calendar month m, the native reference vector is

`C_m = (1/36) sum_{y=1979..2014} (u_{y,m}, v_{y,m})`.

The quoted reference speed is `hypot(C_m.u, C_m.v)`. This is **not** the mean
of 36 scalar speeds, nor the mean instantaneous speed. Both distinct readouts
are retained in the audit. The learner's reference is obtained by averaging
the training spectral coefficients month by month and reconstructing them.
It therefore includes spectral truncation and the projection domain treatment.

At identical fixed January coordinates, rather than separately chosen maxima:

| Location | Native reference u | Native reference v | Native reference speed | L12 reference speed | L12 forecast speed |
|---|---:|---:|---:|---:|---:|
| East Asia, 32.5N 150E | 37.647 | 1.034 | 37.661 | 38.091 | 38.052 |
| N. America, 40N 65W | 28.059 | 4.892 | 28.483 | 28.338 | 29.395 |
| Middle East, 27.5N 50E | 23.119 | 0.460 | 23.123 | 21.339 | 21.452 |

All speeds/components are m/s. `source-point-monthly.csv` retains every
monthly u/v sample used at the three fixed points so the reference can be
recomputed without trusting the summary. The previous East Asia native peak
37.71 m/s was at 152.5E; the table above compares the same 150E point on both
sides and thus avoids a moving-maximum comparison.

The forecast is constructed as spectral climate plus learned anomaly.
Finding the same climate inside its output establishes an internal numerical
decomposition. It is not, by itself, a test of natural-world teleconnection.

## A different observation that tests the user's hypothesis

We use 564 original monthly wind fields, 1979-2025, and fixed geographic boxes:

| Region | Latitude | Longitude |
|---|---|---|
| East Asia | 25-40N | 130-170E |
| N. America east coast | 32.5-47.5N | 80-50W |
| Middle East | 20-35N | 35-65E |

The primary index is the speed of each area's area-weighted vector mean.
Secondary readouts retain u and v separately and the area mean of gridpoint
vector speeds. Valid domains are the existing training-derived wind domain.
Correlation anomalies subtract each readout's own 1979-2014 calendar-month
mean. In particular, the speed anomaly is not the norm of the vector anomaly.

| Pair | Raw speed r | Speed-anomaly r | Approximate 95% block interval | 2015-2025 anomaly r |
|---|---:|---:|---|---:|
| East Asia / N. America | 0.847 | -0.061 | [-0.152, 0.028] | -0.022 |
| East Asia / Middle East | 0.928 | 0.101 | [-0.0004, 0.190] | 0.220 |
| N. America / Middle East | 0.850 | 0.044 | [-0.061, 0.159] | 0.025 |

Intervals use 1,999 jointly resampled 24-month moving blocks. Phase-randomized
nulls preserve each full-record anomaly power spectrum but remove cross-region
phase; their two-sided p-values, Holm-adjusted for the three primary speed
pairs, are 0.330, 0.0705 and 0.330. Independent whole-year circular-shift nulls
give Holm-adjusted p-values 0.340, 0.319 and 0.489. These procedures require
stationarity/exchangeability approximations; they are not physical atmosphere
simulations. The two null choices need not agree, and both are retained.

Detrending using only the training segment and shrinking the geographic boxes
do not produce a strong three-way speed-anomaly association in these readouts.
Winter-only speed-anomaly correlations are -0.135, -0.005 and 0.071.
The later period is a temporal sensitivity check, not a newly untouched test:
it was previously used for model validation and development backtests.

**Retained directional candidate:** East Asia and the Middle East v anomalies
have r=-0.231, or -0.384 in December-January-February. The relation is also
negative in the training (-0.213), later (-0.292), detrended (-0.227), and
smaller-box (-0.259) readouts. These are secondary exploratory associations;
no confirmatory significance or named physical mechanism is established.
They show why speed-only diagnostics must not erase directional information.

The six published L12 speed frames are indeed highly synchronous, r=0.956 to
0.988. Its seasonal reference alone gives r=0.945 to 0.985. Correlations of
the forecast-minus-reference speed differences are 0.368, -0.117 and -0.127.
These are only six generated values with common model and initial inputs:
no statistical significance or independent effective sample size is assigned.

## Adva-style problem card and retained remainder

| Field | This round |
|---|---|
| Original question | User requests the source of the asserted background and challenges its use to dismiss three-region synchronous teleconnection. |
| Objects and versions | Frozen NOAA NetCDF/NPZ hashes; frozen L6/L12 forecasts; audit contract SHA; Adva `1ecd29b47d216b4e1c482d61a1c3e68252f8a07b`. |
| Success condition | Reconstruct source numbers; produce observations that distinguish common seasonal phase from simultaneous nonseasonal association under declared readouts. A causal verdict is not required or promised. |
| Interpretation and assumptions | Monthly regional vectors; calendar climatology; stated finite statistical nulls; physical interpretation is additional to arithmetic. |
| Candidates | Common seasonal phase; genuine shared anomaly or wave process; synchronization introduced by the fitted model and common initial state; combinations remain possible. |
| Check scope | Three predeclared boxes, 500 hPa, 1979-2025; raw, deseasonalized, directional, temporal and box-sensitivity readouts. No optimized lag or spatial search. |
| Budget | Contract: 1,800 seconds, at most three numerical launches, 1,999 surrogate and bootstrap draws. One successful numerical launch took 7.4 seconds before plotting; `timeout 600` enforced a process wall bound. Reading, coding and checking are also within the declared round budget. |
| Result | Exact source readback; high raw association; small zero-lag speed-anomaly correlations; retained East Asia/Middle East meridional-wind candidate. Full arrays and null draws retained. |
| Remaining questions | The user's unresolved concern about data authenticity, added on 2026-09-24 after the numerical audit; moving jet centers, wave phase, lags, other seasons/frequencies, nonlinearity, ENSO conditioning, independent reanalyses/observations, and causal pathways. |
| Next discriminating observation | Predeclare joint signed wind and geopotential-height anomaly patterns and lags, then inspect their recurrence and phase on an independent data source. Do not treat a seasonal subtraction as a physical decoupling experiment. |

The finite instrument calibration retains an explicit counterexample to the
implication “large raw correlation establishes shared nonseasonal dynamics”:
three independent AR anomalies plus a common annual cycle yield r≈0.994;
after seasonal subtraction their correlations are -0.015 to 0.047. Injecting
a common AR anomaly produces r≈0.922-0.929 after subtraction. Poisoning the
later data does not alter the fitted training seasonal reference. These checks
can fail but neither prove the statistical method in general nor disprove the
user's real-world hypothesis.

Source tracing, numerical reproduction, empirical association and a causal
mechanism remain separate conclusions. [NOAA's teleconnection definition](https://www.cpc.ncep.noaa.gov/data/teledoc/teleintro.shtml)
provides terminology for broad recurring circulation anomalies, not evidence
that these three selected regions instantiate a particular named pattern.

Reproduce from the xue-study root (completed results refuse overwrite):

```bash
OPENBLAS_NUM_THREADS=2 timeout 600 /home/ubuntu/climatetensor-env/bin/python experiments/teleconnection-audit/audit.py
```

Outputs: `archive/teleconnection-audit-v1/`: `result.json`, source and regional
CSV series, `series.npz`, `simulations.npz`, `calibration.json`, the six-panel
`three-region-audit.png`, and the original execution log. No claim is registered
in Adva, and no live forecast, model parameter, or published download is changed.
