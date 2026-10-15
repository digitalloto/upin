# Formation cross-check and cooperative fix (layer 153): three drones confirming each other

Two or more drones fly together, each with the UPIN box and a ranging
radio. Every second each drone broadcasts, signed, **where its receiver
says it is**, how sure it is, whether it trusts that fix and where the fix
came from, and the ranges it has measured to the others. The ranging radio
measures the **real** distance between the drones, on a band GNSS attacks
do not touch. The layer compares the distances the receivers *imply* with
the distances the radio *measures*. That one comparison gives two things
no single drone can have.

> **Status: simulation only.** The layer, the check, the fix and the
> message format are tested in simulation through the real box. The radio
> firmware (slot timing, two-way ranging, relaying the messages) is not
> written. Every threshold is an assumption until the real radio's ranging
> sigma is measured.

## 1. A spoof check one receiver cannot do

A single spoofer, whether it generates fake satellite signals or records
and replays real ones, sends **one** set of signals to every receiver in
range. The extra path delay from the spoofer to a given receiver is the
same for all of that receiver's satellites, so it lands in the receiver's
clock bias, not in its position. Every receiver therefore solves to the
**same** fake position.

Three drones 40 to 80 m apart then all report one place. The reported
pairwise distances collapse towards zero while the measured ranges still
show the formation intact. Each receiver, looked at alone, is healthy: a
3-D fix, a stated accuracy, consistent velocity, and with a careful
spoofer, satellite powers shaped like a real sky. The formation sees it at
once.

A stealth drag-off is also harder for the spoofer: to take over a receiver
without a jump it must align its signal with the real one at that
receiver's position. With three receivers in three places it can align
with only one; the other two see a jump.

### The check, pair by pair

For each pair of drones with a fresh message and a fresh range:

    z = (reported distance − measured range) / sqrt(σ_i² + σ_j² + σ_range²)

A pair is inconsistent at |z| > 3 (an **assumption**, to be set from the
real radio's ranging sigma). A peer's reported position is moved to the
epoch time with its reported velocity, its sigma widened by an assumed 1
m/s of velocity error for the skew. Each drone also broadcasts the ranges
it measured to the others, so every drone sees every pair of a three-drone
formation.

| Pattern | Verdict | What it means |
|---|---|---|
| every pair consistent | PASS | the receivers agree with the geometry the radio measures |
| every reported distance under half its measured range, two or more pairs inconsistent | **FAIL, common spoof suspected** | everyone reports the same place: the single-spoofer signature |
| every pair inconsistent, distances not collapsed | FAIL | something is wrong everywhere; the pattern is not the single-spoofer one |
| both pairs of one drone inconsistent, the remaining pair consistent | that drone is the **odd one out**: FAIL if it is me, PASS naming the peer as suspect otherwise | one receiver is wrong; a suspect peer is never used to place anyone |
| exactly one pair inconsistent | WARN | one of two receivers is wrong, or both are spoofed; one pair cannot say which |
| mixed | WARN | the pattern is unclear; reported as such |
| no peer heard, no fresh range, or no fix of my own | NOT RUN, with the reason | |

The verdict reaches the gateway as the check **formation consistency**.
By default (`formation_check_action = "warn"`) a FAIL is shown as a
warning and does not change trust in GNSS, as with the signal-power
check, because the ranging sigma the test relies on has not been measured
on a real radio. Set `"distrust"` once it has. The console's simulation
uses `"distrust"` because the simulator's ranging sigma is known.

## 2. A fix for the drone that lost GNSS

When my own fix is not trusted (jammed, faulted or distrusted by the
checks) and two peers still hold **trusted own-GNSS** fixes, my two
ranges and my barometric altitude put me on two circles that cross at two
points: mirror images across the line between the peers. My own
dead-reckoning estimate, with its honest sigma, decides:

- the rejected mirror image must be more than 3 sigmas (an **assumption**)
  of the prior away, and the chosen one within it; otherwise the layer
  declines with "mirror ambiguous" or "neither candidate agrees with the
  prior";
- a drone on or near the line between its peers cannot be fixed by them
  (the two circles meet at a grazing angle): declined on geometry;
- one trusted peer can detect a spoof but cannot place me: declined;
- three or more trusted peers go through layer 151's weighted solver.

An accepted fix goes through the filter's gate like every other, and
re-anchors the reachable region and the accuracy floor, as a tag or beacon
fix does. Its sigma carries the peers' own position sigmas and the ranging
sigma, so it is honest about being coarser than GNSS.

### No circular confirmation

A peer is an anchor **only if its message says its fix is trusted and
came from its own GNSS**. A drone broadcasting a formation fix, or a
coasting estimate, says so (`source: "upin"`, `trusted: false`) and is
never an anchor. Three drones anchoring on each other would drift together
while agreeing perfectly; the rule forbids it and a test asserts it. The
trust flag and the source are inside the signature.

## 3. Measured in simulation

A V of three on a circuit with 60 to 80 m turns: the lead at the apex, two
wingmen 40 m back and ±40 m aside, each with its own receiver (1.5 m,
Gauss–Markov), 10 m ranging sigma (the beacon simulation's assumed
LoRa-class figure).

| Scenario | Result |
|---|---|
| Honest formation, 300 s, every drone checking every second | no FAIL; 12 of 2,691 pair tests over 3 sigma (0.45%, where pure noise gives 0.27%), each a single-pair WARN |
| One spoofer: every receiver reports one place 300 m off | all three drones FAIL "common spoof" on every epoch; reported distances about 2 m against ranges about 65 m; each receiver alone had a 3-D fix with a stated 1.5 m |
| One wingman's receiver 60 m off | the lead PASSES naming it suspect (33 of 35 epochs); the wingman's own check FAILS (33 of 35); with it excluded one anchor is left and the fix declines |
| Lead without GNSS, two trusted wingmen, prior ±5 m | 117 fixes in 119 s, 12 m rms with a stated 11 m, 95% circle covers 100%, HDOP 1.4; mirror 71 m away |
| Lead on the wingmen's baseline | declined on geometry 17 of 19 epochs |
| Lead at the apex, prior ±100 m | declined, "mirror ambiguous"; with ±5 m the right side is chosen, 5 m error; a prior 500 m off is refused |
| Four drones, lead without GNSS | three anchors through layer 151's solver: 59 fixes, 11 m rms, stated ±10 m |
| Through the box: receiver silent for 50 s, formation on | 43 formation fixes accepted and re-anchoring; output error 12 m mean, 25 m worst; the box's own 100 messages all verify, the trust flag following the mode |
| **Stated limit**: a tailored spoofer shifting all three by the same 144 m | the check PASSES on every epoch |

`python tests/test_formation.py` reproduces every row.

## 4. What it needs

- **The box on every drone**, with `formation = true`, a `drone_id`, the
  shared `beacon_secret_file`, and the same `beacon_radio` as layer 151.
- **A ranging radio on every drone**: 2.4 GHz LoRa-class with ranging
  (SX1280 family) or UWB for short range. Firmware to write: one message
  per drone per one-second slot on the hop schedule, two-way ranging to
  each peer, JSON lines to the box in the beacon radio's format with ids
  `drone-<id>`. Airtime: three messages and three ranging exchanges a
  second fit comfortably in a one-second slot.
- **A formation with a baseline**: a V or a triangle, never a line. The
  drone to be placed must be off the line between its two peers; 40 m
  back and ±40 m aside worked in simulation with 10 m ranging. Wider
  spacing makes the check sharper and the fix better until the radio's
  range limit.
- **Legal band and power**: the operator's responsibility, as for layer
  151 (see `docs/BEACONS.md`).

## 5. Limits, stated

- **A tailored spoofer passes.** Several directional transmitters, each
  aimed at one drone with a lie that preserves the formation's geometry,
  keep the reported distances equal to the measured ranges. Tested and
  shown. Catching it needs something else (the signal-power check, the
  reachable region, tags, beacons).
- **A wide-area jammer takes the formation down together.** No peer has a
  trusted fix, so there is no anchor. The ranges still keep the drones'
  relative geometry honest, but cannot place the formation.
- **The prior decides the mirror.** If the filter's estimate is wrong by
  more than its own sigma says, the wrong side can be chosen. The filter's
  sigma is honest by construction; this is why the gate asks for 3 sigmas.
- **Range of the radio** and line of sight apply as for layer 151.
- **A suspect flagged while I still had a fix stays flagged** until a
  later check with a fix clears it; without a fix of my own I cannot
  re-judge the peers.
- **Nothing is flight-proven.** Simulation only until the radios exist.

## Files

| | |
|---|---|
| `upin/layers/rf/formation.py` | the layer: message signing, the check, the two-range fix, the hand-off to layer 151 |
| `upin/simulation/formation.py` | simulated drones in formation, single and tailored spoofers, ranging noise |
| `upin/box/service.py`, `upin/box/gateway.py` | `formation`, `drone_id`, `formation_check_action`; the "formation consistency" check; `step_formation` |
| `upin/console/` | two simulated wingmen; controls: formation on/off, the lead's receiver fails, tailored spoofer |
| `tests/test_formation.py` | every figure above |
