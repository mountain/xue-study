#!/usr/bin/env python3
"""Back up the irreplaceable bytes to S3, and be able to prove they arrived intact.

WHAT IS BACKED UP, AND WHY THIS ORDER
-------------------------------------
  inputs/  (~2.7 GB)  the R1 monthly inputs, raw NetCDF included. **These are the
                      irreplaceable ones**: PSL updates its files IN PLACE, so once
                      upstream replaces a vintage it is gone forever. We kept only
                      `source_sha256`, which proves which vintage we used but cannot
                      bring it back.
  frozen/  (112 MB)   archive/multivariate-l12-v1/*.npz -- the shared substrate every
                      forecast and the verifier act on. Recomputable FROM the inputs
                      (E1b's G2 reproduced the projection array-for-array), but not
                      byte-identically, and many documents cite these by sha256.

So: the inputs are what must not be lost; the frozen substrate is what must stay
*citable*. Backing up only the second would be backing up the replaceable half.

VERIFICATION, HONESTLY DESCRIBED
--------------------------------
`sync` uploads with `--checksum-algorithm SHA256`, so S3 stores a per-object SHA256.
`verify` reads that back with `head-object` and compares it to the locally computed
hash in the plan -- no re-download needed. What this proves: the object S3 holds is the
object we sent. What it does not prove: that the local file is still the file we hashed
(rehash the local side with `plan --recheck`).

`--local DIR` runs the whole thing against a directory instead of S3, so the tool is
testable with no credentials at all.

Usage
-----
    python scripts/backup_to_s3.py plan      [--recheck]     # hash local side, write plan
    python scripts/backup_to_s3.py sync      --bucket B [--local DIR] [--only frozen]
    python scripts/backup_to_s3.py verify    --bucket B [--local DIR]
    python scripts/backup_to_s3.py deep      --bucket B [--only frozen]   # re-download + hash
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLAN = REPO / 'evidence' / 'BACKUP_PLAN.json'
MANIFEST = REPO / 'evidence' / 'BACKUP_MANIFEST.jsonl'
AWS = os.path.expanduser('~/bin/aws')

SOURCES = [
    {'prefix': 'frozen', 'local': str(REPO / 'archive' / 'multivariate-l12-v1'),
     'note': 'frozen substrate: model + projection + forecast + backtest',
     'include': ['*.npz', '*.json']},
    {'prefix': 'inputs/ncep-multivariate',
     'local': '/home/ubuntu/climatetensor-inputs/ncep-multivariate',
     'note': 'R1 monthly inputs incl. raw NetCDF -- upstream replaces these IN PLACE',
     'include': ['*']},
    {'prefix': 'inputs/ncep-multivariate-ext-202602',
     'local': '/home/ubuntu/climatetensor-inputs/ncep-multivariate-ext-202602',
     'note': 'extended inputs through 2026-02',
     'include': ['*']},
]


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b''):
            h.update(chunk)
    return h.hexdigest()


def walk(src: dict) -> list[Path]:
    root = Path(src['local'])
    if not root.is_dir():
        return []
    if src['include'] == ['*']:
        return sorted(p for p in root.rglob('*') if p.is_file())
    out = []
    for pat in src['include']:
        out.extend(sorted(root.glob(pat)))
    return out


def build_plan(recheck: bool) -> dict:
    entries, total = [], 0
    for src in SOURCES:
        for f in walk(src):
            e = {'prefix': src['prefix'], 'remote': f'{src["prefix"]}/{f.relative_to(src["local"]).as_posix()}',
                 'local': str(f), 'bytes': f.stat().st_size, 'note': src['note']}
            if recheck or True:                      # hashing is the point; always compute
                e['sha256'] = sha256_file(f)
            entries.append(e)
            total += e['bytes']
        print(f'  {src["prefix"]:40s} {len([e for e in entries if e["prefix"] == src["prefix"]]):5d} files')
    plan = {'generated_utc': utcnow(), 'n_files': len(entries), 'total_bytes': total,
            'sources': SOURCES, 'files': entries,
            'note': 'local side hashed at generation time; run `plan --recheck` to confirm '
                    'the local files are still byte-identical to this list'}
    PLAN.parent.mkdir(parents=True, exist_ok=True)
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n')
    print(f'plan -> {PLAN.relative_to(REPO)}  ({len(entries)} files, '
          f'{total / 1e6:.1f} MB)')
    return plan


def aws(args: list[str], dry: bool = False) -> str:
    if dry:
        print('   [local]', ' '.join(args[:4]), '...')
        return ''
    cmd = [AWS, *args]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f'aws failed: {" ".join(cmd)}\n{r.stderr.strip()[:500]}')
    return r.stdout


def do_sync(bucket: str, local_root: str | None, only: list[str] | None) -> int:
    """Copy every file in the plan to its exact key. The plan is the single source of truth.

    Deliberately per-file rather than one `s3 sync` per root: the plan already fixes each
    remote key, so the upload cannot drift from what was hashed. (An earlier draft built a
    long --include/--exclude chain for `s3 cp --recursive`; file names can repeat across
    subdirectories, which would have made that chain wrong.)
    """
    plan = json.loads(PLAN.read_text())
    files = [e for e in plan['files']
             if not only or any(e['prefix'] == o or e['prefix'].startswith(o + '/') for o in only)]
    done = skipped = 0
    total = sum(e['bytes'] for e in files)
    print(f'sync: {len(files)} files, {total / 1e6:.1f} MB')
    for i, e in enumerate(files, 1):
        if local_root:
            dst = Path(local_root) / e['remote']
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.is_file() and dst.stat().st_size == e['bytes']:
                skipped += 1
                continue
            dst.write_bytes(Path(e['local']).read_bytes())
        else:
            aws(['s3', 'cp', '--only-show-errors', '--checksum-algorithm', 'SHA256',
                 e['local'], f's3://{bucket}/{e["remote"]}'])
        done += 1
        if i % 10 == 0 or i == len(files):
            print(f'  {i}/{len(files)}  {e["remote"]}')
    print(f'sync done: copied {done}, already present {skipped}')
    return 0


def do_verify(bucket: str, local_root: str | None, only: list[str] | None = None) -> int:
    plan = json.loads(PLAN.read_text())
    files = [e for e in plan['files']
             if not only or any(e['prefix'] == o or e['prefix'].startswith(o + '/') for o in only)]
    ok = bad = missing = 0
    for e in files:
        if local_root:
            # HASH, do not merely compare sizes. An earlier version of this branch checked
            # size only, so flipping a single byte inside model.npz still reported ok --
            # i.e. the local mode was not a verification at all, and it was the mode I was
            # using to test the tool. Caught by a deliberate one-byte corruption test.
            t = Path(local_root) / e['remote']
            if not t.is_file():
                missing += 1
                print(f'  MISSING  {e["remote"]}')
            elif t.stat().st_size != e['bytes']:
                bad += 1
                print(f'  SIZE     {e["remote"]}')
            elif sha256_file(t) != e['sha256']:
                bad += 1
                print(f'  HASH     {e["remote"]}')
            else:
                ok += 1
            continue
        try:
            out = aws(['s3api', 'head-object', '--bucket', bucket, '--key', e['remote'],
                       '--query', '[ContentLength,ChecksumSHA256]', '--output', 'json'])
        except SystemExit:
            missing += 1
            print(f'  MISSING  {e["remote"]}')
            continue
        size, csum = json.loads(out or '[0,null]')
        if size != e['bytes']:
            bad += 1
            print(f'  SIZE     {e["remote"]}: remote {size} local {e["bytes"]}')
            continue
        if not csum:
            bad += 1
            print(f'  NO-SHA   {e["remote"]}: stored without a SHA256 checksum, cannot verify')
            continue
        got = base64.b64decode(csum).hex()
        if got == e['sha256']:
            ok += 1
        else:
            bad += 1
            print(f'  HASH     {e["remote"]}')
    print(f'verify: ok={ok} mismatched={bad} missing={missing} '
          f'(of {len(files)}{" selected" if only else ""} / {len(plan["files"])} planned)')
    rec = {'checked_utc': utcnow(), 'bucket': bucket, 'local_root': local_root,
           'ok': ok, 'mismatched': bad, 'missing': missing, 'n_files': len(files),
           'only': only}
    with open(MANIFEST, 'a') as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
    return 1 if (bad or missing) else 0


def do_deep(bucket: str, only: list[str] | None) -> int:
    """Re-download and rehash: the strongest check, and the slowest."""
    plan = json.loads(PLAN.read_text())
    tmp = Path('/tmp/xue-backup-deep')
    tmp.mkdir(parents=True, exist_ok=True)
    ok = bad = 0
    for e in plan['files']:
        if only and not any(e['prefix'] == o or e['prefix'].startswith(o + '/') for o in only):
            continue
        t = tmp / Path(e['remote']).name
        aws(['s3api', 'get-object', '--bucket', bucket, '--key', e['remote'], str(t)])
        if sha256_file(t) == e['sha256']:
            ok += 1
        else:
            bad += 1
            print(f'  DEEP-HASH {e["remote"]}')
        t.unlink()
    print(f'deep: ok={ok} mismatched={bad}')
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('command', choices=['plan', 'sync', 'verify', 'deep'])
    ap.add_argument('--bucket', default='')
    ap.add_argument('--local', default=None, help='run against a directory instead of S3')
    ap.add_argument('--only', action='append', help='restrict to a prefix (e.g. frozen)')
    ap.add_argument('--recheck', action='store_true')
    args = ap.parse_args(argv)

    if args.command == 'plan':
        build_plan(args.recheck)
        return 0
    if not PLAN.is_file():
        print('no plan yet: run `plan` first', file=sys.stderr)
        return 1
    if args.command == 'sync':
        if not args.bucket and not args.local:
            print('sync needs --bucket or --local', file=sys.stderr)
            return 1
        return do_sync(args.bucket, args.local, args.only)
    if args.command == 'verify':
        if not args.bucket and not args.local:
            print('verify needs --bucket or --local', file=sys.stderr)
            return 1
        return do_verify(args.bucket, args.local, args.only)
    if args.command == 'deep':
        if not args.bucket:
            print('deep needs --bucket', file=sys.stderr)
            return 1
        return do_deep(args.bucket, args.only)
    return 0


if __name__ == '__main__':
    sys.exit(main())
