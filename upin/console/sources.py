"""
Where the console's data comes from. Every source runs the real UPIN box
(Box -> Gateway -> HonestKalman) on its input; only the input differs.

  sim      SIMULATED sensors: a drone flying a circuit, with spoofing and
           GNSS denial you can switch on. It speaks the receiver's own UBX
           protocol and the flight controller's MAVLink fields, so the data
           goes through the same parser and checks as real data. Labelled
           SIMULATION everywhere; the true position is shown as such.
  browser  This device's own location, from the browser (the part of the old
           phone demo that was real). Real data, poor accuracy: phone or
           laptop location, not a GNSS receiver.
  board    The flight controller on USB, its own GPS as the input. Real data.
  live     The full box: the new receiver plus the flight controller.
  replay   A box log, re-decided by today's code.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
import math

import numpy as np
import random
import threading
import time
from typing import List, Optional

from upin.box.fc_reader import P0_HPA
from upin.box.gnss_parser import encode_mon_rf, encode_nav_pvt, encode_nav_sat
from upin.box.gateway import GnssEpoch
from upin.box.replay import epoch_from_json
from upin.box.service import Box, BoxConfig
from upin.layers.optical.fiducial import TagEntry, TagMap
from upin.simulation.attacks import camera_frame
from upin.simulation.beacons import BeaconSim, SimBeacon
from upin.simulation.formation import SimDrone, SimFormation
from upin.simulation.environment import JammingField, JammingZone
from upin.simulation.markers import SimTag
from upin.console.state import ConsoleState
from upin.detection.reachability import DEG_M

W3C_95_TO_SIGMA = 1.0 / 2.4477
"""Browser location accuracy is a 95% radius (W3C Geolocation API); per-axis
1-sigma is that divided by 2.45."""


class Msg:
    """A MAVLink-shaped message: get_type() plus the field names."""

    def __init__(self, kind, **fields):
        self._kind = kind
        self.__dict__.update(fields)

    def get_type(self):
        return self._kind


class Source:
    controls: List[str] = []

    def __init__(self, state: ConsoleState):
        self.state = state
        self._stop = threading.Event()

    def start(self) -> None:
        pass

    def stop(self) -> None:
        self._stop.set()

    def control(self, action: str) -> str:
        return f"'{action}' is not available for this source"


# -- simulation -------------------------------------------------------------

class _GaussMarkov:
    """Correlated error: GNSS errors persist for tens of seconds."""

    def __init__(self, rng, sigma, tau_s):
        self.rng, self.sigma, self.tau = rng, sigma, tau_s
        self.x = rng.gauss(0, sigma)

    def step(self, dt):
        a = math.exp(-dt / self.tau)
        self.x = a * self.x + math.sqrt(1 - a * a) * self.rng.gauss(0, self.sigma)
        return self.x


class SimSource(Source):
    """A drone flying a stadium-shaped circuit at constant speed."""

    controls = ["spoof_jump", "spoof_drag", "smart_spoofer", "deny", "flow", "tags",
                "beacons", "jam_beacons", "jam_zone", "breadcrumbs",
                "formation", "deny_lead", "tailored_spoofer",
                "flow_attack", "reset"]

    STRAIGHT_M, RADIUS_M, SPEED_MS, ALT_M = 300.0, 60.0, 8.0, 50.0
    # Simulated downward camera and two painted ground tags: id 7 at the
    # circuit's start, surveyed into the box's tag map; id 20 on the far
    # straight, deliberately NOT in the map, so the console shows the honest
    # "seen but not in the map" decline once a lap.
    CAM_PX, CAM_FOV_DEG = 256, 40.0
    TAG_SIZE_M = 4.0
    # Simulated beacons (layer 151): three on the ground around the circuit
    # and one weather balloon launched 30 min before the run, drifting.
    BEACON_SECRET = b"simulated-beacon-secret"
    GNSS_SIGMA_M, GNSS_TAU_S, FC_GNSS_SIGMA_M = 1.5, 30.0, 2.0
    VEL_SIGMA_MS, HEADING_SIGMA_DEG, FLOW_SIGMA_MS = 0.1, 2.0, 0.2
    SPOOF_JUMP_M, SPOOF_DRAG_MS = 500.0, 1.0
    # A steady breeze and the lean a multirotor needs to fly the circuit
    # through it (ASSUMPTIONS: 3 m/s toward the north-east, no gusts; a
    # quadratic drag of 0.02 /m, a cleaner airframe than the training
    # simulator's, so 8 m/s needs about 14 degrees of lean). The attitude
    # and IMU carry that lean; the ground track is unchanged.
    WIND_NE_MS = (2.12, 2.12)
    DRAG_K = 0.02
    ATT_HZ = 10
    FLOW_ATTACK_MS = 2.5
    """Moving ground pattern (the laser-dot attack): the dots sweep east at
    this speed, so the flow sensor sees the ground move."""
    # Simulated sky (a labelled MODEL for exercising the signal-power layer,
    # not measured data): C/N0 = 30 + 0.2 x elevation + noise, dB-Hz.
    SKY = [("gps", 3, 12), ("gps", 7, 24), ("navic", 2, 31), ("galileo", 11, 38),
           ("gps", 14, 46), ("navic", 5, 53), ("galileo", 19, 61), ("gps", 22, 68),
           ("gps", 28, 77), ("navic", 7, 85)]
    CN0_BASE, CN0_PER_DEG, CN0_SIGMA = 30.0, 0.2, 1.5
    AGC_NORMAL, AGC_SIGMA = 3000.0, 20.0
    SPOOF_CN0, SPOOF_AGC, JAM_AGC = 46.0, 2300.0, 1800.0

    def __init__(self, state, start_lat, start_lon, speed=1.0, seed=None,
                 cfg: Optional[BoxConfig] = None):
        super().__init__(state)
        self.start_lat, self.start_lon = start_lat, start_lon
        self.speed = speed
        self.seed = seed
        # formation_check_action is "distrust" here, unlike the deploy default,
        # because the simulator's ranging sigma is known; on hardware it stays
        # "warn" until measured
        self.cfg = cfg or BoxConfig(max_accel_ms2=6.0, max_airspeed_ms=20.0,
                                    camera_flow=True, breadcrumbs=True,
                                    breadcrumb_spacing_m=150.0,   # the circuit is short
                                    formation=True, drone_id="lead",
                                    formation_check_action="distrust",
                                    wind_dr=True, airframe_id="sim-circuit-quad")
        self._lock = threading.Lock()
        self._reset()

    def _reset(self):
        self.rng = random.Random(self.seed)
        self.box = Box(self.cfg)
        self.t = 0.0
        self.err = [_GaussMarkov(self.rng, self.GNSS_SIGMA_M, self.GNSS_TAU_S) for _ in range(2)]
        self.fc_err = [_GaussMarkov(self.rng, self.FC_GNSS_SIGMA_M, self.GNSS_TAU_S) for _ in range(2)]
        self.spoof_jump = self.spoof_drag = self.deny = False
        self.flow = True
        self.smart = False
        self.flow_attack = False
        self.tags_on = True
        self.beacons_on = True
        self.jam_beacons = False
        self.jam_zone_on = False          # a GNSS jammer on the far straight
        self.crumbs_on = True
        self.formation_on = self.cfg.formation
        self.deny_lead = False            # the lead's box receiver fails; the wingmen keep GNSS
        self.tailored = False             # a multi-transmitter spoofer, the stated limit
        self.drag_m = 0.0
        self.nprng = np.random.default_rng(self.seed)
        L, R = self.STRAIGHT_M, self.RADIUS_M
        self.sim_tags = [SimTag(7, -R, -L / 2, self.TAG_SIZE_M, 30.0),
                         SimTag(20, R, L / 2, self.TAG_SIZE_M, 0.0)]
        self.beacon_sim = BeaconSim([
            SimBeacon("g1", *self._ll(600, -700), 20.0, 2.0),
            SimBeacon("g2", *self._ll(600, 700), 35.0, 2.0),
            SimBeacon("mast", *self._ll(-650, 0), 90.0, 2.0),
            SimBeacon("balloon1", *self._ll(-15000, -12000), 50.0, 5.0, kind="balloon",
                      launch_t=-1800.0, wind_ne_ms=(1.5, 4.0))],
            self.BEACON_SECRET, seed=self.seed or 0)
        self.box.beacons.set_secret(self.BEACON_SECRET)
        self.box.crumbs.set_secret(self.BEACON_SECRET)
        self.box.formation.set_secret(self.BEACON_SECRET)
        self.box._radio_out = self._radio_line
        # Two simulated wingmen (layer 153) in a V: 40 m back, ±40 m aside,
        # each with its own receiver; the lead's receiver is the UBX stream
        # above. Ranges are true distances plus the assumed ranging noise.
        self.formation_sim = SimFormation(
            [SimDrone("lead", 0.0, 0.0), SimDrone("w1", -40.0, -40.0), SimDrone("w2", -40.0, 40.0)],
            self.BEACON_SECRET, self.truth, self._ll, self.SPEED_MS, self.ALT_M,
            seed=self.seed or 0)
        L, R = self.STRAIGHT_M, self.RADIUS_M
        # sized from the simulator's own jammer model (6 dB per doubling of
        # distance): the far (north) straight is denied, the near one only
        # warns, so the crumbs drop while the fix is still trusted
        self.jam_zone = JammingZone(*self._ll(R + 20.0, 0.0), 40.0, ("GPS", "NavIC", "LEO"),
                                    name="far-straight jammer")
        lat7, lon7 = self._ll(-R, -L / 2)
        self.box.tags.set_map(TagMap([TagEntry(7, lat7, lon7, self.TAG_SIZE_M,
                                               "field_survey", 0.3, altitude_m=0.0,
                                               name="start tag")]))

    def truth(self, t):
        """(north, east, vn, ve) on the circuit at time t."""
        L, R, v = self.STRAIGHT_M, self.RADIUS_M, self.SPEED_MS
        P = 2 * L + 2 * math.pi * R
        s = (v * t) % P
        if s < L:                                   # south straight, eastbound
            return -R, -L / 2 + s, 0.0, v
        s -= L
        if s < math.pi * R:                         # east turn
            a = -math.pi / 2 + s / R
            return R * math.sin(a), L / 2 + R * math.cos(a), v * math.cos(a), -v * math.sin(a)
        s -= math.pi * R
        if s < L:                                   # north straight, westbound
            return R, L / 2 - s, 0.0, -v
        s -= L                                      # west turn
        a = math.pi / 2 + s / R
        return R * math.sin(a), -L / 2 + R * math.cos(a), v * math.cos(a), -v * math.sin(a)

    def _ll(self, n, e):
        return (self.start_lat + n / DEG_M,
                self.start_lon + e / (DEG_M * math.cos(math.radians(self.start_lat))))

    def _dynamics(self, t):
        """At time t: the circuit's acceleration, and the roll and pitch a
        multirotor needs to produce it through the wind (drag plus the
        acceleration is what the lean must supply), relative to its yaw."""
        h = 0.01
        n, e, vn, ve = self.truth(t)
        _, _, vn1, ve1 = self.truth(t + h)
        _, _, vn0, ve0 = self.truth(t - h)
        an, ae = (vn1 - vn0) / (2 * h), (ve1 - ve0) / (2 * h)
        air_n, air_e = vn - self.WIND_NE_MS[0], ve - self.WIND_NE_MS[1]
        air = math.hypot(air_n, air_e)
        ln, le = self.DRAG_K * air * air_n + an, self.DRAG_K * air * air_e + ae
        tilt = math.atan2(math.hypot(ln, le), 9.80665)
        yaw = math.atan2(ve, vn)
        delta = math.atan2(le, ln) - yaw
        roll = math.asin(math.sin(tilt) * math.sin(delta))
        pitch = math.asin(max(-1.0, min(1.0, -math.sin(tilt) * math.cos(delta) / max(math.cos(roll), 1e-6))))
        turn = (vn * ae - ve * an) / max(vn * vn + ve * ve, 1e-9)
        return an, ae, roll, pitch, yaw, turn

    def _fc_attitude_and_imu(self, tt, rng):
        """One ATTITUDE and one RAW_IMU message at time tt: the lean above,
        the yaw with compass noise, and the specific force the IMU sees in
        that attitude (gravity rotated out)."""
        an, ae, roll, pitch, yaw, turn = self._dynamics(tt)
        yaw_meas = yaw + math.radians(rng.gauss(0, self.HEADING_SIGMA_DEG))
        self.box.on_fc_message(Msg("ATTITUDE", roll=roll, pitch=pitch, yaw=yaw_meas), tt)
        cr, sr, cp, sp, cy, sy = (math.cos(roll), math.sin(roll), math.cos(pitch),
                                  math.sin(pitch), math.cos(yaw_meas), math.sin(yaw_meas))
        f = (an, ae, -9.80665)                          # specific force, NED
        fx = cy * cp * f[0] + sy * cp * f[1] - sp * f[2]
        fy = ((cy * sp * sr - sy * cr) * f[0] + (sy * sp * sr + cy * cr) * f[1] + cp * sr * f[2])
        fz = ((cy * sp * cr + sy * sr) * f[0] + (sy * sp * cr - cy * sr) * f[1] + cp * cr * f[2])
        mg = 9.80665e-3
        self.box.on_fc_message(Msg("RAW_IMU", xacc=(fx + rng.gauss(0, 0.05)) / mg,
                                   yacc=(fy + rng.gauss(0, 0.05)) / mg, zacc=fz / mg,
                                   xgyro=0.0, ygyro=0.0, zgyro=1000.0 * turn), tt)
        return yaw_meas

    def _radio_line(self, line: str) -> None:
        """What the box writes to its radio: a crumb's provisioning stamp, or
        its own formation message (heard by the wingmen; nothing to do here,
        their simulated receivers do not need it)."""
        rec = json.loads(line)
        if rec.get("type") == "provision":
            self._provision_crumb(rec)

    def _tracked_at(self, lat, lon, t) -> int:
        """Satellites a receiver at (lat, lon) would track in the simulated
        sky: the same model as the lead's, without the noise."""
        zone_db = self.jam_zone.cn0_drop_db(lat, lon) if self.jam_zone_on else 0.0
        return sum(1 for i, (_, _, base) in enumerate(self.SKY)
                   if self.CN0_BASE + self.CN0_PER_DEG * (base + 3.0 * math.sin(t / 600.0 + i))
                   - zone_db >= 25.0)

    def _provision_crumb(self, rec: dict) -> None:
        """The box 'sends' a stamp to the crumb's radio; here the crumb lands
        where the TRUE wind carries it during the fall and broadcasts the
        stamp (which used the box's learned wind)."""
        n, e, _, _ = self.truth(self.t)
        fall_s = self.ALT_M / self.box.crumbs.CRUMB_FALL_MS
        lat, lon = self._ll(n + self.WIND_NE_MS[0] * fall_s, e + self.WIND_NE_MS[1] * fall_s)
        self.beacon_sim.drop_crumb(rec, lat, lon, 0.0)
        self.state.event(f"SIMULATION: crumb {rec['id']} dropped, stamped ±{rec['sigma_m']:.1f} m",
                         "sim")

    def control(self, action):
        with self._lock:
            if action == "spoof_jump":
                self.spoof_jump = not self.spoof_jump
                msg = (f"SIMULATION: spoofer {'ON' if self.spoof_jump else 'OFF'}, "
                       f"position jumped {self.SPOOF_JUMP_M:.0f} m east on both receivers")
            elif action == "spoof_drag":
                self.spoof_drag = not self.spoof_drag
                if not self.spoof_drag:
                    self.drag_m = 0.0
                msg = (f"SIMULATION: slow drag-off spoof {'ON' if self.spoof_drag else 'OFF'} "
                       f"({self.SPOOF_DRAG_MS:.0f} m/s north, both receivers)")
            elif action == "smart_spoofer":
                self.smart = not self.smart
                kind = ("SMART: shapes each satellite's power by elevation, "
                        "as a real sky would" if self.smart else
                        "simple: one transmitter, uniform power")
                msg = f"SIMULATION: spoofer type now {kind} (applies when a spoof is on)"
            elif action == "flow_attack":
                self.flow_attack = not self.flow_attack
                msg = (f"SIMULATION: moving ground pattern {'ON' if self.flow_attack else 'OFF'}"
                       f" (laser dots sweeping east at {self.FLOW_ATTACK_MS} m/s under the "
                       f"flow sensor)")
            elif action == "deny":
                self.deny = not self.deny
                msg = f"SIMULATION: GNSS {'jammed (no fix)' if self.deny else 'restored'}"
            elif action == "flow":
                self.flow = not self.flow
                self.cfg.camera_flow = self.flow
                msg = (f"SIMULATION: flow sensors {'ON' if self.flow else 'OFF'} (the flow chip and the "
                       f"camera flow; with both off and no model, wind dead reckoning is the last "
                       f"velocity rung before coasting)")
            elif action == "beacons":
                self.beacons_on = not self.beacons_on
                msg = f"SIMULATION: beacons {'ON' if self.beacons_on else 'OFF'}"
            elif action == "jam_beacons":
                self.jam_beacons = not self.jam_beacons
                msg = (f"SIMULATION: wideband jammer on the beacon band "
                       f"{'ON' if self.jam_beacons else 'OFF'} (a GNSS jammer alone never "
                       f"touches the beacons)")
            elif action == "jam_zone":
                self.jam_zone_on = not self.jam_zone_on
                msg = (f"SIMULATION: GNSS jammer on the far straight {'ON' if self.jam_zone_on else 'OFF'} "
                       f"(C/N0 falls as the drone nears it; crumbs drop while the fix is still good)")
            elif action == "breadcrumbs":
                self.crumbs_on = not self.crumbs_on
                self.cfg.breadcrumbs = self.crumbs_on
                msg = f"SIMULATION: breadcrumb dropping {'ON' if self.crumbs_on else 'OFF'}"
            elif action == "formation":
                self.formation_on = not self.formation_on
                self.cfg.formation = self.formation_on
                msg = (f"SIMULATION: formation {'ON' if self.formation_on else 'OFF'} (two wingmen "
                       f"40 m back and ±40 m aside, each with its own receiver, ranging to the lead)")
            elif action == "deny_lead":
                self.deny_lead = not self.deny_lead
                msg = (f"SIMULATION: the lead's box receiver {'FAILED' if self.deny_lead else 'restored'} "
                       f"(the wingmen keep GNSS; the flight controller's own GPS is untouched)")
            elif action == "tailored_spoofer":
                self.tailored = not self.tailored
                kind = ("TAILORED per drone: each receiver shifted by the same offset, geometry "
                        "preserved -- the stated limit" if self.tailored else
                        "SINGLE transmitter: every receiver reports the same place")
                msg = f"SIMULATION: spoofer {kind} (applies when a spoof is on)"
            elif action == "tags":
                self.tags_on = not self.tags_on
                msg = f"SIMULATION: ground tags {'painted' if self.tags_on else 'removed'}"
            elif action == "reset":
                self._reset()
                msg = "SIMULATION: reset"
            else:
                return super().control(action)
        self.state.event(msg, "sim")
        return msg

    def step(self, dt=1.0):
        """One simulated second: flight-controller messages, then a receiver
        epoch, all through the real box."""
        with self._lock:
            self.t += dt
            t, rng, box = self.t, self.rng, self.box
            n, e, vn, ve = self.truth(t)
            heading = math.degrees(math.atan2(ve, vn)) % 360.0
            errs = [g.step(dt) for g in self.err]
            fc_errs = [g.step(dt) for g in self.fc_err]
            if self.spoof_drag:
                self.drag_m += self.SPOOF_DRAG_MS * dt
            sn = self.drag_m
            se = self.SPOOF_JUMP_M if self.spoof_jump else 0.0

            # Attitude and IMU at ATT_HZ through the second: the lean the wind
            # and the circuit's accelerations demand, and the specific force
            # the IMU sees in that attitude. The camera runs at 5 frames/s but
            # the simulation steps once a second, so the flow layer gets the
            # last 0.2 s pair: a frame at t-0.2 with that moment's attitude
            # and height, then the frame at t.
            t0 = t - 0.2
            n0, e0, vn0, ve0 = self.truth(t0)
            hdg0 = math.degrees(math.atan2(ve0, vn0)) % 360.0
            dots = ({"speed_ne": (0.0, self.FLOW_ATTACK_MS), "spacing_m": 4.0, "dot_m": 0.5}
                    if self.flow_attack else None)
            yaw_meas = None
            for j in range(1, self.ATT_HZ + 1):
                tt = t - dt + j * dt / self.ATT_HZ
                yaw_meas = self._fc_attitude_and_imu(tt, rng)
                if abs(tt - t0) < 1e-6:
                    box.on_fc_message(Msg("DISTANCE_SENSOR", current_distance=round(self.ALT_M * 100),
                                          orientation=25), t0)
                    frame0, _ = camera_frame(e0, n0, hdg0, self.ALT_M, self.CAM_FOV_DEG, self.CAM_PX,
                                             t0, tags=self.sim_tags if self.tags_on else (),
                                             dots=dots, pixel_noise=0.02, rng=self.nprng)
                    box.on_frame(frame0, t0, self.CAM_FOV_DEG)
            press = P0_HPA * (1 - self.ALT_M / 44330.0) ** 5.255
            box.on_fc_message(Msg("SCALED_PRESSURE", press_abs=press + rng.gauss(0, 0.05),
                                  temperature=3000), t)
            if self.flow:
                # The sensor sees the drone's motion relative to the ground
                # pattern; a moving pattern adds its own motion.
                gn, ge = vn, ve + (self.FLOW_ATTACK_MS if self.flow_attack else 0.0)
                hr = math.radians(heading)
                fwd = gn * math.cos(hr) + ge * math.sin(hr)
                right = -gn * math.sin(hr) + ge * math.cos(hr)
                box.on_fc_message(Msg("OPTICAL_FLOW",
                                      flow_comp_m_x=fwd + rng.gauss(0, self.FLOW_SIGMA_MS),
                                      flow_comp_m_y=right + rng.gauss(0, self.FLOW_SIGMA_MS),
                                      quality=200, ground_distance=self.ALT_M), t)
            if self.deny:
                box.on_fc_message(Msg("GPS_RAW_INT", fix_type=1, lat=0, lon=0, alt=0,
                                      satellites_visible=0, h_acc=0), t)
            else:
                flat, flon = self._ll(n + fc_errs[0] + sn, e + fc_errs[1] + se)
                box.on_fc_message(Msg("GPS_RAW_INT", fix_type=3, lat=round(flat * 1e7),
                                      lon=round(flon * 1e7), alt=round(self.ALT_M * 1000),
                                      satellites_visible=12,
                                      h_acc=round(self.FC_GNSS_SIGMA_M * 1000)), t)

            spoofing = self.spoof_jump or self.spoof_drag
            sky, agc = [], self.AGC_NORMAL + rng.gauss(0, self.AGC_SIGMA)
            # a jammer on the far straight: C/N0 falls with distance, satellites
            # drop out one by one, then the fix goes
            zone_db = self.jam_zone.cn0_drop_db(*self._ll(n, e)) if self.jam_zone_on else 0.0
            zone_state = "critical" if zone_db > 10 else "warning" if zone_db > 3 else "ok"
            for i, (gnss, sv, base_elev) in enumerate(self.SKY):
                elev = base_elev + 3.0 * math.sin(t / 600.0 + i)
                real = self.CN0_BASE + self.CN0_PER_DEG * elev + rng.gauss(0, self.CN0_SIGMA)
                if self.deny:
                    cn0 = 0.0
                elif spoofing and self.smart:
                    cn0 = real + 2.0
                elif spoofing:
                    cn0 = self.SPOOF_CN0 + rng.gauss(0, 0.8)
                else:
                    cn0 = real - zone_db
                    if cn0 < 25.0:            # ASSUMPTION: tracking threshold
                        cn0 = 0.0
                sky.append((gnss, sv, cn0, elev, (37 * i) % 360, cn0 > 0))
            tracked = sum(1 for x in sky if x[2] > 0)
            zone_denied = self.jam_zone_on and tracked < 4
            if self.deny:
                agc = self.JAM_AGC + rng.gauss(0, self.AGC_SIGMA)
            elif zone_db > 0:
                agc = max(self.JAM_AGC, self.AGC_NORMAL - 60.0 * zone_db) + rng.gauss(0, self.AGC_SIGMA)
            elif spoofing and not self.smart:
                agc = self.SPOOF_AGC + rng.gauss(0, self.AGC_SIGMA)
            sat_bytes = encode_nav_sat(int(t * 1000), sky)

            h_acc = self.GNSS_SIGMA_M
            if self.deny or self.deny_lead or zone_denied:
                data = sat_bytes + encode_mon_rf("critical", 240, round(agc), 200) + encode_nav_pvt(
                    int(t * 1000), 0.0, 0.0, 0.0, 0.0, 0.0, (0.0, 0.0, 0.0), 0.0,
                    fix_type=0, num_sv=0)
            else:
                lat, lon = self._ll(n + errs[0] + sn, e + errs[1] + se)
                v_spoof = self.SPOOF_DRAG_MS if self.spoof_drag else 0.0
                data = sat_bytes + encode_mon_rf(zone_state, 90, round(agc), 10) + encode_nav_pvt(
                    int(t * 1000), lat, lon, self.ALT_M, h_acc, 3.0,
                    (vn + v_spoof + rng.gauss(0, self.VEL_SIGMA_MS),
                     ve + rng.gauss(0, self.VEL_SIGMA_MS), 0.0),
                    self.VEL_SIGMA_MS * 1.5)
            # the launch-site beacons can be switched off; the crumbs the drone
            # dropped keep talking regardless (they share the radio)
            tlat_b, tlon_b = self._ll(n, e)
            jam = (JammingField([JammingZone(tlat_b, tlon_b, 2000.0,
                                             ("GPS", "NavIC", "LEO", "BEACON"))])
                   if self.jam_beacons else None)
            audible = lambda bid: self.beacons_on or bid.startswith("crumb-")  # noqa: E731
            for m in self.beacon_sim.messages(t):
                if audible(m["id"]):
                    box.on_beacon_line(json.dumps({"type": "msg", **m}), t)
            for bid, r, sg in self.beacon_sim.ranges(tlat_b, tlon_b, self.ALT_M, t, jam):
                if audible(bid):
                    box.on_beacon_line(json.dumps({"type": "range", "id": bid, "range_m": r,
                                                   "sigma_m": sg}), t)
            # the wingmen: their receivers see the same sky and jammer at their
            # own positions, and the same spoofer (one transmitter: one place)
            spoof_pos = (n + sn, e + se) if spoofing and not self.tailored else None
            tailored = (sn, se) if spoofing and self.tailored else None
            self.formation_sim.step(
                t, dt, spoof=spoof_pos, tailored=tailored,
                has_fix=lambda did, lat_, lon_: (not self.deny) and self._tracked_at(lat_, lon_, t) >= 4)
            if self.formation_on and not self.jam_beacons:
                for wid in ("w1", "w2"):
                    m = self.formation_sim.message(wid, t)
                    if m is not None:
                        box.on_beacon_line(json.dumps({"type": "msg", **m}), t)
                for pid, r, sg in self.formation_sim.ranges_for("lead"):
                    box.on_beacon_line(json.dumps({"type": "range", "id": pid, "range_m": r,
                                                   "sigma_m": sg}), t)
            results = box.on_receiver_bytes(data, t, time.time())
            box.on_fc_message(Msg("DISTANCE_SENSOR", current_distance=round(self.ALT_M * 100),
                                  orientation=25), t)
            frame, _ = camera_frame(e, n, heading, self.ALT_M, self.CAM_FOV_DEG, self.CAM_PX, t,
                                    tags=self.sim_tags if self.tags_on else (), dots=dots,
                                    pixel_noise=0.02, rng=self.nprng)
            box.on_frame(frame, t, self.CAM_FOV_DEG)
            tlat, tlon = self._ll(n, e)
            for out, sent in results:
                self.state.update(box, out, sent, sending=False,
                                  truth={"lat": tlat, "lon": tlon})
            return results

    def start(self):
        def loop():
            while not self._stop.is_set():
                self.step(1.0)
                self._stop.wait(1.0 / self.speed)
        threading.Thread(target=loop, daemon=True).start()


# -- this device's location ---------------------------------------------------

class BrowserSource(Source):
    controls = ["deny"]

    def __init__(self, state, cfg: Optional[BoxConfig] = None):
        super().__init__(state)
        self.cfg = cfg or BoxConfig(max_accel_ms2=6.0, max_airspeed_ms=20.0)
        self.box = Box(self.cfg)
        self._lock = threading.Lock()

    def control(self, action):
        if action != "deny":
            return super().control(action)
        with self._lock:
            self.box.deny_gnss = not self.box.deny_gnss
            msg = f"GNSS {'DENIED in software' if self.box.deny_gnss else 'restored'}"
        self.state.event(msg, "warn")
        return msg

    def fix(self, d: dict) -> str:
        """One location from the browser. Fields as the Geolocation API gives
        them; accuracy is a 95% radius in metres."""
        try:
            lat, lon, acc = float(d["lat"]), float(d["lon"]), float(d["accuracy"])
        except (KeyError, TypeError, ValueError):
            return "refused: needs lat, lon and accuracy"
        if not (-90 <= lat <= 90 and -180 <= lon <= 180 and acc > 0):
            return "refused: out of range"
        vel = None
        speed, heading = d.get("speed"), d.get("heading")
        if speed is not None and heading is not None and math.isfinite(float(heading)):
            h = math.radians(float(heading))
            vel = (float(speed) * math.cos(h), float(speed) * math.sin(h), 0.0)
        alt = d.get("altitude")
        with self._lock:
            now = time.monotonic()
            ep = (GnssEpoch(t=now, fix_type=0) if self.box.deny_gnss else
                  GnssEpoch(t=now, fix_type=3, lat=lat, lon=lon,
                            alt_m=float(alt) if alt is not None else None,
                            h_acc_m=acc * W3C_95_TO_SIGMA,
                            # The browser gives no velocity accuracy, so its
                            # velocity is shown but not fused.
                            vel_ned_ms=vel, s_acc_ms=None))
            out, sent = self.box.process(ep, time.time())
            self.state.update(self.box, out, sent, sending=False)
        return out.mode


# -- the real box -------------------------------------------------------------

class LiveSource(Source):
    """The box service in a thread. gnss_source "receiver" is the full box;
    "fc" is board-only. The deny control exists only with allow_control."""

    def __init__(self, state, cfg: BoxConfig, gnss_source: str, send: bool,
                 allow_control: bool):
        super().__init__(state)
        self.cfg, self.gnss_source = cfg, gnss_source
        self.send = send and gnss_source == "receiver"
        self.controls = ["deny"] if allow_control else []
        self.box = None

    def control(self, action):
        if action != "deny" or "deny" not in self.controls or self.box is None:
            return super().control(action)
        self.box.deny_gnss = not self.box.deny_gnss
        msg = f"GNSS {'DENIED in software' if self.box.deny_gnss else 'restored'}"
        self.state.event(msg, "warn")
        return msg

    def start(self):
        from upin.box.service import run

        def on_start(box):
            self.box = box

        def on_result(box, out, sent):
            self.state.update(box, out, sent, sending=self.send)

        def target():
            try:
                run(self.cfg, send=self.send, gnss_source=self.gnss_source,
                    on_start=on_start, on_result=on_result,
                    stop=self._stop.is_set)
            except (SystemExit, Exception) as exc:   # shown, not swallowed
                self.state.event(f"box stopped: {exc}", "bad")
        threading.Thread(target=target, daemon=True).start()


class ReplaySource(Source):
    def __init__(self, state, path: str, cfg: BoxConfig, speed: float = 1.0):
        super().__init__(state)
        self.path, self.cfg, self.speed = path, cfg, speed

    def start(self):
        def loop():
            box = Box(self.cfg)
            with open(self.path, encoding="utf-8") as f:
                epochs = [epoch_from_json(l) for l in f if l.strip()]
            self.state.event(f"replaying {len(epochs)} epochs from {self.path} "
                             f"(GNSS decisions only; FC sensors are not replayed)")
            last_t = None
            for ep in epochs:
                if self._stop.is_set():
                    return
                if last_t is not None and ep.t > last_t:
                    self._stop.wait((ep.t - last_t) / self.speed)
                last_t = ep.t
                out, sent = box.process(ep, time.time())
                self.state.update(box, out, sent, sending=False)
            self.state.event("replay finished")
        threading.Thread(target=loop, daemon=True).start()
