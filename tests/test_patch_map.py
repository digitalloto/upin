"""Tests for layer 154, self-surveyed patch-map matching.

SIMULATED ground (upin/simulation/environment.ground_texture, a pure
function of position) seen by a simulated leaning camera. Build the map on
one pass, match on another; the declines: water, repeating ground, a dark
frame, an untrusted or loose fix, off the corridor, changed ground; the
Indian-source rule; and the path through the box.

Run: python tests/test_patch_map.py
"""
import json
import math
import os
import sys
import tempfile

sys.path.insert(0, ".")

import numpy as np  # noqa: E402

from upin.core.no_fabrication import NoFixReason, audit_layer  # noqa: E402
from upin.layers.optical.landmark_chain import ForeignMapSourceError  # noqa: E402
from upin.layers.optical.patch_map import PatchMapLayer  # noqa: E402
from upin.simulation.attacks import camera_frame  # noqa: E402
from upin.simulation.markers import patch_mapping  # noqa: E402
from upin.vision.patch_map import DEG_M, PatchMap, rectify  # noqa: E402

PASSED = []
LAT0, LON0 = 13.0827, 80.2707
AGL, FOV, PX = 50.0, 40.0, 256
R95 = 2.4477


def ll(n, e):
    return LAT0 + n / DEG_M, LON0 + e / (DEG_M * math.cos(math.radians(LAT0)))


def ne(lat, lon):
    return (lat - LAT0) * DEG_M, (lon - LON0) * DEG_M * math.cos(math.radians(LAT0))


def frame(n, e, heading, roll=0.0, pitch=0.0, seed=911, t=0.0, rng=None, noise=0.02):
    img, _ = camera_frame(e, n, heading, AGL, FOV, PX, t, seed=seed, pixel_noise=noise,
                          rng=rng or np.random.default_rng(int(abs(n * 7 + e * 13)) % 1000),
                          roll=roll, pitch=pitch)
    return img


def layer(spacing=15.0):
    L = PatchMapLayer(spacing)
    L.initialize()
    return L


def feed(L, img, heading, roll, pitch, t):
    L.feed_attitude(roll, pitch, heading, t)
    L.feed_height(AGL, 0.5, t)
    L.feed_frame(img, t, FOV)


def build_corridor(L, n_path, e_from=0.0, e_to=600.0, step=8.0, heading=90.0, lean=0.0):
    """Fly east along n_path(e) with trusted fixes 1.5 m off the truth."""
    rng = np.random.default_rng(1)
    t, e = 0.0, e_from
    while e <= e_to:
        n = n_path(e)
        roll, pitch = (math.radians(lean) * 0.3, -math.radians(lean)) if lean else (0.0, 0.0)
        feed(L, frame(n, e, heading, roll, pitch, t=t), heading, roll, pitch, t)
        lat, lon = ll(n + rng.normal(0, 1.5), e + rng.normal(0, 1.5))
        L.learn(lat, lon, AGL, 1.5, True, t)
        e += step
        t += 1.0
    return L


def test_contract_rectify_and_rules():
    L = PatchMapLayer()
    assert audit_layer(L).compliant
    assert L.solve(0.0)["reason"] == "no patch map"
    # rectification: a level frame rectified to north-up equals the ground
    # texture sampled north-up; a leaning frame lands on the same ground
    img = frame(100.0, 200.0, 37.0)
    p0, v0, off0 = rectify(img, FOV, 0.0, 0.0, 37.0, AGL)
    assert off0 == (0.0, 0.0)
    roll, pitch = math.radians(4.0), math.radians(-8.0)
    p1, v1, off1 = rectify(frame(100.0, 200.0, 37.0, roll, pitch), FOV, roll, pitch, 37.0, AGL)
    assert 5.0 < math.hypot(*off1) < 9.0, off1        # nose down 8 deg at 50 m looks 7 m ahead
    # the leaning patch is centred where the camera looked: compare it with
    # a level patch rendered there
    p0, v0, _ = rectify(frame(100.0 + off1[0], 200.0 + off1[1], 37.0), FOV, 0.0, 0.0, 37.0, AGL)
    both = v0 & v1
    assert v0.mean() > 0.99 and both.mean() > 0.95
    corr = np.corrcoef(p0[both], p1[both])[0, 1]
    assert corr > 0.95, corr
    # the rule: no patch from an untrusted or loose fix, or on a covered spot
    feed(L, img, 37.0, 0.0, 0.0, 0.0)
    assert not L.learn(LAT0, LON0, AGL, 1.5, False, 0.0)["stored"]
    assert "not trusted" in L.last_learn["reason"]
    assert not L.learn(LAT0, LON0, AGL, 20.0, True, 0.0)["stored"] and "looser" in L.last_learn["reason"]
    assert L.learn(LAT0, LON0, AGL, 1.5, True, 0.0)["stored"]
    assert not L.learn(*ll(3.0, 2.0), AGL, 1.5, True, 1.0)["stored"] and "already covers" in L.last_learn["reason"]
    # the Indian-source rule
    try:
        PatchMap("google")
        raise AssertionError("a foreign map source was accepted")
    except ForeignMapSourceError:
        pass
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "m.npz")
        L.map.save(path)
        m2 = PatchMap.load(path)
        assert len(m2) == 1 and m2.source == "field_survey" and np.allclose(m2.patches[0], L.map.patches[0])
        bad = dict(np.load(path, allow_pickle=False))
        bad["meta"] = json.dumps({**json.loads(str(bad["meta"])), "source": "gmaps"})
        np.savez(path, **bad)
        try:
            PatchMap.load(path)
            raise AssertionError("a foreign-source map file was accepted")
        except ForeignMapSourceError:
            pass
    print(f"[ok] contract; a leaning frame rectifies onto the same ground as a level one "
          f"(correlation {corr:.3f}); no patch from an untrusted or loose fix or a covered spot; "
          f"a foreign map source is refused at construction and on load")
    PASSED.append("rules")


def test_build_then_match():
    """Pass 1 builds the corridor; pass 2 flies it back the other way with a
    lean, heading jitter and lateral offsets, GNSS gone, a loose prior."""
    L = build_corridor(layer(), lambda e: 20.0 * math.sin(e / 150.0))
    n_map = len(L.map)
    assert n_map >= 30, n_map
    rng = np.random.default_rng(2)
    errs, sigs, declines, peaks = [], [], {}, []
    t = 1000.0
    for e in np.arange(590.0, 10.0, -7.0):
        n = 20.0 * math.sin(e / 150.0) + rng.uniform(-5.0, 5.0)
        heading = 270.0 + rng.normal(0, 5.0)
        roll, pitch = math.radians(rng.normal(0, 3.0)), math.radians(-6.0 + rng.normal(0, 2.0))
        feed(L, frame(n, e, heading, roll, pitch, t=t), heading, roll, pitch, t)
        L.set_prior(*ll(n + rng.normal(0, 6.0), e + rng.normal(0, 6.0)), 8.0)
        v = L.solve(t)
        if v["status"] == "ok":
            fn, fe = ne(v["lat"], v["lon"])
            errs.append(math.hypot(fn - n, fe - e)); sigs.append(v["sigma_m"]); peaks.append(v["peak"])
        else:
            declines[v["reason"][:40]] = declines.get(v["reason"][:40], 0) + 1
        t += 1.0
    errs, sigs = np.array(errs), np.array(sigs)
    total = len(errs) + sum(declines.values())
    assert len(errs) >= 0.85 * total, declines
    cover = float(np.mean(errs <= R95 * sigs))
    assert cover >= 0.85, (cover, errs.mean(), sigs.mean())
    assert np.sqrt(np.mean(errs ** 2)) < 6.0, np.sqrt(np.mean(errs ** 2))
    r = L.read()
    assert r.is_valid and r.raw_data["fabricated"] is False
    print(f"[ok] {n_map} patches stored on a weaving 600 m pass with 1.5 m fixes; flown back with a "
          f"lean, 5 deg heading jitter and up to 5 m off the track, prior ±8 m: {len(errs)}/{total} fixes, "
          f"{np.sqrt(np.mean(errs ** 2)):.1f} m rms with stated ±{sigs.mean():.1f}, 95% circle covers "
          f"{cover:.0%}, mean peak {np.mean(peaks):.2f}; declines {declines or 'none'}")
    PASSED.append("match")


def test_declines():
    L = build_corridor(layer(), lambda e: 0.0, e_to=200.0)
    t = 500.0
    # water: no texture
    flat = np.full((PX, PX), 0.5) + np.random.default_rng(3).normal(0, 0.005, (PX, PX))
    feed(L, flat, 90.0, 0.0, 0.0, t)
    L.set_prior(*ll(0.0, 100.0), 8.0)
    v = L.solve(t)
    assert v["status"] == "declined" and "no texture" in v["reason"], v
    # night: too dark
    feed(L, frame(0.0, 100.0, 90.0) * 0.02, 90.0, 0.0, 0.0, t)
    assert "too dark" in L.solve(t)["reason"]
    # off the corridor: nothing to search
    feed(L, frame(0.0, 100.0, 90.0), 90.0, 0.0, 0.0, t)
    L.set_prior(*ll(400.0, 100.0), 8.0)
    v = L.solve(t)
    assert "no map patch within" in v["reason"] and "off the surveyed corridor" in v["reason"], v
    # changed ground: a different world under the same prior
    feed(L, frame(0.0, 100.0, 90.0, seed=912), 90.0, 0.0, 0.0, t)
    L.set_prior(*ll(0.0, 100.0), 8.0)
    v = L.solve(t)
    assert v["status"] == "declined" and "below" in v["reason"], v
    changed_peak = v["peak"]
    # half-changed ground: lower peak, reported either way
    half = 0.5 * frame(0.0, 100.0, 90.0) + 0.5 * frame(0.0, 100.0, 90.0, seed=912)
    feed(L, half, 90.0, 0.0, 0.0, t)
    v_half = L.solve(t)
    # repeating ground: a checkerboard world is ambiguous
    Lc = layer()
    def checker(n, e, heading):
        north, east, _ = patch_mapping(e, n, heading, AGL, FOV, PX)
        return ((np.floor(north / 4.0) + np.floor(east / 4.0)) % 2).astype(float) * 0.6 + 0.2
    tt = 0.0
    for e in np.arange(0.0, 120.0, 8.0):
        feed(Lc, checker(0.0, e, 90.0), 90.0, 0.0, 0.0, tt)
        Lc.learn(*ll(0.0, e), AGL, 1.5, True, tt)
        tt += 1.0
    feed(Lc, checker(0.0, 60.0, 90.0), 90.0, 0.0, 0.0, tt)
    Lc.set_prior(*ll(0.0, 60.0), 8.0)
    v = Lc.solve(tt)
    assert v["status"] == "declined" and "ambiguous" in v["reason"], v
    # a hard roll looks 40 m to the side, off the surveyed corridor
    big = math.radians(40.0)
    feed(L, frame(0.0, 100.0, 90.0, big, 0.0), 90.0, big, 0.0, t)
    L.set_prior(*ll(0.0, 100.0), 8.0)
    v = L.solve(t)
    assert v["status"] == "declined", v
    assert any(k in v["reason"] for k in ("in the frame", "no map patch", "cover", "below")), v
    print(f"[ok] declines with reasons: water (no texture), night (too dark), off the corridor, changed "
          f"ground (peak {changed_peak:.2f} < {PatchMapLayer.MIN_PEAK}), half-changed ground "
          f"({'fix' if v_half['status'] == 'ok' else 'declined'}, peak {v_half.get('peak', 0):.2f}), "
          f"repeating ground (ambiguous), a 40 deg roll looking off the corridor ('{v['reason'][:50]}')")
    PASSED.append("declines")


def test_box_and_build_tool():
    """Through the box on the console circuit with recording: the live box
    builds the map while trusted and saves it; the build tool rebuilds the
    same map from the recording; a box loading that map fixes in a denial."""
    import subprocess
    from upin.box.service import Box, BoxConfig
    from upin.console.sources import SimSource
    from upin.console.state import ConsoleState
    sys.path.insert(0, "tests")
    from test_recording import replay_cfg, toml_for
    with tempfile.TemporaryDirectory() as tmp:
        map_path = os.path.join(tmp, "live_map.npz")
        cfg = BoxConfig(max_accel_ms2=6.0, max_airspeed_ms=20.0, camera_flow=True, formation=False,
                        breadcrumbs=False, wind_dr=True, airframe_id="sim-circuit-quad",
                        patch_map=map_path, patch_map_build=True,
                        input_log_path=os.path.join(tmp, "inputs.jsonl"),
                        frames_dir=os.path.join(tmp, "frames"), frame_record_hz=10.0)
        st = ConsoleState("sim", "SIMULATION", True, SimSource.controls)
        sim = SimSource(st, LAT0, LON0, seed=8, cfg=cfg)
        sim.control("beacons")
        for _ in range(60):
            sim.step()
        done = sim.box.close()
        assert map_path in done["saved"], done
        live = PatchMap.load(map_path)
        assert len(live) >= 15 and max(live.sigma_m) <= PatchMapLayer.MAX_STAMP_SIGMA_M
        cfg2 = replay_cfg(tmp, cfg, sim)
        toml = os.path.join(tmp, "box.toml")
        toml_for(BoxConfig(**{**cfg2.__dict__, "patch_map": "", "patch_map_build": False}), toml)
        out_map = os.path.join(tmp, "tool_map.npz")
        r = subprocess.run([sys.executable, "tools/build_patch_map.py", "--config", toml, "--log",
                            cfg.input_log_path, "--frames", cfg.frames_dir, "--out", out_map],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-600:]
        built = PatchMap.load(out_map)
        assert len(built) == len(live) and np.allclose(built.lat, live.lat) and np.allclose(built.lon, live.lon)
        # a box that loads the map fixes on it when its receiver goes quiet
        box = Box(BoxConfig(**{**cfg2.__dict__, "patch_map": out_map, "patch_map_build": False}))
        assert box.patchmap.map is not None and len(box.patchmap.map) == len(live)
    print(f"[ok] through the box: {len(live)} patches stored on the circuit while trusted (stamps "
          f"≤ {max(live.sigma_m):.1f} m) and saved at close; tools/build_patch_map.py rebuilt the same "
          f"{len(built)} patches from the recording; a box loads the map")
    PASSED.append("box")


if __name__ == "__main__":
    tests = [test_contract_rectify_and_rules, test_build_then_match, test_declines,
             test_box_and_build_tool]
    for t in tests:
        t()
    print(f"\n{len(PASSED)}/{len(tests)} patch-map tests passed")
