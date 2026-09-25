"""Finite spectrum/frame calibration against the actual Adva Rust kernel.

Python declares rational geometry, writes ordinary Adva source, and checks the
returned observations. Native identities, diagrams and graft frames are owned
by adva-lisp. This is not a Python implementation of an Adva evaluator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import resource
import signal
import subprocess
import time
from fractions import Fraction as F
from pathlib import Path

HERE = Path(__file__).resolve().parent
MACHINE = HERE.parents[2] / "adva-machine"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def packed(x):
    if isinstance(x, F):
        return str(x)
    if isinstance(x, dict):
        return {k: packed(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [packed(v) for v in x]
    return x


def write(path, obj):
    with path.open("x") as f:
        json.dump(packed(obj), f, indent=2)
        f.write("\n")


def dot(a, b):
    return sum((x*y for x, y in zip(a, b)), F(0))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def scaled(a, k):
    return tuple(k*x for x in a)


def geometry():
    nodes = []
    for z, radius in [(F(3, 5), F(4, 5)), (F(-3, 5), F(4, 5)),
                      (F(4, 5), F(3, 5)), (F(-4, 5), F(3, 5))]:
        for x, y in [(radius, F(0)), (-radius, F(0)), (F(0), radius), (F(0), -radius)]:
            nodes.append((x, y, z))
    return nodes


def fields(nodes):
    ez = (F(0), F(0), F(1))
    result = {k: [] for k in ["zero", "rigid_z", "gradient_z", "toroidal_l2", "toroidal_l3", "rigid_plus_l2"]}
    for r in nodes:
        z = r[2]
        rigid = cross(ez, r)
        t2 = scaled(cross(r, ez), 3*z)
        result["zero"].append((F(0), F(0), F(0)))
        result["rigid_z"].append(rigid)
        result["gradient_z"].append(tuple(b-z*x for b, x in zip(ez, r)))
        result["toroidal_l2"].append(t2)
        result["toroidal_l3"].append(scaled(cross(r, ez), (15*z*z-3)/2))
        result["rigid_plus_l2"].append(tuple(x+y for x, y in zip(rigid, t2)))
    return result


def quadrature(nodes, wind, a=(F(0), F(0), F(1))):
    even = odd = F(0)
    for r, u in zip(nodes, wind):
        mu = dot(a, r)
        inner = dot(cross(a, r), u)
        even += ((mu > 0)-(mu < 0))*inner/len(nodes)
        odd += abs(mu)*inner/len(nodes)
    return [even, odd]


def adva_source(nodes):
    exports = ["spectrum", "turn-i", "twice-i", "conjugate", "p-after-i", "i-after-p",
               "shear", "unshear", "chart-i", "norm", "chart-norm", "old-then-i"]
    parts = ["(module spectrum-frame", "  (export " + " ".join(exports) + ")"]

    def define(name, names, body, scalar=False):
        params = " ".join(f"({n} Real)" for n in names)
        outputs = "Real" if scalar else "(outputs Real Real)"
        parts.append(f"  (def {name} (fn ({params}) {outputs}\n    {body}))")

    define("merge", ["e1", "o1", "e2", "o2"],
           "(frontier (add (use e1) (use e2)) (add (use o1) (use o2)))")
    leaves = []
    inputs = []
    for j, (x, y, z) in enumerate(nodes):
        ce = F((z > 0)-(z < 0), len(nodes))
        co = abs(z)/len(nodes)
        define(f"weights{j}", ["e", "o"],
               f"(frontier (scale {ce} (use e)) (scale {co} (use o)))")
        define(f"sample{j}", ["x", "y", "z"],
               f"(frontier (call weights{j} (copy (add (scale {-y} (use x)) "
               f"(scale {x} (use y))))) (discard (use z)))")
        args = [f"u{j}{c}" for c in "xyz"]
        inputs.extend(args)
        leaves.append(f"(call sample{j} " + " ".join(f"(use {a})" for a in args) + ")")
    while len(leaves) > 1:
        leaves = [f"(call merge {leaves[j]} {leaves[j+1]})" for j in range(0, len(leaves), 2)]
    define("spectrum", inputs, leaves[0])
    define("turn-i", ["e", "o"], "(frontier (neg (use o)) (id (use e)))")
    define("twice-i", ["e", "o"], "(call turn-i (call turn-i (use e) (use o)))")
    define("conjugate", ["e", "o"], "(frontier (id (use e)) (neg (use o)))")
    define("p-after-i", ["e", "o"], "(call conjugate (call turn-i (use e) (use o)))")
    define("i-after-p", ["e", "o"], "(call turn-i (call conjugate (use e) (use o)))")
    define("shear-body", ["e", "o1", "o2"], "(frontier (add (use e) (use o1)) (use o2))")
    define("unshear-body", ["e", "o1", "o2"], "(frontier (add (use e) (neg (use o1))) (use o2))")
    define("shear", ["e", "o"], "(call shear-body (use e) (copy (use o)))")
    define("unshear", ["e", "o"], "(call unshear-body (use e) (copy (use o)))")
    define("chart-i", ["e", "o"], "(call shear (call turn-i (call unshear (use e) (use o))))")
    define("norm", ["e", "o"], "(add (mul (copy (use e))) (mul (copy (use o))))", scalar=True)
    define("chart-norm", ["e", "o"], "(call norm (call unshear (use e) (use o)))", scalar=True)
    define("old-only", ["e", "o"], "(frontier (use e) (discard (use o)) 0)")
    define("old-then-i", ["e", "o"], "(call turn-i (call old-only (use e) (use o)))")
    return "\n".join(parts) + "\n)\n", exports


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True, help="fresh output directory")
    parser.add_argument("--binary", type=Path, default=HERE / "target/debug/sphaera-frame-probe")
    args = parser.parse_args()
    started = time.monotonic()
    contract = json.loads((HERE / "contract.json").read_text())
    limits = contract["limits"]
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("checker wall budget")))
    signal.alarm(limits["checker_wall_seconds"])
    args.out.mkdir(parents=True, exist_ok=False)
    checks = []

    def check(ok, label):
        checks.append({"label": label, "passed": bool(ok)})
        if len(checks) > limits["assertions"] or not ok:
            write(args.out / "first-failure.json", {"checks": checks, "last": label})
            raise AssertionError(label)

    revision = subprocess.check_output(["git", "-C", str(MACHINE), "rev-parse", "HEAD"], text=True).strip()
    check(revision == contract["machine_revision"], "machine revision is pinned")
    subprocess.run(["git", "-C", str(MACHINE), "diff", "--exit-code", "HEAD", "--", "crates"],
                   check=True, capture_output=True)
    nodes = geometry()
    for j, r in enumerate(nodes):
        check(dot(r, r) == 1, f"unit node {j}")
        check(scaled(r, -1) in nodes, f"antipodal node {j}")
    source, functions = adva_source(nodes)
    source_path = args.out / "spectrum.adva"
    source_path.write_text(source)
    wind_fields = fields(nodes)
    expected = {}
    cases = []

    def case(label, fn, inputs, want):
        cases.append({"id": label, "function": fn, "inputs": {k: float(v) for k, v in inputs.items()}})
        expected[label] = want

    for label, wind in wind_fields.items():
        for j, (r, u) in enumerate(zip(nodes, wind)):
            check(dot(r, u) == 0, f"tangent {label}:{j}")
        q = quadrature(nodes, wind)
        case(label, "spectrum", {f"u{j}{c}": val for j, u in enumerate(wind) for c, val in zip("xyz", u)}, q)
        check(quadrature(nodes, wind, (F(0), F(0), F(-1))) == [q[0], -q[1]], f"axis reversal {label}")
    reference = {
        "turn-i": lambda e, o: [-o, e],
        "twice-i": lambda e, o: [-e, -o],
        "conjugate": lambda e, o: [e, -o],
        "p-after-i": lambda e, o: [-o, -e],
        "i-after-p": lambda e, o: [o, e],
        "shear": lambda e, o: [e+o, o],
        "unshear": lambda e, o: [e-o, o],
        "chart-i": lambda e, o: [e-2*o, e-o],
        "norm": lambda e, o: [e*e+o*o],
        "chart-norm": lambda e, o: [(e-o)**2+o*o],
        "old-then-i": lambda e, o: [F(0), e],
    }
    for e in map(F, [-2, -1, 0, 1, 2]):
        for o in map(F, [-2, -1, 0, 1, 2]):
            for fn, oracle in reference.items():
                case(f"{fn}:{e}:{o}", fn, {"e": e, "o": o}, oracle(e, o))
    for label in ["zero", "rigid_z"]:
        e, o = expected[label]
        case(f"project-first:{label}", "old-then-i", {"e": e, "o": o}, [F(0), e])
    request = args.out / "request.json"
    write(request, {"functions": functions, "cases": cases})

    def native_limits():
        resource.setrlimit(resource.RLIMIT_CPU, (limits["native_cpu_seconds"],)*2)
        memory = limits["native_address_space_mb"] * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        size = limits["native_evidence_mb"] * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_FSIZE, (size, size))

    with (args.out / "native.log").open("x") as log:
        proc = subprocess.run([str(args.binary.resolve()), str(source_path.resolve()), str(request.resolve()),
                               str((args.out / "native.json").resolve())], stdout=log, stderr=subprocess.STDOUT,
                              timeout=limits["native_wall_seconds"], preexec_fn=native_limits)
    check(proc.returncode == 0, "native process returned successfully")
    result = json.loads((args.out / "native.json").read_text())
    observed = {}
    max_error = 0.0
    for row in result["evaluations"]:
        label = row["id"]
        actual = row["result"]["values"]
        want = expected[label]
        error = max(abs(x-float(y)) for x, y in zip(actual, want))
        max_error = max(max_error, error)
        check(len(actual) == len(want) and all(math.isfinite(x) for x in actual) and error <= 1e-12,
              f"native agrees with Fraction oracle: {label}")
        observed[label] = actual
    check(observed["zero"] == observed["gradient_z"], "declared gradient probe remains invisible")
    check(abs(observed["rigid_z"][0]) < 1e-12 and observed["rigid_z"][1] > .3,
          "odd observer distinguishes rigid rotation")
    check(abs(observed["toroidal_l3"][0]) < 1e-12 and abs(observed["toroidal_l3"][1]) > .7,
          "odd observer also distinguishes degree three")
    check(abs(observed["toroidal_l2"][0]) > 1 and abs(observed["toroidal_l2"][1]) < 1e-12,
          "original even observer retained")
    check(observed["project-first:zero"] == observed["project-first:rigid_z"],
          "multiplying the old spectrum by i does not recover the odd witness")
    for e in [-2, -1, 0, 1, 2]:
        for o in [-2, -1, 0, 1, 2]:
            check(observed[f"p-after-i:{e}:{o}"] == [-v for v in observed[f"i-after-p:{e}:{o}"]],
                  f"parity anticommutes with J: {e}:{o}")
    # One concrete chart pair is inside the declared input grid.
    check(observed["shear:1:1"] == [2, 1], "nonorthogonal chart witness")
    check(observed["unshear:2:1"] == [1, 1], "transported observer returns original reading")
    check(observed["shear:1:1"] != [1, 1], "stale observer exposes a false reading")
    check(observed["chart-norm:2:1"] == observed["norm:1:1"] == [2], "transported metric preserves norm")
    check(observed["norm:2:1"] == [5], "stale metric exposes a false norm")
    check(bool(result["refusals"]["implicit_alias"]), "native alias refusal retained")
    check(bool(result["refusals"]["nonfinite_input"]), "native nonfinite-input refusal retained")
    root = result["functions"]["spectrum"]["compilation"]
    frame = {
        "schema": "xue-study.spectrum-interpretation-frame.v0",
        "native_compilation_certificate": root["certificate"]["id"],
        "native_graft_root": root["graft_trace"]["result"]["root"],
        "native_graft_certificate": root["graft_trace"]["certificate"]["id"],
        "native_artifact_sha256": digest(args.out / "native.json"),
        "source_sha256": digest(source_path),
        "geometry": {"nodes": nodes, "weights": [F(1, 16)]*16, "axis": [0, 0, 1]},
        "carrier": ["even observer output", "odd observer output"],
        "J": [[0, -1], [1, 0]], "G": [[1, 0], [0, 1]], "O": [[1, 0], [0, 1]],
        "parity": [[1, 0], [0, -1]],
        "chart": {"T": [[1, 1], [0, 1]], "J": [[1, -2], [1, -1]],
                  "G": [[1, -1], [-1, 2]], "O": [[1, -1], [0, 1]]},
        "interpretation_boundary": "A new finite interpretation over actual native GraftFrames, not an instance of the old iota cut-graph H profile and not a new stable Frame type.",
        "dynamics": "NotSpecified", "weather_skill": "NotTested",
        "parity_boundary": "For a full axis field C(-a)=conj(C(a)); uniform multiplication by i does not preserve this reality condition. No global parity-preserving complex structure on that constrained signature space is claimed."
    }
    write(args.out / "frame.json", frame)
    evidence = {
        "status": "FiniteNativeSpectrumFrameChecked",
        "machine_revision": revision, "source_sha256": digest(source_path),
        "contract_sha256": digest(HERE / "contract.json"), "checker_sha256": digest(Path(__file__)),
        "driver_sha256": digest(HERE / "src/main.rs"),
        "binary_sha256": digest(args.binary),
        "profile_sha256": digest(MACHINE / "spec/framework/iota-frame-v1.md"),
        "checks": checks, "check_count": len(checks), "native_evaluations": len(cases),
        "max_float_error": max_error,
        "fields": {label: {"exact": expected[label], "native": observed[label]} for label in wind_fields},
        "graft_frame_count": len(root["graft_trace"]["result"]["frames"]),
        "elapsed_seconds": time.monotonic()-started,
        "boundary": contract["residuals"],
        "independence": "Fraction quadrature and native Rust evaluation are different arithmetic paths but share this experiment's author and mathematical formulation."
    }
    write(args.out / "evidence.json", evidence)
    signal.alarm(0)
    print(json.dumps({k: evidence[k] for k in ["status", "check_count", "native_evaluations", "max_float_error", "graft_frame_count", "fields"]}, indent=2, default=str))


if __name__ == "__main__":
    main()
