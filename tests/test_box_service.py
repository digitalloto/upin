"""Tests for the box service: flight-controller reader, the Pi's main logic,
config, and the log.

Flight-controller messages are fake objects with the MAVLink common-message
field names; receiver data is synthetic UBX bytes built from the published
layout. No serial port, no pymavlink, no flight controller. The live loop in
service.run() is not exercised here and stays UNTESTED.

Run: python tests/test_box_service.py
"""
import io
import json
import math
import os
import sys
import tempfile

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(__file__))

from test_box import LAT0, LON0, ll, pvt_payload  # noqa: E402

from upin.box.fc_reader import FcReader, pressure_altitude_m  # noqa: E402
from upin.box.gateway import DEGRADED, NO_FIX, TRUSTED, body_to_ne  # noqa: E402
from upin.box.gnss_parser import ubx_frame  # noqa: E402
from upin.box.replay import epoch_from_json  # noqa: E402
from upin.box.service import Box, BoxConfig, load_config  # noqa: E402

PASSED = []


class Msg:
    """Stands in for a pymavlink message."""

    def __init__(self, kind, **fields):
        self._kind = kind
        self.__dict__.update(fields)

    def get_type(self):
        return self._kind


def attitude(heading_deg):
    return Msg("ATTITUDE", roll=0.0, pitch=0.0, yaw=math.radians(heading_deg))


def fc_gps(lat, lon, h_acc_mm=3000):
    return Msg("GPS_RAW_INT", fix_type=3, lat=round(lat * 1e7), lon=round(lon * 1e7),
               alt=50000, satellites_visible=12, h_acc=h_acc_mm)


def pvt_bytes(k, lat, lon, **kw):
    return ubx_frame(0x01, 0x07, pvt_payload(345600000 + 1000 * k, lat, lon, **kw))


def cfg(**kw):
    d = dict(max_accel_ms2=6.0, max_airspeed_ms=20.0)
    d.update(kw)
    return BoxConfig(**d)


def test_reader_parses_and_refuses_circular():
    r = FcReader()
    a = r.handle(attitude(-90.0), 1.0)
    assert abs(a.heading_deg - 270.0) < 1e-9
    b = r.handle(Msg("SCALED_PRESSURE", press_abs=1013.25, temperature=2500), 1.0)
    assert abs(b.pressure_alt_m) < 1e-6
    assert abs(pressure_altitude_m(1001.29) - 100.0) < 1.0      # ISA: ~100 m
    f = r.handle(Msg("OPTICAL_FLOW", flow_comp_m_x=2.0, flow_comp_m_y=-1.0,
                     quality=200, ground_distance=12.0), 1.0)
    assert f.forward_ms == 2.0 and f.ground_distance_m == 12.0
    assert r.handle(Msg("OPTICAL_FLOW", flow_comp_m_x=0.0, flow_comp_m_y=0.0,
                        quality=0, ground_distance=0.0), 1.1) is None
    rng = r.handle(Msg("DISTANCE_SENSOR", current_distance=1234, orientation=25), 1.0)
    assert abs(rng.distance_m - 12.34) < 1e-9
    g = r.handle(fc_gps(LAT0, LON0), 1.0)
    assert g.h_acc_m == 3.0 and abs(g.lat - LAT0) < 1e-7
    g2 = r.handle(Msg("GPS_RAW_INT", fix_type=3, lat=0, lon=0, alt=0,
                      satellites_visible=9), 1.0)
    assert g2.h_acc_m is None
    for kind in ("GLOBAL_POSITION_INT", "LOCAL_POSITION_NED", "GPS2_RAW"):
        assert r.handle(Msg(kind, lat=1, lon=1, x=0, y=0), 1.0) is None
    assert r.ignored == {"GLOBAL_POSITION_INT": 1, "LOCAL_POSITION_NED": 1,
                         "GPS2_RAW": 1}
    print("[ok] reader: heading, pressure altitude, flow, rangefinder and the "
          "FC's own GPS parsed; invalid flow dropped, not read as zero; the "
          "FC's position, local position and GPS2_RAW refused as circular")
    PASSED.append("reader")


def test_flow_rotation():
    for heading, (fwd, right), (vn, ve) in [(0, (1, 0), (1, 0)), (90, (1, 0), (0, 1)),
                                           (90, (0, 1), (-1, 0)), (180, (2, 0), (-2, 0))]:
        n, e = body_to_ne(fwd, right, heading)
        assert abs(n - vn) < 1e-9 and abs(e - ve) < 1e-9, (heading, n, e)
    print("[ok] body forward/right turned to north/east correctly at 0/90/180 deg")
    PASSED.append("rotation")


def test_end_to_end_trusted_shadow_and_log():
    log = io.StringIO()
    box = Box(cfg(), log=log)
    sent = []
    for k in range(10):
        t = float(k)
        box.on_fc_message(attitude(90.0), t)
        box.on_fc_message(Msg("SCALED_PRESSURE", press_abs=1000.0, temperature=2500), t)
        lat, lon = ll(0.0, 5.0 * k)
        box.on_fc_message(fc_gps(lat, lon), t)
        for out, msg in box.on_receiver_bytes(pvt_bytes(k, lat, lon, vel=(0.0, 5.0, 0.0)),
                                              t, 1.8e9 + t):
            sent.append((out, msg))
    assert len(sent) == 10 and all(o.mode == TRUSTED for o, _ in sent)
    assert all(m.gps_id == 1 and m.fix_type == 3 for _, m in sent)
    lines = [json.loads(l) for l in log.getvalue().splitlines()]
    assert len(lines) == 10 and lines[-1]["fc_gps"]["h_acc_m"] == 3.0
    assert lines[-1]["sent"]["gps_id"] == 1 and lines[-1]["heading_deg"] == 90.0
    ep = epoch_from_json(log.getvalue().splitlines()[-1])
    assert ep.fix_type == 3 and len(ep.constellation_fixes) == 2
    print("[ok] UBX bytes + FC messages -> TRUSTED, sent as GPS 2 (gps_id 1); "
          "both receivers cross-checked; every epoch logged and replayable")
    PASSED.append("e2e")


def test_receivers_disagree_distrusts():
    box = Box(cfg())
    for k in range(5):
        lat, lon = ll(0.0, 0.0)
        box.on_fc_message(fc_gps(lat, lon), float(k))
        box.on_receiver_bytes(pvt_bytes(k, lat, lon, vel=(0, 0, 0)), float(k), 0.0)
    box.on_fc_message(fc_gps(*ll(0.0, 0.0)), 5.0)
    (out, msg), = box.on_receiver_bytes(pvt_bytes(5, *ll(0.0, 150.0), vel=(0, 0, 0)),
                                        5.0, 0.0)
    assert out.mode == DEGRADED and msg.fix_type == 0
    assert any("disagree" in r for r in out.reasons), out.reasons
    print("[ok] the box's receiver and the FC's GPS 150 m apart: fix distrusted, "
          "no fix sent (forward_degraded off)")
    PASSED.append("disagree")


def test_deny_gnss_and_flow():
    results = {}
    for with_flow in (False, True):
        box = Box(cfg(max_degraded_h_acc_m=1e6))
        for k in range(30):
            box.on_fc_message(attitude(0.0), float(k))
            box.on_receiver_bytes(pvt_bytes(k, *ll(5.0 * k, 0.0), vel=(5.0, 0, 0)),
                                  float(k), 0.0)
        box.deny_gnss = True
        for k in range(30, 90):
            t = float(k)
            box.on_fc_message(attitude(0.0), t)
            if with_flow:
                box.on_fc_message(Msg("OPTICAL_FLOW", flow_comp_m_x=5.0,
                                      flow_comp_m_y=0.0, quality=200,
                                      ground_distance=20.0), t)
            (out, _), = box.on_receiver_bytes(pvt_bytes(k, *ll(5.0 * k, 0.0)), t, 0.0)
        results[with_flow] = out
    assert results[False].mode == DEGRADED and results[True].mode == DEGRADED
    assert results[True].h_acc_m < results[False].h_acc_m
    n = (results[True].lat - LAT0) * 111_320.0
    box2 = Box(cfg(max_degraded_h_acc_m=20.0), deny_gnss=False)
    for k in range(10):
        box2.on_receiver_bytes(pvt_bytes(k, *ll(0, 0), vel=(0, 0, 0)), float(k), 0.0)
    box2.deny_gnss = True
    modes = [box2.on_receiver_bytes(pvt_bytes(k, *ll(0, 0)), float(k), 0.0)[0][0].mode
             for k in range(10, 60)]
    assert modes[0] == DEGRADED and modes[-1] == NO_FIX
    print(f"[ok] --deny-gnss: DEGRADED, then NO_FIX past the limit; with flow "
          f"from the FC, 60 s denied ends at h_acc {results[True].h_acc_m:.1f} m "
          f"(truth 445 m north, estimate {n:.0f} m) vs "
          f"{results[False].h_acc_m:.0f} m without")
    PASSED.append("deny")


def test_config():
    text = """
[airframe]
max_accel_ms2 = 6.0
max_airspeed_ms = 20.0

[ports]
receiver_port = "/dev/ttyUSB0"
fc_connection = "/dev/ttyAMA0"

[output]
gps_id = 1
shadow = true
"""
    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
        f.write(text)
    try:
        c = load_config(f.name)
        assert c.gps_id == 1 and c.shadow and not c.forward_degraded
        with open(f.name, "w") as g:
            g.write(text.replace("gps_id = 1", "gps_id = 0"))
        try:
            load_config(f.name)
            raise AssertionError("shadow mode accepted gps_id 0")
        except ValueError:
            pass
        with open(f.name, "w") as g:
            g.write(text + "\n[extra]\nmax_acel = 3\n")
        try:
            load_config(f.name)
            raise AssertionError("a misspelt key was accepted")
        except ValueError:
            pass
    finally:
        os.unlink(f.name)
    example = load_config("deploy/box.example.toml")
    assert example.shadow and example.gps_id == 1
    print("[ok] config loads; shadow mode refuses to be GPS 1; misspelt keys "
          "refused; deploy/box.example.toml is valid")
    PASSED.append("config")


if __name__ == "__main__":
    tests = [test_reader_parses_and_refuses_circular, test_flow_rotation,
             test_end_to_end_trusted_shadow_and_log, test_receivers_disagree_distrusts,
             test_deny_gnss_and_flow, test_config]
    for t in tests:
        t()
    print(f"\n{len(PASSED)}/{len(tests)} box-service tests passed")
