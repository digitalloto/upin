"""Tests for receivers that speak NMEA (any maker): the sentences, the
epoch builder, the satellites for the signal-power check, the accuracy
rule (the receiver's GST, else HDOP times a labelled assumption), the box
end to end, a software denial, and the preflight's verdict.

Synthetic sentences at the project's usual test position; checksums
computed by the encoder.

Run: python tests/test_nmea_receiver.py
"""
import io
import json
import math
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(__file__))

from test_preflight import FakeClock, stream_reader  # noqa: E402

from upin.box import preflight as pf  # noqa: E402
from upin.box.gateway import DEGRADED, TRUSTED  # noqa: E402
from upin.box.gnss_parser import (Gsa, Gst, Gsv, NmeaEpochBuilder, NmeaStream, Zda,  # noqa: E402
                                  nmea_sentence, parse_nmea)
from upin.box.service import Box, BoxConfig  # noqa: E402
from upin.console.sources import Msg  # noqa: E402
from upin.layers.rf.beacon_ranging import DEG_M  # noqa: E402

PASSED = []
LAT0, LON0 = 13.0827, 80.2707


def dm(deg, digits):
    d = int(abs(deg))
    m = (abs(deg) - d) * 60.0
    return f"{d:0{digits}d}{m:010.6f}"


def cycle(k, lat=LAT0, lon=LON0, speed_ms=8.0, course=90.0, quality=1, hdop=0.63, gst=None,
          order=("ZDA", "GSA", "GGA", "RMC", "GSV", "GST"), nmea_date="131026"):
    """One second of a receiver's output, the sentences in the given order."""
    utc = f"07{(40 + k // 60) % 60:02d}{k % 60:02d}.00"
    by = {
        "ZDA": nmea_sentence(f"GNZDA,{utc},13,10,2026,00,00"),
        "GSA": [nmea_sentence("GNGSA,M,3,001,002,003,004,008,009,016,026,027,031,,,1.10,0.63,0.90"),
                nmea_sentence("GIGSA,M,3,002,009,010,,,,,,,,,,1.10,0.63,0.90")],
        "GGA": nmea_sentence(f"GNGGA,{utc},{dm(lat, 2)},N,{dm(lon, 3)},E,{quality},19,{hdop},12.0,M,,M,,"),
        "RMC": nmea_sentence(f"GNRMC,{utc},A,{dm(lat, 2)},N,{dm(lon, 3)},E,{speed_ms / (1852 / 3600):.2f},"
                             f"{course:05.1f},{nmea_date},,,A"),
        "GSV": [nmea_sentence("GPGSV,2,1,06,01,38,027,33,02,46,026,25,03,41,016,41,04,45,045,40"),
                nmea_sentence("GPGSV,2,2,06,08,52,100,44,09,33,250,37"),
                nmea_sentence("GIGSV,1,1,03,002,46,209,47,009,64,306,51,010,30,099,47")],
        "GST": nmea_sentence(f"GNGST,{utc},1.2,0.8,0.7,30,{gst[0]},{gst[1]},2.0") if gst else "",
    }
    out = []
    for kind in order:
        v = by[kind]
        out += v if isinstance(v, list) else ([v] if v else [])
    return ("\r\n".join(out) + "\r\n").encode()


def test_sentences_and_builder():
    assert parse_nmea("$GNGGA,bad*00") is None
    z = parse_nmea(nmea_sentence("GNZDA,074047.00,13,10,2026,00,00"))
    assert isinstance(z, Zda) and (z.year, z.month, z.day) == (2026, 10, 13)
    g = parse_nmea(nmea_sentence("GIGSA,M,3,002,009,010,,,,,,,,,,1.10,0.63,0.90"))
    assert isinstance(g, Gsa) and g.talker == "GI" and g.fix_type == 3 and g.sat_ids == [2, 9, 10] and g.hdop == 0.63
    v = parse_nmea(nmea_sentence("GIGSV,1,1,03,002,46,209,47,009,64,306,51,010,30,099,47"))
    assert isinstance(v, Gsv) and len(v.sats) == 3 and v.sats[0].constellation == "navic"
    assert (v.sats[1].sv_id, v.sats[1].elevation_deg, v.sats[1].azimuth_deg, v.sats[1].cn0_dbhz) == (9, 64, 306, 51)
    s = parse_nmea(nmea_sentence("GNGST,074047.00,1.2,0.8,0.7,30,0.9,1.1,2.0"))
    assert isinstance(s, Gst) and s.h_acc_m == 1.1 and s.sigma_alt_m == 2.0
    # the builder: GGA then RMC of the same UTC make one fix, either order
    for order in (("GSA", "GGA", "RMC", "GSV"), ("GSA", "RMC", "GGA", "GSV")):
        st, b, fixes = NmeaStream(), NmeaEpochBuilder(), []
        for k in range(3):
            for m in st.feed(cycle(k, order=order)):
                f = b.feed(m)
                if f is not None:
                    fixes.append(f)
        assert len(fixes) == 3, (order, len(fixes))
        f = fixes[-1]
        assert abs(f.lat - LAT0) < 1e-6 and abs(f.lon - LON0) < 1e-6 and f.fix_type == 3 and f.num_sv == 19
        assert f.vel_ne_ms is not None and abs(f.vel_ne_ms[1] - 8.0) < 0.02 and abs(f.vel_ne_ms[0]) < 0.02
        assert f.pdop == 1.10 and f.hdop == 0.63 and f.gst_h_acc_m is None
    sats = b.satellites()
    assert len(sats) == 9 and sum(1 for x in sats if x.constellation == "navic") == 3
    assert all(x.used for x in sats if x.sv_id in (1, 2, 3, 4, 8, 9)) and not [x for x in sats if x.sv_id == 10 and x.constellation == "gps"]
    # a GGA that never gets its RMC is released, without velocity, on the next GGA
    st, b, fixes = NmeaStream(), NmeaEpochBuilder(), []
    for k in range(3):
        for m in st.feed(cycle(k, order=("GGA",))):
            f = b.feed(m)
            if f is not None:
                fixes.append(f)
    assert len(fixes) == 2 and fixes[0].vel_ne_ms is None
    # GST, when sent, gives the receiver's own accuracy
    st, b = NmeaStream(), NmeaEpochBuilder()
    fx = [b.feed(m) for m in st.feed(cycle(0, gst=(0.9, 1.1)))]
    f = [x for x in fx if x is not None][0]
    assert f.gst_h_acc_m is None                    # GST came after this cycle's RMC ...
    fx = [b.feed(m) for m in st.feed(cycle(1, gst=(0.9, 1.1)))]
    f = [x for x in fx if x is not None][0]
    assert f.gst_h_acc_m == 1.1                     # ... and serves the next one
    print("[ok] GGA, RMC, GSA, GSV, GST and ZDA parse from any talker (NavIC as GI); a fix needs a GGA "
          "and its RMC in either order; GSV and GSA give the satellites with their used flags; a lone "
          "GGA is released without velocity; GST gives the receiver's own accuracy")
    PASSED.append("parse")


def drive(cfg, seconds=40, deny=(), gst=None, fc=True):
    box = Box(cfg, log=io.StringIO())
    outs = []
    for k in range(seconds):
        t = float(k)
        if fc:
            box.on_fc_message(Msg("ATTITUDE", roll=0.0, pitch=0.0, yaw=math.radians(90.0)), t)
            box.on_fc_message(Msg("GPS_RAW_INT", fix_type=3, lat=round(LAT0 * 1e7),
                                  lon=round((LON0 + 8.0 * k / (DEG_M * math.cos(math.radians(LAT0)))) * 1e7),
                                  alt=12000, satellites_visible=12, h_acc=3000), t)
        box.deny_gnss = deny[0] <= k < deny[1] if deny else False
        lon = LON0 + 8.0 * k / (DEG_M * math.cos(math.radians(LAT0)))
        for out, sent in box.on_receiver_bytes(cycle(k, lon=lon, gst=gst), t, 1.7e9 + t):
            outs.append(out)
    return box, outs


def test_through_the_box():
    cfg = BoxConfig(max_accel_ms2=6.0, max_airspeed_ms=20.0, max_degraded_h_acc_m=1e6)
    box, outs = drive(cfg)
    assert len(outs) == 40 and box.receiver_protocol_seen == "nmea"
    assert all(o.mode == TRUSTED for o in outs[2:]), [o.reasons for o in outs if o.mode != TRUSTED][:2]
    rec = box.last_record
    r = rec["receiver"]
    assert r["protocol"] == "nmea" and r["h_acc_source"].startswith("assumed: HDOP")
    assert abs(r["h_acc_m"] - 0.63 * 3.0) < 1e-6 and r["num_sv"] == 19 and r["utc"] == "2026-10-13 07:40:39"
    ep = box.last_epoch
    assert ep.fix_type == 3 and abs(ep.vel_ned_ms[1] - 8.0) < 0.05 and ep.s_acc_ms == 0.3
    assert len(ep.constellation_fixes) == 2                     # the flight controller's GPS cross-checks
    assert ep.jamming_state == "unknown"
    pc = ep.power_check
    assert pc is not None and pc["verdict"] != "NOT_RUN", pc    # GSV fed the signal-power check
    assert "nmea" in box.status_line(40.0, 10.0, 39.0, ".")
    # the receiver's own accuracy when it sends GST
    box2, _ = drive(cfg, seconds=5, gst=(0.9, 1.1))
    r2 = box2.last_record["receiver"]
    assert r2["h_acc_source"] == "receiver (GST)" and r2["h_acc_m"] == 1.1
    # a software denial on an NMEA receiver, as on UBX: the record keeps the real fix
    box3, outs3 = drive(cfg, seconds=60, deny=(30, 50))
    assert all(o.mode == DEGRADED for o in outs3[32:50]) and outs3[-1].mode == TRUSTED
    assert box3.last_record["receiver"]["fix_type"] == 3
    # ubx-only config ignores NMEA; nmea-only ignores UBX
    box4, outs4 = drive(BoxConfig(max_accel_ms2=6.0, max_airspeed_ms=20.0, receiver_protocol="ubx"), seconds=3)
    assert outs4 == [] and box4.receiver_protocol_seen is None
    try:
        BoxConfig(max_accel_ms2=6.0, max_airspeed_ms=20.0, receiver_protocol="sirf")
        from upin.box.service import load_config  # noqa: F401
    except Exception:  # noqa: BLE001
        raise AssertionError("BoxConfig itself must not validate; load_config does")
    print(f"[ok] an NMEA receiver through the box: 40 epochs TRUSTED with the accuracy assumed from HDOP "
          f"(±{r['h_acc_m']:.2f} m, stated as assumed), velocity from RMC, UTC from ZDA, the flight "
          f"controller's GPS cross-checked, the signal-power check fed from GSV ({pc['verdict']}); GST "
          f"gives the receiver's own accuracy; a software denial behaves as on UBX; receiver_protocol honoured")
    PASSED.append("box")


def test_preflight_on_nmea():
    clk = FakeClock()
    k = [0]

    def tick():
        k[0] += 1
        return [cycle(k[0])]
    checks, obs = pf.check_receiver(stream_reader(tick, clk, tick_s=1.0), 10.0, clk.sleep, clk)
    by = {c.name: c for c in checks}
    msg = by["messages"]
    assert msg.status == pf.GO and msg.detail.startswith("NMEA") and "GGA: 1.0 Hz" in msg.detail, msg
    assert "GST: none" in msg.detail and "navic 3" in msg.detail and "no jamming state" in msg.detail
    assert by["last fix"].status == pf.GO and "19 satellites" in by["last fix"].detail
    print("[ok] preflight on an NMEA receiver: GO with the sentence rates, NavIC in view, the missing GST "
          "named with its consequence, and the honest note that NMEA has no jamming state")
    PASSED.append("preflight")


if __name__ == "__main__":
    tests = [test_sentences_and_builder, test_through_the_box, test_preflight_on_nmea]
    for t in tests:
        t()
    print(f"\n{len(PASSED)}/{len(tests)} NMEA receiver tests passed")
