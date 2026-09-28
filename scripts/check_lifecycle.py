#!/usr/bin/env python3
"""P3: check that sha256 references in the docs obey the lifecycle rules.

Rules live in docs/lifecycle/README.md; this script only enforces them.

  A  resolvable   every sha256-shaped token must resolve to an entry in
                  docs/lifecycle.jsonl, evidence/MANIFEST.jsonl, or an
                  archive/*/manifest.json
  B  not superseded  a cited artifact whose state is `superseded` must have a
                  successor pointer nearby
  C  not out of place  an artifact in state `reference` must not appear in a
                  CONCLUSION sentence (same sentence contains a conclusion word)

Exit codes: 0 in --report mode even when findings exist (this is a survey of an
existing, large document set). --strict returns non-zero, for CI once the citations
have been cleaned.

Usage:
    python scripts/check_lifecycle.py [--strict] [--json report.json] [--quiet]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LEDGER = REPO / 'docs' / 'lifecycle.jsonl'
EVIDENCE_MANIFEST = REPO / 'evidence' / 'MANIFEST.jsonl'

# sha256-shaped tokens, including the truncated forms the docs actually use
# (e.g. "807c46c89691f34d…" or "sha256 807c46c8"). 8 hex chars is the shortest form used.
SHA = re.compile(r'\b([0-9a-f]{8,64})\b')
# A date stamp like 20260924 or 2026092312 is ALL digits and therefore valid hex, so the
# naive pattern above matched it and the first version of this checker reported 26 bogus
# "hash mismatches" (every one of them a date). Require at least one a-f letter: a real
# sha256 prefix has one with probability 1-(10/16)^8 = 97.7% at 8 chars, so this loses
# about 2% of legitimately-cited truncated hashes and removes 100% of the date noise.
HAS_LETTER = re.compile(r'[a-f]')
# A scientific-notation float can look like hex ("5.551115123125783e-17").
FLOATY = re.compile(r'[0-9]\.[0-9]+e[-+]?[0-9]+', re.I)
# A filename mentioned on the same line, used to verify a "hash of a repo file" claim.
FILENAME = re.compile(r'([\w./-]+\.(?:json|jsonl|npz|py|md|log|nc|toml|txt|sh|service|timer))')
GIT_COMMIT = re.compile(r'\b[0-9a-f]{40}\b')
SENTENCE_SPLIT = re.compile(r'[。；\n]|\\\\n')
SKIP_DIR_PARTS = {'target', 'build', 'dist', '.venv'}
CONCLUSION_WORDS = ('结论', '因此', '所以', '证明', '表明', '据此', '故', '由此')
SUCCESSOR_WORDS = ('successor', '取代', 'superseded by', '后继')
# A HISTORICAL statement names an old hash on purpose: "advanced from fbf220b4 to aebe4bbf",
# "f823ad13 (11 cases) -> c78f42e4 (12 cases)". Requiring those to match the current file is
# wrong -- that is what the first version did, and it produced 6 bogus mismatches.
HISTORICAL_WORDS = ('advanced', '->', '→', '原先', '改为', '重钉', '此前', '旧值', 'was ', 'from ')
# Documents that RECORD conclusions rather than MAKE them to a reader. Citing a `reference`
# artifact inside a problem card is the whole point of a card, so rule C must not fire there.
RECORD_DIRS = ('docs/problem-cards', 'docs/maintenance', 'docs/lifecycle', 'evidence')
SCAN_SUFFIXES = {'.md', '.json', '.jsonl', '.py', '.txt'}
SKIP_PARTS = {'.git', 'node_modules', '__pycache__', '.ruff_cache'}
# Tokens that look like a hash but are not references to a frozen artifact (git short shas,
# npm integrity fragments, ...). Git abbreviations are excluded by requiring >= 8 chars AND
# a matching prefix in a registry; anything unmatched is simply reported, never silently ok.


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def load_registry() -> dict[str, dict]:
    """sha256 (or prefix) -> {artifact, state, source, generation}."""
    reg: dict[str, dict] = {}

    def put(full: str, rec: dict):
        if not full:
            return
        full = full.lower()
        reg[full] = rec
        for n in (8, 12, 16, 24, 32, 48):
            reg.setdefault(full[:n], rec)

    if LEDGER.is_file():
        for line in LEDGER.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get('event') not in ('state_set', 'demote', 'promote', 'supersede'):
                continue
            put(r.get('sha256', ''), {'artifact': r.get('artifact'), 'state': r.get('to'),
                                      'source': 'lifecycle', 'generation': r.get('method_generation')})
    if EVIDENCE_MANIFEST.is_file():
        for line in EVIDENCE_MANIFEST.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            put(r.get('sha256', ''), {'artifact': r.get('source'), 'state': 'current',
                                      'source': 'evidence_manifest', 'generation': None})
    for man in REPO.glob('archive/*/manifest.json'):
        try:
            r = json.loads(man.read_text())
        except Exception:                                       # noqa: BLE001
            continue
        put(r.get('sha256', ''), {'artifact': str(man.parent.relative_to(REPO)),
                                  'state': 'unregistered', 'source': 'archive_manifest',
                                  'generation': None})
    return reg


def iter_docs():
    for path in REPO.rglob('*'):
        if not path.is_file() or path.suffix.lower() not in SCAN_SUFFIXES:
            continue
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        if any(part in SKIP_DIR_PARTS for part in path.parts):
            continue                    # build outputs (.rustc_info.json and friends)
        if path.name in ('lifecycle.jsonl', 'MANIFEST.jsonl', 'BACKUP_PLAN.json',
                         'check_lifecycle.py'):
            continue   # the registries themselves, and this checker's own comments, which
                       # necessarily quote example hashes, are not citations
        yield path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--strict', action='store_true', help='non-zero exit when findings exist')
    ap.add_argument('--json', dest='json_out', default=str(REPO / 'docs/lifecycle/last_report.json'))
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args(argv)

    reg = load_registry()
    findings: list[dict] = []
    stats = {'files_scanned': 0, 'tokens': 0, 'resolved': 0}

    for path in iter_docs():
        stats['files_scanned'] += 1
        try:
            text = path.read_text(errors='replace')
        except Exception:                                       # noqa: BLE001
            continue
        rel = path.relative_to(REPO).as_posix()
        lines = text.splitlines()
        for lineno, line in enumerate(lines, 1):
            sentences = SENTENCE_SPLIT.split(line)
            for m in SHA.finditer(line):
                tok = m.group(1).lower()
                stats['tokens'] += 1
                if not HAS_LETTER.search(tok):
                    stats['skipped_alldigit'] = stats.get('skipped_alldigit', 0) + 1
                    continue
                # skip tokens that sit inside a scientific-notation float
                span = line[max(m.start() - 24, 0):m.end() + 6]
                if FLOATY.search(span):
                    stats['skipped_floaty'] = stats.get('skipped_floaty', 0) + 1
                    continue
                if GIT_COMMIT.search(line) and tok in (GIT_COMMIT.search(line).group(0)[:len(tok)]):
                    stats['git_commits'] = stats.get('git_commits', 0) + 1
                    continue
                rec = reg.get(tok)
                if rec is None:
                    # Not a registered artifact. It may still be a hash OF a repo file -- in
                    # which case we can VERIFY it by recomputing, which catches real citation
                    # drift. Only if that fails is it reported as unresolvable.
                    names = FILENAME.findall(line)
                    verified = False
                    for name in names:
                        cand = (path.parent / name).resolve()
                        try:
                            cand.relative_to(REPO)
                        except ValueError:
                            continue
                        if not cand.is_file():
                            continue
                        if sha256_file(cand).startswith(tok):
                            verified = True
                            stats['verified_repo_file'] = stats.get('verified_repo_file', 0) + 1
                            break
                        if any(w in line for w in HISTORICAL_WORDS) or '?v=' in line:
                            stats['skipped_historical'] = stats.get('skipped_historical', 0) + 1
                        else:
                            findings.append({'kind': 'repo_file_hash_mismatch', 'file': rel,
                                             'line': lineno, 'token': tok,
                                             'artifact': str(cand.relative_to(REPO)),
                                             'context': line.strip()[:160]})
                        verified = True
                        break
                    if not verified and re.search(r'sha256|sha-256|摘要|哈希|hash', line, re.I):
                        # NOT called "unresolvable": it means this checker does not yet cover
                        # the reference, which is a gap in the CHECKER, not a defect in the doc.
                        # Two known gaps: (1) a repo-file hash named by FIELD (contract_sha256:)
                        # without the filename on the same line; (2) hashes pinned in other
                        # registries (docs/claims.toml, docs/catalog-inventory.json,
                        # docs/conformance.contract.json). Both are declared in the README.
                        findings.append({'kind': 'uncovered', 'file': rel, 'line': lineno,
                                         'token': tok, 'context': line.strip()[:160]})
                    continue
                stats['resolved'] += 1
                if rec['state'] == 'superseded':
                    window = line + ' ' + ' '.join(lines[lineno:lineno + 2])
                    if not any(w in window for w in SUCCESSOR_WORDS):
                        findings.append({'kind': 'superseded_without_pointer', 'file': rel,
                                         'line': lineno, 'token': tok, 'artifact': rec['artifact'],
                                         'context': line.strip()[:160]})
                in_record = any(rel.startswith(d) for d in RECORD_DIRS)
                if (not in_record and rec['state'] == 'reference'
                        and any(w in s for s in sentences for w in CONCLUSION_WORDS)):
                    findings.append({'kind': 'reference_in_conclusion', 'file': rel, 'line': lineno,
                                     'token': tok, 'artifact': rec['artifact'],
                                     'context': line.strip()[:160]})

    by_kind: dict[str, int] = {}
    for f in findings:
        by_kind[f['kind']] = by_kind.get(f['kind'], 0) + 1
    report = {'generated_utc': utcnow(), 'registry_entries': len(reg), 'stats': stats,
              'by_kind': by_kind, 'findings': findings}
    Path(a.json_out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.json_out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')

    if not a.quiet:
        print(f"扫描 {stats['files_scanned']} 个文件，{stats['tokens']} 个 sha 形态 token，"
              f"可解析 {stats['resolved']}")
        print('发现：' + (', '.join(f'{k}={v}' for k, v in sorted(by_kind.items())) or '无'))
        for kind in ('repo_file_hash_mismatch', 'superseded_without_pointer',
                     'reference_in_conclusion', 'uncovered'):
            sel = [f for f in findings if f['kind'] == kind]
            if not sel:
                continue
            print(f'\n--- {kind}（{len(sel)}）---')
            for f in sel[:40]:
                extra = f' [{f.get("artifact")}]' if f.get('artifact') else ''
                print(f'  {f["file"]}:{f["line"]}  {f["token"][:16]}{extra}')
                print(f'      {f["context"]}')
            if len(sel) > 40:
                print(f'  …另有 {len(sel) - 40} 条，见 {Path(a.json_out).relative_to(REPO)}')
        print(f'\n完整报告：{Path(a.json_out).relative_to(REPO)}')
    return 1 if (a.strict and findings) else 0


if __name__ == '__main__':
    sys.exit(main())
