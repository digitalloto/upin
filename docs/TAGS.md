# Tag landmarks (layer 149): a fix from a printed tag

A printed UPIN tag at a surveyed spot. When the downward camera sees it,
UPIN knows exactly where the drone is: the tag's apparent size gives the
height, its place in the frame gives the offset on the ground, and the
tag's surveyed coordinates do the rest. One tag is a full fix, with its
accuracy computed from the geometry, never assumed.

> **Status: simulation only.** Tags painted into the simulator's ground are
> read with sub-pixel accuracy. No real camera, lens or printed tag has
> been tried. The camera driver is untested.

## What it is for, in order

1. **Ground truth on the test range.** Put tags at surveyed spots. Every
   time the drone flies over one, UPIN has a position with no GNSS
   involved, and `tools/tag_truth.py` reports how far off the receiver,
   the flight controller's GPS and UPIN's own output were. This is how
   every other layer's real error gets measured.
2. **Landing pad and "home" without GNSS.**
3. **Indoor and GPS-denied tests**, with tags on the floor.

## The tag

Our own design (`upin/vision/upin_tag.py`), not a tag library: an 8 × 8
grid, black border, white ring, a 4 × 4 code with check bits. All 256 ids
read correctly from any rotation, and the reading also says which way the
tag faces. Print one:

```bash
python -m upin.vision.upin_tag 7 tag7.png
```

Print it so the 8 cells, black edge to black edge, measure the `size_m`
you will put in the map. Survey the tag's centre and write the map
(`deploy/tags.example.json` shows the format): its id, latitude,
longitude, size, the survey's own accuracy, and the map source, which must
be an Indian source or `field_survey`, the same rule as the landmark layer.

## How far away a tag can be read

A tag must span at least 24 pixels (3 per cell, an assumption to measure on
the real camera). So the range depends on the tag size, the camera's
resolution and its field of view:

| Tag | Camera | Readable up to |
|---|---|---|
| 0.5 m | 640 px, 62° | about 10 m |
| 0.5 m | 1280 px, 62° | about 20 m |
| 2 m | 640 px, 62° | about 40 m |
| 4 m painted marker | 640 px, 62° | about 80 m |

These follow from the geometry; the real limit also depends on light,
blur and lens quality, and must be measured.

## In the box

In `box.toml`:

```toml
[camera]
camera = "pi"                      # or a folder of recorded .npy frames
camera_fov_deg = 62.0              # the real lens's horizontal field of view
camera_size_px = 256
tag_map = "/etc/upin/tags.json"
```

A tag fix goes through the Kalman filter's gate like every other
measurement, and when accepted it also **re-anchors the physically
reachable region**: from then on a GNSS fix that jumps away from where the
tag put the drone is physically impossible, and a spoofer is caught against
something it cannot move. The console's "Other fixes" card shows every tag
fix or the reason there is none.

## Measured in simulation (not on hardware)

- 8 views at 25 and 50 m, four headings: position within 0.4 pixel, height
  within 0.5 m at 50 m.
- Through the box: coasting through a turn with GNSS denied drifted about
  25 m in 32 s; the tag re-anchored the filter to under a metre while in
  view; once the tag passed, coasting resumed and the error grew again,
  which the test asserts rather than hides. A 300 m GNSS spoof after the
  re-anchor was rejected.

## Honest limits

- Only where tags are placed, and only while one is in the frame: at 6 m/s
  and 40 m height a 4 m tag is in view for about four seconds.
- Needs light; the detector is written for a downward camera at modest
  tilt. Steep banks are not handled.
- The tag's survey accuracy is part of the fix's accuracy; a badly
  surveyed tag gives a confidently wrong fix. Survey honestly.
- Untested on a real camera: the corner-error assumption (0.7 px), the
  field of view and the minimum readable size all need measuring.

## Files

| | |
|---|---|
| `upin/vision/upin_tag.py` | the tag, printing, detection, pose |
| `upin/layers/optical/fiducial.py` | the layer, the tag map, declines |
| `upin/simulation/markers.py` | tags painted into the simulator's ground |
| `upin/box/camera.py` | Pi camera / recorded-frame source (untested) |
| `tools/tag_truth.py` | every other source's error against tag fixes |
| `tests/test_fiducial.py` | codes, detection and pose, declines, through the box, the tool |
