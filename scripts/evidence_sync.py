#!/usr/bin/env python3
"""Copy the version-worthy evidence out of archive/ into evidence/ (tracked by git).

Why this exists
---------------
`.gitignore` excludes `archive/`, for good reasons: it holds third-party data whose
redistribution is restricted, plus large rebuildable arrays. But it also holds the
SMALL text results WE generated -- report.json / run.log -- and those are byte-level
evidence: they carry the gates, the controls, the recorded failures and the sha256s that
every claim in the docs points at. Leaving them untracked means a lost server loses the
evidence, while the prose that cites it stays in git.

Policy (deliberate, and enforced here)
--------------------------------------
IN   : `archive/*/report.json`, `archive/*/run.log`, and `archive/*/*.json` under the
       per-file size cap -- i.e. our own generated text/JSON results.
OUT  : arrays and figures (`.npz`, `.png`, `.svg`, `.gif`, `.nc`, `.h5`, `.zarr`, ...)
       and anything above the cap. The frozen substrate (`model.npz` 28 MB,
       `projection-L12.npz` 29 MB, `forecast.npz` 13 MB, `backtest.npz` 45 MB) therefore
       stays OUT of git on purpose -- see evidence/README.md for what that risks.

Rules
-----
* Append-only: an existing evidence file is NEVER overwritten. Same bytes => skip;
  different bytes => refuse and report (non-zero exit). If a result really changed, the
  archive entry was rewritten, which is itself a finding worth a human look.
* Every copied file is recorded in `evidence/MANIFEST.jsonl` with its sha256 and size, so
  the copy can be checked against the archive original at any time.

Usage:  python scripts/evidence_sync.py [--check]      (--check writes nothing)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ARCHIVE = REPO / 'archive'
EVIDENCE = REPO / 'evidence'
MANIFEST = EVIDENCE / 'MANIFEST.jsonl'
SIZE_CAP = 1_000_000
DENY_SUFFIXES = {'.npz', '.npy', '.png', '.svg', '.gif', '.jpg', '.jpeg', '.webp', '.mp4',
                 '.nc', '.h5', '.hdf5', '.zarr', '.zip', '.gz', '.pkl', '.pt', '.bin'}
ALLOW_NAMES = {'report.json', 'run.log'}
# Dependency metadata is NOT result evidence, and the source it belongs to
# (experiments/observable-seasonal/) is already tracked in this repo, so copying the
# lockfiles here would only duplicate them. Added during the first import, after the
# initial sweep had pulled six of them in.
DENY_NAMES = {'package.json', 'package-lock.json', 'package-lock.yaml', 'yarn.lock',
              'pnpm-lock.yaml'}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def candidates() -> list[Path]:
    if not ARCHIVE.is_dir():
        return []
    out = []
    for sub in sorted(p for p in ARCHIVE.iterdir() if p.is_dir()):
        for f in sorted(sub.iterdir()):
            if not f.is_file():
                continue
            if f.suffix.lower() in DENY_SUFFIXES:
                continue
            if f.name in DENY_NAMES:
                continue
            if f.name not in ALLOW_NAMES and f.suffix.lower() != '.json':
                continue
            if f.stat().st_size > SIZE_CAP:
                continue
            out.append(f)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--check', action='store_true', help='report what would happen; write nothing')
    args = ap.parse_args(argv)

    known = {}
    if MANIFEST.is_file():
        for line in MANIFEST.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                known[rec['source']] = rec

    copied, skipped, conflicts, too_big = [], [], [], []
    for src in candidates():
        rel = src.relative_to(REPO).as_posix()
        dst = EVIDENCE / src.relative_to(ARCHIVE)
        digest = sha256_file(src)
        size = src.stat().st_size
        if size > SIZE_CAP:
            too_big.append((rel, size))
            continue
        if dst.is_file():
            if sha256_file(dst) == digest:
                skipped.append(rel)
                continue
            conflicts.append(rel)
            continue
        if args.check:
            copied.append((rel, size))
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        rec = {'source': rel, 'evidence': dst.relative_to(REPO).as_posix(),
               'sha256': digest, 'bytes': size, 'copied_utc': utcnow(),
               'note': 'copied from archive/ by scripts/evidence_sync.py; archive original is the master'}
        with open(MANIFEST, 'a') as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
        copied.append((rel, size))

    total = sum(s for _r, s in copied)
    print(f'candidates scanned : {len(candidates())}')
    print(f'copied             : {len(copied)} files, {total} bytes'
          + (' (--check: nothing written)' if args.check else ''))
    print(f'already present    : {len(skipped)}')
    print(f'REFUSED (different bytes, not overwritten): {len(conflicts)}')
    for rel in conflicts:
        print(f'   ! {rel}')
    if too_big:
        print(f'over cap           : {len(too_big)}')
        for rel, size in too_big:
            print(f'   - {rel} ({size} bytes)')
    return 1 if conflicts else 0


if __name__ == '__main__':
    sys.exit(main())
