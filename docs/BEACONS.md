# Known-position beacons (layer 151): the balloon idea, made honest

The user's idea: weather balloons carrying beacons on a band GNSS jammers
do not touch, hopping frequency, several at once, expendable. This layer
is that idea built so it can be trusted: a beacon counts only if it knows
where it is, signs what it says, hops on the shared schedule, and states
how well it knows its own position. The drone measures its range to each
beacon and solves its position.

> **Status: simulation only.** Beacons and balloons are simulated
> (`upin/simulation/beacons.py`). No radio, no beacon firmware, no balloon
> has been built. The serial reader is untested. Every figure below is a
> model or an assumption, labelled.

## What is sound about the idea

- **A different band escapes GNSS jammers.** The common jammers are built
  for GNSS frequencies; a beacon on another band is simply not in their
  way.
- **Kilometres instead of 20,000 km.** A beacon's signal arrives thousands
  of times stronger than a satellite's, so it is far harder to drown.
- **Height gives coverage.** A balloon at 20–30 km sees a huge area, and a
  ground jammer must radiate upward over all of it to reach it.
- **Prior art exists**, which means the physics is settled: balloon-borne
  pseudolite constellations have been designed in the literature (an MDPI
  *Electronics* paper, 2024), armies field ground pseudolites, and
  stratospheric-platform pseudolites were studied in 2004. Any patent
  wording around this must be careful.

## What has to be true for it to work

1. **Each beacon must know its own position.** A beacon that does not know
   where it is cannot tell the drone where it is. Balloons drift tens to
   hundreds of kilometres. Either the balloon carries its own GNSS
   receiver (at 20–30 km it is probably above a ground jammer's reach:
   probably, not certainly), or two surveyed ground sites track it by
   direction finding, as radiosondes were tracked before GPS. Either way
   the beacon broadcasts its position **with its sigma**, and the layer
   carries that sigma into the fix instead of hiding it. A beacon that
   knows itself to 500 m widens the fix accordingly; the test asserts it.
2. **Hopping stays inside a permitted band.** "No satellite uses it" does
   not make a band free; nearly all spectrum is allocated. For tests,
   India's delicensed bands most consistently reported are 865–867 MHz
   (1 W, 4 W ERP, 200 kHz) and 2.4 GHz; 5.8 GHz is unclear. These must be
   checked against WPC's gazette notifications, and an airborne transmitter
   may need separate clearance **[TO CONFIRM with WPC/DGCA]**.
3. **A different band stops GNSS jammers, not all jammers.** A determined
   adversary can barrage-jam the beacon band or find and shoot the
   balloons. Hopping on a secret schedule makes them jam the whole band,
   and signing every message stops replay and fakes. The simulation shows
   both: a GNSS jammer leaves the beacon fix intact; a wideband jammer
   silences it, and the layer says so.
4. **How the drone measures range sets the accuracy.** Two-way ranging
   (the drone pings, the beacon replies) needs no synchronised clocks and
   is the baseline: tens of metres with LoRa-class radios, centimetres
   with UWB at short range. One-way timing like GPS needs synchronised
   beacon clocks and is a later option.

**Timing:** a latex balloon climbs at about 5 m/s, bursts at 20–35 km and
gives 1.5–2 hours aloft, landing tens to hundreds of kilometres downwind.
Launches are staggered and sited upwind; the mission window is planned
around them.

## What a beacon sends, and what the drone checks

Every slot: `id, time, lat, lon, alt, position sigma, sequence, channel,
signature`. Before a message counts, the layer checks the HMAC-SHA256
signature with the shared secret, that the channel is the one the secret
schedule gives for that time slot (one slot of clock error tolerated),
that the sequence is newer than the last from that beacon (no replay), and
that the message is fresh. Refused messages are counted and shown, never
used.

## The solve

Weighted least squares on the ranges in a local east-north-up frame, by
Gauss–Newton from the beacons' centroid. Each range's weight folds in the
beacon's own position sigma. Three beacons plus a barometric altitude, or
four beacons, make a fix. DOP is reported; a bunched geometry declines.
An accepted fix goes through the Kalman filter's gate and re-anchors the
physically reachable region, like a tag fix.

## Measured in simulation (models, not hardware)

| Scenario | Result |
|---|---|
| Four ground beacons, 10 m ranging sigma, drone moving | fix error ≈ 6 m rms, stated sigma ≈ 7 m, 95% coverage ≈ 97% |
| Four balloons at 15–30 km, drifting, drone inside a 3 km GNSS jammer | fix ≈ 10 m rms, stated sigma ≈ 11 m, coverage ≈ 95%, HDOP ≈ 2; the GNSS jammer changed nothing |
| Wideband jammer on the beacon band | beacons silent; the layer declines, with the reason |
| Unsigned, off-schedule, replayed, stale or wrong-key messages | refused and counted |
| One beacon knowing itself only to 500 m | the stated fix sigma widens from ≈ 7 m to tens of metres |
| Four beacons bunched 28 km away | declined: HDOP too high |

The ranging sigma (10 m) and the link margin (20 dB) are assumptions until
a radio is measured.

## A tethered aerostat over the base

The sound version of "the balloon gives altitude": a balloon that only has
to hover can stay up for hours on no power, so a **tethered aerostat a few
hundred metres over the base** makes a persistent, wide-coverage home
beacon. Its position is known from the surveyed anchor point plus the
blowdown: in wind the tether leans by an angle set by drag against net
lift (a 3 m aerostat with 60 N net lift on a 300 m tether leans about 11°
in 3 m/s and 45° in 8 m/s). That lean is the uncertainty: a 2 m/s doubt
about the wind moves it tens of metres, and the beacon's broadcast carries
that sigma (the simulator's `tethered` kind does exactly this, and a test
asserts that strong uncertain wind widens the stated sigma). Measure the
tether angle, or track the aerostat from two surveyed sites, to tighten
it. It needs an aerostat, tether and winch, the beacon, and airspace
clearance for a tethered object [TO CONFIRM with DGCA]; it is a visible,
persistent target; and it has wind limits. It beats a free balloon as the
home beacon because it never drifts away and never bursts.

## Should the drone carry its own balloon? The numbers

`python tools/compare_balloon_carry.py` writes `BALLOON_CARRY.md` from
labelled physics. In short: a balloon that lifts a 0.3 kg beacon is about
1.3 m across and drags more than a small drone's hover thrust at 10 m/s;
deflated with a gas cylinder it is about 1.5 kg to carry; and released
inside a 1 km jammer its own GNSS only works again a couple of kilometres
up, several minutes later, during which its position is a kilometre-scale
guess. A balloon-lifted drone is good for loitering in calm air and bad
for any transit. The verdict the numbers give: breadcrumbs on the way in,
launch-site balloons for area coverage, an aerostat over the base, no
balloons on the mission drone.

## What to build on the beacon side (not code yet)

- The radio: a 2.4 GHz LoRa-class module with ranging (SX1280 family) on
  the box and on each beacon, or UWB for short-range tests.
- Beacon firmware: hop on the schedule, sign and send the message every
  slot, answer ranging requests. An ESP32 with a LoRa module is the right
  job for an ESP32 in this project.
- The beacon's position source: its own GNSS receiver, or ground tracking
  from two surveyed sites.
- The first field test needs only three radios on tripods. The balloons
  come later with the same code.

## In the box

```toml
[beacons]
beacon_radio = "/dev/ttyUSB1"
beacon_secret_file = "/etc/upin/beacon.key"   # never in the repo
```

The radio's firmware prints one JSON object per line (`upin/box/beacon_radio.py`
shows the format). The box checks every message in layer 151, solves once
per GNSS epoch, and the console's "Other fixes" card shows the fix or why
there is none, and how many messages were refused and why.

## Files

| | |
|---|---|
| `upin/layers/rf/beacon_ranging.py` | the layer: message checks, the solve, declines |
| `upin/simulation/beacons.py` | simulated beacons and balloons, ranging, band jamming |
| `upin/box/beacon_radio.py` | the serial reader (untested) |
| `tests/test_beacon_ranging.py` | message checks, ground fix, balloons under a GNSS jammer, band jammer, widening, geometry |
