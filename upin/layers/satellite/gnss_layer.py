"""
L0 -- GNSS and NavIC that know when they are being jammed or lied to (spec 2).

A GNSS receiver is the best navigation sensor on the aircraft until someone
turns on a jammer or a spoofer, and then it is the worst: a jammed receiver
goes quiet, which is survivable, but a spoofed one keeps producing confident,
consistent, wrong fixes. This layer's job is to be useful while the signal is
honest and to stop being believed the moment it may not be.

  jamming        judged from the receiver's own reports -- satellites tracked
                 against satellites the almanac says are up, and how far the
                 noise floor has risen. The legacy layer read the simulator's
                 "jammed" flag instead, which no receiver has.

  integrity      RAIM on every fix, with exclusion of a single faulty
                 satellite when there are enough to spare one.

  spoofing       a spoofer that fakes every satellite consistently passes
                 RAIM, so the fix is also checked against an independent
                 reference -- dead reckoning, landmarks, the Arbiter's
                 estimate -- supplied through set_reference(). A fix that
                 disagrees beyond the combined uncertainty is not reported.

  return         after an outage, or after a rejected fix, the receiver is
                 not trusted again until it has agreed with the reference on
                 several consecutive epochs (spec 2.4). A "returning" signal
                 is exactly what a spoofer would send.

WHERE IT REFUSES

No pseudoranges, fewer than four satellites, a RAIM fault it cannot isolate,
disagreement with the reference, or a return it cannot yet validate -- each
declines with the reason. A rejected solution is carried in raw_data under
"rejected_position", labelled, for the operator; it never reaches fusion as a
position.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from upin.core.layer_base import (
    LayerCapability, LayerGroup, LayerReading, NavigationLayer,
)
from upin.core.no_fabrication import NoFixReason, no_fix
from upin.core.position import Position
from upin.detection.anti_spoof import AntiSpoofDetector
from upin.layers.satellite.gnss_receiver import (
    Reception, consistency, judge_reception, solve,
)

GATE_CHI2_2DOF = 13.816
"""Reference consistency gate: chi-squared, 2 degrees of freedom, p = 0.999.
An honest fix fails it once in a thousand epochs."""


@dataclass
class _Epoch:
    t: Optional[float]
    valid: bool
    reason: str = ""
    detail: str = ""
    solution: object = None
    reception: str = Reception.CLEAR
    reception_why: str = ""
    gate_statistic: Optional[float] = None
    gate_distance_m: Optional[float] = None
    spoof: Optional[Dict] = None


class GNSSReceiverLayer(NavigationLayer):
    """One constellation's receiver. GPS and NavIC subclass it."""

    NO_FABRICATION = True
    CONSTELLATION = "GPS"

    VALIDATION_EPOCHS = 5
    """**Assumption.** Consecutive agreeing epochs before a new or returning
    signal is trusted. At 1 Hz that is five seconds -- long enough that a
    spoofer must hold a consistent lie, short enough not to waste a good
    return. Not tuned against a real spoofer."""

    OUTAGE_S = 2.0
    """A gap this long in the fix stream counts as an outage, after which the
    signal must be validated again before it is believed."""

    REFERENCE_MAX_AGE_S = 5.0

    def __init__(self, layer_id: str, layer_number: int, name: str,
                 description: str):
        super().__init__(
            layer_id=layer_id, layer_number=layer_number, name=name,
            group=LayerGroup.A_SATELLITE_CELESTIAL,
            capabilities=[LayerCapability.POSITION, LayerCapability.TIMING],
            description=description,
        )
        self._epoch: Optional[_Epoch] = None
        self._disabled = False
        self._reference = None           # (lat, lon, sigma, t)
        self._trusted = False
        self._agreeing = 0
        self._ever_trusted = False
        self._last_good_t: Optional[float] = None
        # The gap that defines an outage is a gap in *solutions*, not in
        # trusted fixes: epochs spent validating are not trusted, and
        # measuring from the last trusted fix made every validating epoch
        # look like a fresh outage, so a returning signal never got past
        # one agreeing epoch.
        self._last_solution_t: Optional[float] = None
        self._needs_reference = False
        self._spoof = AntiSpoofDetector()
        self.jamming_map = None
        self.history: List[str] = []

    # -- wiring -----------------------------------------------------

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.7

    def simulate_jamming(self, jammed: bool = True) -> None:
        """Receiver switched off or disconnected. It then reports nothing."""
        self._disabled = jammed

    def set_reference(self, lat: float, lon: float, sigma_m: float,
                      t: Optional[float] = None) -> None:
        """An independent position to check fixes against -- never GNSS."""
        if not (sigma_m > 0 and math.isfinite(sigma_m)):
            raise ValueError("a reference must state a positive sigma")
        self._reference = (lat, lon, sigma_m, t)

    def clear_reference(self) -> None:
        self._reference = None

    @property
    def trusted(self) -> bool:
        return self._trusted

    # -- one receiver epoch -----------------------------------------

    def feed_gnss(self, pseudoranges: Sequence[Dict],
                  quality: Optional[Dict] = None,
                  t: Optional[float] = None) -> _Epoch:
        """One epoch of receiver output: pseudoranges and its own quality."""
        if self._disabled:
            self._epoch = _Epoch(t, False, NoFixReason.SENSOR_UNAVAILABLE,
                                 "receiver disabled")
            return self._epoch

        reception, rwhy = judge_reception(quality)
        sol, why = solve(pseudoranges, self.CONSTELLATION)

        if sol is None:
            self._lose(t)
            reason = (NoFixReason.FAILED_VALIDATION if "RAIM" in why
                      else NoFixReason.INSUFFICIENT_INPUT)
            detail = why + (f"; {rwhy}" if rwhy else "")
            ep = _Epoch(t, False, reason, detail, None, reception, rwhy)
            self._log_jamming(ep, quality)
            self._epoch = ep
            return ep

        # An outage just ended: the signal must earn trust again.
        if (self._ever_trusted and self._last_solution_t is not None
                and t is not None and t - self._last_solution_t > self.OUTAGE_S):
            self._distrust("return after outage", needs_reference=True)
        self._last_solution_t = t

        spoof = self._spoof.check(sol.lat, sol.lon, gps_accuracy_m=sol.drms_m,
                                  gps_signal_dbm=sol.mean_cn0_dbhz or -130.0,
                                  now=t)
        gate_stat = gate_dist = None
        ref = self._fresh_reference(t)
        if ref is not None:
            gate_stat, gate_dist = consistency(
                sol.lat, sol.lon, sol.sigma_east_m, sol.sigma_north_m,
                ref[0], ref[1], ref[2])

        failed = ""
        if spoof["is_spoofed"]:
            failed = "spoof checks: " + ", ".join(a["check"] for a in spoof["alerts"])
        elif gate_stat is not None and gate_stat > GATE_CHI2_2DOF:
            failed = (f"disagrees with the independent reference by "
                      f"{gate_dist:.0f} m (statistic {gate_stat:.1f} > "
                      f"{GATE_CHI2_2DOF:.1f})")

        if failed:
            self._distrust(failed, needs_reference=True)
            ep = _Epoch(t, False, NoFixReason.FAILED_VALIDATION,
                        f"possible spoofing -- {failed}", sol, reception, rwhy,
                        gate_stat, gate_dist, spoof)
        elif not self._trusted:
            if self._needs_reference and ref is None:
                ep = _Epoch(t, False, NoFixReason.FAILED_VALIDATION,
                            "returning signal cannot be validated: no "
                            "independent reference to check it against",
                            sol, reception, rwhy, None, None, spoof)
            else:
                self._agreeing += 1
                if self._agreeing >= self.VALIDATION_EPOCHS:
                    self._trusted = self._ever_trusted = True
                    self._needs_reference = False
                    self.history.append("trusted")
                    ep = _Epoch(t, True, "", "", sol, reception, rwhy,
                                gate_stat, gate_dist, spoof)
                else:
                    ep = _Epoch(t, False, NoFixReason.FAILED_VALIDATION,
                                f"validating: {self._agreeing} of "
                                f"{self.VALIDATION_EPOCHS} agreeing epochs",
                                sol, reception, rwhy, gate_stat, gate_dist, spoof)
        else:
            ep = _Epoch(t, True, "", "", sol, reception, rwhy,
                        gate_stat, gate_dist, spoof)

        if ep.valid:
            self._last_good_t = t
        self._log_jamming(ep, quality)
        self._epoch = ep
        return ep

    def _fresh_reference(self, t):
        if self._reference is None:
            return None
        lat, lon, sigma, rt = self._reference
        if t is not None and rt is not None and t - rt > self.REFERENCE_MAX_AGE_S:
            return None
        return self._reference

    def _lose(self, t) -> None:
        if self._trusted and self._last_solution_t is not None and t is not None \
                and t - self._last_solution_t > self.OUTAGE_S:
            self._distrust("outage", needs_reference=True)

    def _distrust(self, why: str, needs_reference: bool) -> None:
        if self._trusted or self._agreeing:
            self.history.append(f"distrusted: {why}")
        self._trusted = False
        self._agreeing = 0
        self._needs_reference = self._needs_reference or needs_reference
        self._spoof = AntiSpoofDetector()

    def _log_jamming(self, ep: _Epoch, quality: Optional[Dict]) -> None:
        if self.jamming_map is None or not quality:
            return
        if ep.valid and ep.solution is not None:
            lat, lon, sig = ep.solution.lat, ep.solution.lon, ep.solution.drms_m
        elif self._reference is not None:
            lat, lon, sig = self._reference[0], self._reference[1], self._reference[2]
        else:
            return      # nowhere trustworthy to pin the observation
        self.jamming_map.record(lat, lon, sig,
                                float(quality.get("noise_floor_rise_db") or 0.0),
                                int(quality.get("tracked", 0)))

    # -- the reading ------------------------------------------------

    def read(self) -> LayerReading:
        ep = self._epoch
        if ep is None:
            return no_fix(self.layer_id, NoFixReason.NO_INPUT,
                          self.REQUIRES.describe_missing(),
                          feed_via=self.REQUIRES.feed_methods)
        extra = {"reception": ep.reception, "reception_detail": ep.reception_why,
                 "constellation": self.CONSTELLATION, "independent": True}
        sol = ep.solution
        if sol is not None:
            extra.update(satellites=sol.satellites, hdop=round(sol.hdop, 3),
                         vdop=round(sol.vdop, 3), pdop=round(sol.pdop, 3),
                         radius95_m=round(sol.radius95_m, 3),
                         raim_statistic=sol.raim_statistic,
                         raim_threshold=sol.raim_threshold, raim_ok=sol.raim_ok,
                         excluded_satellites=list(sol.excluded))
        if ep.gate_statistic is not None:
            extra.update(reference_statistic=round(ep.gate_statistic, 3),
                         reference_distance_m=round(ep.gate_distance_m, 2))
        if not ep.valid:
            if sol is not None:
                extra["rejected_position"] = {
                    "lat": sol.lat, "lon": sol.lon, "drms_m": sol.drms_m,
                    "note": "not trusted -- for the operator, never for fusion"}
            return no_fix(self.layer_id, ep.reason, ep.detail, **extra)
        return LayerReading(
            layer_id=self.layer_id,
            position=Position(latitude=sol.lat, longitude=sol.lon,
                              altitude=sol.alt, accuracy_m=sol.drms_m,
                              altitude_accuracy_m=sol.sigma_up_m,
                              timestamp=ep.t or 0.0),
            self_confidence=float(1.0 / (1.0 + sol.radius95_m / 20.0)),
            is_valid=True,
            raw_data={"fabricated": False, "trusted": True,
                      "validated_against_reference": ep.gate_statistic is not None,
                      **extra},
        )
