# Correction: the skill curve measured a resolution change as skill decay

Status: correction. Corrects `xue.anchor.field-against-measurement.v0` in
`docs/claims.toml`, and `xue-verification-report.md` §13's skill-curve entry.

## What I reported

> 7 valid hours, time of day held fixed: mean MAE at the shortest lead
> **1.808 K**, at the longest lead **1.999 K**, growth **+0.191 K**, and
> 7/7 hours worse. So the forecast degrades measurably.

I told the user this meant the 2 m temperature forecast was reliable, with a
measurable skill decay of about 10% per day.

## What is the case

**+0.011 K over 12 hours, and only 6 of 7 hours worse** — indistinguishable
from no growth at all.

## Why the first number was wrong

The three readable runs do **not** carry the same tier. Probed directly:

| run | full (0.25°, 1440×721) | half (0.5°, 720×361) |
|---|---|---|
| `2026091618` | 200 | 404 |
| `2026091606` | 404 | **200** |
| `2026091700` | 200 | 200 |

Leads 0–12 came from full and leads 18–24 from **half**. The curve therefore
compared a 0.25° forecast at short lead against a 0.5° forecast at long lead,
and called the difference skill decay.

`tier-control` measures the penalty on the one run that has both tiers, over
the same hours: half costs **+0.137 K** in MAE against full (0.120–0.159 across
leads 0–6, near-constant, which is the shape a resolution effect has and a
skill effect does not). That accounts for about **72%** of the +0.191 K.

Re-running with `--tier full` removes the confound from both sides: same time of
day, same resolution. The growth nearly vanishes.

## Why it matters

"Reliable, degrading about 10% a day" and "no measurable growth over 12 hours"
are different claims about the same product, and the second is the stronger and
the true one. A retention artefact — that the archive keeps one tier of one run
and the other tier of the next — had been read as a physical property of the
atmosphere.

## What the error has in common with the four before it

This is the same shape as `max(p)` as a surface pressure, as the pressure-range
test for `lapse850_500`, as the 6-minute grid, and as the `now - 10k` grid: **a
criterion that is not the object's rule, applied confidently.** The object here
was a cross-run series, and the rule it must satisfy is that every member of a
series is measured the same way. Nothing checked that until the tiers were
listed.

The specific new lesson: when a series is assembled from an *archive*, the
archive's own inconsistencies enter the series. I had already measured that the
retention here is partial and irregular; I did not ask whether the survivors
were comparable.

## What is preserved

Both readings are kept in the claim: the mixed one with its 7/7 and its number,
then the tier-control that explains it, then the clean one. The forbidden
conflations gain "error growth versus a resolution change" and "a curve
stitched across runs versus a curve at one resolution".

Recorded in `xue-verification-report.md` §13.
