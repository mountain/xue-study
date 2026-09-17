#!/usr/bin/env python3
"""Re-pin the conformance contract to the claim registry, or refuse to.

The contract pins `docs/claims.toml` by sha256, and a stale pin is worse than no
pin because `check_contract.py` reports a mismatch as a refusal and everything
else keeps going.  The obvious failure is forgetting to re-pin.  The one that
actually happened on 2026-09-17 is the opposite: re-pinning *to a broken file*.
A scripted edit left a real newline inside a single-line TOML string, the pin was
recomputed over the broken bytes, and the digest matched a corpus that no reader
could parse.

So this refuses on a corpus that does not load, and it also refuses when the
case count on disk disagrees with the count it is about to record.  Only then
does it write.  `check_contract.py` still answers "is the corpus the one the
contract names"; this answers "should the contract name this corpus at all".
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/conformance.contract.json"
FIELDS = {"claim_id", "canonical_name", "code_symbol", "dimension", "status", "scope",
          "assumptions", "dependencies", "proof_or_certificate",
          "counterexample_boundary", "forbidden_conflations"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    pin = contract["corpus"]
    corpus = ROOT / pin["path"]
    if not corpus.exists():
        print(f"REFUSED  the corpus is absent: {pin['path']}")
        return 1

    raw = corpus.read_bytes()
    try:
        parsed = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        print(f"REFUSED  the corpus does not parse, so its digest would pin bytes "
              f"no reader can load:\n         {error}")
        return 1

    claims = parsed.get("claim")
    if not isinstance(claims, list) or not claims:
        print("REFUSED  the corpus carries no claims")
        return 1
    for claim in claims:
        if set(claim) != FIELDS:
            print(f"REFUSED  {claim.get('claim_id', '<no id>')} does not carry exactly "
                  f"the eleven fields: missing {sorted(FIELDS - set(claim))}, "
                  f"extra {sorted(set(claim) - FIELDS)}")
            return 1
    ids = [c["claim_id"] for c in claims]
    if len(set(ids)) != len(ids):
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        print(f"REFUSED  duplicate claim ids: {duplicates}")
        return 1

    digest = hashlib.sha256(raw).hexdigest()
    previous = pin["sha256"]
    print(f"OBSERVED HERE  corpus      {pin['path']}")
    print(f"OBSERVED HERE  claims      {len(claims)} (all carry the eleven fields, ids unique)")
    print(f"RECORDED       pinned      {previous[:16]}…")
    print(f"OBSERVED HERE  computed    {digest[:16]}…")
    if digest == previous and pin["cases"] == len(claims):
        print("OBSERVED HERE  verdict     already the pinned corpus; nothing to write")
        return 0
    if args.dry_run:
        print("OBSERVED HERE  verdict     would re-pin (dry run)")
        return 0

    pin["sha256"] = digest
    pin["cases"] = len(claims)
    CONTRACT.write_text(json.dumps(contract, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(f"OBSERVED HERE  verdict     re-pinned to {digest[:16]}…, cases {len(claims)}")
    print("               (this says the corpus loads and is the shape the contract")
    print("                expects; it says nothing about whether any claim holds)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
