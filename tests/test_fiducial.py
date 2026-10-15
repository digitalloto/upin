"""Tests for layer 149, tag landmarks (fiducial_e25), and the UPIN tag.

Everything here is SIMULATED: tags painted into the simulator's ground
texture with the same geometry a downward pinhole camera would see. It
tests the code and the maths, not a real camera or lens.

Run: python tests/test_fiducial.py
"""
import io
import json
import math
import os
import sys
import tempfile

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np  # noqa: E402

from upin.box.gnss_parser import encode_nav_pvt  # noqa: E402
from upin.box.service import Box, BoxConfig  # noqa: E402
from upin.console.sources import Msg  # noqa: E402
from upin.core.no_fabrication import NoFixReason, audit_layer  # noqa: E402
from upin.layers.optical.fiducial import FiducialTagLayer, TagEntry, TagMap  # noqa: E402
from upin.layers.optical.landmark_chain import ForeignMapSourceError  # noqa: E402
from upin.simulation.markers import SimTag, ground_patch_with_tags  # noqa: E402
from upin.vision import upin_tag as T  # noqa: E402

PASSED = []
LAT0, LON0 = 13.0827, 80.2707
DEG_M = 111_320.0


def ll(n, e):
    return LAT0 + n / DEG_M, LON0 + e / (DEG_M * math.cos(math.radians(LAT0)))


def ne(lat, lon):
    return (lat - LAT0) * DEG_M, (lon - LON0) * DEG_M * math.cos(math.radians(LAT0))


TAG = SimTag(7, north_m=120.0, east_m=-40.0, size_m=4.0, yaw_deg=25.0)
MAP = TagMap([TagEntry(7, *ll(TAG.north_m, TAG.east_m), 4.0, "field_survey", 0.3,
                       altitude_m=12.0, name="range tag")])


def test_codes():
    for tag_id in sorted(T.VALID_IDS):
        g = T._grid_from_bits(T.pattern_bits(tag_id))
        for k in range(4):
            assert T.decode_grid(np.rot90(g, k)) == (tag_id, (4 - k) % 4 if k else 0) or \
                T.decode_grid(np.rot90(g, k))[0] == tag_id
    try:
        T.cell_colours(300)
        raise AssertionError("invalid id accepted")
    except ValueError:
        pass
    try:
        TagEntry(7, LAT0, LON0, 0.5, "google maps", 0.3)
        raise AssertionError("foreign map source accepted")
    except ForeignMapSourceError:
        pass
    print(f"[ok] {len(T.VALID_IDS)} tag ids decode correctly from all four rotations; "
          f"a bad id and a foreign map source are refused")
    PASSED.append("codes")


def test_detect_and_pose_in_simulation():
    layer = FiducialTagLayer(MAP)
    layer.initialize()
    rng = np.random.default_rng(3)
    worst_px = worst_agl = 0.0
    n = 0
    for agl in (25.0, 50.0):
        for hdg in (0, 90, 200, 315):
            dn, de = rng.uniform(-6, 6), rng.uniform(-6, 6)
            img, gsd = ground_patch_with_tags(TAG.east_m + de, TAG.north_m + dn, hdg, agl,
                                              40.0, 256, [TAG], pixel_noise=0.02, rng=rng)
            layer.feed_attitude(0.0, 0.0, hdg, 1.0)
            layer.feed_frame(img, 1.0, 40.0)
            v = layer.solve()
            assert v["status"] == "ok", (agl, hdg, v)
            en, ee = ne(v["lat"], v["lon"])
            err = math.hypot(en - (TAG.north_m + dn), ee - (TAG.east_m + de))
            assert err < 2 * gsd, (agl, hdg, err, gsd)
            assert abs(v["agl_m"] - agl) / agl < 0.02
            worst_px = max(worst_px, err / gsd)
            worst_agl = max(worst_agl, abs(v["agl_m"] - agl))
            n += 1
    r = layer.read()
    assert r.is_valid and r.position is not None and r.raw_data["independent"]
    print(f"[ok] {n} simulated views at 25 and 50 m, four headings: tag read, position "
          f"within {worst_px:.1f} px, height within {worst_agl:.2f} m; accuracy from geometry")
    PASSED.append("pose")


def test_declines():
    layer = FiducialTagLayer()
    layer.initialize()
    assert audit_layer(layer).compliant
    assert layer.solve()["reason_code"] == NoFixReason.NO_INPUT          # no map
    layer.set_map(MAP)
    assert "frame" in layer.solve()["reason"]
    plain, _ = ground_patch_with_tags(0.0, 0.0, 0.0, 30.0, 40.0, 256, [])
    layer.feed_frame(plain, 5.0, 40.0)
    assert "attitude" in layer.solve()["reason"]
    layer.feed_attitude(0.0, 0.0, 0.0, 5.0)
    assert layer.solve()["reason_code"] == NoFixReason.INSUFFICIENT_INPUT  # no tag
    assert layer.solve(t=9.0)["reason_code"] == NoFixReason.STALE_INPUT
    far, _ = ground_patch_with_tags(TAG.east_m, TAG.north_m, 0.0, 150.0, 40.0, 256, [TAG])
    layer.feed_frame(far, 6.0, 40.0)
    layer.feed_attitude(0.0, 0.0, 0.0, 6.0)
    v = layer.solve()
    assert v["status"] == "declined", v        # 4 m tag at 150 m: 9 px, unreadable
    unknown = SimTag(20, TAG.north_m, TAG.east_m, 4.0, 0.0)
    img, _ = ground_patch_with_tags(TAG.east_m, TAG.north_m, 0.0, 30.0, 40.0, 256, [unknown])
    layer.feed_frame(img, 7.0, 40.0)
    layer.feed_attitude(0.0, 0.0, 0.0, 7.0)
    v = layer.solve()
    assert v["reason_code"] == NoFixReason.FAILED_VALIDATION and v["seen_ids"] == [20]
    print("[ok] declines, each with its reason: no map, no frame, no attitude, no tag in "
          "view, stale frame, tag too small to read, tag not in the map")
    PASSED.append("declines")


def test_through_the_box():
    """GNSS trusted, then denied while the drone turns, so coasting drifts;
    the tag comes into view and re-anchors the filter; a spoofed GNSS fix is
    then rejected. SIMULATED."""
    cfg = BoxConfig(max_accel_ms2=6.0, max_airspeed_ms=20.0, max_degraded_h_acc_m=1e6)
    box = Box(cfg)
    rng = np.random.default_rng(5)
    # the path: straight east, then a gentle turn once GNSS is denied
    path, vel, hdg = [], [], []
    n, e, course = 0.0, 0.0, math.radians(90.0)
    for k in range(110):
        if k >= 60:
            course += math.radians(2.0)                 # 2 deg/s turn: 0.2 m/s^2
        vn, ve = 6.0 * math.cos(course), 6.0 * math.sin(course)
        n, e = n + vn, e + ve
        path.append((n, e)); vel.append((vn, ve)); hdg.append(math.degrees(course) % 360)
    tag = SimTag(7, *path[95], 4.0, 25.0)                 # under the drone at t = 95 s
    box.tags.set_map(TagMap([TagEntry(7, *ll(*path[95]), 4.0, "field_survey", 0.3,
                                      altitude_m=12.0, name="range tag")]))
    log = io.StringIO()
    box.log = log
    errs = {}
    last_fix_k = None
    for k in range(110):
        t = float(k)
        n, e = path[k]
        vn, ve = vel[k]
        box.on_fc_message(Msg("ATTITUDE", roll=0.0, pitch=0.0, yaw=math.radians(hdg[k])), t)
        box.deny_gnss = t >= 60
        lat, lon = ll(n + rng.normal(0, 1.5), e + rng.normal(0, 1.5))
        box.on_receiver_bytes(encode_nav_pvt(int(t * 1000), lat, lon, 50, 1.5, 3,
                                             (vn + rng.normal(0, 0.1), ve + rng.normal(0, 0.1), 0),
                                             0.15), t, 0.0)
        if t >= 60:
            box.on_frame(ground_patch_with_tags(e, n, hdg[k], 40.0, 40.0, 256, [tag],
                                                pixel_noise=0.02, rng=rng)[0], t, 40.0)
        if box.last_tag and box.last_tag["status"] == "ok":
            last_fix_k = k
            # the output of this epoch, after the tag fix of the same second
            est = box.gateway.kf.estimate()
            on, oe = ne(est.lat, est.lon)
            errs[k] = math.hypot(on - n, oe - e)
            continue
        out = box.gateway.log[-1]
        if out.lat is not None:
            on, oe = ne(out.lat, out.lon)
            errs[k] = math.hypot(on - n, oe - e)
    fx = box.gateway.last_fixes["fiducial"]
    assert fx["accepted"] and fx["anchored"], fx
    assert last_fix_k is not None and 93 <= last_fix_k <= 98, last_fix_k
    assert errs[92] > 10.0, errs[92]                       # coasting through a turn drifts
    assert errs[last_fix_k] < 1.0, errs[last_fix_k]
    # once the tag has passed, it coasts again -- stated, not hidden
    assert errs[109] > errs[last_fix_k]
    # a spoofed GNSS fix 300 m away now disagrees with a physically anchored estimate
    box.deny_gnss = False
    n, e = path[-1]
    lat, lon = ll(n + 300, e)
    out, _ = box.on_receiver_bytes(encode_nav_pvt(110000, lat, lon, 50, 1.5, 3, (0, 6, 0), 0.15),
                                   110.0, 0.0)[0]
    assert out.mode != "TRUSTED" and any("impossible" in r or "inconsistent" in r
                                        for r in out.reasons), out.reasons
    lines = log.getvalue().splitlines()
    assert json.loads(lines[-1])["fixes"]["fiducial"]["accepted"]
    print(f"[ok] through the box: coasting through a turn drifted {errs[92]:.1f} m; the tag "
          f"re-anchored the filter to {errs[last_fix_k]:.2f} m while in view (about "
          f"{last_fix_k - 92} s at 6 m/s), then coasting resumed ({errs[109]:.1f} m at "
          f"t=109); a 300 m spoof is rejected")
    PASSED.append("box")


def test_tag_truth_tool():
    sys.path.insert(0, "tools")
    from tag_truth import analyse, report
    lines = []
    for k in range(10):
        lat, lon = ll(100.0, 50.0)
        rlat, rlon = ll(100.0 + 3.0, 50.0 + 4.0)      # receiver 5 m off
        lines.append(json.dumps({"t": float(k), "receiver": {"fix_type": 3, "lat": rlat, "lon": rlon},
                                 "fc_gps": None, "lat": lat, "lon": lon,
                                 "fixes": {"fiducial": {"t": float(k), "lat": lat, "lon": lon,
                                                        "sigma_m": 0.4, "accepted": True}}}))
    errors, sigmas = analyse(lines)
    assert abs(np.median(errors["receiver"]) - 5.0) < 0.05 and len(sigmas) == 10
    assert "receiver" in report(errors, sigmas)
    print("[ok] tools/tag_truth.py: receiver error against tag fixes measured (5.0 m)")
    PASSED.append("tool")


if __name__ == "__main__":
    tests = [test_codes, test_detect_and_pose_in_simulation, test_declines,
             test_through_the_box, test_tag_truth_tool]
    for t in tests:
        t()
    print(f"\n{len(PASSED)}/{len(tests)} tag-landmark tests passed")
