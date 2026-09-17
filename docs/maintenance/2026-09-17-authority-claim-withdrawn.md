# Withdrawal: "no party is named as the semantic authority"

Status: withdrawn. Corrects `xue-verification-report.md` and `README.md`.

I asserted repeatedly that the contour half-code rule "has no named
authority". Checked, that is false. `tests/test_pressure.py`'s module
docstring says it outright: the committed `tests/fixtures/pressure-registry.json`
is what binds the three implementations, read by the Python tests, the Rust
encoder's unit tests and the frontend's vitest — and "nothing but a test
states it". Four sibling goldens (`isobaric-`, `surface-`, `ocean-`,
`tc-registry.json`) follow the same pattern.

The authority is a committed cross-implementation golden per family, not a
component. Recorded in `xue-verification-report.md` §13, third entry.
