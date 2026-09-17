#!/usr/bin/env python3
"""Edit a claim field without being able to break the corpus.

Three times on 2026-09-17 an edit to `docs/claims.toml` produced a file that no
reader could parse, every time the same way: a fragment carrying a real newline
was spliced into a single-line TOML string, so the string ended early and the
rest of the paragraph became illegal syntax.

The third time, `scripts/repin_contract.py` refused to advance the pin, which is
what it exists for.  But refusing to pin a broken file still leaves a broken file.
This is the other half: make the edit itself unable to produce one.

Every insertion is escaped (newlines become the two characters `\\n`, quotes are
escaped) and the result is parsed and checked against the eleven-field schema
before anything is written.  If it does not parse, the file is left alone.

  # append a paragraph to the end of a field that already has text
  python3 scripts/claim_edit.py --claim xue.anchor... --field scope --append-file notes.txt

  # replace one exact occurrence inside a field
  python3 scripts/claim_edit.py --claim xue.anchor... --field scope \\
      --replace-old old.txt --replace-new new.txt
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "docs" / "claims.toml"
FIELDS = {"claim_id", "canonical_name", "code_symbol", "dimension", "status", "scope",
          "assumptions", "dependencies", "proof_or_certificate",
          "counterexample_boundary", "forbidden_conflations"}
LIST_FIELDS = {"assumptions", "dependencies", "forbidden_conflations"}


def escape(text: str) -> str:
    """A fragment safe to splice into a single-line TOML basic string."""
    return (text.replace("\\", "\\\\").replace('"', '\\"')
                .replace("\r\n", "\n").replace("\n", "\\n"))


def locate(source: str, claim_id: str, field: str) -> tuple[int, int]:
    """Byte span of one field assignment belonging to one claim."""
    start = source.index(f'claim_id = "{claim_id}"')
    end = source.find("\n[[claim]]", start)
    if end == -1:
        end = len(source)
    block = source[start:end]
    match = re.search(rf'^{field} = ', block, re.M)
    if not match:
        raise SystemExit(f"{claim_id} has no {field}")
    field_start = start + match.start()
    # the assignment ends at the closing quote of the string, or at the closing
    # bracket of an array
    cursor = source.index("=", field_start) + 1
    while source[cursor] in " \t":
        cursor += 1
    if source[cursor] == "[":
        depth = 0
        while True:
            if source[cursor] == "[":
                depth += 1
            elif source[cursor] == "]":
                depth -= 1
                if depth == 0:
                    return field_start, cursor + 1
            cursor += 1
    cursor += 1                              # opening quote
    while True:
        if source[cursor] == "\\":
            cursor += 2
            continue
        if source[cursor] == '"':
            return field_start, cursor + 1
        cursor += 1


def validate(source: str) -> None:
    parsed = tomllib.loads(source)
    claims = parsed["claim"]
    ids = [c["claim_id"] for c in claims]
    for claim in claims:
        if set(claim) != FIELDS:
            raise SystemExit(f"REFUSED {claim.get('claim_id')} lost or gained a field: "
                             f"missing {sorted(FIELDS - set(claim))}, "
                             f"extra {sorted(set(claim) - FIELDS)}")
    if len(set(ids)) != len(ids):
        raise SystemExit("REFUSED duplicate claim ids")
    if len(claims) != 12:
        print(f"  note: the corpus now holds {len(claims)} claims, not 12")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--claim", required=True)
    ap.add_argument("--field", required=True)
    ap.add_argument("--append", help="text to append to the field")
    ap.add_argument("--append-file")
    ap.add_argument("--replace-old", help="an exact substring to replace")
    ap.add_argument("--replace-old-file")
    ap.add_argument("--replace-new", default="")
    ap.add_argument("--replace-new-file")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    def read(inline, path):
        if path:
            return Path(path).read_text(encoding="utf-8")
        return inline or ""

    if not 0 <= sum(bool(x) for x in (args.append or args.append_file,
                                      args.replace_old or args.replace_old_file)) <= 1:
        ap.error("give exactly one of --append/--append-file or "
                 "--replace-old/--replace-old-file")

    source = CORPUS.read_text(encoding="utf-8")
    before = source
    start, end = locate(source, args.claim, args.field)
    segment = source[start:end]

    if args.append or args.append_file:
        text = read(args.append, args.append_file).rstrip()
        if args.field in LIST_FIELDS:
            raise SystemExit(f"--append is for string fields; {args.field} is an array, "
                             "edit it by --replace-old/--replace-new")
        # segment is `field = "….` and ends with the closing quote
        segment = segment[:-1] + escape(text) + '"'
    else:
        # The caller quotes the text as the claim reads it, not as the TOML
        # stores it, so both sides are escaped before matching.
        old = escape(read(args.replace_old, args.replace_old_file))
        new = read(args.replace_new, args.replace_new_file)
        if args.field in LIST_FIELDS and not new:
            raise SystemExit("removing an array element needs --replace-new too")
        occurrences = segment.count(old)
        if occurrences != 1:
            raise SystemExit(f"REFUSED --replace-old matches {occurrences} times in "
                             f"{args.claim}.{args.field}; it must match exactly once")
        segment = segment.replace(old, escape(new) if args.field not in LIST_FIELDS else new)

    source = source[:start] + segment + source[end:]
    try:
        validate(source)
    except tomllib.TOMLDecodeError as error:
        print(f"REFUSED the edit would not parse, so nothing was written:\n  {error}")
        return 1

    delta = len(source) - len(before)
    if args.dry_run:
        print(f"OBSERVED HERE  would edit {args.claim}.{args.field} ({delta:+d} bytes); dry run")
        return 0
    CORPUS.write_text(source, encoding="utf-8")
    print(f"OBSERVED HERE  edited {args.claim}.{args.field} ({delta:+d} bytes), "
          f"corpus parses and every claim carries the eleven fields")
    print("               now re-pin: python3 scripts/repin_contract.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
