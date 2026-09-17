# Re-pin: the claim registry moved, and the contract was re-pinned deliberately

Status: correction. Corrects `xue-verification-report.md` §13's record; it re-pins
`docs/conformance.contract.json` after the registry moved, and corrects neither.

`scripts/check_contract.py` refused on 2026-09-17 with `digest MISMATCH`, as it
should: `xue.store.container-byte-identity.v0` gained an `assumptions` entry —
a counterexample the project ships itself, where the codes match and the
compressed bytes do not because the two sides were written at different zstd
levels (`tests/prepare_web_fixture.py:211` writes level 3).

The pin was therefore re-computed rather than left stale, and this note is the
record the checker's refusal message asks for. What did **not** change: no
claim's verdict, no claim's `counterexample_boundary`, and no checker's result.
Only one claim's stated precondition became more explicit.

Recorded in `xue-verification-report.md` §13.

## Second move, same day

`scripts/check_contract.py` refused again after a **forward test** was recorded
in the same claim: `scripts/plateau_mechanism_check.py` tested the below-ground
mechanism on `tmp925` / `tmp850` / `tmp500` and the gradient (+6.33 / +5.16 /
+2.05 K) went into that claim's `counterexample_boundary`.

Appended rather than rewritten, as this project keeps corrections: the first
entry above still stands as it was written. Re-pinned again, and again no
claim's verdict changed — one claim's boundary gained a measured gradient and
a partial counterexample (the 500 hPa anomaly is not zero).

## Third move, same day

The 500 hPa residual of the same claim was tested and the test is on the record
as **unresolved**: `hgt500` is confounded by terrain, `vvel500` divides by a
near-zero control, and `rh500` shows a same-direction signal. A test that fails
to settle a question is a result, so it went into the boundary.

The contract gained `base_commit`, `controls` and `residuals` in the same pass;
those live in `docs/conformance.contract.json` and do not move the pin, which
covers the registry only. Re-pinned a third time.

## Fourth move, same day

The 500 hPa residual that the third entry recorded as **unresolved** is now
**resolved**, so that entry's boundary was corrected in place by appending:

the published geopotential heights show the 500 hPa and 250 hPa surfaces at
essentially the same absolute altitude over the plateau and over the
same-latitude lowlands (58 m of 5894, and 3 m of 10 927), so the temperature
comparison at those levels **is** like-for-like and the +2.05 K is a warm
anomaly at matched altitude rather than a geometry artifact. What makes 850 hPa
an artifact is not its absolute height but that it lies ~3 km under the
plateau's ~4500 m ground.

Nothing else changed: no claim's verdict, and no checker's result. Re-pinned a
fourth time.

## Fifth move, same day

The mechanism is now measured **per gridpoint** rather than argued from a box
mean, using terrain the study previously only assumed. `scripts/dem_elevation.py`
reads Copernicus DEM GLO-90 over `/vsicurl/` and averages it onto the forecast
grid: the plateau box measures **4140 m**, against the ~4500 m the claim had
written in as a common-knowledge value.

`scripts/plateau_profile_check.py` then bins the temperature anomaly by height
above ground and finds a dose-response: `tmp850` runs +6.73 K where the level is
3-4 km under the ground, +3.76 K at 2-3 km under, and ~+0.5 K at 1-2 km under;
`tmp500`, which is above ground everywhere, runs +2.72 K where it is only
0.5-1.5 km above the surface and +0.84 K at 1.5-3 km.

**Rights note, because this project's boundary requires it**: Copernicus DEM is
free and redistributable with attribution but is **not** public domain and
**not** CC0, so under `PUBLICATION_BOUNDARY.md` it is **not admissible** into
the public repositories. Nothing was vendored: the tiles were read over HTTPS
and only the derived per-cell means were kept, **in `/tmp`, outside this
folder**. Re-pinned a fifth time; no claim's verdict changed.

## Sixth move, same day

The clamp fraction itself was binned by height above ground
(`scripts/thetae_profile_check.py`): 61.8% of gridpoints sit at the codebook
ceiling where the 850 hPa level is 3-4 km under the ground, 31.5% at 2-3 km
under, 13.4% at 1-2 km under, and 0% nearer the surface. That is the same
monotone decline the temperature profile shows on the same bins, from a second
variable -- so the mechanism is now measured on theta-e itself rather than
argued from box means.

Two things the note has to say rather than smooth over:

- The ceiling is now **read from the published metadata** (230 + 0.5 x 254 =
  357.0 K), not typed into the script. A hard-coded ceiling is a number the
  script would be checking itself against.
- The earlier "62-66% of the plateau box" came from frames 40 and 160; this run
  is frame 0. **The two are not comparable**, and the per-gridpoint curve
  replaces the single box number as the claim's evidence.

Re-pinned a sixth time; no claim's verdict changed.
