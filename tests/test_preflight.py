"""Tests for the preflight check (upin/box/preflight.py, tools/preflight.py).

Synthetic UBX bytes and fake flight-controller messages through the real
logic: rates, bad checksums, NMEA-only, a missing heartbeat, missing
optional streams, the flight controller's GPS without an accuracy, disk,
config, and the GO / NO-GO verdict.

Run: python tests/test_preflight.py
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(__file__))

from test_box import pvt_payload  # noqa: E402

from upin.box import preflight as pf  # noqa: E402
from upin.box.gnss_parser import encode_mon_hw, encode_mon_rf, encode_nav_sat, ubx_frame  # noqa: E402
from upin.console.sources import Msg  # noqa: E402

PASSED = []


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def sleep(self, dt):
        self.t += dt


def stream_reader(frames_per_tick, clock, tick_s=0.2, seconds=10.0, garbage=b""):
    """read() returns one tick's worth of bytes and advances the clock."""
    end = clock.t + seconds

    def read():
        if clock.t >= end:
            return b""
        clock.t += tick_s
        return garbage + b"".join(frames_per_tick())
    return read


def ubx_tick(k=[0]):
    k[0] += 1
    sat = encode_nav_sat(k[0] * 200, [("gps", 3, 40.0, 30.0, 100, True)] * 8 +
                         [("navic", 2, 38.0, 50.0, 200, True)] * 3)
    pvt = ubx_frame(0x01, 0x07, pvt_payload(345600000 + 200 * k[0], 13.0827, 80.2707))
    return [pvt, sat, encode_mon_rf("ok")]


def test_receiver_checks():
    clk = FakeClock()
    checks, obs = pf.check_receiver(stream_reader(ubx_tick, clk), 10.0, clk.sleep, clk)
    by = {c.name: c for c in checks}
    assert by["messages"].status == pf.GO and "NAV-PVT: 5.0 Hz" in by["messages"].detail, by["messages"]
    assert "MON-RF" in by["messages"].detail
    assert by["last fix"].status == pf.GO and "satellites" in by["last fix"].detail
    assert "gps 8" in by["constellations"].detail and "navic 3" in by["constellations"].detail
    # an M8: MON-HW instead of MON-RF
    clk = FakeClock()
    checks, _ = pf.check_receiver(stream_reader(lambda: [ubx_tick()[0], encode_mon_hw("ok")], clk),
                                  10.0, clk.sleep, clk)
    msg = [c for c in checks if c.name == "messages"][0]
    assert "MON-HW" in msg.detail and "M8" in msg.detail and "NAV-SAT: none" in msg.detail
    assert msg.status == pf.NOGO                     # NAV-SAT is required
    # NMEA only
    clk = FakeClock()
    nmea = b"$GNGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47\r\n"
    checks, _ = pf.check_receiver(stream_reader(lambda: [nmea], clk), 10.0, clk.sleep, clk)
    msg = [c for c in checks if c.name == "messages"][0]
    assert msg.status == pf.NOGO and "only NMEA" in msg.detail, msg
    # silence
    clk = FakeClock()
    checks, _ = pf.check_receiver(stream_reader(lambda: [], clk), 10.0, clk.sleep, clk)
    msg = [c for c in checks if c.name == "messages"][0]
    assert msg.status == pf.NOGO and "nothing at all" in msg.detail
    # corrupted frames are counted, not half-parsed
    clk = FakeClock()
    bad = bytearray(ubx_tick()[0]); bad[-1] ^= 0xFF
    checks, obs = pf.check_receiver(stream_reader(lambda: [bytes(bad)] + ubx_tick(), clk), 10.0, clk.sleep, clk)
    assert obs["bad_checksum"] >= 40 and "bad checksum" in [c for c in checks if c.name == "messages"][0].detail
    print("[ok] receiver: UBX at 5 Hz with NAV-SAT and MON-RF is GO with the fix shown; an M8's MON-HW is "
          "recognised; NAV-SAT missing, NMEA-only and silence are NO-GO with the cause; bad checksums counted")
    PASSED.append("receiver")


class FakeConn:
    def __init__(self, heartbeat, messages, clock, span_s=10.0):
        self.hb, self.msgs, self.clock = heartbeat, list(messages), clock
        self.target_system, self.target_component = 1, 1
        self.sent = []
        self.mav = self
        self._end = None
        self._i = 0
        self.span_s = span_s

    def command_long_send(self, *args):
        self.sent.append(args)

    def wait_heartbeat(self, timeout=30):
        return self.hb

    def recv_match(self, blocking=False):
        if self._end is None:
            self._end = self.clock() + self.span_s
        if self._i >= len(self.msgs):
            self.clock.t = max(self.clock.t, self._end)
            return None
        m = self.msgs[self._i]
        self._i += 1
        self.clock.t += self.span_s / len(self.msgs)
        return m


def fc_messages(h_acc=3000, with_range=False, n=10):
    out = []
    for k in range(n):
        out += [Msg("ATTITUDE", roll=0.0, pitch=0.0, yaw=0.0)] * 50
        out += [Msg("RAW_IMU", xacc=0, yacc=0, zacc=-1000, xgyro=0, ygyro=0, zgyro=0)] * 50
        out += [Msg("SCALED_PRESSURE", press_abs=1000.0, temperature=2500)] * 10
        out += [Msg("GPS_RAW_INT", fix_type=3, lat=130827000, lon=802707000, alt=50000,
                    satellites_visible=14, h_acc=h_acc)] * 10
        out += [Msg("HEARTBEAT", base_mode=0)]
        if with_range:
            out += [Msg("DISTANCE_SENSOR", current_distance=500, orientation=25)] * 10
    return out


def test_flight_controller_checks():
    clk = FakeClock()
    hb = Msg("HEARTBEAT", type=2, autopilot=3, base_mode=0)
    conn = FakeConn(hb, fc_messages(with_range=True), clk)
    checks, info = pf.check_flight_controller(conn, 10.0, clk.sleep, clk)
    by = {c.name: c for c in checks}
    assert by["heartbeat"].status == pf.GO and "disarmed" in by["heartbeat"].detail
    assert len(conn.sent) == 8                                    # the eight stream requests, nothing else
    assert by["ATTITUDE"].status == pf.GO and by["RAW_IMU"].status == pf.GO
    assert by["DISTANCE_SENSOR"].status == pf.GO
    assert by["OPTICAL_FLOW"].status == pf.NOTE and "absent" in by["OPTICAL_FLOW"].detail
    assert by["GPS accuracy"].status == pf.GO and "14 satellites" in by["GPS accuracy"].detail
    # the flight controller's GPS without an accuracy: the cross-check cannot run
    clk = FakeClock()
    conn = FakeConn(hb, fc_messages(h_acc=0), clk)
    checks, _ = pf.check_flight_controller(conn, 10.0, clk.sleep, clk)
    by = {c.name: c for c in checks}
    assert by["GPS accuracy"].status == pf.NOTE and "GPS_TYPE" in by["GPS accuracy"].detail
    assert by["DISTANCE_SENSOR"].status == pf.NOTE
    # no heartbeat
    clk = FakeClock()
    checks, _ = pf.check_flight_controller(FakeConn(None, [], clk), 10.0, clk.sleep, clk)
    assert checks[0].status == pf.NOGO and "none in" in checks[0].detail and len(checks) == 1
    # no attitude at all
    clk = FakeClock()
    conn = FakeConn(hb, [m for m in fc_messages() if m.get_type() != "ATTITUDE"], clk)
    checks, _ = pf.check_flight_controller(conn, 10.0, clk.sleep, clk)
    assert {c.name: c for c in checks}["ATTITUDE"].status == pf.NOGO
    print("[ok] flight controller: heartbeat, eight stream requests and nothing else, rates against the "
          "asked rates, optional streams absent as notes, GPS without an accuracy named (GPS_TYPE), "
          "no heartbeat and no attitude are NO-GO")
    PASSED.append("fc")


def test_config_disk_verdict_and_cli():
    env = pf.check_environment()
    assert {c.name for c in env} >= {"python", "serial", "pymavlink", "numpy", "scipy"}
    assert [c for c in env if c.name == "python"][0].status == pf.GO
    cfg, cc = pf.check_config("deploy/box.example.toml")
    assert cfg is not None and cc[0].status == pf.GO
    assert any(c.name == "wind_dr" and "airframe_id" in c.detail for c in cc)
    none, bad = pf.check_config("/nonexistent/box.toml")
    assert none is None and bad[0].status == pf.NOGO
    ports = pf.check_ports(cfg)
    assert any(c.name == "receiver_port" and c.status == pf.NOGO for c in ports)
    disk = pf.check_disk(cfg, "/tmp/box.jsonl")
    assert disk and disk[0].status in (pf.GO, pf.NOGO)
    unit = pf.check_unit_file("deploy/upin-box.service")
    assert unit[0].status == pf.GO and "--no-send" in unit[0].detail
    checks = env + cc + ports + disk + unit
    assert pf.overall(checks) == pf.NOGO
    text = pf.render(checks)
    assert "RESULT: NO-GO" in text and "[ports]" in text
    rec = pf.to_json(checks)
    json.dumps(rec)
    out = subprocess.run([sys.executable, "tools/preflight.py", "--config", "deploy/box.example.toml",
                          "--skip-fc", "--skip-receiver"], capture_output=True, text=True)
    assert out.returncode == 1 and "RESULT: NO-GO" in out.stdout and "receiver_port" in out.stdout
    print("[ok] environment, config, ports, disk and the unit file checked; the verdict is NO-GO on a "
          "missing port and the tool exits 1 with the checklist")
    PASSED.append("cli")


if __name__ == "__main__":
    tests = [test_receiver_checks, test_flight_controller_checks, test_config_disk_verdict_and_cli]
    for t in tests:
        t()
    print(f"\n{len(PASSED)}/{len(tests)} preflight tests passed")
