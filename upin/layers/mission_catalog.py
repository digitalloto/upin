"""
The mission catalogue: every honest way UPIN can get a position, velocity,
heading or check -- what each gives, what it needs, which situations it
works in, what it has measured in simulation, the box.toml lines that turn
it on, and its README. Hand-written and tested against the registry.

Only components that honour the no-fabrication contract and have been
tested are listed. The layers that still invent readings are never
recommended; tools/mission_index.py lists them separately from the
registry so nobody loads one by mistake.

Every accuracy figure here is a SIMULATION figure until the bench says
otherwise.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

# -- vocabulary -----------------------------------------------------------------

HARDWARE_TAGS: Dict[str, str] = {
    "flight_controller": "ArduPilot flight controller over MAVLink (IMU, compass, barometer)",
    "gnss_receiver": "a GNSS receiver on the box with UBX output (NAV-PVT, NAV-SAT, MON-RF)",
    "raw_gnss": "a receiver with raw pseudoranges (and the ephemeris decoder, not built)",
    "second_receiver": "a second GNSS receiver or the flight controller's own",
    "camera": "a downward camera on the box",
    "rangefinder": "a downward rangefinder on the flight controller",
    "flow_chip": "an optical-flow sensor on the flight controller",
    "tags_surveyed": "printed UPIN tags at surveyed spots",
    "beacon_radio": "a ranging radio on the box, with a shared secret",
    "beacons_deployed": "three or more known-position beacons on the beacon band",
    "crumb_dispenser": "breadcrumb units and a release mechanism",
    "formation_peers": "two or more drones flying together, each with the box and a ranging radio",
    "sdr": "an RTL-SDR dongle and a VHF antenna, with fresh orbit elements",
    "trained_model": "an AI motion predictor model trained on this airframe's flights",
    "georeferenced_map": "an Indian-source map with charted landmarks",
    "attitude_mode_fc": "a flight controller in a non-GPS attitude mode (GUIDED_NOGPS)",
    "command_log": "a readable motor-command stream from the flight controller",
}

SITUATIONS: Dict[str, str] = {
    "gnss_healthy": "GNSS healthy",
    "jammed": "GNSS jammed (no fix)",
    "spoofed": "GNSS spoofed (a fix, but a lie)",
    "long_denial": "GNSS denied for minutes",
    "night": "night or no light",
    "featureless": "featureless ground or water",
    "indoor": "indoor",
    "fast": "moving fast",
    "still": "stationary or hovering",
}

YES, LIMITED, NO = "yes", "limited", "no"


@dataclass(frozen=True)
class Entry:
    layer_id: str                      # registry id, or "box:<name>" for a box component
    name: str
    gives: FrozenSet[str]              # POSITION / VELOCITY / HEADING / ALTITUDE / CHECK
    needs: FrozenSet[str]              # HARDWARE_TAGS keys
    works: Dict[str, Tuple[str, str]]  # situation -> (yes/limited/no, why)
    measured: str                      # simulation figures, labelled
    enable: str                        # box.toml lines, or how it runs
    readme: str
    status: str                        # simulation / untested driver / bench
    falls_back_to: str = ""
    notes: str = ""

    @property
    def in_box(self) -> bool:
        return not self.enable.startswith("not in the box")


def _w(**kw) -> Dict[str, Tuple[str, str]]:
    """works-when table with a default of yes."""
    out = {s: (YES, "") for s in SITUATIONS}
    for k, v in kw.items():
        out[k] = v
    return out


E = Entry
ENTRIES: List[Entry] = [
    E("gps_l1", "GPS (L0, raw measurements)", frozenset({"POSITION"}),
      frozenset({"raw_gnss"}),
      _w(jammed=(NO, "no satellites"), spoofed=(LIMITED, "detects a drag-off against an "
         "independent reference; a consistent multi-constellation spoof passes"),
         long_denial=(NO, "no satellites"), indoor=(NO, "no sky")),
      "Simulation: RAIM/FDE on raw pseudoranges; caught a 1 m/s drag-off spoof after 14 s "
      "against an independent reference.",
      "not in the box yet: needs raw pseudoranges and the ephemeris decoder (not built); "
      "the box uses the receiver's own fix", "docs/layers/gps_l1.md",
      "simulation; not wired into the box"),
    E("navic_l2", "NavIC (L0, raw measurements)", frozenset({"POSITION"}),
      frozenset({"raw_gnss"}),
      _w(jammed=(NO, "no satellites"), spoofed=(LIMITED, "as GPS; cross-checked against GPS"),
         long_denial=(NO, "no satellites"), indoor=(NO, "no sky")),
      "Simulation: as GPS; the sovereign constellation for the cross-check.",
      "not in the box yet: as GPS", "docs/layers/navic_l2.md",
      "simulation; not wired into the box"),
    E("box:receiver_fix", "The receiver's own fix, checked (box gateway)",
      frozenset({"POSITION", "VELOCITY", "ALTITUDE"}), frozenset({"gnss_receiver"}),
      _w(jammed=(NO, "no fix: the box reports NO_FIX or coasts"),
         spoofed=(LIMITED, "a jump is caught by the reachable region and the filter gate; a "
                  "slow drag inside the airframe's envelope is not"),
         long_denial=(NO, "no fix"), indoor=(NO, "no sky")),
      "Simulation: 500 m spoof jump rejected as physically impossible; honest fixes never fell "
      "outside the reachable region (0 of 11,600).",
      "receiver_port = \"/dev/ttyUSB0\"", "docs/HARDWARE.md", "simulation; serial I/O untested",
      falls_back_to="UPIN's own estimate (DEGRADED), then NO_FIX"),
    E("box:cross_check", "Cross-constellation / second-receiver check",
      frozenset({"CHECK"}), frozenset({"gnss_receiver", "second_receiver"}),
      _w(jammed=(NO, "nothing to compare"), spoofed=(LIMITED, "catches a spoofer faking one "
         "constellation or receiver; a consistent spoof of all passes, and the check says so"),
         long_denial=(NO, "no fixes"), indoor=(NO, "no sky")),
      "Simulation: GPS-only spoof flagged; 1 in 5,000 false alarms on honest pairs.",
      "automatic when the flight controller's GPS reports accuracy; split the constellations "
      "between the two receivers to make it a constellation check", "docs/HARDWARE.md",
      "simulation"),
    E("cn0spoof_a20", "GNSS signal-power spoof check (146)", frozenset({"CHECK"}),
      frozenset({"gnss_receiver"}),
      _w(jammed=(LIMITED, "reports jamming from the receiver's gain control"),
         spoofed=(LIMITED, "catches one transmitter with uniform power; an elevation-shaped "
                  "spoofer passes"), long_denial=(LIMITED, "jamming only"), indoor=(NO, "no sky")),
      "Simulation: 0 of 3,600 false alarms on a synthetic sky; simple spoofer caught every time; "
      "the smart spoofer is not, and the test says so.",
      "power_check_action = \"warn\"   # \"distrust\" once calibrated on this receiver",
      "docs/layers/cn0spoof_a20.md", "simulation; thresholds unmeasured"),
    E("box:reachability", "Physically reachable region", frozenset({"CHECK"}),
      frozenset({"flight_controller"}),
      _w(jammed=(LIMITED, "bounds where the drone can be from the last trusted fix"),
         spoofed=(LIMITED, "a jump is impossible; a slow drag inside the envelope is not seen")),
      "Simulation: 0 false alarms in 11,600 honest fixes; a 500 m jump rejected.",
      "max_accel_ms2 and max_airspeed_ms from the airframe's spec, never tuned to a result",
      "docs/HARDWARE.md", "simulation"),
    E("box:kalman", "HonestKalman fusion", frozenset({"POSITION", "VELOCITY", "HEADING", "ALTITUDE"}),
      frozenset({"flight_controller"}),
      _w(jammed=(LIMITED, "coasts; uncertainty grows honestly; velocity sensors keep it tight"),
         long_denial=(LIMITED, "only as good as the velocity and fix sources below")),
      "Simulation: 95% circle covers 94.8% (theory 95%); Doppler cut 60 s drift from 13.4 to "
      "5.1 m; the only option that rejected a 300 m outlier.",
      "always on in the box", "docs/KALMAN.md", "simulation",
      falls_back_to="coasting on its own prediction, with a growing circle"),
    E("box:flow_chip", "Flight controller's flow sensor, integrity-checked",
      frozenset({"VELOCITY"}), frozenset({"flight_controller", "flow_chip", "rangefinder"}),
      _w(night=(LIMITED, "the chip needs light"), featureless=(NO, "no texture to track"),
         indoor=(LIMITED, "works on a textured floor")),
      "Simulation: 60 s without GNSS, h_acc 4.7 m with flow vs 269 m coasting; a moving ground "
      "pattern is caught by the IMU check (flow_integrity).",
      "automatic from MAVLink OPTICAL_FLOW; flow_check_action = \"distrust\"",
      "docs/HARDWARE.md", "simulation", falls_back_to="camera flow, then the AI predictor, then coasting"),
    E("camflow_e24", "Camera optical flow with weighted RANSAC (148)", frozenset({"VELOCITY"}),
      frozenset({"camera", "rangefinder", "flight_controller"}),
      _w(night=(NO, "needs light"), featureless=(NO, "no texture: declines"),
         spoofed=(YES, "a moving ground pattern is thrown out"),
         indoor=(LIMITED, "a textured floor"), fast=(LIMITED, "search radius; measure")),
      "Simulation: 0.22 m/s rms honest flight; laser dots 4 m apart: naive tracker dragged "
      "1.6 m/s, ours within 0.40 m/s; dots in every patch followed (stated limit).",
      "camera = \"pi\"\ncamera_fov_deg = 62.0\ncamera_flow = true",
      "docs/CAMERA_FLOW.md", "simulation; camera untested",
      falls_back_to="the AI predictor, then coasting"),
    E("learnedio_b14", "AI motion predictor (147)", frozenset({"VELOCITY"}),
      frozenset({"flight_controller", "trained_model"}),
      _w(jammed=(YES, "needs a wind estimate learned while GNSS was good"),
         long_denial=(LIMITED, "errors persist; the record measures it"),
         night=(YES, "no camera needed"), featureless=(YES, "no camera needed"),
         indoor=(LIMITED, "no wind, so stamps assume calm"),
         fast=(LIMITED, "only within the conditions it trained in; flags outside")),
      "Simulation: 0.46 m/s air-velocity rms on held-out flights; through the box 60 s without "
      "GNSS: 23 m vs 309 m coasting. A model trained on the simulator knows only the simulator.",
      "airframe_id = \"my-quad-1\"\nlearned_io_model = \"upin_flights/models/vN.npz\"",
      "docs/LEARNED_IO.md", "simulation; needs real flight logs",
      falls_back_to="coasting"),
    E("cmddr_b12", "Command-based dead reckoning (143)", frozenset({"POSITION", "VELOCITY"}),
      frozenset({"command_log", "flight_controller"}),
      _w(long_denial=(LIMITED, "drifts with unmodelled wind; needs a calibrated airframe model"),
         night=(YES, ""), featureless=(YES, "")),
      "Simulation: accurate to 1-2 m over a 500 m denied leg while stating 20-42 m (overconfident "
      "statement noted).",
      "not in the box yet: needs the flight controller's command stream mapped in",
      "docs/layers/cmddr_b12.md", "simulation; not wired into the box"),
    E("mapclick_b13", "Map-click guided navigation (145)", frozenset({"POSITION", "HEADING", "VELOCITY"}),
      frozenset({"attitude_mode_fc", "flight_controller"}),
      _w(long_denial=(LIMITED, "a propagated estimate with a growing circle"),
         night=(YES, ""), featureless=(YES, "")),
      "Simulation: reached a 500 m GPS-denied target with the truth inside its 95% circle ~98% "
      "of the time in gusty air.",
      "not in the box yet: a guidance layer; flown through the autopilot interface",
      "docs/layers/mapclick_b13.md", "simulation; MAVLink untested"),
    E("fiducial_e25", "Tag landmarks (149)", frozenset({"POSITION", "ALTITUDE"}),
      frozenset({"camera", "tags_surveyed", "flight_controller"}),
      _w(night=(NO, "needs light"), featureless=(YES, "the tag is the feature"),
         indoor=(YES, "tags on the floor"), spoofed=(YES, "physical: cannot be spoofed by radio"),
         jammed=(YES, ""), long_denial=(LIMITED, "only while a tag is in view")),
      "Simulation: position within 0.4 px, height within 0.5 m at 50 m; re-anchors the filter "
      "to under a metre while in view.",
      "camera = \"pi\"\ntag_map = \"/etc/upin/tags.json\"", "docs/TAGS.md",
      "simulation; camera untested", falls_back_to="whatever else is loaded"),
    E("lmkchain_e23", "Landmark chain navigation (144)", frozenset({"POSITION", "HEADING"}),
      frozenset({"camera", "georeferenced_map", "flight_controller"}),
      _w(night=(NO, "needs light"), featureless=(NO, "no landmarks"), indoor=(NO, "no charted landmarks"),
         spoofed=(YES, "physical"), jammed=(YES, "")),
      "Simulation: resection from charted landmarks with the solve's covariance as accuracy; "
      "breadcrumbs for the return leg.",
      "not in the box yet: needs the landmark detector and an Indian-source map",
      "docs/layers/lmkchain_e23.md", "simulation; not wired into the box"),
    E("beaconrng_d27", "Known-position beacons, balloons included (151)", frozenset({"POSITION", "ALTITUDE"}),
      frozenset({"beacon_radio", "beacons_deployed"}),
      _w(jammed=(YES, "a different band"), spoofed=(YES, "signed, hopping"),
         long_denial=(YES, "while beacons are up"), night=(YES, ""), featureless=(YES, ""),
         indoor=(LIMITED, "short-range beacons only")),
      "Simulation: four ground beacons with 10 m ranging: 6 m rms, 97% coverage; four balloons "
      "inside a 3 km GNSS jammer: 13 m rms; a beacon-band jammer silences it, stated.",
      "beacon_radio = \"/dev/ttyUSB1\"\nbeacon_secret_file = \"/etc/upin/beacon.key\"",
      "docs/BEACONS.md", "simulation; radio and firmware not built",
      falls_back_to="breadcrumbs, then the AI predictor and coasting"),
    E("breadcrumb_d28", "Breadcrumb beacons (152)", frozenset({"POSITION", "ALTITUDE"}),
      frozenset({"beacon_radio", "crumb_dispenser"}),
      _w(jammed=(YES, "if crumbs were dropped on the way in"), spoofed=(YES, "signed"),
         long_denial=(LIMITED, "along the trail; poor past it"), night=(YES, ""),
         featureless=(YES, ""), indoor=(LIMITED, "short range"),
         gnss_healthy=(LIMITED, "drops only while trusted; no fix needed then")),
      "Simulation: 20 m rms with 22 m stated sigma along a weaving trail, 96% coverage; "
      "crumbs on a straight line decline on geometry (stated limit).",
      "beacon_radio = \"/dev/ttyUSB1\"\nbeacon_secret_file = \"/etc/upin/beacon.key\"\n"
      "breadcrumbs = true", "docs/BREADCRUMBS.md", "simulation; crumb firmware not built",
      falls_back_to="the AI predictor and coasting"),
    E("formation_d29", "Formation cross-check and cooperative fix (153)",
      frozenset({"CHECK", "POSITION", "ALTITUDE"}), frozenset({"beacon_radio", "formation_peers"}),
      _w(gnss_healthy=(YES, "every fix is checked against the measured ranges to the peers"),
         jammed=(LIMITED, "a fix only while two peers keep trusted GNSS; a wide-area jammer takes "
                 "the whole formation down together"),
         spoofed=(YES, "a single spoofer gives every receiver the same place while the ranges show "
                  "the formation intact; a tailored multi-transmitter spoof passes (stated)"),
         long_denial=(LIMITED, "as jammed"), indoor=(LIMITED, "short range; same rules"),
         still=(LIMITED, "a hovering formation keeps its geometry; the fix needs the drone off "
                "the line between its peers")),
      "Simulation: a V of three, 40 m back and ±40 m aside, 10 m ranging: no false alarm in 300 s "
      "(0.45% of pairs over 3 sigma, as noise predicts); a single spoofer caught on every epoch; a "
      "lead without GNSS placed to 12 m rms with a stated 11 m; a tailored spoof passes, stated.",
      "beacon_radio = \"/dev/ttyUSB1\"\nbeacon_secret_file = \"/etc/upin/beacon.key\"\n"
      "formation = true\ndrone_id = \"lead\"", "docs/FORMATION.md",
      "simulation; radio firmware not built",
      falls_back_to="beacons or breadcrumbs if deployed, then the AI predictor and coasting"),
    E("leodoppler_a21", "LEO Doppler anchor (150)", frozenset({"POSITION"}),
      frozenset({"sdr"}),
      _w(jammed=(YES, "a different band"), spoofed=(LIMITED, "a faked Doppler curve is possible"),
         long_denial=(LIMITED, "one coarse fix per pass, an hour or two apart"),
         fast=(NO, "the receiver must be still or state its motion"),
         indoor=(NO, "no sky"), still=(YES, "")),
      "Simulation: 250 m error with 190 m stated sigma per pass; a wrong satellite fits "
      "perfectly and is refused by the prior; the mirror is reported or declined.",
      "sdr = \"rtl\"\nleo_satellites = \"/etc/upin/satellites.json\"",
      "docs/LEO_DOPPLER.md", "simulation; radio untested",
      falls_back_to="nothing: it is the last anchor"),
]

BY_ID: Dict[str, Entry] = {e.layer_id: e for e in ENTRIES}

LADDERS: Dict[str, List[Tuple[str, str]]] = {
    "velocity": [
        ("box:flow_chip", "sub-metre per second; needs light and texture"),
        ("camflow_e24", "about 0.2-0.4 m/s; throws out moving patterns"),
        ("learnedio_b14", "about 0.5 m/s, worse outside its training; no camera needed"),
        ("box:kalman", "coasting: the circle grows with the square of time"),
    ],
    "position": [
        ("box:receiver_fix", "metres, while trusted"),
        ("fiducial_e25", "sub-metre while a tag is in view"),
        ("beaconrng_d27", "metres to tens of metres while beacons are up"),
        ("breadcrumb_d28", "tens of metres along the trail"),
        ("formation_d29", "about ten metres while two peers keep trusted GNSS"),
        ("leodoppler_a21", "hundreds of metres, once per pass, when still"),
        ("box:kalman", "dead reckoning from the last fix: the circle grows"),
    ],
}

PROFILES: List[Tuple[str, str, FrozenSet[str]]] = [
    ("Bench rig, shadow mode", "gnss_healthy", frozenset({"flight_controller", "gnss_receiver", "second_receiver"})),
    ("Day flight into jamming, camera fitted", "jammed",
     frozenset({"flight_controller", "gnss_receiver", "camera", "rangefinder", "flow_chip", "tags_surveyed"})),
    ("Night flight into jamming, no camera", "jammed",
     frozenset({"flight_controller", "gnss_receiver", "trained_model", "beacon_radio", "beacons_deployed", "crumb_dispenser"})),
    ("Spoofing suspected, two receivers", "spoofed",
     frozenset({"flight_controller", "gnss_receiver", "second_receiver", "camera", "rangefinder", "tags_surveyed"})),
    ("Long denial, stationary observation post", "long_denial",
     frozenset({"flight_controller", "gnss_receiver", "sdr", "beacon_radio", "beacons_deployed"})),
    ("Indoor test", "indoor", frozenset({"flight_controller", "camera", "rangefinder", "tags_surveyed"})),
    ("Formation of three into spoofing", "spoofed",
     frozenset({"flight_controller", "gnss_receiver", "beacon_radio", "formation_peers"})),
]


def recommend(have: Sequence[str], situation: str) -> List[Tuple[Entry, str, str]]:
    """(entry, verdict, why) for every entry usable in the box with the
    hardware at hand, in ladder order; verdict is yes/limited. Entries that
    cannot work in the situation or lack hardware are left out."""
    have_set = set(have)
    unknown = have_set - set(HARDWARE_TAGS)
    if unknown:
        raise ValueError(f"unknown hardware tag(s) {sorted(unknown)}; known: {sorted(HARDWARE_TAGS)}")
    if situation not in SITUATIONS:
        raise ValueError(f"unknown situation {situation!r}; known: {sorted(SITUATIONS)}")
    order = [i for _, rungs in LADDERS.items() for i, _ in rungs]
    out = []
    for e in sorted(ENTRIES, key=lambda e: order.index(e.layer_id) if e.layer_id in order else 99):
        if not e.in_box or not e.needs <= have_set:
            continue
        verdict, why = e.works[situation]
        if verdict == NO:
            continue
        out.append((e, verdict, why))
    return out
