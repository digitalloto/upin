# Camera optical flow (layer 148): flow that throws out the laser dots

UPIN's own ground-velocity sensor from a downward camera, built so that a
moving pattern on the ground cannot drag it. From the Alloy Robotics reel:
a flow sensor that averages the motion of everything it sees follows a
sweeping grid of laser dots into a wall; the fix is weighted RANSAC, which
keeps the motion the trusted points agree on and throws the rest out.

> **Status: simulation only.** Frames come from the simulator's ground
> texture. No real camera has been tried. Thresholds are assumptions until
> measured on the real camera and lens.

## Why UPIN needs its own flow

The flow-sensor chip on the flight controller gives one averaged number per
frame. UPIN's integrity check (`upin/detection/flow_integrity.py`) can catch
that number lying by comparing it with the IMU, GNSS and the AI predictor,
but it cannot fix it. Only a layer that sees the pixels can judge each
tracked point. This layer does.

## How it works

1. A 6 × 6 grid of 16-pixel patches in the last frame; each is found again
   in the new frame by block matching with sub-pixel refinement. Each patch
   is one point: a displacement, a contrast and a distinctiveness. The
   matching is **robust**: each pixel's difference is capped, so a few bright
   pixels (a laser dot) cannot dominate a patch. A naive matcher lets the dot
   win, and that is the first half of the reel's attack.
2. The shift the drone's own rotation would cause (from the gyro and the
   focal length) is removed first, so a turn is not read as a slide.
3. **Weighted RANSAC:** every point proposes "the ground moved by my
   displacement". The proposal that the most *trust* agrees with wins, and
   the velocity is the trust-weighted mean of its inliers.
4. **Trust** is earned slowly by agreeing since takeoff and lost quickly by
   clearly disagreeing. Points on the still floor end up outweighing points
   on a moving pattern.
5. Pixels become metres with the rangefinder height and the field of view.
   The sigma comes from the inliers' spread, the height's sigma and the
   frame interval.

It declines, saying why, with no frame pair, frames too far apart, no
height, no gyro, too little texture, or when less than half the trust
agrees on one motion: "cannot tell the drone moving from the floor moving".

## Measured in simulation (not on hardware)

| Test | Result |
|---|---|
| Honest 30 s flight with a turn, 5 frames/s | velocity error 0.22 m/s rms; the 95% interval covers 98% |
| Turning in place at 20°/s | 0.30 m/s with gyro compensation; 3.1 m/s without it |
| Laser dots 4 m apart sweeping at 3 m/s | a naive tracker (plain matching, plain average) is dragged 1.6 m/s off; robust matching plus weighted RANSAC stays within 0.40 m/s |
| The console's circuit, honest (straights and curves) | 0.34 m/s rms, no bias on the curves once each patch's search is centred on its predicted shift |
| The console's circuit under the dot attack at 2.5 m/s | 0.9 m/s rms with a stated sigma of about 0.3 (widened for low agreement): **still overconfident under a partial attack**, stated here; the flight controller's flow chip read 2.5 m/s off in the same run |
| Dots in every patch | the flow follows them, about 3 m/s off: **the stated limit**. When everything in the image moves together, no image method can tell the floor from the pattern; only a non-image check (the IMU-based flow integrity check) can |

The simulator's ground is smoother than real ground; real texture should
track better, and real lighting, blur and lens distortion are not modelled.

## In the box

```toml
[camera]
camera = "pi"
camera_fov_deg = 62.0          # the real lens's horizontal field of view
camera_flow = true             # off by default
range_sigma_m = 0.1            # the rangefinder's 1-sigma, from its datasheet
```

It needs the rangefinder and the gyro over MAVLink from the flight
controller; the box feeds both. Its velocity goes to the Kalman filter as a
separate source (`camera_flow`) beside the flight controller's flow sensor,
so the two can be compared in the log. The console's sensors card shows the
velocity, how many points agreed and how much trust they carried.

## Honest limits

- Needs texture, height and light. Over water, a plain floor or in the dark
  it declines.
- If the moving pattern is in every patch, everything moves together and
  the flow follows it. The test shows this rather than hiding it. The
  IMU-based flow integrity check (`upin/detection/flow_integrity.py`) is the
  defence for that case, because it does not use the image.
- Trust settles below 1 on the simulator's smooth, noisy ground (about
  0.7 mean); real ground with more texture should track better.
- Roll and pitch compensation use the geometry's signs and are unverified
  on hardware; yaw compensation is verified in simulation.
- Compute cost on the Pi is to be measured: 36 patches at 256 pixels takes
  tens of milliseconds here; the Pi Zero 2 W is expected to be too slow.

## Files

| | |
|---|---|
| `upin/layers/optical/camera_flow.py` | the layer |
| `upin/simulation/attacks.py` | the sweeping laser-dot grid, and frames with tags and dots |
| `tests/test_camera_flow.py` | declines, honest flight, rotation, dots thrown out, the stated limit |
