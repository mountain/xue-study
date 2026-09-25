"""Exact spherical dynamics identities plus native Adva observation witnesses.

Run with SymPy available. This reuses the prior Rust driver without modifying
its source or original run. Every output directory must be fresh.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
import resource
import signal
import subprocess
import time
from fractions import Fraction as F

HERE = Path(__file__).resolve().parent
PREVIOUS = HERE.parent / "sphaera-frame"
spec = importlib.util.spec_from_file_location("spectrum_reference", PREVIOUS / "check.py")
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--binary", type=Path, default=PREVIOUS / "target/debug/sphaera-frame-probe")
    args = parser.parse_args()
    started = time.monotonic()
    contract = json.loads((HERE / "contract.json").read_text())
    limits = contract["limits"]
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("checker wall budget")))
    signal.alarm(limits["checker_wall_seconds"])
    resource.setrlimit(resource.RLIMIT_CPU, (limits["checker_cpu_seconds"],)*2)
    args.out.mkdir(parents=True, exist_ok=False)
    import sympy as s

    checks = []

    def check(ok, label):
        checks.append({"label": label, "passed": bool(ok)})
        if len(checks) > limits["assertions"] or not ok:
            ref.write(args.out / "first-failure.json", {"checks": checks})
            raise AssertionError(label)

    x, y, z, a, b, w, p = s.symbols("x y z a b w p", real=True)
    r = s.Matrix([x, y, z])

    def grad(f):
        return s.Matrix([s.diff(f, q) for q in r])

    def bracket(f, g):
        return s.expand(r.dot(grad(f).cross(grad(g))))

    def laplace_sphere(f):
        # Restriction of an ambient polynomial to the unit sphere.
        euler = r.dot(grad(f))
        return s.expand(sum(s.diff(f, q, 2) for q in r) - r.dot(grad(euler)) - euler)

    def mean_sphere(f):
        result = 0
        for powers, coeff in s.Poly(s.expand(f), x, y, z).terms():
            if any(k % 2 for k in powers):
                continue
            numerator = math.prod(s.factorial2(k - 1) for k in powers)
            result += coeff * numerator / s.factorial2(sum(powers) + 1)
        return s.expand(result)

    h2 = x*x-y*y
    g2 = 2*x*y
    h4 = x**4-6*x*x*y*y+y**4
    psi2 = a*h2+b*g2
    psi = -w*z+psi2
    vorticity = laplace_sphere(psi)
    speed = (2*w-p)/3
    adot, bdot = -2*speed*b, 2*speed*a
    dt = lambda f: s.expand(s.diff(f, a)*adot+s.diff(f, b)*bdot)
    advection = bracket(psi, vorticity+2*p*z)
    residual = s.expand(dt(vorticity)+advection)
    check(laplace_sphere(z) == -2*z, "degree-one eigenvalue")
    check(laplace_sphere(h2) == -6*h2 and laplace_sphere(g2) == -6*g2,
          "degree-two eigenvalues")
    check(s.expand(laplace_sphere(h4)+20*h4) == 0, "degree-four eigenvalue")
    check(residual == 0, "exact nonlinear vorticity equation for symbolic a,b,w,p")
    wrong_residual = s.expand(dt(vorticity).subs(w, 0)+advection)
    check(wrong_residual != 0, "discarding the hidden rotation changes the PDE tendency")
    check(dt(a*a+b*b) == 0, "shape amplitude is constant in this exact family")
    even_spectrum = -s.Rational(3, 4)*psi2
    power = mean_sphere(even_spectrum**2)
    check(s.expand(power-s.Rational(3, 20)*(a*a+b*b)) == 0,
          "continuous normalized even spectral power")
    velocity = r.cross(grad(psi))
    momentum = [mean_sphere(q) for q in r.cross(velocity)]
    check(momentum == [0, 0, 2*w/3], "degree one carries normalized angular momentum")
    energy = mean_sphere(velocity.dot(velocity))/2
    check(s.expand(energy-w*w/3-s.Rational(4, 5)*(a*a+b*b)) == 0,
          "exact kinetic energy retains a degree-one contribution")
    even_only = h2+h4
    odd_tendency = -bracket(even_only, laplace_sphere(even_only))
    check(odd_tendency != 0 and s.expand(odd_tendency.subs(
        {x: -x, y: -y, z: -z}, simultaneous=True)+odd_tendency) == 0,
        "two different even degrees generate a nonzero odd tendency")
    point = {x: s.Rational(1, 3), y: s.Rational(2, 3), z: s.Rational(2, 3)}
    check(odd_tendency.subs(point) != 0, "odd tendency witness lies on the unit sphere")

    machine_revision = subprocess.check_output(
        ["git", "-C", str(ref.MACHINE), "rev-parse", "HEAD"], text=True).strip()
    check(machine_revision == contract["machine_revision"], "machine revision is pinned")
    subprocess.run(["git", "-C", str(ref.MACHINE), "diff", "--exit-code", "HEAD", "--", "crates"],
                   check=True, capture_output=True)
    nodes = ref.geometry()
    source, _ = ref.adva_source(nodes)
    marker = "(export spectrum "
    check(source.count(marker) == 1, "source export insertion has one target")
    source = source.replace(marker, "(export phase-speed phase-rhs even-coeff " + "spectrum ")
    check(source.endswith("\n)\n"), "source module has expected closing boundary")
    source = source[:-3] + """
  (def phase-speed (fn ((w Real) (p Real)) Real
    (scale 1/3 (add (scale 2 (use w)) (neg (use p))))))
  (def spin-products (fn ((a Real) (b Real) (c1 Real) (c2 Real)) (outputs Real Real)
    (call turn-i (scale 2 (mul (use a) (use c1)))
                 (scale 2 (mul (use b) (use c2))))))
  (def phase-rhs (fn ((a Real) (b Real) (c Real)) (outputs Real Real)
    (call spin-products (use a) (use b) (copy (use c)))))
  (def even-coeff (fn ((a Real) (b Real) (w Real)) (outputs Real Real)
    (frontier (scale -3/4 (use a)) (scale -3/4 (use b)) (discard (use w)))))
)
"""
    source_path = args.out / "dynamics.adva"
    source_path.write_text(source)
    functions = ["spectrum", "turn-i", "norm", "phase-speed", "phase-rhs", "even-coeff"]
    cases, expected = [], {}

    def case(label, fn, inputs, want):
        cases.append({"id": label, "function": fn, "inputs": {k: float(v) for k, v in inputs.items()}})
        expected[label] = list(want)

    # The final time is pi/4; phases are exact, so no approximate trig input.
    states = {
        "still.initial": (F(1), F(0), F(0)),
        "moving.initial": (F(1), F(0), F(3, 2)),
        "still.final": (F(1), F(0), F(0)),
        "moving.final": (F(0), F(1), F(3, 2)),
    }
    # Columns are the global directions of local x,y,z. All are proper rotations.
    charts = {
        "z": ((F(1), F(0), F(0)), (F(0), F(1), F(0)), (F(0), F(0), F(1))),
        "x": ((F(0), F(1), F(0)), (F(0), F(0), F(1)), (F(1), F(0), F(0))),
        "diagonal": ((F(-4, 5), F(3, 5), F(0)), (F(0), F(0), F(1)), (F(3, 5), F(4, 5), F(0))),
    }
    for axis, chart in charts.items():
        check(all(ref.dot(col, col) == 1 for col in chart) and ref.cross(chart[0], chart[1]) == chart[2],
              f"proper rational observation chart: {axis}")
    for label, (aa, bb, ww) in states.items():
        cc = 2*ww/3
        case(label+":coeff", "even-coeff", {"a": aa, "b": bb, "w": ww}, [-3*aa/4, -3*bb/4])
        case(label+":shape", "norm", {"e": aa, "o": bb}, [aa*aa+bb*bb])
        case(label+":rhs", "phase-rhs", {"a": aa, "b": bb, "c": cc}, [-2*cc*bb, 2*cc*aa])
        for axis, chart in charts.items():
            winds = []
            for local in nodes:
                xx, yy, zz = global_r = tuple(sum(local[k]*chart[k][j] for k in range(3)) for j in range(3))
                global_u = ref.cross(global_r, (2*aa*xx+2*bb*yy, -2*aa*yy+2*bb*xx, -ww))
                local_u = tuple(ref.dot(col, global_u) for col in chart)
                check(ref.dot(local, local_u) == 0, f"tangent wind: {label}:{axis}:{len(winds)}")
                winds.append(local_u)
            want = ref.quadrature(nodes, winds)
            case(label+":"+axis, "spectrum", {f"u{j}{k}": val for j, u in enumerate(winds)
                                              for k, val in zip("xyz", u)}, want)
    for ww in [F(-3, 2), F(0), F(3, 2)]:
        for pp in [F(0), F(1)]:
            cc = (2*ww-pp)/3
            case(f"speed:{ww}:{pp}", "phase-speed", {"w": ww, "p": pp}, [cc])
            for aa, bb in [(F(1), F(0)), (F(3, 5), F(4, 5))]:
                case(f"rhs:{ww}:{pp}:{aa}", "phase-rhs", {"a": aa, "b": bb, "c": cc}, [-2*cc*bb, 2*cc*aa])
    check(len(functions) <= limits["functions"] and len(cases) <= limits["evaluations"], "native request inside budget")
    request_path = args.out / "request.json"
    ref.write(request_path, {"functions": functions, "cases": cases})

    def native_limits():
        resource.setrlimit(resource.RLIMIT_CPU, (limits["native_cpu_seconds"],)*2)
        resource.setrlimit(resource.RLIMIT_AS, (limits["native_address_space_mb"]*1024*1024,)*2)
        resource.setrlimit(resource.RLIMIT_FSIZE, (limits["native_evidence_mb"]*1024*1024,)*2)

    with (args.out / "native.log").open("x") as log:
        proc = subprocess.run([str(args.binary.resolve()), str(source_path.resolve()), str(request_path.resolve()),
                               str((args.out / "native.json").resolve())], stdout=log, stderr=subprocess.STDOUT,
                              timeout=limits["native_wall_seconds"], preexec_fn=native_limits)
    check(proc.returncode == 0, "native compiler and evaluator completed")
    native = json.loads((args.out / "native.json").read_text())
    observed = {}
    max_error = 0.0
    for row in native["evaluations"]:
        label, actual = row["id"], row["result"]["values"]
        want = expected[label]
        err = max(abs(v-float(q)) for v, q in zip(actual, want))
        max_error = max(max_error, err)
        check(len(actual) == len(want) and all(math.isfinite(v) for v in actual) and err <= 1e-12,
              "native agrees with rational reference: "+label)
        check(label not in observed, "unique native result: "+label)
        observed[label] = actual
    check(set(observed) == set(expected), "all requested observations returned")
    check(observed["still.initial:coeff"] == observed["moving.initial:coeff"], "initial complete even spectrum is identical")
    check(observed["still.final:coeff"] != observed["moving.final:coeff"], "future complete even spectrum differs")
    check(observed["still.initial:rhs"] != observed["moving.initial:rhs"], "hidden degree one changes the current tendency")
    check(all(observed[label+":shape"] == [1.0] for label in states), "shape target remains identical at both times")
    for axis in charts:
        check(abs(observed["still.initial:"+axis][0]-observed["moving.initial:"+axis][0]) < 1e-12,
              "native original quadrature initially hides degree one: "+axis)
    check(abs(observed["still.final:x"][0]-observed["moving.final:x"][0]) > 0.1,
          "native original quadrature distinguishes the future states")
    check(abs(observed["moving.initial:z"][1]-observed["still.initial:z"][1]) > 0.1,
          "native odd observer detects the initial hidden rotation")

    symbolic = {"streamfunction": str(psi), "relative_vorticity": str(vorticity),
                "phase_speed": str(speed), "pde_residual": str(residual),
                "wrong_speed_residual": str(s.factor(wrong_residual)),
                "spectral_power": str(power), "angular_momentum": list(map(str, momentum)),
                "kinetic_energy": str(s.expand(energy)), "even_to_odd_tendency": str(s.factor(odd_tendency)),
                "odd_tendency_at_unit_point": str(odd_tendency.subs(point))}
    ref.write(args.out / "symbolic.json", symbolic)
    evidence = {
        "status": "ExactModelAndNativeTargetDependentLossChecked", "machine_revision": machine_revision,
        "sympy_version": s.__version__, "checks": checks, "check_count": len(checks),
        "native_evaluations": len(cases), "max_float_error": max_error,
        "witness": {"time": "pi/4 dimensionless", "planet_rotation": 0,
                    "continuous_fixed_x_spectrum": {"still.initial": "-3/4", "moving.initial": "-3/4", "still.final": "-3/4", "moving.final": "0"},
                    "continuous_shape_power": "3/20 for all four states", "states": states,
                    "native_finite_quadrature": {label: value for label, value in observed.items()
                                                 if label.rsplit(":", 1)[-1] in charts}},
        "symbolic": symbolic, "elapsed_seconds": time.monotonic()-started,
        "hashes": {"checker": ref.digest(Path(__file__)), "contract": ref.digest(HERE / "contract.json"),
                   "previous_checker": ref.digest(PREVIOUS / "check.py"), "driver": ref.digest(PREVIOUS / "src/main.rs"),
                   "binary": ref.digest(args.binary), "source": ref.digest(source_path),
                   "native": ref.digest(args.out / "native.json"), "request": ref.digest(request_path)},
        "residuals": contract["residuals"],
    }
    ref.write(args.out / "evidence.json", evidence)
    signal.alarm(0)
    print(json.dumps({key: evidence[key] for key in ["status", "check_count", "native_evaluations", "max_float_error", "symbolic", "witness"]}, indent=2, default=str))


if __name__ == "__main__":
    main()
