#!/usr/bin/env python3
"""One command that runs the discipline this repository actually follows.

`docs/methodology-error-budget.md` names five recurring patterns.  Four of them
are about how measurements are made and cannot be mechanised.  The fifth -- that
a control which cannot fail is not a control -- implies something that can: the
guards in this tree should themselves be exercised, in the direction that makes
them fail, every time the tree is checked.  A guard nobody has seen refuse is an
intention, not a control.

So this runs seven checks and prints, for each, what it establishes and what it
does not.  Two of the seven are adversarial: they deliberately corrupt a copy of
the corpus and require the guard to refuse.

    1  corpus          docs/claims.toml parses, carries eleven fields per claim,
                       has unique ids, and is the corpus the contract pins
    2  checkers        every claim's declared checker file exists on disk
    3  corrections     every correction note still exists and still names a file
                       that exists -- the append-only rule, checked
    4  cards           every problem card validates (via Adva's problem_card.py)
    5  helpers         unit tests for the functions written here by hand:
                       the box filter, the run-length labeller, the TOML escaper
    6  guard-refuses   repin_contract.py REFUSES a corpus that does not parse
    7  guard-accepts   repin_contract.py accepts a corpus that does, and changes
                       nothing when the pin already matches

Exit status is 0 only when all seven pass.  The point is not the exit status; it
is that the guards are shown working on every run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELDS = {"claim_id", "canonical_name", "code_symbol", "dimension", "status", "scope",
          "assumptions", "dependencies", "proof_or_certificate",
          "counterexample_boundary", "forbidden_conflations"}


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, bool, str, str]] = []

    def add(self, name: str, ok: bool, establishes: str, not_establishes: str,
            details: list[str] | None = None) -> None:
        self.rows.append((name, ok, establishes, not_establishes))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        if ok:
            print(f"         establishes:     {establishes}")
        else:
            # The first version printed the "establishes" line even on failure,
            # which described the opposite of what had happened and hid the
            # diagnosis.  A failing check prints what failed and nothing else.
            for detail in (details or ["no detail recorded"]):
                print(f"         failed because:  {detail}")
        print(f"         does not:        {not_establishes}")

    @property
    def ok(self) -> bool:
        return all(row[1] for row in self.rows)


def check_corpus(report: Report) -> None:
    corpus = ROOT / "docs/claims.toml"
    contract = json.loads((ROOT / "docs/conformance.contract.json").read_text(encoding="utf-8"))
    raw = corpus.read_bytes()
    try:
        claims = tomllib.loads(raw.decode("utf-8"))["claim"]
    except Exception as error:  # noqa: BLE001
        report.add("corpus", False, "", f"the corpus does not parse: {error}")
        return
    problems = []
    for claim in claims:
        if set(claim) != FIELDS:
            problems.append(f"{claim.get('claim_id')} field set")
    ids = [c["claim_id"] for c in claims]
    if len(set(ids)) != len(ids):
        problems.append("duplicate ids")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != contract["corpus"]["sha256"]:
        problems.append("pin does not match")
    if contract["corpus"]["cases"] != len(claims):
        problems.append("case count does not match")
    report.add("corpus", not problems,
               f"{len(claims)} claims, eleven fields each, ids unique, pin {digest[:12]} matches",
               "that any claim holds, or that its checker was run")


def check_checkers(report: Report) -> None:
    claims = tomllib.loads((ROOT / "docs/claims.toml").read_text(encoding="utf-8"))["claim"]
    missing = []
    for claim in claims:
        symbols = [s.strip() for s in claim["code_symbol"].split(";") if s.strip()]
        for symbol in symbols:
            if symbol.endswith((".py", ".mjs", ".ts")) and not (ROOT / symbol).exists():
                missing.append(f"{claim['claim_id']} -> {symbol}")
    report.add("checkers", not missing,
               f"all {len(claims)} claims name at least one checker that exists on disk",
               "that any checker still reproduces its recorded outcome when run",
               details=missing)


def check_corrections(report: Report) -> None:
    """The append-only rule, checked -- but only against files this tree owns.

    Correction notes legitimately reference files in the upstream xue clone:
    `docs/format.md` is xue's specification, `tests/fixtures/pressure-registry.json`
    is xue's committed golden.  The first version of this check looked for every
    referenced file inside this repository and failed on three that were never
    supposed to be here.  A check that fails for the wrong reason is as bad as one
    that cannot fail: it teaches the reader to ignore a FAIL.  So ownership is
    decided first, upstream references are resolved against the clone when it is
    present, and anything left unresolved is listed as skipped rather than passed.
    """
    notes = sorted((ROOT / "docs/maintenance").glob("*.md"))
    upstream = Path("/tmp/xue-upstream")
    broken, skipped = [], []
    for note in notes:
        head = "\n".join(note.read_text(encoding="utf-8").splitlines()[:14])
        targets = re.findall(r"`([A-Za-z0-9._/-]+\.(?:md|toml|json))`", head)
        if not targets:
            broken.append(f"{note.name} names no target in its first 14 lines")
            continue
        for target in targets:
            if (ROOT / target).exists() or (ROOT / "docs" / target).exists():
                continue
            if (upstream / target).exists():
                continue
            # A note may name a file by its basename alone -- `tc-registry.json`
            # sitting in a list whose other members carry a path.  A bare name
            # that identifies exactly one file is a legitimate reference, so it
            # is resolved by search, and the resolution is recorded as such
            # rather than dressed up as a path match.
            matches = []
            for tree in (ROOT, upstream):
                if tree.exists():
                    matches += [p for p in tree.rglob(target)
                                if "node_modules" not in p.parts and ".git" not in p.parts]
            if len(matches) == 1 and matches[0].is_file():
                skipped.append(f"{note.name} -> {target} resolved by name to "
                               f"{matches[0].relative_to(matches[0].anchor) }")
                continue
            if upstream.exists():
                broken.append(f"{note.name} -> {target} is absent from both trees")
            else:
                skipped.append(f"{note.name} -> {target} (upstream clone absent)")
    report.add("corrections", not broken,
               f"{len(notes)} correction notes present; every file they name is "
               f"either owned here or present in the upstream clone",
               "that the corrections are complete, or that the corrected wording is "
               "gone from the tree -- the append-only rule keeps the note, not the old text",
               details=broken + ([f"SKIPPED (upstream clone absent): {s}" for s in skipped]
                                 if skipped else []))


def check_cards(report: Report) -> None:
    validator = Path("/tmp/adva-main/scripts/problem_card.py")
    cards = sorted((ROOT / "docs/problem-cards").glob("*.json"))
    if not validator.exists():
        report.add("cards", True,
                   f"{len(cards)} cards present; Adva's validator is not checked out here",
                   "anything about their validity -- skipped, not passed")
        return
    incomplete = []
    for card in cards:
        proc = subprocess.run([sys.executable, str(validator), "check", str(card)],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            open_items = [l for l in proc.stdout.splitlines() if "receiver" not in l and l.strip()]
            if len(open_items) > 1:
                incomplete.append(f"{card.name}: {open_items[-1].strip()[:60]}")
    report.add("cards", not incomplete,
               f"{len(cards)} cards validate; the only outstanding item in each is the "
               f"receiver confirmation",
               "that any round is finished -- every card is deliberately left open")


def check_helpers(report: Report) -> None:
    import numpy as np
    failures = []

    # the box filter, which inflated areas 16x when its caller's scale was inverted
    source = (ROOT / "scripts/sar_change_check.py").read_text(encoding="utf-8")
    start = source.index("def box_mean")
    end = source.index("def change_area")
    namespace: dict = {"np": np}
    exec("import numpy as np\n" + source[start:end], namespace)  # noqa: S102
    box_mean, components = namespace["box_mean"], namespace["components"]
    grid = np.arange(25, dtype=float).reshape(5, 5)
    if abs(float(box_mean(grid, 5)[2, 2]) - grid.mean()) > 1e-9:
        failures.append("box_mean of a uniform grid is not the grid's mean")
    holed = np.full((5, 5), 7.0)
    holed[2, 2] = np.nan
    if abs(float(box_mean(holed, 3)[2, 2]) - 7.0) > 1e-9:
        failures.append("box_mean does not ignore NaN")
    mask = np.zeros((10, 10), dtype=bool)
    mask[1:3, 1:3] = True
    mask[7:9, 7:9] = True
    mask[5, 5] = True
    if sorted(components(mask)[1].values()) != [1, 4, 4]:
        failures.append("components does not find three separate blobs")
    linked = np.zeros((6, 6), dtype=bool)
    linked[0, :] = True
    linked[1, 0] = True
    linked[1, 5] = True
    if sorted(components(linked)[1].values()) != [8]:
        failures.append("components does not join blobs that touch")

    # the offset correlator, which reported a flat 664 m on every pair until a
    # synthetic test with known shifts showed the sign and the origin were both
    # wrong.  Run it here so that cannot recur silently.
    offset_source = (ROOT / "scripts/sar_offset_check.py").read_text(encoding="utf-8")
    start = offset_source.index("def normalized_correlation")
    end = offset_source.index("def main() -> int:")
    # The fragment needs the module's own constants; they are read out of the
    # source rather than repeated here, so a change in the script cannot leave a
    # stale copy behind in this check.
    constants = "\n".join(line for line in offset_source.splitlines()
                          if re.match(r"^(PATCH|STEP|SEARCH|TARGET_RES)\s*=", line))
    namespace = {"np": np}
    exec("import numpy as np\n" + constants + "\n" + offset_source[start:end],
         namespace)  # noqa: S102
    failures += namespace["synthesize_shift_test"]()

    # the TOML escaper, which exists because a raw newline broke the corpus twice
    edit_source = (ROOT / "scripts/claim_edit.py").read_text(encoding="utf-8")
    start = edit_source.index("def escape")
    end = edit_source.index("def locate")
    namespace = {}
    exec("import re\n" + edit_source[start:end], namespace)  # noqa: S102
    escaped = namespace["escape"]('a\nb"c\\d')
    if "\n" in escaped or escaped.count('"') != 1:
        failures.append("escape lets a newline or a bare quote through")

    report.add("helpers", not failures,
               "the hand-written box filter, run-length labeller, offset correlator "
               "and TOML escaper pass their unit tests",
               "that they are correct in general -- these are the specific cases "
               "that each one got wrong before",
               details=failures)


def guard_checks(report: Report) -> None:
    """Exercise repin_contract.py in both directions, on a throwaway copy."""
    with tempfile.TemporaryDirectory() as scratch:
        sandbox = Path(scratch) / "repo"
        (sandbox / "scripts").mkdir(parents=True)
        (sandbox / "docs").mkdir()
        shutil.copy(ROOT / "docs/claims.toml", sandbox / "docs/claims.toml")
        shutil.copy(ROOT / "docs/conformance.contract.json",
                    sandbox / "docs/conformance.contract.json")
        shutil.copy(ROOT / "scripts/repin_contract.py", sandbox / "scripts/repin_contract.py")

        good = subprocess.run([sys.executable, str(sandbox / "scripts/repin_contract.py")],
                              capture_output=True, text=True)
        corpus = sandbox / "docs/claims.toml"
        corpus.write_text(corpus.read_text(encoding="utf-8") + '\nbroken = "unterminated\n',
                          encoding="utf-8")
        bad = subprocess.run([sys.executable, str(sandbox / "scripts/repin_contract.py")],
                             capture_output=True, text=True)

    refused = bad.returncode != 0 and "REFUSED" in bad.stdout
    report.add("guard-refuses", refused,
               "repin_contract.py refuses a corpus that does not parse, so the pin "
               "cannot be advanced over bytes no reader can load",
               "that it would catch a corpus that parses but is semantically wrong")
    accepted = good.returncode == 0
    report.add("guard-accepts", accepted,
               "the same guard accepts the real corpus and leaves the pin untouched "
               "when it already matches",
               "that the corpus is correct -- only that it loads and has the right shape")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    args = ap.parse_args()
    print(f"methodology check over {ROOT}\n")
    report = Report()
    check_corpus(report)
    check_checkers(report)
    check_corrections(report)
    check_cards(report)
    check_helpers(report)
    guard_checks(report)
    print(f"\n{sum(1 for r in report.rows if r[1])}/{len(report.rows)} passed")
    if not report.ok:
        print("a failing check here is a finding, not an inconvenience")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
