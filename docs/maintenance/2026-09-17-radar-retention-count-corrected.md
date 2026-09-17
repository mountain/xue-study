# Correction: the radar retention count was wrong — a probe grid is not the object

Status: correction. Corrects `docs/claims.toml`, and through it
`xue-verification-report.md` §13's radar entry. Fourth entry of its kind in one
day, and the first that corrupted a claim rather than a sentence.

## What was filed

`xue.radar.public-retention-and-rebuild-determinism.v0` first read:

> cma: 442 candidates over 17 window-start hours, 2 hits — the live window and
> its predecessor. So each collection exposes two rolling windows.

## What is the case

Four windows, in a clear shape: **two adjacent runs, two builds each.**

| window | span | frames |
|---|---|---|
| `cma.2026091701/0351` | 01:00–03:24Z | 24 |
| `cma.2026091701/0400` | 01:00–03:30Z | 25 |
| `cma.2026091702/0452` | 02:00–04:18Z | 22 |
| `cma.2026091702/0502` | 02:00–04:42Z | 24 |

A one-minute-step probe of five runs, covering run+1h to run+6h, gave 1,505
candidates and these four hits. Run `2026091700` and everything older gave
nothing.

## Why the first probe was wrong

I assumed the build id lands on the 6-minute grid of the source cadence. It does
not: the id is when the build finished, and the minutes are unconstrained —
`0351`, `0400`, `0452`, `0502`. A 6-minute step samples about one sixth of the
possible ids, so three quarters of the live windows were invisible to it.

What exposed it was an eviction happening while I worked. Re-running the
animation script mid-session, the live window had moved from
`cma.2026091702/0442` to `cma.2026091702/0502` and the old one returned 404.
`0502` is not on the coarse grid — 44 is reachable, 02 is not. So the session
observed the very eviction the claim describes, and in doing so showed that the
probe could not have seen it.

## What the error has in common with the previous two

The third §13 correction was turning "I did not find it" into "it is not there".
The radar entry's first attempt was guessing a window id (`0500`) for eleven old
runs and reporting the resulting 404s as absence. This is the same move a third
time: **an empty result from an incomplete candidate set is not a measurement.**
The difference is that this time the incomplete candidate set was inside a claim
I had already filed, and the tool that would have caught it — the dense probe —
was the one I had made too coarse.

## What changed beyond the numbers

Both readings are kept in the claim rather than the first being overwritten: the
`scope` carries the coarse probe, its count, and the reason it was wrong. Two
`forbidden_conflations` entries were added — "no hit in an incomplete candidate
set is not a short retention period" and "the live window's build id is not on a
tidy time grid" — so that the specific way this failed travels with the claim.

The MRMS and JMA counts still rest on the coarse probe and are recorded as
unverified in the claim's `assumptions` and in the contract's `residuals`.

Recorded in `xue-verification-report.md` §13, fourth correction.
