# Withdrawal: "the Himalaya box is effectively outside the CMA mosaic's coverage"

Status: withdrawn. Corrects statements made in session on 2026-09-17 against
`xue-verification-report.md`; the report itself never carried the wrong text,
so this note records an announced conclusion that was about to be filed.

## What I said

Reading one CMA radar window (20 frames, 2026-09-17 02:00–04:06Z) I found that
in the Himalaya/Tibet box (80–92E, 26–32N) only 851 of 37,264 cells — 2.3% —
ever carried echo, against 40.7% in an East-China control. I told the user that
the box was **effectively outside the mosaic's coverage**, not merely dry, and
that the codebook's `0` meant both "no echo" and "no radar" with nothing to
separate them.

The second half was half right. The first half was wrong.

## What is actually the case

1. **The codebook does declare a nodata code.** `cref`'s published
   `quantization` carries `nodataCode: 255`, and the Zarr array's `fill_value`
   is 255. I had asserted the product carries no way to separate the two
   meanings without having read the variable metadata. The accurate statement
   is narrower and worse: the code is *declared* and *never written* — 0 times
   in 40,370,176 samples of the merged window, with the observed code range
   topping out at 139.

2. **The low echo fraction was not a coverage artefact.** Applying four
   tests — blob coherence, temporal persistence, frame-to-frame IoU, and echo
   level — the echo present in that box behaves like real precipitation:
   74.5% of echo pixels sit in 4-connected blobs of 25 cells or more, only
   9.4% of echoing cells echo in a single frame, the median longest run is 5
   frames of 30, IoU is 0.642, p90 is 43 dBZ. North China, a control with
   unquestioned coverage, scores 74.4% / IoU 0.581 / p90 34 dBZ.

   The discriminator was calibrated before it was used: the South China Sea box
   lies outside every Chinese radar's range and is the only box with a *high*
   p90 (76 dBZ) together with a *low* big-blob share (20.1%) and a low IoU
   (0.374). Real precipitation does not look like that; leakage does.

3. **The truth is in between, and sharper than either version.** The box
   straddles the coverage edge. On the 80–92E transect the three bands
   26–27N, 27–28N and 28–29N carry **0.0%** echo while the model rains over
   74–95% of their cells; 29–30N jumps to 10.4% with a correlation of 0.507
   against the model's rain rate. The step is at 29N — the Himalayan crest.

4. **But the edge is ragged, not a circle of range.** On the 95–100E transect
   the sense reverses: 26–27N carries 8.8% echo and 29–32N carries **0.0%**
   while the model rains over 98.8–100% of those cells. Two transects 15
   degrees apart cross at 29N.

## Why the error mattered

It pointed the opposite way from the truth on the one question the rainfall
direction exists to answer. "Outside coverage" would have meant the radar can
say nothing about the Himalaya at all. The measurement says the radar sees the
plateau side and is blind to the Nepal side, at a boundary that is neither
published nor inferable from the data — because the code that would mark it is
never written. The correct conclusion is a *conditional* capability, not a
blank one, and the condition has to be established by measurement every time
the box moves.

## What replaced it

`xue.radar.absence-not-marked-in-band.v0` in `docs/claims.toml`, whose
`forbidden_conflations` now carry both halves of the original error: "codebook
declares a nodataCode" is not "the product writes one", and "a box's echo
fraction" is not "that box's rainfall fraction" once the box crosses the edge.

Recorded in `xue-verification-report.md` §13, as a withdrawal rather than a
correction, because the earlier text was spoken and never written down — the
append-only rule protects the record, and here there was no record to protect,
which is its own lesson about how conclusions travel before they are filed.
