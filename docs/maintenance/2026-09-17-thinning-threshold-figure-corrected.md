# Correction: the thinning check's threshold figure came from an unexempted set

Status: correction. Corrects `docs/claims.toml` (one figure inside
`xue.sounding.thinning-rule-conformance.v0`) and
`xue-verification-report.md` §13's point-product entry.

## What was filed first

The claim read that the sounding product's unflagged adjacent level pairs have
a **minimum ratio of 1.0010**, well below the rule's 3% threshold, and that
this showed the boundary handling could not affect the verdict of zero
violations.

## What the number should be

**1.0300 — exactly the threshold.**

The 1.0010 came from a set that still contained the level the rule *exempts*:
a sounding's highest level is always published, whatever its pressure gap, so
pairs ending on it are not subject to the 3% test. With those pairs removed the
unflagged minimum is exactly the threshold, the fifth percentile is 1.0301 and
the median is 1.0308.

## Why it matters more than a digit

The two readings support opposite statements about the rule's slack. "Minimum
1.0010, far below the threshold" says the rule is satisfied loosely and the
boundary convention is irrelevant. "Minimum exactly 1.0300" says the rule is
satisfied with **no slack at all**, so whether a ratio of exactly 1.03 counts as
passing decides the verdict — and that convention is now declared in the
claim's `assumptions` instead of being left implicit.

## What did not change

The verdict. Zero pairs below 1.03, `p` strictly descending in all 1,844
ascents, and every parallel array of length `n`, all hold under both readings.
The correction is to the reason the boundary was called irrelevant, not to the
result.

## The pattern

This is the same failure as the two before it in the same round, and the same
as the radar retention count: **a criterion that was not the object's rule,
applied confidently.** There the criterion was a pressure range and an exact
mandatory level, against a product that interpolates near a threshold; here it
was a set that included exempt members. The claim's `assumptions` keeps both
superseded figures so that a reader cannot mix the versions.

Recorded in `xue-verification-report.md` §13, point-product entry, section four.
