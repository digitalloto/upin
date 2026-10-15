"""Tests for layer 153, formation cross-check and cooperative fix.

SIMULATED drones (upin/simulation/formation.py) fly a circuit in a V,
each with its own receiver, exchanging signed messages and ranges. Tests
the check's verdicts (no false alarms, the single-spoofer signature, the
odd one out, the stated tailored-spoofer limit), the cooperative fix and
its declines (one peer, collinear, mirror ambiguity), the message
refusals, and the path through the box.

Run: python tests/test_formation.py
"""
import json
import math
import sys

sys.path.insert(0, ".")

import numpy as np  # noqa: E402

from upin.box.gnss_parser import encode_mon_rf, encode_nav_pvt  # noqa: E402
from upin.box.fc_reader import P0_HPA  # noqa: E402
from upin.box.gateway import DEGRADED, TRUSTED  # noqa: E402
from upin.box.service import Box, BoxConfig  # noqa: E402
from upin.console.sources import Msg  # noqa: E402
from upin.core.no_fabrication import NoFixReason, audit_layer  # noqa: E402
from upin.layers.rf.beacon_ranging import DEG_M, hop_channel  # noqa: E402
from upin.layers.rf.formation import (PEER_PREFIX, SOURCE_UPIN, FormationLayer,  # noqa: E402
                                      sign_peer_message, verify_peer_message)
from upin.simulation.formation import SimDrone, SimFormation  # noqa: E402

PASSED = []
LAT0, LON0 = 13.0827, 80.2707
SECRET = b"formation-test-secret"
L, R, V, ALT = 400.0, 80.0, 8.0, 50.0
R95 = 2.4477


def ll(n, e):
    return LAT0 + n / DEG_M, LON0 + e / (DEG_M * math.cos(math.radians(LAT0)))


def ne(lat, lon):
    return (lat - LAT0) * DEG_M, (lon - LON0) * DEG_M * math.cos(math.radians(LAT0))


def circuit(t):
    """A stadium: two straights L apart joined by half circles of radius R."""
    P = 2 * L + 2 * math.pi * R
    s = (V * t) % P
    if s < L:
        return -R, -L / 2 + s, 0.0, V
    s -= L
    if s < math.pi * R:
        a = -math.pi / 2 + s / R
        return R * math.sin(a), L / 2 + R * math.cos(a), V * math.cos(a), -V * math.sin(a)
    s -= math.pi * R
    if s < L:
        return R, L / 2 - s, 0.0, -V
    s -= L
    a = math.pi / 2 + s / R
    return R * math.sin(a), -L / 2 + R * math.cos(a), V * math.cos(a), -V * math.sin(a)


V_FORMATION = [SimDrone("lead", 0.0, 0.0), SimDrone("w1", -40.0, -40.0), SimDrone("w2", -40.0, 40.0)]


def layers(ids):
    out = {}
    for i in ids:
        lyr = FormationLayer(i)
        lyr.initialize()
        lyr.set_secret(SECRET)
        out[i] = lyr
    return out


def exchange(sim, lyrs, t):
    """Every drone hears every other's message and its own radio's ranges."""
    msgs = {i: sim.message(i, t) for i in lyrs}
    for i, lyr in lyrs.items():
        for j, m in msgs.items():
            if j != i and m is not None:
                lyr.feed_message(m, t)
        for pid, r, s in sim.ranges_for(i):
            lyr.feed_range(pid, r, s, t)


def own_check(lyr, rep, t):
    return lyr.check(rep.lat, rep.lon, rep.alt_m, rep.sigma_m, t)


def test_contract_and_refusals():
    lyr = FormationLayer("a")
    assert audit_layer(lyr).compliant
    assert lyr.solve(0.0)["reason_code"] == NoFixReason.NO_CALIBRATION
    assert lyr.check(LAT0, LON0, ALT, 1.5, 0.0)["verdict"] == "NOT_RUN"
    lyr.set_secret(SECRET)
    good = {"id": PEER_PREFIX + "b", "t": 10.0, "lat": LAT0, "lon": LON0, "alt_m": ALT,
            "sigma_m": 1.5, "seq": 5, "channel": hop_channel(SECRET, 10.0), "vn": 1.0, "ve": 0.0,
            "trusted": True, "source": "gnss", "ranges": [[PEER_PREFIX + "c", 80.0, 10.0]]}
    unsigned = dict(good, sig="0" * 16)
    assert lyr.feed_message(unsigned, 10.0) == "bad signature"
    flipped = dict(sign_peer_message(good, SECRET))
    flipped["trusted"] = False                          # the trust flag is signed too
    assert lyr.feed_message(flipped, 10.0) == "bad signature"
    assert verify_peer_message(sign_peer_message(good, SECRET), SECRET)
    nearby = {hop_channel(SECRET, 10.0 + k) for k in (-1, 0, 1)}
    off = sign_peer_message(dict(good, channel=next(c for c in range(32) if c not in nearby)), SECRET)
    assert lyr.feed_message(off, 10.0) == "off the hop schedule"
    assert lyr.feed_message(sign_peer_message(good, SECRET), 20.0).endswith("s old")
    assert lyr.feed_message(sign_peer_message(good, SECRET), 10.0) == "accepted"
    assert lyr.feed_message(sign_peer_message(good, SECRET), 10.0) == "replayed (sequence not newer)"
    assert lyr.feed_message({"id": "x"}, 10.0) == "malformed message"
    bad_src = sign_peer_message(dict(good, seq=6, source="oracle"), SECRET)
    assert lyr.feed_message(bad_src, 10.0) == "unknown fix source"
    own = sign_peer_message(dict(good, id=PEER_PREFIX + "a", seq=7), SECRET)
    assert lyr.feed_message(own, 10.0) == "own message ignored"
    assert lyr.feed_range(PEER_PREFIX + "zz", 50.0, 10.0, 10.0) == "range from a peer with no accepted message"
    assert lyr.feed_range(PEER_PREFIX + "b", 50.0, 0.0, 10.0) == "range without a stated sigma"
    assert lyr.feed_range(PEER_PREFIX + "b", 50.0, 10.0, 10.0) == "accepted"
    # a peer whose fix came from UPIN (coasting, or this very layer) is never an anchor
    coasting = sign_peer_message(dict(good, seq=8, trusted=False, source=SOURCE_UPIN), SECRET)
    assert lyr.feed_message(coasting, 10.0) == "accepted"
    lyr.feed_range(PEER_PREFIX + "b", 50.0, 10.0, 10.0)
    lyr.set_altitude(ALT, 1.0, 10.0)
    v = lyr.solve(10.0)
    assert v["reason_code"] == NoFixReason.INSUFFICIENT_INPUT and "never anchors" in v["reason"], v
    assert sum(lyr.rejected.values()) == 9, lyr.rejected
    print("[ok] contract; unsigned, flipped-flag, off-schedule, stale, replayed, malformed and "
          "unknown-source messages refused and counted; own echo ignored; a peer coasting on UPIN "
          "is never an anchor")
    PASSED.append("refusals")


def fly(seconds, drones=V_FORMATION, seed=1, **step_kw):
    """Fly the formation; yield (t, sim, layers, reports) each second after
    the first exchange so every layer has every peer."""
    sim = SimFormation(drones, SECRET, circuit, ll, V, ALT, seed=seed)
    lyrs = layers([d.drone_id for d in drones])
    for k in range(seconds):
        t = float(k)
        kw = {key: (val(t) if key == "spoof" and callable(val) else val) for key, val in step_kw.items()}
        reps = sim.step(t, 1.0, **kw)
        exchange(sim, lyrs, t)
        if k >= 1:
            yield t, sim, lyrs, reps


def test_honest_formation_no_false_alarms():
    verdicts, pairs, failed = {}, 0, 0
    for t, sim, lyrs, reps in fly(300):
        for i, lyr in lyrs.items():
            v = own_check(lyr, reps[i], t)
            verdicts[v["verdict"]] = verdicts.get(v["verdict"], 0) + 1
            pairs += len(v["pairs"])
            failed += sum(1 for p in v["pairs"] if not p["ok"])
            assert v["n_pairs"] == 3, v
    assert verdicts.get("FAIL", 0) == 0, verdicts
    assert verdicts.get("WARN", 0) <= 0.02 * sum(verdicts.values()), verdicts
    print(f"[ok] honest V formation, 300 s on a circuit with turns, three drones each checking: "
          f"{verdicts}; {failed} of {pairs} pair tests over |z| = {FormationLayer.Z_MAX:.0f} "
          f"({failed / pairs:.2%}; a standard normal gives 0.27%)")
    PASSED.append("honest")


def test_common_spoof_detected():
    """One spoofer: every receiver reports the same place. Each receiver
    alone looks healthy; the formation check fails on every drone."""
    verdicts = {}
    for t, sim, lyrs, reps in fly(40, spoof=lambda t: (circuit(t)[0] + 300.0, circuit(t)[1] + 150.0)):
        if t < 5:
            continue
        for i, lyr in lyrs.items():
            rep = reps[i]
            assert rep.has_fix and rep.sigma_m == 1.5                  # the receiver looks fine
            v = own_check(lyr, rep, t)
            verdicts[(i, v["verdict"], v.get("pattern"))] = verdicts.get((i, v["verdict"], v.get("pattern")), 0) + 1
            assert v["verdict"] == "FAIL" and v["pattern"] == "common_spoof", v
            assert all(p["reported_m"] < 0.2 * p["range_m"] for p in v["pairs"]), v["pairs"]
    sample = next(iter(lyrs.values())).last_check
    print(f"[ok] single spoofer, every receiver reporting one place 300 m off: all three drones "
          f"FAIL 'common spoof' on every epoch ({len(verdicts)} drone/verdict kinds, all FAIL); "
          f"reported distances {np.mean([p['reported_m'] for p in sample['pairs']]):.0f} m against "
          f"ranges {np.mean([p['range_m'] for p in sample['pairs']]):.0f} m; each receiver alone "
          f"had a 3-D fix with a stated 1.5 m accuracy")
    PASSED.append("common")


def test_odd_one_out():
    """One wingman's receiver is 60 m off: the lead's check passes and names
    it suspect, the wingman's own check fails, and it is no longer an anchor."""
    lead_ok, w1_fail = 0, 0
    for t, sim, lyrs, reps in fly(40, offsets={"w1": (60.0, 0.0)}):
        if t < 5:
            continue
        v = own_check(lyrs["lead"], reps["lead"], t)
        if v["verdict"] == "PASS" and v.get("suspect") == PEER_PREFIX + "w1":
            lead_ok += 1
        if own_check(lyrs["w1"], reps["w1"], t)["verdict"] == "FAIL":
            w1_fail += 1
        if v.get("suspect") == PEER_PREFIX + "w1":
            assert PEER_PREFIX + "w1" not in [p.peer_id for p in lyrs["lead"].anchors(t)]
    assert lead_ok >= 30 and w1_fail >= 30, (lead_ok, w1_fail)
    lyrs["lead"].set_altitude(ALT, 1.0, t)
    lyrs["lead"].set_prior(*ll(*ne(reps["lead"].true_lat, reps["lead"].true_lon)), 5.0)
    v = lyrs["lead"].solve(t)
    assert v["reason_code"] == NoFixReason.INSUFFICIENT_INPUT and "one peer can detect" in v["reason"], v
    print(f"[ok] one wingman 60 m off: the lead PASSES naming it suspect ({lead_ok}/35 epochs), the "
          f"wingman's own check FAILS ({w1_fail}/35); with it excluded one anchor is left and the fix "
          f"declines: '{v['reason']}'")
    PASSED.append("odd")


def test_cooperative_fix_two_peers():
    """The lead loses its fix; the two wingmen hold trusted GNSS. Two ranges
    and altitude place the lead, the prior resolving the mirror."""
    errs, sigs, hdops, declines = [], [], [], {}
    rng = np.random.default_rng(7)
    for t, sim, lyrs, reps in fly(120, has_fix=lambda did, lat, lon: did != "lead"):
        lead = lyrs["lead"]
        rep = reps["lead"]
        assert not rep.has_fix
        lead.set_altitude(ALT + rng.normal(0, 1.0), 1.0, t)
        pn, pe = rep.true_n + rng.normal(0, 3.0), rep.true_e + rng.normal(0, 3.0)
        lead.set_prior(*ll(pn, pe), 5.0)                      # the filter's coasting estimate
        v = lead.solve(t)
        if v["status"] == "ok":
            n, e = ne(v["lat"], v["lon"])
            errs.append(math.hypot(n - rep.true_n, e - rep.true_e))
            sigs.append(v["sigma_m"])
            hdops.append(v["hdop"])
            assert v["n_anchors"] == 2 and v["mirror_distance_m"] > 40.0, v
        else:
            declines[v["reason_code"]] = declines.get(v["reason_code"], 0) + 1
    errs, sigs = np.array(errs), np.array(sigs)
    assert len(errs) >= 0.9 * (len(errs) + sum(declines.values())), declines
    cover = float(np.mean(errs <= R95 * sigs))
    assert cover >= 0.85, cover
    assert np.sqrt(np.mean(errs ** 2)) < 2.0 * sigs.mean(), (errs.mean(), sigs.mean())
    print(f"[ok] lead without GNSS, two trusted wingmen 40 m back and ±40 m aside, 10 m ranging: "
          f"{len(errs)} fixes in 119 s, {np.sqrt(np.mean(errs ** 2)):.0f} m rms with a stated sigma of "
          f"{sigs.mean():.0f} m, 95% circle covers {cover:.0%}, HDOP {np.mean(hdops):.1f}; mirror "
          f"{lyrs['lead'].last['mirror_distance_m']:.0f} m away, resolved by a ±5 m prior; "
          f"declines {declines or 'none'}")
    PASSED.append("coop")


def test_one_peer_cannot_place_me():
    two = [SimDrone("lead", 0.0, 0.0), SimDrone("w1", -40.0, -40.0)]
    for t, sim, lyrs, reps in fly(10, drones=two, has_fix=lambda did, lat, lon: did != "lead"):
        pass
    lead = lyrs["lead"]
    lead.set_altitude(ALT, 1.0, t)
    lead.set_prior(reps["lead"].true_lat, reps["lead"].true_lon, 5.0)
    v = lead.solve(t)
    assert v["reason_code"] == NoFixReason.INSUFFICIENT_INPUT and "one peer can detect" in v["reason"]
    # but that one peer still lets the lead judge a fix: a spoof on both is caught as a pair warning
    c = lead.check(*ll(reps["w1"].true_n, reps["w1"].true_e), ALT, 1.5, t)
    assert c["verdict"] == "WARN" and c["pattern"] == "one_pair", c
    print(f"[ok] with one peer: no fix ('{v['reason']}'); the check still runs and a fix sitting on "
          f"the peer's own position is flagged as a pair warning, undetermined")
    PASSED.append("one_peer")


def test_collinear_and_mirror():
    """On the line between its peers the lead cannot be fixed; a loose prior
    cannot pick the mirror; a tight prior picks the right side."""
    line = [SimDrone("lead", -40.0, 0.0), SimDrone("w1", -40.0, -40.0), SimDrone("w2", -40.0, 40.0)]
    poor = 0
    for t, sim, lyrs, reps in fly(20, drones=line, has_fix=lambda did, lat, lon: did != "lead"):
        lead = lyrs["lead"]
        lead.set_altitude(ALT, 1.0, t)
        lead.set_prior(reps["lead"].true_lat, reps["lead"].true_lon, 5.0)
        v = lead.solve(t)
        poor += v["status"] == "declined" and v["reason_code"] == NoFixReason.POOR_GEOMETRY
    assert poor >= 17, poor
    for t, sim, lyrs, reps in fly(10, has_fix=lambda did, lat, lon: did != "lead"):
        pass
    lead = lyrs["lead"]
    lead.set_altitude(ALT, 1.0, t)
    rep = reps["lead"]
    lead.set_prior(rep.true_lat, rep.true_lon, 100.0)
    v = lead.solve(t)
    assert v["reason_code"] == NoFixReason.POOR_GEOMETRY and "mirror ambiguous" in v["reason"], v
    lead.set_prior(rep.true_lat, rep.true_lon, 5.0)
    v = lead.solve(t)
    assert v["status"] == "ok"
    n, e = ne(v["lat"], v["lon"])
    err = math.hypot(n - rep.true_n, e - rep.true_e)
    assert err < 3.0 * v["sigma_m"], (err, v["sigma_m"])
    # a prior far from both candidates is refused rather than snapped to one
    lead.set_prior(*ll(rep.true_n + 500.0, rep.true_e), 5.0)
    w = lead.solve(t)
    assert w["reason_code"] == NoFixReason.FAILED_VALIDATION and "neither candidate" in w["reason"], w
    print(f"[ok] lead on the wingmen's baseline: declined on geometry {poor}/19 epochs; at the apex "
          f"with a ±100 m prior: '{v['reason'] if v['status'] != 'ok' else 'mirror ambiguous'}' -> "
          f"declined; with a ±5 m prior the right side is chosen ({err:.0f} m error, ±{v['sigma_m']:.0f} m, "
          f"mirror {v['mirror_distance_m']:.0f} m away); a prior 500 m off is refused")
    PASSED.append("mirror")


def test_tailored_spoof_passes_stated_limit():
    """A multi-transmitter spoofer shifting every drone by the same offset
    keeps the geometry: the check passes. The stated limit, kept true."""
    passes = total = 0
    for t, sim, lyrs, reps in fly(30, tailored=(120.0, 80.0)):
        if t < 5:
            continue
        total += 1
        passes += own_check(lyrs["lead"], reps["lead"], t)["verdict"] == "PASS"
    assert passes >= 0.95 * total, (passes, total)
    print(f"[ok] STATED LIMIT: a tailored spoofer shifting all three drones by the same 144 m "
          f"passes the formation check ({passes}/{total} epochs); only a geometry-breaking spoof is caught")
    PASSED.append("tailored")


def test_three_anchors_use_layer_151():
    four = V_FORMATION + [SimDrone("w3", -80.0, 0.0)]
    errs, sigs = [], []
    for t, sim, lyrs, reps in fly(60, drones=four, has_fix=lambda did, lat, lon: did != "lead"):
        lead = lyrs["lead"]
        lead.set_altitude(ALT, 1.0, t)
        lead.set_prior(reps["lead"].true_lat, reps["lead"].true_lon, 5.0)
        v = lead.solve(t)
        if v["status"] == "ok":
            assert v["n_anchors"] == 3 and "151" in v["method"], v
            n, e = ne(v["lat"], v["lon"])
            errs.append(math.hypot(n - reps["lead"].true_n, e - reps["lead"].true_e))
            sigs.append(v["sigma_m"])
    errs, sigs = np.array(errs), np.array(sigs)
    assert len(errs) >= 50 and np.mean(errs <= R95 * sigs) >= 0.85, (len(errs), np.mean(errs <= R95 * sigs))
    r = lyrs["lead"].read()
    assert r.is_valid and r.raw_data["fabricated"] is False
    print(f"[ok] four-drone formation, lead without GNSS: three anchors go through layer 151's "
          f"solver, {len(errs)} fixes, {np.sqrt(np.mean(errs ** 2)):.0f} m rms, stated ±{sigs.mean():.0f} m")
    PASSED.append("many")


def test_through_the_box():
    """The box checks its own fix against the formation, broadcasts its own
    signed message, and when its receiver goes quiet takes a formation fix
    that re-anchors the reachable region."""
    cfg = BoxConfig(max_accel_ms2=6.0, max_airspeed_ms=20.0, max_degraded_h_acc_m=1e6,
                    formation=True, drone_id="lead", formation_check_action="distrust")
    box = Box(cfg)
    box.formation.set_secret(SECRET)
    sent = []
    box._radio_out = sent.append
    sim = SimFormation(V_FORMATION, SECRET, circuit, ll, V, ALT, seed=5)
    rng = np.random.default_rng(5)
    press = P0_HPA * (1 - ALT / 44330.0) ** 5.255
    fixes, errs, checks = 0, [], {}
    for k in range(100):
        t = float(k)
        denied = 40 <= k < 90
        reps = sim.step(t, 1.0, has_fix=lambda did, lat, lon: did != "lead" or not denied)
        lead = reps["lead"]
        hdg = math.degrees(math.atan2(lead.ve, lead.vn)) % 360
        box.on_fc_message(Msg("ATTITUDE", roll=0.0, pitch=0.0, yaw=math.radians(hdg)), t)
        box.on_fc_message(Msg("SCALED_PRESSURE", press_abs=press, temperature=3000), t)
        for j in ("w1", "w2"):
            box.on_beacon_line(json.dumps({"type": "msg", **sim.message(j, t)}), t)
        for pid, r, s in sim.ranges_for("lead"):
            box.on_beacon_line(json.dumps({"type": "range", "id": pid, "range_m": r, "sigma_m": s}), t)
        if denied:
            data = encode_mon_rf("critical") + encode_nav_pvt(int(t * 1000), 0, 0, 0, 0, 0, (0, 0, 0), 0,
                                                              fix_type=0, num_sv=0)
        else:
            data = encode_mon_rf("ok") + encode_nav_pvt(
                int(t * 1000), lead.lat, lead.lon, ALT, 1.5, 3.0,
                (lead.vn + rng.normal(0, 0.1), lead.ve + rng.normal(0, 0.1), 0.0), 0.15)
        for out, gps in box.on_receiver_bytes(data, t, 1.7e9 + t):
            c = [x for x in box.gateway.last_checks if x["check"] == "formation consistency"][0]
            checks[c["status"]] = checks.get(c["status"], 0) + 1
            if k < 40 and k > 2:
                assert out.mode == TRUSTED and c["status"] == "PASS", (k, out.mode, c)
            if denied and k > 42:
                assert out.mode == DEGRADED, (k, out.mode, out.reasons)
                assert c["status"] == "NOT RUN" and "no own GNSS fix" in c["detail"], c
                f = box.last_formation
                if f["status"] == "ok":
                    fixes += 1
                    assert f["fix"]["accepted"] and f["fix"]["anchored"], f["fix"]
                    n, e = ne(out.lat, out.lon)
                    errs.append(math.hypot(n - lead.true_n, e - lead.true_e))
    assert fixes >= 40, (fixes, box.last_formation)
    errs = np.array(errs)
    assert errs.max() < 60.0 and errs.mean() < 25.0, (errs.mean(), errs.max())
    rec = box.last_record
    assert rec["formation"]["status"] in ("ok", "declined", "standby") and "formation" in rec["fixes"]
    # the box's own broadcasts: signed, trust flag following the mode
    msgs = [json.loads(s) for s in sent if json.loads(s).get("type") == "msg"]
    assert len(msgs) >= 90 and all(verify_peer_message(m, SECRET) for m in msgs)
    assert msgs[10]["trusted"] is True and msgs[10]["source"] == "gnss"
    assert msgs[60]["trusted"] is False and msgs[60]["source"] == SOURCE_UPIN
    assert any(len(m["ranges"]) == 2 for m in msgs)
    try:
        Box(BoxConfig(max_accel_ms2=6.0, max_airspeed_ms=20.0, formation_check_action="shout"))
        raise AssertionError("bad formation_check_action accepted")
    except ValueError:
        pass
    print(f"[ok] through the box: 'formation consistency' {checks}; receiver silent for 50 s -> "
          f"{fixes} formation fixes accepted and re-anchoring, output error {errs.mean():.0f} m mean, "
          f"{errs.max():.0f} m worst; {len(msgs)} own messages broadcast, all verify, trust flag "
          f"follows the mode; bad action refused")
    PASSED.append("box")


if __name__ == "__main__":
    tests = [test_contract_and_refusals, test_honest_formation_no_false_alarms,
             test_common_spoof_detected, test_odd_one_out, test_cooperative_fix_two_peers,
             test_one_peer_cannot_place_me, test_collinear_and_mirror,
             test_tailored_spoof_passes_stated_limit, test_three_anchors_use_layer_151,
             test_through_the_box]
    for t in tests:
        t()
    print(f"\n{len(PASSED)}/{len(tests)} formation tests passed")
