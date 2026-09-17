#!/usr/bin/env python3
"""A receiver for the problem-card rounds, following the Adva receiver convention.

Four rounds in this repository are stuck on `handoff.receiver_confirms_same_question
= false`.  That field asks a question no worker can answer about its own work: is
the thing you are handing back still the question I asked?  Adva mechanised this
in PR #192-#195 as a separate process -- `receive.py --expected E --candidate C`
-- so this is the same shape, applied to a round rather than to a probability
receipt.

What it decides, and why only this much:

  SameQuestion     the candidate preserves the declared question, the success
                   condition, the candidate set and the check scope.  Nothing
                   else follows: the receiver does not say the round is finished,
                   that the result is right, or that the question was worth asking.
  ChangedQuestion  the question text differs after canonicalisation.
  ChangedScope     the question is preserved but the check scope or the candidate
                   set is not.
  ChangedBudget    the question and scope are preserved but the declared budget is not.
  InvalidCandidate required fields are absent or the wrong type.

The receiver never imports the producer.  It reads the card as the *expected*
side, so a card cannot certify itself by being re-emitted: the fields it must
match are the ones it declared before the round ran.

Like Adva's receivers, this one reports `native_authority`, `close_authorized`
and `free_authorized` as false.  A passing receive confirms one thing -- that the
question is the same one -- and authorises nothing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time

INVARIANTS = ("question", "success_condition", "candidates", "check_scope")
SUCCESS = {"SameQuestion"}


def canon(text) -> str:
    """Canonical form of a declared string: whitespace and case carry no meaning.

    A receiver that compared raw strings would refuse a candidate for reflowing a
    paragraph, and would accept one that changed a number.  Both are wrong, so the
    comparison strips layout and keeps every token.
    """
    if not isinstance(text, str):
        return ""
    return re.sub(r"\s+", "", text).strip().lower()


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--expected", required=True,
                    help="the round's card, as declared before the work ran")
    ap.add_argument("--candidate", required=True,
                    help="a handoff candidate to receive")
    args = ap.parse_args()
    started = time.perf_counter()

    outcome, reason, delta, diagnostics = "InvalidCandidate", "unstarted", [], {}

    try:
        card = load(args.expected)
        candidate = load(args.candidate)
    except Exception as error:  # noqa: BLE001 - a bad file is a refusal, not a crash
        print(json.dumps({
            "profile": "xue.study.receive-question.v0", "outcome": "InvalidCandidate",
            "reason": f"{type(error).__name__}: {error}", "accepted_claim": None,
            "diagnostics": {}, "semantic_delta": [], "native_authority": False,
            "close_authorized": False, "free_authorized": False,
            "wall_seconds": time.perf_counter() - started}, sort_keys=True))
        return 0

    try:
        declared = {
            "question": card["handoff"]["question"],
            "success_condition": card["success_condition"],
            "candidates": card["candidates"],
            "check_scope": card["check_scope"],
        }
        offered = {
            "question": candidate["question"],
            "success_condition": candidate.get("success_condition"),
            "candidates": candidate.get("candidates"),
            "check_scope": candidate.get("checks"),
        }
        if candidate.get("question_id") not in (None, card.get("question_id")):
            raise KeyError("question_id")
    except (KeyError, TypeError) as error:
        print(json.dumps({
            "profile": "xue.study.receive-question.v0", "outcome": "InvalidCandidate",
            "reason": f"missing or wrong-typed field: {error}", "accepted_claim": None,
            "diagnostics": {}, "semantic_delta": [], "native_authority": False,
            "close_authorized": False, "free_authorized": False,
            "wall_seconds": time.perf_counter() - started}, sort_keys=True))
        return 0

    diagnostics = {name: canon(declared[name]) == canon(offered.get(name)) for name in INVARIANTS}

    if not diagnostics["question"]:
        outcome, reason = "ChangedQuestion", "the offered question is not the declared one"
    elif not diagnostics["candidates"]:
        outcome, reason = "ChangedScope", "the offered candidate set is not the declared one"
    elif not diagnostics["check_scope"]:
        outcome, reason = "ChangedScope", "the offered check scope is not the declared one"
    elif not diagnostics["success_condition"]:
        outcome, reason = "ChangedScope", "the offered success condition is not the declared one"
    else:
        outcome, reason = "SameQuestion", "declared question, candidates, check scope and success condition preserved"
        delta = ["the offered question is the declared one",
                 "the offered candidate set is the declared one",
                 "the offered check scope is the declared one",
                 "the offered success condition is the declared one"]

    if outcome not in SUCCESS:
        delta = []

    print(json.dumps({
        "profile": "xue.study.receive-question.v0",
        "outcome": outcome,
        "reason": reason,
        "expected_question_id": card.get("question_id"),
        "accepted_claim": candidate["question"] if outcome in SUCCESS else None,
        "diagnostics": diagnostics,
        "semantic_delta": delta,
        "native_authority": False,
        "close_authorized": False,
        "free_authorized": False,
        "wall_seconds": time.perf_counter() - started,
    }, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
