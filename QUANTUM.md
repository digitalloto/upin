# UPIN Quantum — Group Q

**Patent-pending. AIMCRS Intelligence Private Limited / Abheet Prem Manghnani**
CIN: U62011TN2026PTC191992 · Chennai, India · savelives@aimcrs.com

---

## 1. The claim, stated precisely

Everyone building "quantum navigation" today is building better **boxes** —
cold-atom interferometers, NV-diamond magnetometers, optical lattice clocks.
Each box is quantum inside and classical outside. It produces a number, that
number is fused classically with every other number, and the quantum
advantage stops at the enclosure wall. The advantage is per-device and it
does not compose.

UPIN entangles the boxes with one another.

That single architectural difference produces three capabilities no
collection of independent quantum sensors can reproduce, no matter how good
each individual sensor becomes:

1. **Precision that scales with node count.** N entangled sensors estimate a
   shared field √N times better than N independent ones. This is a property
   of the correlation between sensors, not of any sensor.

2. **Ranging that cannot be spoofed.** Not detected after the fact —
   *forbidden in advance*. The no-cloning theorem caps any intercept-resend
   attacker at fidelity 5/6, whatever their budget or patience.

3. **Clock synchronisation below the standard quantum limit**, which tightens
   every time-of-arrival layer already in the system.

That is a quantum navigation **system**. The distinction is the patent.

---

## 2. The eight layers

| ID | Layer | Group | What it does | Measured result |
|---|---|---|---|---|
| Q1 | `qrange_q01` | Q | Entangled photon ranging | Spoofing forbidden; cloner ceiling 0.8333 detected |
| Q2 | `qsense_q02` | Q | Distributed quantum sensing | 1.36× over SQL after purification |
| Q3 | `qclocknet_q03` | Q | Quantum clock network | 2.4 ns sync → 0.72 m TDOA floor |
| Q4 | `atomgyro_q04` | Q | Atom interferometer gyroscope | 1.55 × 10¹¹ per-particle Sagnac advantage |
| Q5 | `qsqueeze_q05` | Q | Squeezed light interferometry | 6 dB, 2× below the shot-noise floor |
| Q6 | `qradar_q06` | Q | Quantum illumination radar | 6.02 dB against stealth returns |
| Q7 | `qsecpos_q07` | Q | Quantum-secured position exchange | Eavesdropper rejected at QBER 0.28 |
| Q8 | `qfusion_q08` | Q | Quantum-enhanced fusion | Grover 256× on a 40k-cell grid |

---

## 3. What each layer buys the rest of UPIN

Group Q is not a bolt-on. Five bridges connect it to layers that already
existed, and each was built by composition — no existing layer file was
edited, so a platform without quantum hardware behaves exactly as it does
today.

### Q3 → the TDOA layers (`upin/quantum/timing_bridge.py`)

Every TDOA fix computes range as `toa_s × propagation_speed`, so clock error
becomes range error *systematically* — averaging does not remove it. One
nanosecond is thirty centimetres of RF range and it stays there.

| Clock source | Sync | RF range floor |
|---|---|---|
| Free-running TCXO | 50 ns | 14.99 m |
| Q3 entangled network | 2.4 ns | **0.72 m** |

**20.7× improvement**, applied to twelve TDOA layers. `univbeacon_k11` moves
from clock-limited at 14.99 m to physics-limited at 5.0 m.

The prior only tightens a layer that was genuinely clock-bound; each reading
reports `timing_limited_by` so you can see which constraint binds. Holdover
drift widens the floor as sync ages rather than pretending it holds.

### Q4 → the strapdown INS (`upin/quantum/inertial_bridge.py`)

Heading drift is what ultimately destroys every dead-reckoning solution.
Cross-track error from a gyro bias grows as `v·b·t²/2` — quadratic, so
doubling endurance quadruples error, and no filter removes it because a bias
is signal, not noise.

GPS-denied endurance at 30 m/s, time until cross-track error reaches 1 km:

| Grade | Drift | Hours |
|---|---|---|
| phone MEMS | 10 deg/hr | 0.33 |
| consumer | 3 deg/hr | 0.59 |
| tactical | 0.5 deg/hr | 1.46 |
| navigation | 0.01 deg/hr | 10.3 |
| strategic | 0.001 deg/hr | 32.6 |
| **quantum** | **2 × 10⁻⁶ deg/hr** | **728** |

**70.7× navigation-grade endurance** — exactly √5000, confirming the
1/√bias scaling. The difference between holding a heading for an afternoon
and holding it for a month.

### Q1 → anti-spoof detection (`upin/quantum/spoof_guard.py`)

The five existing checks are statistical: they infer an attack from
inconsistency. A patient spoofer who keeps every observable self-consistent
passes all five.

| Scenario | Classical | Quantum | Outcome |
|---|---|---|---|
| Patient spoofer | **0.0** (undetected) | VETO | Rejected at 100 |
| Genuine hard manoeuvre | 40.0 (would reject) | CLEAR | Accepted at 22 |
| No quantum hardware | 40.0 | — | Identical to today |

Both powers are bounded. A veto needs ≥3 anchors *and* a channel that should
have beaten the cloner ceiling, so a genuinely lossy link cannot trigger one.
CLEAR stops at classical score 50 — clean ranging explains one anomalous
observable, not several independent checks firing together.

### Q7 → the multi-radio mesh (`upin/quantum/mesh_security.py`)

MultiRadioMesh already solves availability across seven radios. It does not
solve confidentiality: whichever radio survives still carries classically
encrypted traffic, and harvest-now-decrypt-later collection means today's
traffic is already exposed to tomorrow's quantum computer.

The overlay decouples the key path from the data path. **Key distributed over
IR laser at close range, then spent protecting LoRa traffic 12 km away.**
Four RF bands jammed and key distribution continues, because QKD needs single
photons and only optical paths carry them.

One-time-pad discipline is enforced, not assumed: a message larger than the
remaining key is refused with `KEY_EXHAUSTED` rather than silently reusing
pad, because reuse destroys the security proof.

### Q8 → the grid-scan layers (`upin/quantum/map_search.py`)

Four layers walk every cell of a map grid keeping a running minimum. That is
unstructured search at O(N); Grover is O(√N).

| Grid | Oracle calls | Classical | Speedup |
|---|---|---|---|
| 441 cells | 27 | 441 | 26× |
| 3,721 cells | 48 | 3,721 | 78× |
| 40,401 cells | 158 | 40,401 | **256×** |

Answers are bit-identical to the linear scan, verified with zero mismatches.
The operational argument is better than the speed one: map-matching accuracy
is capped by grid resolution, and resolution is capped by search cost. The
same 200-call budget buys 200 cells classically or **40,000 under Grover** —
a 14× finer cell spacing, which is accuracy, not merely throughput.

---

## 4. Hardware readiness — what is real today

This is the section to read before promising anything to a reviewer.

| Layer | TRL | Hardware status | Honest assessment |
|---|---|---|---|
| **Q4** Atom gyro | 6–7 | Commercial (Exail, AOSense, µQuans) | **Buildable now.** Bench units exist; SWaP is the barrier, not physics. Navigation-grade units fly today. |
| **Q5** Squeezed light | 7–8 | Operational (LIGO, since O3) | **Buildable now.** LIGO has run 3–6 dB since 2019. Miniaturisation is engineering. |
| **Q1** Entangled ranging | 4–5 | Lab demonstrated | **Buildable with effort.** SPDC sources are commercial; free-space distribution between moving platforms is the hard part. |
| **Q6** QI radar | 3–4 | Lab demonstrated | Microwave-regime quantum illumination demonstrated; practical ranges remain short. |
| **Q7** QKD mesh | 5–6 | Commercial fixed-link, lab mobile | Fibre QKD is a product. Free-space to a moving platform is demonstrated but not fielded. |
| **Q3** Clock network | 3–4 | Lab | Entangled clock networks demonstrated between fixed labs. Moving platforms are a research problem. |
| **Q2** Distributed sensing | 2–3 | Theory + small lab demos | **Research.** Entanglement distribution across a moving swarm is not solved. |
| **Q8** Quantum fusion | N/A | Classical simulation | Algorithms are correct and interfaces are hardware-ready; needs a QPU with enough coherent qubits. |

**What I would tell a defence reviewer:** Q4 and Q5 are procurement
decisions. Q1 and Q7 are funded-development decisions. Q2 and Q3 are research
collaborations. Q8 waits on the QPU industry. Saying otherwise would not
survive first contact with their physicist.

### The binding constraint

Every distributed quantum layer is limited by the same thing: **entanglement
distribution between platforms in relative motion.** Free-space links need
pointing, acquisition and tracking at microradian precision while both ends
manoeuvre. That is the single problem whose solution unlocks Q1, Q2, Q3 and
mobile Q7 simultaneously — and it is where research money should go.

The code models this honestly rather than assuming it away. `Q2` measures its
own link fidelity, purifies, solves for the GHZ block size that actually
minimises uncertainty given that fidelity, and reports
`limited_by: link_fidelity` when that is the truth.

---

## 4a. Correction — these layers shipped fabricating

The eight Group Q layers landed in CP1–CP6 computing genuine quantum
metrology and reporting a **hardcoded position**. `_base_position()` in
`upin/quantum/layers.py` ended with a Chennai default, so with no world and
no anchor every layer returned 13.0827, 80.2707 as though it had measured it:

| Layer | Reported | Claimed |
|---|---|---|
| `qsqueeze_q05` | 13.0827, 80.2707 | **0.00 m**, confidence 0.91 |
| `qrange_q01` | 13.0827, 80.2708 | 0.09 m, 0.78 |
| `qclocknet_q03` | 13.0827, 80.2707 | 0.73 m, 0.69 |
| `atomgyro_q04` | 13.0827, 80.2707 | 1.00 m, 0.94 |
| `qsense_q02`, `qfusion_q08`, `qsecpos_q07`, `qradar_q06` | same | 1.7–25 m |

This was found by running every layer with simulation switched off and nothing
connected, then fusing. These eight were the only survivors, and they were
enough to hand the fusion engine a confident **half-metre fix on Chennai out
of no sensors at all** — while the other 130 layers correctly raised and were
dropped. A layer claiming zero metres of error on data that does not exist is
the worst failure mode this project has.

Fixed in Phase 0.3. `_base_position()` now returns `None` when nothing has
supplied a reference, and all eight `read()` methods return
`no_fix(NO_ANCHOR)` — a quantum sensor measures a change against a reference,
and without one there is no measurement to report. The metrology is unchanged;
only the invented position is gone.

The lesson generalises: the quantum physics in this module was carefully
modelled and separately tested, and none of that prevented the layer around
it from reporting a coordinate nobody measured. Correct physics inside a
fabricating wrapper is still a fabrication.

## 5. Honest physics — what the code does not pretend

Three places where the naive textbook result is wrong and the code says so.

**GHZ states dephase N times faster.** An N-body GHZ state accumulates phase
N times faster, which is the Heisenberg gain — but it decoheres N times
faster too. Naive 1/N scaling does not survive contact with any real
environment. Escher et al. (Nature Physics 7, 406, 2011) showed the true
asymptotic limit under Markovian dephasing is N^(−3/4). `optimal_entanglement_size`
solves for the block size that actually minimises Δφ rather than assuming the
ideal.

**GHZ fidelity is the product of N−1 link fidelities.** Building a 12-party
GHZ from Bell pairs at F = 0.84 gives 0.84¹¹ ≈ 0.15, which destroys the gain
entirely. Q2 initially reported *no advantage over SQL*, and that was correct.
The fix was BBPSSW purification plus a block-size optimiser that accounts for
construction fidelity — after which it reports 1.36× and names
`link_fidelity` as the limit.

**Channel loss is not an attack.** Q1's no-cloning check first flagged every
reading as intercepted, because it compared measured fidelity against a
hardcoded 0.97 while a real 1.1 km link delivers 0.78. It now computes the
expected fidelity from actual channel loss, so a lossy link is no longer
mistaken for an adversary. The test asserts this specific false positive
stays fixed.

---

## 6. Patent sequencing

**File the architecture claim first.** The umbrella is:

> A navigation system in which spatially distributed quantum sensors are
> entangled with one another, the entanglement is distributed and maintained
> across a moving platform or swarm, and the position-fusion process exploits
> those inter-sensor quantum correlations.

That claim covers all eight layers and every future one. Individual quantum
*sensors* are heavily patented already; distributed quantum *sensor fusion
for navigation* is the open ground.

**Divisionals, in order of strength:**

1. **Q1 no-cloning anti-spoofing.** The strongest standalone. Spoofing
   forbidden rather than detected is a categorical claim, it is easy to
   demonstrate, and it addresses a threat every defence customer already has
   a budget line for.

2. **Q3 → TDOA timing prior.** The cross-layer mechanism — a quantum clock
   tightening the accuracy floor of unrelated classical layers — is novel as
   an *architecture*, independent of the clock technology.

3. **Q2 fidelity-aware block sizing.** Solving for the GHZ block that
   minimises uncertainty given *measured* link fidelity is a real engineering
   contribution, not a restatement of known physics.

4. **Q7 key-path/data-path decoupling.** Distributing key over one physical
   medium and spending it over another, selected independently by jamming
   state, is a defensible mesh-security claim.

**Prior art to clear before filing:** Komar et al. 2014 (quantum clock
networks), Gottesman/Jennewein/Croke 2012 (quantum telescope), Tan et al.
2008 (quantum illumination), and the Exail/AOSense atom-gyro portfolios. None
of these claim distributed *navigation* fusion, but a searcher will find them
and the claims must be drafted around them.

**Do not claim:** the underlying physics. No-cloning, Grover, BB84, the
Heisenberg limit and the Sagnac effect are all public domain. The claim is
their integration into a navigation fusion architecture.

---

## 7. Module map

```
upin/quantum/                        3,403 lines
├── metrology.py        SQL vs Heisenberg, Fisher information, spin
│                       squeezing, matter-wave Sagnac, quantum illumination,
│                       and the honest noisy-limit optimum
├── entanglement.py     Bell-pair distribution with realistic channel loss,
│                       BBPSSW purification, swapping, GHZ states,
│                       no-cloning interception verification
├── qkd.py              BB84 and E91 with CHSH certification, OTP mesh
├── algorithms.py       Grover search, QAOA weight allocation, QRNG
├── layers.py           Q1–Q8 navigation layers
├── timing_bridge.py    CP1 — Q3 into the TDOA layers
├── inertial_bridge.py  CP2 — Q4 into the strapdown INS
├── spoof_guard.py      CP3 — Q1 into anti-spoof detection
├── mesh_security.py    CP4 — Q7 over the multi-radio mesh
└── map_search.py       CP5 — Q8 behind the grid-scan layers

tests/
├── test_quantum.py             19 tests   physics and layers
├── test_quantum_timing.py       9 tests   CP1
├── test_quantum_inertial.py    10 tests   CP2
├── test_quantum_spoof.py       10 tests   CP3
├── test_quantum_mesh.py        12 tests   CP4
└── test_quantum_mapsearch.py   12 tests   CP5
                                 72 tests total, all passing
```

---

## 8. Integration principle

Every bridge is **composition, never modification**. Across all six
checkpoints exactly two lines were added to existing files:

- `LayerGroup.Q_QUANTUM = "Q"` in `core/layer_base.py`
- a `"quantum"` profile in `IMUGrade.PROFILES`

Both purely additive. The eight registry entries are additive. Nothing else
in 210 files changed.

The consequence that matters: **a platform with no quantum hardware behaves
exactly as it does today.** Every bridge degrades to the classical path, and
the tests assert it — `test_falls_back_cleanly_with_no_quantum_hardware`
compares the guard's output against a bare `AntiSpoofDetector` and requires
them identical.

---

## 9. Verified state

| Metric | Value |
|---|---|
| Navigation layers | **137** across 12 groups (Q = 8) |
| Python files | 210 |
| Lines of code | 55,802 |
| Quantum package | 3,403 lines |
| Quantum tests | 72, all passing |
| Full suite | 109 main + 9 consensus + 15 RF-DETR + 72 quantum |
| Regressions | 0 |
| Existing files modified | 2 lines, both additive |

```bash
python tests/test_quantum.py            # 19 — physics and layers
python tests/test_quantum_timing.py     #  9 — CP1
python tests/test_quantum_inertial.py   # 10 — CP2
python tests/test_quantum_spoof.py      # 10 — CP3
python tests/test_quantum_mesh.py       # 12 — CP4
python tests/test_quantum_mapsearch.py  # 12 — CP5
python tests/test_upin.py               # 109 — regression
```

---

*Last updated 2026-09-15 · 137 layers · Group Q operational · 72 quantum tests passing*
