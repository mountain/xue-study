"""E2 checker: three-face receipts, witnesses, controls, verdict.

Rules are read from contract.json; nothing is decided here that the contract does
not state. Fail-closed: an unresolvable witness, a schema violation, or a broken
negative control is a TOOL FAILURE (non-zero exit). A verdict of
`partial_frontier` or `relabel_risk` is a legitimate finding, not a failure.
"""
from pathlib import Path
import hashlib
import itertools
import json
import re
import sys
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CONTRACT = HERE / 'contract.json'
RECEIPTS = HERE / 'receipts'
REPORT = HERE / 'report.json'
LOG = HERE / 'run.log'
FACES = ['t', 'x', 'k']
SLOTS = ['局部单元', '重叠', '相容条件', '粘合产物']
STATUSES = ['present', 'degenerate', 'absent']

failures = []
log_lines = []


def log(msg):
    log_lines.append(msg)
    print(msg, flush=True)


def fail(msg):
    failures.append(msg)
    log('FAIL ' + msg)


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def check_witness(face, where, w):
    """Return True iff the witness resolves. kind in {file_contains,file_sha256}."""
    if not isinstance(w, dict) or 'kind' not in w:
        fail(f'{face}/{where}: witness is not an object with kind')
        return False
    ref = w.get('ref')
    if not isinstance(ref, str) or not ref:
        fail(f'{face}/{where}: witness.ref missing')
        return False
    p = ROOT / ref
    if not p.is_file():
        fail(f'{face}/{where}: witness file not found: {ref}')
        return False
    if w['kind'] == 'file_contains':
        needle = w.get('needle')
        if not isinstance(needle, str) or not needle:
            fail(f'{face}/{where}: file_contains without needle')
            return False
        if needle not in p.read_text(errors='replace'):
            fail(f'{face}/{where}: needle not found in {ref}: {needle[:70]!r}')
            return False
        return True
    if w['kind'] == 'file_sha256':
        want = w.get('sha256')
        got = sha256_bytes(p.read_bytes())
        if want != got:
            fail(f'{face}/{where}: sha256 mismatch for {ref}: want {want} got {got}')
            return False
        return True
    fail(f'{face}/{where}: unknown witness kind {w["kind"]!r}')
    return False


def main():
    contract_bytes = CONTRACT.read_bytes()
    contract_sha = sha256_bytes(contract_bytes)
    c = json.loads(contract_bytes)
    log(f'contract {CONTRACT.name} sha256 {contract_sha}')
    log(f'contract version {c["version"]} question_id {c["question_id"]}')

    counted = [f for f in c['receipt_schema']['receipt_fields']
               if f not in c['identity_fields']['fields']]
    counted_expected = set(c['closed_vocabularies'].keys())
    if set(counted) != counted_expected:
        fail(f'counted fields {sorted(counted)} != closed_vocabularies {sorted(counted_expected)}')
    log(f'counted fields: {len(counted)}')

    receipts = {}
    for face in FACES:
        p = RECEIPTS / f'{face}.json'
        if not p.is_file():
            fail(f'receipt missing: {p}')
            continue
        r = json.loads(p.read_text())
        receipts[face] = r
        if r.get('contract_sha256') != contract_sha:
            fail(f'{face}: receipt recorded contract_sha256 {r.get("contract_sha256")} '
                 f'but contract is {contract_sha} (contract edited after filling?)')
        if r.get('filled_after_contract') is not True:
            fail(f'{face}: filled_after_contract is not true')

    if failures:
        return finish(c, contract_sha, receipts, None, None, None)

    # ---- schema + witnesses
    for face in FACES:
        r = receipts[face]
        for f in c['receipt_schema']['receipt_fields']:
            if f not in r.get('fields', {}):
                fail(f'{face}: missing receipt field {f}')
                continue
            entry = r['fields'][f]
            if f in c['identity_fields']['fields']:
                allowed = c['identity_fields']['domain']
            else:
                allowed = c['closed_vocabularies'][f]
            if entry.get('value') not in allowed:
                fail(f'{face}/{f}: value {entry.get("value")!r} not in closed vocabulary')
            ws = entry.get('witness')
            if not isinstance(ws, list) or not ws:
                fail(f'{face}/{f}: no witness')
                continue
            for w in ws:
                check_witness(face, f, w)
        for slot in SLOTS:
            if slot not in r.get('template_slots', {}):
                fail(f'{face}: missing template slot {slot}')
                continue
            s = r['template_slots'][slot]
            if s.get('status') not in STATUSES:
                fail(f'{face}/{slot}: status {s.get("status")!r} not in {STATUSES}')
            if s.get('status') in ('present', 'degenerate'):
                if not s.get('instance'):
                    fail(f'{face}/{slot}: status {s["status"]} but no instance')
            if s.get('status') == 'absent' and not s.get('why'):
                fail(f'{face}/{slot}: status absent but no why')
            ws = s.get('witness')
            if not isinstance(ws, list) or not ws:
                fail(f'{face}/{slot}: no witness')
                continue
            for w in ws:
                check_witness(face, slot, w)

    # ---- vocabulary rule: min size and at least one unused element
    for f in counted:
        vocab = c['closed_vocabularies'][f]
        if len(vocab) < c['vocabulary_rule']['min_size']:
            fail(f'{f}: vocabulary size {len(vocab)} < {c["vocabulary_rule"]["min_size"]}')
        chosen = {receipts[face]['fields'][f]['value'] for face in FACES}
        if not (set(vocab) - chosen):
            fail(f'{f}: every vocabulary element was chosen by some face (no unused element)')

    if failures:
        return finish(c, contract_sha, receipts, None, None, None)

    # ---- distinguishing fields (11 counted fields)
    def distinguish(rs):
        out = {}
        for f in counted:
            vals = [rs[face]['fields'][f]['value'] for face in FACES]
            out[f] = len(set(vals)) == len(FACES)
        return out

    dist = distinguish(receipts)
    n_dist = sum(dist.values())

    # ---- template slot states
    slot_state = {face: {slot: receipts[face]['template_slots'][slot]['status'] for slot in SLOTS}
                  for face in FACES}
    n_present = sum(1 for face in FACES for slot in SLOTS if slot_state[face][slot] == 'present')

    # ---- criteria
    condition_1 = n_dist >= 4
    condition_2 = n_present == len(FACES) * len(SLOTS)
    if condition_1 and condition_2:
        verdict = 'three_faces'
    elif condition_1:
        verdict = 'partial_frontier'
    else:
        verdict = 'relabel_risk'

    # ---- controls
    control_log = {}

    # C1: label permutation invariance + no face label embedded in counted values
    perms = {}
    for perm in itertools.permutations(FACES):
        relabelled = {new: receipts[old] for new, old in zip(FACES, perm)}
        perms[''.join(perm)] = sum(distinguish(relabelled).values())
    c1_invariant = len(set(perms.values())) == 1 and perms['txk'] == n_dist
    # Revision 2 (2026-09-28): the first version searched for the bare substrings
    # `t_`/`x_`/`k_` anywhere in the value, which fired on ordinary words
    # (digest_record, six_matrix_products, mask_then_gram_solve, ...). That was a
    # FALSE POSITIVE in the checker, not a property of the receipts: the tool
    # correctly refused to emit a verdict (tool_status=failure) until the control
    # was fixed. A face label counts only as a prefix of the value or at a
    # non-alphanumeric boundary.
    label_re = re.compile(r'(?<![0-9A-Za-z_])(?:t_|x_|k_|时_|空_|构_)')
    embedded = []
    for f in counted:
        for face in FACES:
            v = receipts[face]['fields'][f]['value']
            if label_re.search(v):
                embedded.append(f'{face}/{f}={v}')
    if not c1_invariant:
        fail(f'C1 failed: distinguishing count not invariant under label permutation: {perms}')
    if embedded:
        fail(f'C1 failed: counted value embeds a face label: {embedded}')
    control_log['C1_permute_labels'] = {
        'permutation_counts': perms, 'invariant': c1_invariant,
        'face_label_tokens_in_values': embedded, 'passed': c1_invariant and not embedded}

    # C2: copy one receipt onto all three faces -> must collapse
    copied = {face: receipts['t'] for face in FACES}
    dist_copy = distinguish(copied)
    n_copy = sum(dist_copy.values())
    copy_verdict = 'three_faces' if n_copy >= 4 else 'relabel_risk'
    c2_ok = (n_copy == 0 and copy_verdict == 'relabel_risk')
    if not c2_ok:
        fail(f'C2 failed: copying one receipt gave distinguishing={n_copy}, verdict={copy_verdict}')
    control_log['C2_copy_one_receipt'] = {
        'distinguishing_fields': n_copy, 'verdict': copy_verdict, 'passed': c2_ok}

    # ---- predictions (recorded in the contract before filling)
    pred_rows = []
    for item in c['predictions']['items']:
        face, slot, want = item['face'], item['slot'], item['predict']
        if slot == 'verdict':
            got = verdict
        else:
            got = slot_state[face][slot]
        pred_rows.append({'face': face, 'slot': slot, 'predicted': want, 'observed': got,
                          'hit': want == got})
    hits = sum(1 for r in pred_rows if r['hit'])
    log(f'predictions: {hits}/{len(pred_rows)} hit')
    for r in pred_rows:
        if not r['hit']:
            log(f'  MISS face={r["face"]} slot={r["slot"]} predicted={r["predicted"]} observed={r["observed"]}')

    return finish(c, contract_sha, receipts,
                  {'distinguishing_fields': n_dist, 'distinguishing': dist,
                   'slot_state': slot_state, 'n_present_slots': n_present,
                   'condition_1': condition_1, 'condition_2': condition_2, 'verdict': verdict,
                   'controls': control_log, 'predictions': pred_rows,
                   'predictions_hit': hits, 'predictions_total': len(pred_rows)},
                  None, None)


def finish(c, contract_sha, receipts, result, _a, _b):
    report = {
        'version': c['version'],
        'question_id': c['question_id'],
        'checked_at_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'contract_sha256': contract_sha,
        'receipt_sha256': {face: sha256_bytes((RECEIPTS / f'{face}.json').read_bytes())
                           for face in FACES if (RECEIPTS / f'{face}.json').is_file()},
        'tool_status': 'failure' if failures else 'ok',
        'failures': failures,
    }
    if result and failures:
        # A broken control or witness means no verdict is established: withhold it
        # rather than reporting a number the tool cannot stand behind.
        withheld = {k: result[k] for k in ('distinguishing_fields', 'condition_1',
                                          'condition_2', 'verdict')}
        result = {**result, 'verdict_withheld': True, 'withheld': withheld}
        result.pop('verdict', None)
        result.pop('verdict_text', None)
    if result:
        report.update(result)
        if 'verdict' in result:
            report['verdict_text'] = {
            'three_faces': '三面在本载体上都有完整三段式，且收据可区分',
            'partial_frontier': '不是三面：若干面完整、若干面退化或指不出实例（见 slot_state）',
            'relabel_risk': '收据不可区分 ⇒ 0036 §4.1 的红队句成立，报告层必须降级',
        }[result['verdict']]
        absent = [f'{face}/{slot}' for face in FACES for slot in SLOTS
                  if result['slot_state'][face][slot] != 'present']
        report['slots_not_present'] = absent
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    LOG.write_text('\n'.join(log_lines) + '\n')
    print('--- report ---')
    print(json.dumps({k: v for k, v in report.items()
                      if k not in ('distinguishing', 'slot_state', 'predictions')},
                     ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
