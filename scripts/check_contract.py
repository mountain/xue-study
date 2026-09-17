"""Check that the pinned conformance contract still describes this registry.

`docs/conformance.contract.json` pins the claim registry by sha256 and by case
count. A pin that is never re-checked is decoration: this is the check.

It does not run any claim's checker. It answers one question -- is the corpus
the contract names still the corpus on disk -- and reports the answer without
inferring anything from it.

Usage: python3 scripts/check_contract.py
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/conformance.contract.json"


def main() -> int:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    pin = contract["corpus"]
    corpus = ROOT / pin["path"]
    if not corpus.exists():
        print(f"REFUSED  the pinned corpus is absent here: {pin['path']}")
        return 1

    actual = hashlib.sha256(corpus.read_bytes()).hexdigest()
    digest_ok = actual == pin["sha256"]
    cases = len(tomllib.loads(corpus.read_text(encoding="utf-8"))["claim"])
    count_ok = cases == pin["cases"]

    print(f"OBSERVED HERE  contract      {contract['schema']}")
    print(f"OBSERVED HERE  corpus        {pin['path']}")
    print(f"RECORDED       pinned sha256 {pin['sha256']}")
    print(f"OBSERVED HERE  actual sha256 {actual}")
    print(f"OBSERVED HERE  digest        {'match' if digest_ok else 'MISMATCH'}")
    print(f"OBSERVED HERE  cases         recorded {pin['cases']}, on disk {cases}"
          f"  {'match' if count_ok else 'MISMATCH'}")
    if not (digest_ok and count_ok):
        print("REFUSED  the registry moved; re-pin the contract and say so in a correction note,")
        print("         rather than editing the pin silently.")
        return 1
    print("OBSERVED HERE  verdict       the registry is the corpus the contract names.")
    print("               (Nothing here says a claim holds, or that a checker was run.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
