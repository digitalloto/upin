"""Tests for the UPIN box: parsers, gateway decision, GPS_INPUT, replay.

UBX frames are built from the published message layouts -- synthetic test
vectors, not captures from a receiver. The NMEA sentences are the widely
published textbook examples. The flight is synthetic. Nothing here has
touched a receiver or a flight controller.

Run: python tests/test_box.py
"""
import json
import math
import struct
import sys

sys.path.insert(0, ".")

import numpy as np

from upin.box.gateway import DEGRADED, NO_FIX, TRUSTED, Gateway, GnssEpoch
from upin.box.gnss_parser import (Gga, MonRf, NavPvt, NavSat, Rmc, UbxStream,
                                  decode_ubx, nmea_sentence, parse_nmea,
                                  ubx_frame)
from upin.box.mavlink_out import GPS_EPOCH_UNIX, build, gps_week
from upin.box.replay import epoch_from_json, epoch_to_json, epochs_from_ubx, run
from upin.detection.constellation_check import CANNOT_RULE_OUT, ConstellationFix
from upin.detection.reachability import DEG_M, Envelope

PASSED = []
LAT0, LON0 = 13.0827, 80.2707
ENV = Envelope(max_accel_ms2=6.0, max_airspeed_ms=20.0)


def ll(n, e):
    return (LAT0 + n / DEG_M,
            LON0 + e / (DEG_M * math.cos(math.radians(LAT0))))


def pvt_payload(itow, lat, lon, hmsl_m=50.0, hacc_m=2.5, vel=(5.0, 0.0, 0.0),
                fix=3, num_sv=14):
    p = bytearray(92)
    struct.pack_into("<IHBBBBBB", p, 0, itow, 2026, 10, 7, 12, 0, 0, 0x07)
    struct.pack_into("<BBBB", p, 20, fix, 0x01, 0, num_sv)
    struct.pack_into("<iiii", p, 24, round(lon * 1e7), round(lat * 1e7),
                     round(hmsl_m * 1000) + 86000, round(hmsl_m * 1000))
    struct.pack_into("<II", p, 40, round(hacc_m * 1000), 4000)
    struct.pack_into("<iiii", p, 48, *(round(v * 1000) for v in vel),
                     round(math.hypot(vel[0], vel[1]) * 1000))
    struct.pack_into("<I", p, 68, 300)
    struct.pack_into("<H", p, 76, 150)
    return bytes(p)


def test_ubx_nav_pvt_and_checksum():
    frame = ubx_frame(0x01, 0x07, pvt_payload(345600000, LAT0, LON0))
    s = UbxStream()
    msgs = [decode_ubx(*f) for f in s.feed(b"\x00garbage\xb5" + frame[:10])]
    msgs += [decode_ubx(*f) for f in s.feed(frame[10:])]
    assert len(msgs) == 1 and isinstance(msgs[0], NavPvt), msgs
    m = msgs[0]
    assert abs(m.lat - LAT0) < 1e-7 and abs(m.lon - LON0) < 1e-7
    assert m.fix_type == 3 and m.gnss_fix_ok and m.num_sv == 14
    assert abs(m.h_acc_m - 2.5) < 1e-9 and abs(m.s_acc_ms - 0.3) < 1e-9
    assert abs(m.vel_ned_ms[0] - 5.0) < 1e-9 and abs(m.pdop - 1.5) < 1e-9
    bad = bytearray(frame)
    bad[30] ^= 0x01
    s2 = UbxStream()
    assert list(s2.feed(bytes(bad))) == [] and s2.stats.bad_checksum == 1
    print("[ok] UBX NAV-PVT parsed across split reads after garbage; one "
          "flipped bit is rejected by the checksum")
    PASSED.append("pvt")


def test_ubx_nav_sat_and_mon_rf():
    sat = bytearray(8 + 24)
    struct.pack_into("<IBB", sat, 0, 1000, 1, 2)
    struct.pack_into("<BBBbhhI", sat, 8, 0, 5, 42, 60, 120, 0, 0x08 | 0x07)
    struct.pack_into("<BBBbhhI", sat, 20, 7, 3, 38, 45, 200, 0, 0x04)
    m = decode_ubx(0x01, 0x35, bytes(sat))
    assert isinstance(m, NavSat) and len(m.satellites) == 2
    assert m.satellites[0].constellation == "gps" and m.satellites[0].used
    assert m.satellites[1].constellation == "navic" and not m.satellites[1].used
    rf = bytearray(4 + 48)
    struct.pack_into("<BB", rf, 0, 0, 2)
    struct.pack_into("<BB", rf, 4, 0, 1)
    struct.pack_into("<HHB", rf, 16, 90, 3000, 10)
    struct.pack_into("<BB", rf, 28, 1, 3)
    struct.pack_into("<HHB", rf, 40, 240, 900, 200)
    r = decode_ubx(0x0A, 0x38, bytes(rf))
    assert isinstance(r, MonRf) and r.worst_state == "critical"
    assert r.blocks[1].jam_indicator == 200
    print("[ok] NAV-SAT gives constellation, C/N0 and used flag per satellite; "
          "MON-RF gives the receiver's jamming state per band")
    PASSED.append("sat_rf")


def test_nmea():
    gga = parse_nmea("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47")
    assert isinstance(gga, Gga) and gga.quality == 1 and gga.num_sv == 8
    assert abs(gga.lat - (48 + 7.038 / 60)) < 1e-9 and abs(gga.lon - (11 + 31 / 60)) < 1e-9
    rmc = parse_nmea("$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A")
    assert isinstance(rmc, Rmc) and rmc.valid and abs(rmc.speed_ms - 22.4 * 1852 / 3600) < 1e-9
    assert parse_nmea("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*48") is None
    south = parse_nmea(nmea_sentence("GNGGA,000000,1304.962,S,08016.242,W,1,10,0.8,12.0,M,,M,,"))
    assert south.lat < 0 and south.lon < 0
    print("[ok] NMEA GGA and RMC parsed; a wrong checksum is refused; S/W signs right")
    PASSED.append("nmea")


def flight(seconds, seed=3):
    """Truth: steady 8 m/s east with a gentle turn. Fixes 1 Hz, 2.5 m sigma."""
    rng = np.random.default_rng(seed)
    out = []
    for t in range(seconds):
        n, e = 20 * math.sin(t / 60.0), 8.0 * t
        vn, ve = (20 / 60.0) * math.cos(t / 60.0), 8.0
        out.append((float(t), n, e, vn, ve,
                    n + rng.normal(0, 2.5), e + rng.normal(0, 2.5)))
    return out


def epoch(t, n, e, vn, ve, **kw):
    lat, lon = ll(n, e)
    d = dict(t=t, fix_type=3, lat=lat, lon=lon, alt_m=50.0, h_acc_m=2.5,
             v_acc_m=4.0, vel_ned_ms=(vn, ve, 0.0), s_acc_ms=0.3, num_sv=14,
             jamming_state="ok")
    d.update(kw)
    return GnssEpoch(**d)


def test_gateway_honest_flight_trusted():
    """The statistical gate distrusts an honest fix about once in a thousand
    epochs by design. That costs one epoch, not a revalidation."""
    total = distrusted = 0
    for seed in range(10):
        gw = Gateway(ENV)
        for t, n, e, vn, ve, fn, fe in flight(300, seed):
            total += 1
            distrusted += gw.process(epoch(t, fn, fe, vn, ve)).mode != TRUSTED
    assert distrusted / total < 0.005, (distrusted, total)
    print(f"[ok] honest flights: {total - distrusted}/{total} epochs TRUSTED; "
          f"{distrusted} honest fixes distrusted by the statistical gate, one "
          f"epoch each (designed rate 0.001)")
    PASSED.append("honest")


def test_gateway_spoof_jump_then_return():
    gw = Gateway(ENV)
    trusted_acc = []
    outs = []
    for t, n, e, vn, ve, fn, fe in flight(200):
        if 100 <= t < 115:
            fe += 500.0                        # spoofer jumps 500 m east
        o = gw.process(epoch(t, fn, fe, vn, ve))
        outs.append(o)
        if o.mode == TRUSTED:
            trusted_acc.append(o.h_acc_m)
    spoofed = outs[100:115]
    assert all(o.mode == DEGRADED for o in spoofed), [o.mode for o in spoofed]
    assert any("physically impossible" in r for r in spoofed[0].reasons)
    assert spoofed[0].h_acc_m > max(trusted_acc)
    assert spoofed[-1].h_acc_m > spoofed[0].h_acc_m
    # Once the region has grown past 500 m only the Kalman gate rejects the
    # spoof; it still does, and says why.
    assert all(o.reasons for o in spoofed)
    truth_n, truth_e = flight(200)[114][1:3]
    o = spoofed[-1]
    err = math.hypot((o.lat - LAT0) * DEG_M - truth_n,
                     (o.lon - LON0) * DEG_M * math.cos(math.radians(LAT0)) - truth_e)
    back = [o.mode for o in outs[115:125]]
    assert back[:4] == [DEGRADED] * 4 and back[4] == TRUSTED, back
    print(f"[ok] 500 m spoof jump: rejected as physically impossible, UPIN's "
          f"estimate sent instead (h_acc {spoofed[0].h_acc_m:.1f} -> "
          f"{spoofed[-1].h_acc_m:.1f} m over 15 s with no velocity sensor, truth {err:.1f} m away); "
          f"real GNSS trusted again after 5 clean epochs")
    PASSED.append("spoof")


def test_optical_flow_keeps_estimate_tight():
    accs = {}
    rng = np.random.default_rng(11)
    for use_flow in (False, True):
        gw = Gateway(ENV, max_degraded_h_acc_m=1e6)   # report, don't cut off
        for t, n, e, vn, ve, fn, fe in flight(160):
            if t >= 100:
                if use_flow:
                    gw.feed_velocity(vn + rng.normal(0, 0.3),
                                     ve + rng.normal(0, 0.3), 0.3, t)
                o = gw.process(epoch(t, 0, 0, 0, 0, fix_type=0, h_acc_m=float("inf")))
            else:
                o = gw.process(epoch(t, fn, fe, vn, ve))
        accs[use_flow] = o
    assert accs[True].h_acc_m < accs[False].h_acc_m
    print(f"[ok] 60 s with no GNSS: h_acc {accs[False].h_acc_m:.0f} m coasting, "
          f"{accs[True].h_acc_m:.1f} m with optical-flow velocity (velocity "
          f"sigma 0.3 m/s assumed, not measured)")
    PASSED.append("flow")


def test_gateway_no_fix_cases():
    gw = Gateway(ENV, max_degraded_h_acc_m=20.0)
    o = gw.process(epoch(0, 0, 0, 0, 0, fix_type=0, h_acc_m=float("inf")))
    assert o.mode == NO_FIX and any("no trusted fix yet" in r for r in o.reasons)
    for t, n, e, vn, ve, fn, fe in flight(50):
        gw.process(epoch(t, fn, fe, vn, ve))
    modes = [gw.process(epoch(50 + k, 0, 0, 0, 0, fix_type=0,
                              h_acc_m=float("inf"))).mode for k in range(120)]
    assert modes[0] == DEGRADED and modes[-1] == NO_FIX
    o = gw.process(epoch(500, 0, 0, 0, 0, jamming_state="critical"))
    assert any("jamming" in r for r in o.reasons)
    print(f"[ok] NO_FIX before any trusted fix, and once coasting passes the "
          f"20 m limit (after {modes.index(NO_FIX)} s); receiver-reported "
          f"jamming distrusts the fix")
    PASSED.append("nofix")


def test_gateway_constellation_disagreement():
    gw = Gateway(ENV)
    for t, n, e, vn, ve, fn, fe in flight(20):
        gw.process(epoch(t, fn, fe, vn, ve))
    t, n, e, vn, ve, fn, fe = flight(21)[20]
    lat, lon = ll(fn, fe)
    blended = epoch(t, fn, fe, vn, ve, constellation_fixes=[
        ConstellationFix("gps", *ll(fn + 200, fe), 3.0),
        ConstellationFix("navic", lat, lon, 4.0),
        ConstellationFix("galileo", lat, lon, 3.0)])
    o = gw.process(blended)
    assert o.mode == DEGRADED and any("suspect: gps" in r for r in o.reasons), o.reasons
    gw2 = Gateway(ENV)
    o2 = gw2.process(epoch(0, 0, 0, 0, 0, constellation_fixes=[
        ConstellationFix("gps", *ll(0, 0), 3.0), ConstellationFix("navic", *ll(1, 1), 4.0)]))
    assert o2.mode == TRUSTED and o2.caveat == CANNOT_RULE_OUT
    print("[ok] constellations disagreeing distrusts the fix and names GPS; "
          "agreement passes and carries the cannot-rule-out caveat")
    PASSED.append("constellations")


def test_gps_input_message():
    gw = Gateway(ENV)
    trusted = gw.process(epoch(0, 0, 0, 1, 2))
    m = build(trusted, 1.8e9)
    assert m.fix_type == 3 and m.lat == round(LAT0 * 1e7) and m.horiz_accuracy == 2.5
    deg = gw.process(epoch(1, 0, 0, 0, 0, fix_type=0, h_acc_m=float("inf")))
    assert deg.mode == DEGRADED
    assert build(deg, 1.8e9).fix_type == 0
    fwd = build(deg, 1.8e9, forward_degraded=True)
    assert fwd.fix_type == 3 and fwd.horiz_accuracy == deg.h_acc_m
    assert gps_week(GPS_EPOCH_UNIX - 18) == (0, 0)
    print("[ok] GPS_INPUT: trusted fix sent as 3-D; degraded sent as no fix "
          "unless forward_degraded, then with UPIN's own h_acc (UNTESTED on a "
          "flight controller)")
    PASSED.append("gps_input")


def test_replay():
    data = b"".join(ubx_frame(0x01, 0x07, pvt_payload(
        345600000 + 1000 * k, *ll(fn, fe))) for k, (t, n, e, vn, ve, fn, fe)
        in enumerate(flight(10)))
    eps = list(epochs_from_ubx(data))
    assert len(eps) == 10 and abs(eps[1].t - eps[0].t - 1.0) < 1e-9
    outs = run(eps, Gateway(ENV))
    assert len(outs) == 10 and outs[0].mode == TRUSTED
    e2 = epoch_from_json(epoch_to_json(epoch(0, 1, 2, 3, 4, constellation_fixes=[
        ConstellationFix("gps", LAT0, LON0, 3.0)])))
    assert e2.constellation_fixes[0].constellation == "gps" and e2.vel_ned_ms == (3, 4, 0.0)
    json.loads(epoch_to_json(e2))
    print("[ok] replay: a UBX capture and the JSON-lines log both drive the gateway")
    PASSED.append("replay")


if __name__ == "__main__":
    tests = [test_ubx_nav_pvt_and_checksum, test_ubx_nav_sat_and_mon_rf, test_nmea,
             test_gateway_honest_flight_trusted, test_gateway_spoof_jump_then_return,
             test_optical_flow_keeps_estimate_tight, test_gateway_no_fix_cases,
             test_gateway_constellation_disagreement, test_gps_input_message,
             test_replay]
    for t in tests:
        t()
    print(f"\n{len(PASSED)}/{len(tests)} box tests passed")
