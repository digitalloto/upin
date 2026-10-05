# The Kalman filter in UPIN

How UPIN combines uncertain sources into one estimate, what that requires
to stay honest, and what it can and cannot do. Every number on this page is
checked by `tests/test_kalman.py` or measured by `tools/compare_fusion.py`.

## The idea in one example

Navigation has two kinds of source, and neither is enough alone:

- **prediction from physics** — where you were, plus how you moved. Smooth,
  but every small error carries forward, so it drifts.
- **measurement** — GNSS, a landmark bearing, a star sight. Anchored to
  reality, but noisy.

The Kalman filter combines them and keeps track of **how uncertain** its
answer is, as well as the answer. Each belief is a bell curve: the centre is
the best guess, the spread (variance) is how unsure it is.

A car on a straight road. The model predicts **100 m, variance 4**. GPS
reports **106 m, variance 12**.

1. The disagreement is 6 m — the **innovation**, or surprise.
2. The **Kalman gain** decides how much of the surprise to believe:
   prediction variance / total variance = 4 / (4 + 12) = **1/4**.
3. Move a quarter of the way: 100 + 6/4 = **101.5 m** — closer to the
   prediction, because it was the more reliable source.
4. Precisions (1 / variance) add: 1/4 + 1/12 = 1/3, so the new variance is
   **3** — better than either source alone.

`test_the_worked_example` reproduces this exactly in UPIN's filter.

## When combining actually helps — and when it lies

Step 4 is only true under conditions that are easy to break silently:

| Condition | What breaks it | What happens |
|---|---|---|
| **Errors are independent** | the same fix counted twice; a layer that propagates the filter's own estimate | precisions add for no reason: one GPS fix fused twice gives variance 2.4 instead of 3 — certainty out of nothing |
| **Stated variances are true** | a layer that claims 5 m when it is 50 m out, or 40 m when it is 2 m | the filter weights the wrong source; it can only be as honest as its inputs |
| **The surprise is plausible** | a spoofed or faulty fix | without a check, a 300 m error is averaged in |
| **Angles are compared correctly** | 359° vs 1° read as 358° apart | the estimate swings to 180° |
| **Noise is roughly Gaussian, models roughly linear** | multipath, sharp manoeuvres | the bell curve stops describing the error |

## The two filters in the repo

**The live filter** — `ExtendedKalmanFilter` in `upin/core/fusion_engine.py`.
Its core arithmetic is correct (it also gives 101.5 m / 3). Around it:
heading innovations are not wrapped (359° + 1° → 180°), every reading is
treated as independent, the noise matrices mix degrees and metres, there is
no innovation check, and the accuracy the engine reports comes from a
lookup on a confidence score (0.5 / 2 / 10 / 50 / 200 m), not from the
filter's own variance.

**HonestKalmanFusion** — `upin/fusion/honest_kalman.py`, a separate option
that changes nothing already built. It:

- works in metres around the first fix, with the first fix's own variance
- compares angles the short way round
- never fuses a reading marked `independent: False`, and takes at most one
  measurement per source per cycle
- tests every measurement's surprise against χ² and records rejections
- accepts velocity (GNSS Doppler, later optical flow), altitude and heading
- **reports its own covariance** as the accuracy and the 95% radius
- has an offline smoother for replaying logged flights — never presented as
  a live result

With inputs whose stated noise is true, its 95% circle contains the truth
**94.8%** of the time, median error/radius **0.47** (theory 0.48).

## How to get the most accuracy — honestly

The filter cannot create information. These are the ways to give it more:

1. **Measure velocity, not only position.** In steady cruise, Doppler
   velocity cut drift 30 s after positions stopped from 13.4 m to 5.1 m
   (simulation). Optical flow (spec item 8) is the GNSS-denied equivalent.
2. **Make every layer's stated accuracy true.** The comparison found the
   command dead-reckoning layer accurate to 1–2 m in simulation while
   claiming 20–42 m. Its drift model is a declared assumption; it should be
   measured on the airframe, not tuned to a simulator that is kinder than
   the air (no model mismatch, calm wind).
3. **Better prediction.** Wiring the strapdown INS in as the prediction step
   (spec item 4) replaces "constant velocity" with measured motion.
4. **Measure the process noise.** `ACCEL_PSD_H/V` are labelled assumptions;
   log real flights and set them from the data.
5. **Use independent sources.** A landmark fix, a terrain fix and a GNSS fix
   fail for different reasons; three readings from one receiver do not.

## What it cannot do

- It cannot make a source better than it is. Fusion beats the best single
  source only when errors are independent and stated variances are true.
- It cannot know the aircraft's position without any source. When every
  source is gone the uncertainty grows, and the filter says so.
- Simulation results are not field results. Real accuracy is measured on
  the Raspberry Pi rig (`ROADMAP.md`, Part 3).

See `FUSION_COMPARISON.md` for every fusion option in the repo measured on
identical inputs.
