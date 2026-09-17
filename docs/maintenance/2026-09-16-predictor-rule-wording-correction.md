# Correction: "the rule is wrong" conflated a specification with an optimisation

Status: correction. Corrects `xue-verification-report.md` §5.4 and §5.6.

Both sections said the container's encoder rule is "wrong for most
variables". The measurement establishes **compressed bytes** — that a given
variable codes smaller under one chain. The rule itself is a normative
encoder rule in `docs/format.md` whose purpose is to hold the two encoders
byte-identical. It is a specification, not a compression heuristic, and
coding smaller does not make it an error.

The accurate statement is that the rule is not size-optimal for 23 of the 43
variables. Recorded as the first forbidden conflation of
`xue.predictor.per-variable-preference.v0`.

Recorded in `xue-verification-report.md` §13, second entry.
