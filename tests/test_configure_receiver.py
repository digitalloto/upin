"""Tests for the receiver configuration frames (upin/box/ubx_config.py,
tools/configure_receiver.py) and the M8's MON-HW parsing.

The frames are checked byte for byte against the UBX protocol's layouts
and their Fletcher checksums; the observe/verdict step is run on a
synthetic stream. Nothing here proves a real receiver accepts them: the
tool's own listening step does that, on the bench.

Run: python tests/test_configure_receiver.py
"""
import os
import subprocess
import sys

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(__file__))

from test_box import pvt_payload  # noqa: E402

from upin.box.gnss_parser import (MON_HW, UbxStream, decode_ubx, encode_mon_hw, parse_mon_hw,  # noqa: E402
                                  ubx_checksum, ubx_frame)
from upin.box.ubx_config import (CFG_VALSET, cfg_cfg_save_frame, cfg_msg_frame, cfg_rate_frame,  # noqa: E402
                                 cfg_valset_frame, observe, plan, verdict)

PASSED = []


def test_frames_byte_for_byte():
    # CFG-RATE: measRate 200 ms, navRate 1, timeRef 1 (GPS)
    assert cfg_rate_frame(200).hex() == "b56206080600c80001000100de6a"
    # CFG-MSG: NAV-PVT (01 07) on USB (rate array index 3) once per solution
    assert cfg_msg_frame((0x01, 0x07), "usb", 1).hex() == "b56206010800010700000001000018df"
    # on UART1 the rate sits at index 1
    f = cfg_msg_frame((0x01, 0x35), "uart1", 1)
    assert f[6:8] == b"\x01\x35" and f[8:14] == b"\x00\x01\x00\x00\x00\x00"
    # CFG-CFG: clear nothing, save all sections (0x0000FFFF), load nothing, BBR + flash (0x03)
    assert cfg_cfg_save_frame().hex() == "b56206090d0000000000ffff000000000000031dab"
    # every frame carries a valid Fletcher checksum and parses back
    for frame in (cfg_rate_frame(1000), cfg_msg_frame((0x0A, 0x38), "usb", 1), cfg_cfg_save_frame()):
        body = frame[2:-2]
        assert bytes(ubx_checksum(body)) == frame[-2:]
        s = UbxStream()
        got = list(s.feed(frame))
        assert len(got) == 1 and s.stats.bad_checksum == 0
    # CFG-VALSET: version 0, layers RAM|BBR|flash, then key/value pairs
    v = cfg_valset_frame([(0x20910009, 1, 1), (0x30210001, 200, 2)])
    assert v[2:4] == bytes(CFG_VALSET) and v[6:10] == b"\x00\x07\x00\x00"
    assert v[10:15] == b"\x09\x00\x91\x20\x01" and v[15:21] == b"\x01\x00\x21\x30\xc8\x00"
    labels = [p[0] for p in plan("usb", 5.0)]
    assert labels[0].startswith("CFG-RATE 200 ms") and labels[-1].startswith("CFG-CFG")
    assert sum(1 for x in labels if x.startswith("CFG-MSG")) == 4
    assert [p[0] for p in plan("uart1", 1.0, valset=True)][0].startswith("CFG-VALSET")
    print("[ok] CFG-RATE, CFG-MSG, CFG-CFG and CFG-VALSET frames match the protocol byte for byte, "
          "checksums verify, the plan is rate, messages, save")
    PASSED.append("frames")


def test_observe_and_verdict():
    class Clock:
        t = 0.0

    clk = Clock()
    k = [0]

    def read():
        if clk.t >= 10.0:
            return b""
        clk.t += 0.2
        k[0] += 1
        return (ubx_frame(0x01, 0x07, pvt_payload(345600000 + 200 * k[0], 13.0, 80.0))
                + encode_mon_hw("ok"))
    obs = observe(read, 10.0, sleep=lambda dt: setattr(clk, "t", clk.t + dt), clock=lambda: clk.t)
    assert abs(obs["rates_hz"]["NAV-PVT"] - 5.0) < 0.3 and obs["bad_checksum"] == 0
    ok, notes = verdict(obs)
    assert not ok and any("NAV-SAT: none" in n for n in notes) and any("MON-HW" in n for n in notes)
    ok2, notes2 = verdict(obs, need=("NAV-PVT",))
    assert ok2
    m = parse_mon_hw(encode_mon_hw("critical", 120, 1500, 200)[6:-2])
    assert m.jamming_state == "critical" and m.agc_count == 1500 and m.jam_indicator == 200
    assert m.as_mon_rf().worst_state == "critical" and m.as_mon_rf().blocks[0].agc_count == 1500
    s = UbxStream()
    frames = list(s.feed(encode_mon_hw("warning")))
    assert frames[0][:2] == MON_HW and decode_ubx(*frames[0]).jamming_state == "warning"
    out = subprocess.run([sys.executable, "tools/configure_receiver.py", "--dry-run", "--hz", "2"],
                         capture_output=True, text=True)
    assert out.returncode == 0 and "CFG-RATE 500 ms" in out.stdout and "CFG-CFG" in out.stdout
    out = subprocess.run([sys.executable, "tools/configure_receiver.py"], capture_output=True, text=True)
    assert out.returncode == 2 and "--port is required" in out.stderr
    print("[ok] observe counts what arrives at measured rates; the verdict names what is missing; "
          "MON-HW decodes to the box's jamming state and AGC; --dry-run prints the frames; no port refused")
    PASSED.append("observe")


if __name__ == "__main__":
    tests = [test_frames_byte_for_byte, test_observe_and_verdict]
    for t in tests:
        t()
    print(f"\n{len(PASSED)}/{len(tests)} configure-receiver tests passed")
