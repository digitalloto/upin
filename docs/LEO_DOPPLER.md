# LEO Doppler anchor (layer 150): a GNSS-free fix from a satellite pass

A satellite in low orbit crosses the sky in about ten minutes. Its received
carrier slides from high to low, and the shape of that slide depends on
where the receiver stands relative to the orbit. With the orbit known from
a published two-line element set, one pass gives a position: how the
Transit system worked before GPS, now on a cheap USB software radio.

> **Status: simulation only.** An analytic orbit and synthetic Doppler.
> No radio, no antenna, no real satellite. The radio source and the pass
> runner are untested. The reel this came from showed weather-satellite
> pictures; those NOAA satellites were retired in 2025, so the layer is
> written for any satellite with a published orbit and a steady carrier.
> Orbcomm's VHF downlinks (137–138 MHz) are the usual choice in published
> work.

## What it is for

A coarse position, hundreds of metres, once per pass, on a band that GNSS
jammers do not touch, with no infrastructure of ours. An anchor for a long
GNSS outage, not navigation.

## How it works

1. The radio records the pass; the tracker (`doppler_track.py`) turns the
   samples into a carrier frequency every second with a stated sigma.
2. The fit solves four unknowns: latitude, longitude, the radio's frequency
   offset (a cheap oscillator is off by about a part per million) and its
   drift. Altitude comes from the barometer. Weighted Gauss–Newton from a
   prior position; the sigma comes from the covariance.
3. Orbits come from `sgp4` (MIT-licensed) for real TLEs, or an analytic
   circular orbit for tests.

## What it refuses, and why

| It declines when | Because |
|---|---|
| the TLE is older than 7 days | along-track error reaches kilometres |
| the pass is under 120 s or peaks below 15° | the geometry cannot fix a position |
| there is no prior position | the Doppler curve is the same for the **mirror position** across the satellite's track; the prior chooses the side |
| the prior is too weak to choose the side | it would be a guess |
| the fix lands far from the prior | a **wrong satellite**, or the wrong phase of the right orbit, fits a receiver shifted along the track *perfectly*; the residuals cannot tell, only the prior can (found in testing, asserted) |
| the residuals do not fit the stated noise | interference or a wrong orbit |
| the receiver moves without saying so | motion changes the curve; stated motion is fitted |

## Measured in simulation (not on a real satellite)

| Scenario | Result |
|---|---|
| One 860 s pass peaking at 32°, 2 Hz noise, 1 ppm offset and drift | position error ≈ 250 m (max ≈ 430 m), stated sigma ≈ 190 m; the offset recovered to within 0.1 Hz |
| 20 passes with random priors and offsets | 95% intervals cover 90% |
| Orbit 0.3 s stale (≈ 2 km along-track) | the fix moves by hundreds of metres, as it must |
| Wrong satellite phase | fits perfectly 550 km away; refused by the prior check |
| Weak prior (200 km) | ambiguous: the mirror 100+ km away fits too; declined |
| Carrier tracker at −10 dB per-sample SNR | frequency error ≈ 1 Hz rms with an honest sigma |

Published results for context: Transit reached about 70 m with two
frequencies; a UAV experiment aided an inertial system with two Orbcomm
satellites to 8.9 m after 30 s. UPIN claims none of this until measured.

## In the box

```toml
[leo]
sdr = "rtl"
leo_satellites = "/etc/upin/satellites.json"
```

Fetch fresh TLEs before the mission. The runner (`upin/box/leo_pass.py`)
waits for a satellite above 10°, records the pass, solves when it sets,
and hands an accepted fix to the filter **without re-anchoring the
reachable region**: a fix hundreds of metres wide must not narrow a
physical bound. The console's "Other fixes" card shows the runner's state
and the last fix.

## Honest limits

- Hundreds of metres to kilometres with a cheap oscillator and one pass.
- One fix per pass; passes an hour or two apart per satellite.
- Needs a prior; the receiver must be still or state its motion.
- A spoofer could fake a Doppler curve.
- Which satellites still transmit, and on what, must be checked at the
  time; satellites retire.

## Files

| | |
|---|---|
| `upin/layers/satellite/leo_doppler.py` | frames, orbits, the fit, the checks |
| `upin/layers/satellite/doppler_track.py` | carrier tracking; synthetic samples for tests |
| `upin/box/sdr.py`, `upin/box/leo_pass.py` | the radio and the pass runner (untested) |
| `tests/test_leo_doppler.py` | declines, fit, coverage, stale and wrong orbits, mirror, motion, tracker, sgp4 |
