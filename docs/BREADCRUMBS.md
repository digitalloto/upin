# Breadcrumb beacons (layer 152): drop them while you still know where you are

The drone carries a few small beacons and **drops them on the way in, as
jamming begins to rise, while its position is still trusted**. Each crumb
is stamped with the position it will land at and how well that is known.
Inside the jammed zone, and on the way back, the drone ranges to its own
crumbs and solves its position from them: the radio form of the landmark
layer's breadcrumbs, built on layer 151's ranging and message checks.

This is the version of "release a beacon when jamming starts" that works.
A balloon released *after* jamming starts doesn't know where it is; a
crumb dropped *before* does.

> **Status: simulation only.** Crumb radio firmware, the release
> mechanism and the box's provisioning line are not built or tested. The
> stamp maths, the drop policy and the fix are tested in simulation.

## The one rule

**A crumb is never dropped on an untrusted or loose fix.** A crumb stamped
with a guessed position would poison every later fix. The drop policy
refuses and says why; a test asserts it. It also refuses when there is no
wind estimate or height for the fall, when the last crumb is too close,
and when all crumbs are gone.

## The stamp

- landing position = the fix at release + wind × fall time
  (fall time = height ÷ an assumed 15 m/s terminal velocity, to be measured
  by dropping one);
- stamp sigma = fix sigma combined with wind sigma (gusts included) × fall
  time. With no wind estimate yet, the stamp assumes calm air with a 5 m/s
  sigma (an assumption: a moderate day), is marked "wind unknown", and is
  honest but loose: about ±20 m from 60 m up.

In simulation, over 300 drops with wind error and gusts, the true landing
point is inside the stamp's 95% circle about 95% of the time. The crumb
then broadcasts that stamp, signed and hopping, like any beacon, and layer
151's checks apply (signature, schedule, no replay, freshness). The
stamp's sigma travels into every fix the crumb gives.

## The trigger

The box turns what it already knows into a threat level: clear; rising
(the signal-power layer says jamming, the receiver reports a warning, or
the box is no longer trusting GNSS); jammed (no fix or a critical
report). Crumbs drop at `breadcrumb_spacing_m` intervals once the threat
is rising, up to `breadcrumb_max`. Because the rule above forbids drops
once trust is lost, all drops happen before the jam closes.

## Measured in simulation

| Scenario | Result |
|---|---|
| Weaving into a jammed zone and back along the trail, 1.5 m GNSS, crumbs every 200 m, 10 m ranging | four crumbs dropped as the threat rose, all before the jam; inside the jam 143 of 149 epochs got a fix: 20 m rms with a stated sigma of 22 m, the 95% circle covering 96%; the rest declined on geometry past the trail |
| Through the box, the receiver's jamming state rising then critical, one heading only | three crumbs provisioned; the box had no wind estimate, so the stamps honestly said so and carried ±20 m; inside the jam a crumb fix re-anchored the filter; output error about 34 m with GNSS gone |
| One crumb only | declines: needs three with altitude |
| Crumbs dropped along a straight line | declines on geometry inside the zone: collinear beacons cannot fix the cross-track position (**stated limit**: weave while dropping) |

## Drop on a weave, not a straight line

Crumbs dropped along a straight flight path are collinear, and ranges to
collinear beacons cannot tell which side of the line the drone is on. The
solve declines on geometry, and a test asserts it. Weave while dropping
so that successive crumbs land on opposite sides of the track, with a
sideways offset of about half the spacing (a weave as long as the spacing
itself puts the crumbs back on a line), or drop at turns.

## What the crumbs need

- A ranging radio module (the same 2.4 GHz LoRa-class family as layer
  151, or UWB for short range), a small microcontroller, a coin cell, a
  streamer or small parachute, a casing that survives the landing. Tens of
  grams each.
- A release mechanism on the drone: a servo-driven dispenser.
- Firmware: receive the provisioning line (its stamp and the shared
  secret) before release, then broadcast and answer ranging requests like
  any beacon. An ESP32 plus a LoRa module is the right job for an ESP32 in
  this project.

## In the box

```toml
[beacons]
beacon_radio = "/dev/ttyUSB1"
beacon_secret_file = "/etc/upin/beacon.key"
breadcrumbs = true
breadcrumb_spacing_m = 300.0
breadcrumb_max = 6
breadcrumb_drop_agl_m = 50.0     # used only when no rangefinder reports the height
```

The console's "Other fixes" card shows crumbs dropped, crumbs in range,
the fix or why there is none, and the drop policy's last reason. Dropped
crumbs appear on the map as hollow squares at their stamped positions.

## Honest limits

- Only as good as the fix at the moment of release and the wind estimate
  for the fall.
- Ground-level radios: a kilometre or three with line of sight; terrain
  blocks them. Crumbs stay behind (recoverable) and the number carried is
  small.
- Legal: the same band and power rules as layer 151 (see
  `docs/BEACONS.md`).

## Files

| | |
|---|---|
| `upin/layers/rf/breadcrumbs.py` | the layer: policy, stamp, routing to layer 151's solve |
| `upin/simulation/beacons.py` | crumbs that land at their true point and broadcast their stamp |
| `tests/test_breadcrumbs.py` | policy, stamp honesty, the fix inside the zone, through the box |
