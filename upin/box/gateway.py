"""
The box's decision, once per GNSS epoch: what does the flight controller get?

  TRUSTED   the receiver's own fix, passed through, with its own accuracy
  DEGRADED  UPIN's estimate (HonestKalman, predicted from the last trusted
            fix plus any non-GNSS velocity such as optical flow), with its
            honest, growing accuracy
  NO_FIX    nothing trustworthy -- the flight controller's failsafe takes over

A fix is distrusted, with the reason recorded, when any of these says so:

  1. the receiver has no 3-D fix
  2. the receiver's RF monitor reports jamming as critical
  3. per-constellation fixes disagree (constellation_check) -- only when
     they are supplied; a single blended fix cannot be split afterwards
  4. the fix is physically impossible for this airframe (reachability)
  5. the fix fails the Kalman filter's innovation gate: inconsistent with
     where UPIN, from its own uncertainty, expects the aircraft to be

After a distrust, GNSS must pass all five checks for RETURN_EPOCHS epochs
running before it is TRUSTED again (return validation, as in L0). The one
exception: a single isolated failure of check 5 alone distrusts only that
epoch. That gate is statistical and an honest fix fails it one time in a
thousand by design; two in a row starts return validation.

WHAT IT CANNOT CATCH

- Spoofing from power-on: before the first trusted fix there is nothing to
  compare against except other constellations.
- A slow drag-off within the airframe's envelope passes check 4; check 5
  catches it only once the drift exceeds the filter's own uncertainty, and
  while GNSS is trusted that uncertainty is set by GNSS itself. The L0
  layers' independent-reference gate is the stronger check for this.
- A spoofer faking every constellation consistently passes check 3.

Simulation and synthetic inputs only. Never run against a flight controller.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from upin.detection.constellation_check import (CANNOT_RULE_OUT,
                                                ConstellationFix, cross_check)
from upin.detection.reachability import Envelope, ReachabilityGuard
from upin.fusion.honest_kalman import HonestKalmanFusion

TRUSTED, DEGRADED, NO_FIX = "TRUSTED", "DEGRADED", "NO_FIX"


def body_to_ne(forward: float, right: float, heading_deg: float) -> Tuple[float, float]:
    """Rotate a forward/right vector to north/east (heading clockwise from
    north)."""
    h = math.radians(heading_deg)
    return (forward * math.cos(h) - right * math.sin(h),
            forward * math.sin(h) + right * math.cos(h))


@dataclass
class GnssEpoch:
    """One epoch from the receiver, already parsed."""
    t: float
    fix_type: int                       # UBX convention: 3 = 3-D
    lat: float = 0.0
    lon: float = 0.0
    alt_m: Optional[float] = None
    h_acc_m: float = float("inf")       # the receiver's own estimate
    v_acc_m: Optional[float] = None
    vel_ned_ms: Optional[Tuple[float, float, float]] = None
    s_acc_ms: Optional[float] = None
    num_sv: int = 0
    jamming_state: str = "unknown"      # from MON-RF, if the receiver has it
    constellation_fixes: Sequence[ConstellationFix] = ()
    power_check: Optional[dict] = None   # verdict of layer cn0spoof_a20, if run


@dataclass
class GatewayOutput:
    t: float
    mode: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    alt_m: Optional[float] = None
    h_acc_m: Optional[float] = None
    vel_ned_ms: Optional[Tuple[float, float, float]] = None
    s_acc_ms: Optional[float] = None
    num_sv: int = 0
    reasons: List[str] = field(default_factory=list)
    caveat: str = ""


class Gateway:
    RETURN_EPOCHS = 5
    """**Assumption**, matching L0's VALIDATION_EPOCHS: consecutive clean
    epochs before GNSS is trusted again after any distrust."""

    MAX_DEGRADED_H_ACC_M = 50.0
    """Above this, UPIN's own estimate is too loose to fly on and the box
    reports NO_FIX instead. A setting for the operator, not a measured
    figure."""

    def __init__(self, envelope: Envelope,
                 max_degraded_h_acc_m: Optional[float] = None,
                 power_check_action: str = "warn"):
        """power_check_action: "warn" shows the signal-power check without
        acting on it (its thresholds are not yet calibrated); "distrust"
        makes it a hard check."""
        if power_check_action not in ("warn", "distrust"):
            raise ValueError("power_check_action must be 'warn' or 'distrust'")
        self.power_check_action = power_check_action
        self._warnings: List[str] = []
        self.guard = ReachabilityGuard(envelope)
        self.kf = HonestKalmanFusion()
        self.max_degraded_h_acc_m = (max_degraded_h_acc_m
                                     if max_degraded_h_acc_m is not None
                                     else self.MAX_DEGRADED_H_ACC_M)
        self._clean_run = 0
        self._ever_distrusted = False
        self._gate_only_run = 0
        self._trusted_h_acc: Optional[float] = None
        self._trusted_drms: float = 0.0
        self.last_checks: List[dict] = []
        self.log: List[GatewayOutput] = []

    # -- inputs besides GNSS ------------------------------------------------

    def feed_velocity(self, vn: float, ve: float, sigma_ms: float, t: float,
                      source: str = "optical_flow") -> None:
        """Ground velocity from a non-GNSS sensor. This is what keeps the
        DEGRADED estimate tight; without it the estimate only coasts."""
        if self.kf.estimate() is None:
            return
        self.kf.predict(t)
        self.kf.update_velocity(vn, ve, sigma_ms, source=source)

    def feed_flow(self, forward_ms: float, right_ms: float, heading_deg: float,
                  sigma_ms: float, t: float, source: str = "optical_flow") -> None:
        """Body-frame ground velocity from a downward flow sensor, already
        scaled by height, turned to north/east with the heading."""
        vn, ve = body_to_ne(forward_ms, right_ms, heading_deg)
        self.feed_velocity(vn, ve, sigma_ms, t, source=source)

    def feed_heading(self, heading_deg: float, sigma_deg: float, t: float,
                     source: str = "heading") -> None:
        if self.kf.estimate() is None:
            return
        self.kf.predict(t)
        self.kf.update_heading(heading_deg, sigma_deg, source=source)

    def feed_altitude(self, alt_m: float, sigma_m: float, t: float,
                      source: str = "baro") -> None:
        if self.kf.estimate() is None:
            return
        self.kf.predict(t)
        self.kf.update_altitude(alt_m, sigma_m, source=source)

    # -- the decision -------------------------------------------------------

    def _checks(self, ep: GnssEpoch) -> Tuple[List[str], bool]:
        """The reasons to distrust, and whether the only one is the
        statistical gate. Each check's own result is kept in last_checks,
        for display: PASS, FAIL, or NOT RUN with the reason it could not."""
        why: List[str] = []
        checks: List[dict] = []
        self.last_checks = checks
        self._warnings = []

        def note(name, status, detail):
            checks.append({"check": name, "status": status, "detail": detail})

        # Signal power first: it can see jamming even when there is no fix.
        pc = ep.power_check
        if pc is None:
            note("signal power pattern", "NOT RUN",
                 "no per-satellite signal data (UBX NAV-SAT)")
        elif pc["verdict"] == "NOT_RUN":
            note("signal power pattern", "NOT RUN", pc["reason"])
        elif pc["verdict"] in ("SUSPECT_SPOOFING", "JAMMING"):
            label = "spoofing suspected" if pc["verdict"] == "SUSPECT_SPOOFING" else "jamming"
            if self.power_check_action == "distrust":
                why.append(f"signal power, {label}: {pc['reason']}")
                note("signal power pattern", "FAIL", f"{label}: {pc['reason']}")
            else:
                self._warnings.append(f"signal power, {label}: {pc['reason']}")
                note("signal power pattern", "WARN",
                     f"{label}: {pc['reason']} (warning only: thresholds not "
                     f"yet calibrated on this receiver)")
        else:
            note("signal power pattern", "PASS", pc["reason"])
        if ep.fix_type < 3:
            note("receiver fix", "FAIL", "no 3-D fix")
            return ["receiver has no 3-D fix"], False
        if not math.isfinite(ep.h_acc_m) or ep.h_acc_m <= 0:
            note("receiver fix", "FAIL", "the receiver does not state its accuracy")
            return ["receiver gives a fix but not its accuracy: unusable"], False
        if ep.h_acc_m > self.max_degraded_h_acc_m:
            # Also stops a spoofer widening the checks below by claiming a
            # huge accuracy figure.
            note("receiver fix", "FAIL",
                 f"accuracy {ep.h_acc_m:.1f} m worse than the "
                 f"{self.max_degraded_h_acc_m:.0f} m limit")
            return [f"receiver's own accuracy {ep.h_acc_m:.0f} m is too poor "
                    f"to use"], False
        note("receiver fix", "PASS", f"3-D, accuracy {ep.h_acc_m:.1f} m")
        if ep.jamming_state == "critical":
            why.append("receiver reports jamming as critical")
            note("receiver jamming report", "FAIL", "critical")
        elif ep.jamming_state in ("ok", "warning"):
            note("receiver jamming report", "PASS", ep.jamming_state)
        else:
            note("receiver jamming report", "NOT RUN",
                 "this receiver does not report a jamming state")
        if ep.constellation_fixes:
            cc = cross_check(ep.constellation_fixes)
            if cc.checked and not cc.consistent:
                why.append(f"constellations disagree: {cc.reason} "
                           f"(suspect: {', '.join(cc.suspects)})")
                note("cross-check", "FAIL",
                     f"{cc.reason} (suspect: {', '.join(cc.suspects)})")
            elif cc.checked:
                note("cross-check", "PASS", f"{cc.reason}; {cc.caveat}")
            else:
                note("cross-check", "NOT RUN", cc.reason)
        else:
            note("cross-check", "NOT RUN", "no second receiver or "
                 "per-constellation fix supplied")
        v = self.guard.check(ep.lat, ep.lon, ep.t, sigma_m=ep.h_acc_m)
        if not v.possible:
            why.append(v.reason)
            note("physically reachable", "FAIL", v.reason)
        elif self.guard.anchored:
            note("physically reachable", "PASS",
                 f"{-v.excess_m:.0f} m inside the region")
        else:
            note("physically reachable", "NOT RUN", v.reason)
        hard = bool(why)
        if self.kf.estimate() is not None:
            trial = copy.deepcopy(self.kf)
            d = trial.update_position(ep.lat, ep.lon, ep.h_acc_m,
                                      source="gnss", t=ep.t)
            if not d.accepted:
                why.append(f"inconsistent with UPIN's own estimate "
                           f"({d.reason})")
                note("consistent with UPIN's estimate", "FAIL", d.reason)
            else:
                note("consistent with UPIN's estimate", "PASS",
                     f"NIS {d.nis:.1f} <= {d.threshold:.1f}"
                     if d.nis is not None and d.threshold is not None
                     else d.reason)
        else:
            note("consistent with UPIN's estimate", "NOT RUN",
                 "no estimate yet")
        return why, bool(why) and not hard

    def _accept(self, ep: GnssEpoch) -> None:
        self.kf.update_position(ep.lat, ep.lon, ep.h_acc_m, source="gnss",
                                t=ep.t, alt=ep.alt_m, sigma_v_m=ep.v_acc_m)
        vel = (0.0, 0.0)
        if ep.vel_ned_ms is not None and ep.s_acc_ms and ep.s_acc_ms > 0:
            self.kf.update_velocity(ep.vel_ned_ms[0], ep.vel_ned_ms[1],
                                    ep.s_acc_ms, source="gnss_doppler")
            vel = (ep.vel_ned_ms[0], ep.vel_ned_ms[1])
        self._trusted_h_acc = ep.h_acc_m
        self._trusted_drms = self.kf.estimate().drms_m
        self.guard.anchor(ep.lat, ep.lon, ep.t, velocity_ne=vel,
                          sigma_pos_m=ep.h_acc_m,
                          sigma_vel_ms=ep.s_acc_ms or 1.0)

    def process(self, ep: GnssEpoch) -> GatewayOutput:
        why, gate_only = self._checks(ep)
        self._gate_only_run = self._gate_only_run + 1 if gate_only else 0
        caveat = CANNOT_RULE_OUT if ep.constellation_fixes else (
            "no per-constellation fixes supplied: constellations not cross-checked")
        if why:
            isolated = gate_only and self._gate_only_run == 1
            if not isolated:
                self._clean_run = 0
                self._ever_distrusted = (self._ever_distrusted
                                         or self.kf.estimate() is not None)
            out = self._degraded(ep.t, why)
        elif self._ever_distrusted and self._clean_run + 1 < self.RETURN_EPOCHS:
            self._clean_run += 1
            out = self._degraded(ep.t, [
                f"GNSS back and clean, validating {self._clean_run}/"
                f"{self.RETURN_EPOCHS} epochs before trusting it"])
        else:
            self._accept(ep)
            self._clean_run = 0
            self._ever_distrusted = False
            out = GatewayOutput(ep.t, TRUSTED, ep.lat, ep.lon, ep.alt_m,
                                ep.h_acc_m, ep.vel_ned_ms, ep.s_acc_ms,
                                ep.num_sv,
                                ["all checks passed"] if not self._warnings else
                                ["all hard checks passed"] +
                                [f"warning: {w}" for w in self._warnings])
        out.caveat = caveat
        self.log.append(out)
        return out

    def _degraded(self, t: float, why: List[str]) -> GatewayOutput:
        if self.kf.estimate() is None:
            return GatewayOutput(t, NO_FIX, reasons=why + [
                "no trusted fix yet: UPIN has no estimate of its own"])
        self.kf.predict(t)
        est = self.kf.estimate()
        # The filter treats successive GNSS fixes as independent, so its own
        # spread can shrink below the receiver's accuracy. Real GNSS errors
        # persist for minutes (multipath, ionosphere), so that shrinkage is
        # not real. Floor: the receiver's accuracy at the last trusted fix,
        # plus whatever uncertainty the filter has gained since.
        grown = math.sqrt(max(est.drms_m ** 2 - self._trusted_drms ** 2, 0.0))
        h_acc = (math.hypot(self._trusted_h_acc, grown)
                 if self._trusted_h_acc is not None else est.drms_m)
        if h_acc > self.max_degraded_h_acc_m:
            return GatewayOutput(t, NO_FIX, reasons=why + [
                f"UPIN's own estimate has grown to {h_acc:.0f} m, beyond the "
                f"{self.max_degraded_h_acc_m:.0f} m limit"])
        return GatewayOutput(t, DEGRADED, est.lat, est.lon, est.alt, h_acc,
                             (est.velocity_ne[0], est.velocity_ne[1], 0.0),
                             est.sigma_velocity_ms, 0, why)
