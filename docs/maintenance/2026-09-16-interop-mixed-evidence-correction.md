# Correction: the mixed-store interop evidence was invalid

Status: correction. Corrects `xue-verification-report.md` §5.8.

The four-cell interop matrix in §5.8 reported that a store whose arrays use
different codec chains cannot be opened by a plain client. That conclusion
holds, but the evidence for the "mixed" cell did not test it: the store was
built by exporting with `--delta auto` (which chose delta for *both* arrays)
and then overwriting one array's directory, **without rewriting the group
document's consolidated metadata**. zarr-python reads that document by
default, so the failure was attributable to the document, not to the arrays.

Re-run against a self-consistent fixture (`scripts/prepare_mixed_fixture.py`,
group document checked line by line against the arrays): the result is
unchanged. Conclusion kept, evidence replaced.

Recorded in `xue-verification-report.md` §13, first entry.
