# A paired spherical spectrum executed by the native Adva kernel

Date: 2026-09-24. Author: Codex (OpenAI). User-directed local experiment.

The user proposed that the frame's `i` might help compute odd-degree responses,
then asked to express the sphaera spectrum using Adva's native frame machinery.
This experiment gives that proposal a finite executable interpretation.

**Result:** the existing Rust compiler and evaluator compute the two-channel
spectrum, explicit copying, complex turn and coordinate transport. The new
channel distinguishes degree-one and degree-three rotation probes that the
original channel cannot distinguish from zero. Multiplying the original output
by `i` after projection does not recover either probe.

## What is native

The generated [Adva program](runs/run-001/spectrum.adva) is parsed, linked,
compiled, serialized, imported through validation, and evaluated by the actual
`adva-lisp` crate at machine commit
`3043be35ff1186d502d091baa8bb96581449595c`.
The spectrum compilation contains **48 compiler-generated GraftFrames**.
Their identities, ordered holes, call history, explicit copy occurrences and
compilation/graft/import certificates are retained in
[native.json](runs/run-001/native.json).

The machine's `spec/framework/iota-frame-v1.md` explicitly does not introduce a
general native complex `Frame` type. This experiment therefore uses native
`Real` output ports and native `GraftFrame` provenance, with a separately bound
[interpretation frame](runs/run-001/frame.json). It does not relabel a Python
object as a native frame. The old profile's iota process, cut-graph Laplacian,
exponential and physical-clock interpretations are not imported by analogy.

Python supplies a finite source program and rational input data. It does not
allocate native semantic identities or evaluate the Adva program. Its independent
`Fraction` quadrature is an external numerical reference, not a native certificate.
Both paths share the experiment's author and mathematical formulation.

## The two observations

For an oriented unit axis `a`, unit position `r`, and Cartesian tangent wind `u`:

\[
E(a)=\langle\operatorname{sgn}(a\cdot r)(a\times r),u\rangle,
\qquad
O(a)=\langle|a\cdot r|(a\times r),u\rangle.
\]

The brackets mean the same normalized quadrature in both channels.
`E` retains the original idealized sphaera kernel. `O` is an explicitly **new
observer**, applied to the wind before information is discarded. We interpret
the ordered pair as `C=E+iO` and use

\[
J(E,O)=(-O,E),\quad J^2=-I.
\]

The actual native definition is:

```lisp
(def turn-i
  (fn ((e Real) (o Real)) (outputs Real Real)
    (frontier (neg (use o)) (id (use e)))))
```

The compiler retains two sources; equality of numerical values never merges
them. Each sample's scalar wind projection is explicitly copied before its
two distinct weighting operations.

## Finite geometry and measured results

There are 16 rational unit vectors: four cardinal azimuths on each of the
latitude rings `z=3/5,-3/5,4/5,-4/5`. Each has weight `1/16`; the axis is `e_z`.
Native arithmetic computes `(-r_y)u_x+r_x u_y` and both weighted sums.
The unused radial-coordinate input component is explicitly discarded with its
history retained. Signs and absolute values are fixed geometry coefficients in
this finite program; no general native sign or spherical-integration builtin
was added.

| Synthetic field | Original E | Added O |
| --- | ---: | ---: |
| Zero | 0 | 0 |
| Rigid rotation `e_z × r` (degree 1) | 0 | 42/125 = 0.336 |
| `grad_S z` | 0 | 0 |
| `r × grad_S P₂(z)` | −126/125 = −1.008 | 0 |
| `r × grad_S P₃(z)` | 0 | −441/625 = −0.7056 |
| Rigid rotation plus degree 2 | −126/125 | 42/125 |

These are **finite quadrature values**, not exact whole-sphere integrals.
For comparison, the ideal continuous values for the three rotation probes
are respectively `(0,1/4)`, `(-3/4,0)`, and `(0,-1/4)`.
The 16-point rule is chosen to provide small exact parity witnesses, not a
converged spherical transform or an independent degree-by-degree inversion.

The [evidence](runs/run-001/evidence.json) records **456 passed checks**,
**283 native evaluations**, maximum absolute disagreement with the rational
reference of **5.551115123125783e-17**, and the original/native source hashes.
Native evaluation uses `f64`. Structural certificates do not certify floating
point exactness or the correctness of the meteorological interpretation.

## Controls that distinguish the hypothesis

1. **Applying i too late fails.** Zero and rigid rotation both produce old
   spectrum zero. The native `old-then-i` function returns `(0,0)` for both.
   The paired observation separates them only because it reads another part of
   the original wind field.
2. **A nonorthogonal chart needs a transported observer and metric.** For
   `T(E,O)=(E+O,O)`, `(1,1)` becomes `(2,1)`. The transported observer recovers
   `(1,1)`, and the transported metric gives squared norm 2. The stale observer
   reads `(2,1)` and the stale Euclidean metric gives 5. Both failures are
   explicitly retained as controls.
3. **Parity and i are different operations.** Axis reversal acts as
   `P(E,O)=(E,-O)`, and the native programs verify `PJ=-JP` on the declared
   25-input grid. `i` is not itself an odd-degree projector.
4. **The native boundary refuses malformed use.** The Rust compiler rejects
   an input used twice without explicit copy; finite evaluation rejects NaN.

The transported matrices are

\[
J'=TJT^{-1}=\begin{pmatrix}1&-2\\1&-1\end{pmatrix},\quad
G'=T^{-T}T^{-1}=\begin{pmatrix}1&-1\\-1&2\end{pmatrix},\quad
O'=T^{-1}=\begin{pmatrix}1&-1\\0&1\end{pmatrix}.
\]

The parity relation also exposes a further boundary: a full signature satisfies
`C(-a)=conj(C(a))`. Uniform multiplication by `i` does not preserve this reality
condition. The pair at one declared axis carries `J`; we do not infer that the
constrained space of physical signatures has a globally parity-preserving
complex structure. A chart/observer change and a physical operation on the
wind remain different questions.

## Why the added channel sees odd degrees

On the ideal unit sphere, integration by parts makes `E` a vorticity convolution
with `|a·r|`; `O` is a vorticity convolution with
`(a·r)|a·r|/2`. The first scalar kernel is even, the second odd.
For a vorticity spherical harmonic of degree `l`, the multipliers are

\[
\beta_l=\tfrac12\int_{-1}^{1}|x|P_l(x)\,dx,\qquad
\gamma_l=\tfrac14\int_{-1}^{1}x|x|P_l(x)\,dx.
\]

`β_l=0` for odd `l`, whereas `γ_l=0` for even `l`.
For even `l`, `β_l=P_l(0)/(2-l(l+1))`.
For odd `l`,

\[
\gamma_l=\frac{\int_0^1P_l(x)\,dx}{6-l(l+1)}.
\]

These identities follow by applying the Legendre differential operator to
`|x|` and `x|x|/2`, including the weak derivative at zero, then integrating
against `P_l`. The numerators are nonzero in their stated parity classes;
the denominators have no zero in those classes. Thus in the ideal continuous
full-axis setting the pair retains every nonconstant vorticity harmonic.
This is a written derivation, not a native proof, a discrete rank test at all
degrees, or a claim of stable inversion under noise. Both channels remain
blind to the gradient component of the wind.

## Reproduce

The sibling checkout `../../../adva-machine` must be at the pinned revision.

```sh
cd experiments/sphaera-frame
timeout 300s cargo build --offline --locked
python3 check.py --out runs/run-002
```

The output directory must be fresh. `contract.json` fixes one finite run,
16 native functions maximum, 512 evaluations maximum, a 45-second native wall
limit, 40 CPU seconds, 2 GiB address space and 16 MiB native evidence.
The checker has a 90-second wall limit and 2,000-assertion cap. No automatic
continuation or fuel reset is performed. The initial build completed in
23.58 seconds; `build-001.log` retains its actual output.

## What this contributes to the seasonal prediction study

The observer has become more discriminating in a precisely demonstrated way:
two declared odd-degree wind fields that were invisible now produce nonzero
native outputs. That is the bounded learning step. It does not establish
slow atmospheric dynamics, predictive state closure, seasonal skill, or a
physical interpretation of the frame's imaginary unit.

The next question is whether the added channel carries information about a
specified future monthly/seasonal target after conditioning on the original
channel, season and slow-variable baselines. The old and new observers should
remain available as an ablation pair for that comparison.
