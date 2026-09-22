"""
The two sources of sensor data, behind one interface.

A navigation layer should not know whether the bearing it was handed came off
a camera or out of a simulator. That is the whole point of taking simulation
out of the layers: once a layer can tell, it can behave differently, and the
moment it behaves differently the thing you tested is not the thing that
flies.

So both sources answer the same questions:

    available()            is there anything behind this feed at all?
    observation(kind)      the current value of one physical quantity, or
                           None when this feed cannot produce it

WorldFeed answers from `SimulationWorld`, which already models 26 observable
quantities properly -- pseudoranges, magnetic field, cell signals, star
positions, acoustic arrivals. AgentFeed answers from the real platform
scanners in `upin/agents/`, each gated on its own `is_available()`, so a
machine with no WiFi radio simply has no WiFi observations rather than fake
ones.

WHAT A FEED DOES NOT DO

A feed never touches a layer. It supplies values; an adapter decides what to
do with them. Keeping those apart means a layer's input path is exercised
identically in simulation and in the field, and that the noise a simulation
adds lands at the input, where the no-fabrication contract says sensor noise
belongs.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


class Observation:
    """Names for the physical quantities a feed can supply.

    Strings rather than an enum because adapters, feeds and the readiness
    report all pass them around, and a plain name reads better in a log than
    `Observation.MAGNETIC_FIELD`.
    """
    TRUE_STATE = "true_state"            # simulation only: ground truth
    PSEUDORANGES = "pseudoranges"
    MAGNETIC_FIELD = "magnetic_field"
    GRAVITY = "gravity"
    WIFI_RSSI = "wifi_rssi"
    CELL_SIGNALS = "cell_signals"
    RF_EMITTERS = "rf_emitters"
    ACOUSTIC_ARRIVALS = "acoustic_arrivals"
    STAR_POSITIONS = "star_positions"
    TERRAIN_FEATURES = "terrain_features"
    TERRAIN_ELEVATION = "terrain_elevation"
    BAROMETRIC_PRESSURE = "barometric_pressure"
    PULSAR_TIMING = "pulsar_timing"
    STEREO_CAMERA = "stereo_camera"
    OCEAN_CURRENT = "ocean_current"
    TIDAL_SIGNATURE = "tidal_signature"
    BATHYMETRY = "bathymetry"
    CHEMICAL_GRADIENTS = "chemical_gradients"
    IONOSPHERIC_DENSITY = "ionospheric_density"
    SCHUMANN_RESONANCE = "schumann_resonance"
    MUON_FLUX = "muon_flux"
    # Real-side only, for now: a position an agent has already solved.
    AGENT_POSITION = "agent_position"
    IMU = "imu"


@dataclass
class TrueState:
    """Where the platform actually is, in simulation.

    Only a `WorldFeed` can answer this, and only adapters that need to derive
    a geometry -- a bearing to a landmark, a range to a beacon -- should ask.
    An adapter that hands this straight to a layer has reinvented the bug this
    whole exercise exists to remove, so `NavigationHarness` refuses to run an
    adapter that does that.
    """
    latitude: float
    longitude: float
    altitude: float
    heading_deg: float = 0.0
    velocity_north: float = 0.0
    velocity_east: float = 0.0
    timestamp: float = field(default_factory=time.time)


class Feed:
    """One source of sensor data."""

    name = "feed"
    is_simulated = False

    def available(self) -> bool:
        raise NotImplementedError

    def observation(self, kind: str) -> Optional[Any]:
        raise NotImplementedError

    def kinds(self) -> List[str]:
        """Which observations this feed can currently produce."""
        raise NotImplementedError


class WorldFeed(Feed):
    """Observations derived from a `SimulationWorld`.

    Every entry in the map below is a method the world already implements. The
    simulator was always capable of producing proper observations; the layers
    just read `world.true_lat` instead and added noise to it, 203 times across
    the codebase against 51 genuine physics calls. This feed is the other
    direction: observations get pushed out of the world, and no layer needs to
    know where the platform really is.
    """

    name = "simulation"
    is_simulated = True

    def __init__(self, world):
        self._world = world
        self._map: Dict[str, Callable[[], Any]] = {
            # get_pseudoranges takes a constellation; a receiver sees all the
            # ones it is built for, so the observation carries each separately
            # rather than silently picking one.
            Observation.PSEUDORANGES: lambda: {
                c: world.get_pseudoranges(c)
                for c in ("GPS", "NAVIC", "LEO")
            },
            Observation.MAGNETIC_FIELD: lambda: world.get_magnetic_field(),
            Observation.GRAVITY: lambda: world.get_gravity(),
            Observation.WIFI_RSSI: lambda: world.get_wifi_rssi(),
            Observation.CELL_SIGNALS: lambda: world.get_cell_tower_signals(),
            Observation.RF_EMITTERS: lambda: world.get_rf_emitter_signals(),
            Observation.ACOUSTIC_ARRIVALS: lambda: world.get_acoustic_arrivals(),
            Observation.STAR_POSITIONS: lambda: world.get_star_positions(),
            Observation.TERRAIN_FEATURES: lambda: world.get_terrain_features(),
            Observation.TERRAIN_ELEVATION: lambda: world.get_terrain_elevation(),
            Observation.BAROMETRIC_PRESSURE: lambda: world.get_barometric_pressure(),
            Observation.PULSAR_TIMING: lambda: world.get_pulsar_timing(),
            Observation.STEREO_CAMERA: lambda: world.get_stereo_camera_data(),
            Observation.OCEAN_CURRENT: lambda: world.get_ocean_current(),
            Observation.TIDAL_SIGNATURE: lambda: world.get_tidal_signature(),
            Observation.BATHYMETRY: lambda: world.get_bathymetry_depth(),
            Observation.CHEMICAL_GRADIENTS: lambda: world.get_chemical_gradients(),
            Observation.IONOSPHERIC_DENSITY: lambda: world.get_ionospheric_density(),
            Observation.SCHUMANN_RESONANCE: lambda: world.get_schumann_resonance(),
            Observation.MUON_FLUX: lambda: world.get_muon_flux(),
            Observation.TRUE_STATE: self._true_state,
        }

    @property
    def world(self):
        return self._world

    def _true_state(self) -> TrueState:
        w = self._world
        return TrueState(
            latitude=w.true_lat, longitude=w.true_lon, altitude=w.true_alt,
            heading_deg=float(getattr(w, "true_heading", 0.0) or 0.0),
            velocity_north=float(getattr(w, "true_vn", 0.0) or 0.0),
            velocity_east=float(getattr(w, "true_ve", 0.0) or 0.0),
        )

    def available(self) -> bool:
        return self._world is not None

    def kinds(self) -> List[str]:
        return sorted(self._map)

    def observation(self, kind: str) -> Optional[Any]:
        fn = self._map.get(kind)
        if fn is None or self._world is None:
            return None
        try:
            return fn()
        except Exception:
            # A world method that fails is a missing observation, not a crash
            # in the middle of a flight cycle.
            return None


# Provenance markers an agent may stamp on a reading. The filter is
# default-deny: a reading is passed on only if it positively identifies itself
# as coming from a real measurement. Everything else is dropped, including
# readings that carry no marker at all.
REAL_SOURCES = frozenset({
    "mls",          # Mozilla Location Service, from a real WiFi scan
    "opencellid",   # OpenCellID, from real tower identifiers
    "cached",       # a real fix, recently
    "device",
    "hardware",
    "gnss_receiver",
})

SIMULATED_MARKERS = ("sim", "simulated", "fake", "mock", "synthetic")


def _looks_simulated(value: Any) -> bool:
    """Does this provenance value admit to being invented?"""
    text = str(value).lower()
    return any(m in text for m in SIMULATED_MARKERS)


class AgentFeed(Feed):
    """Observations from the platform scanners in `upin/agents/`.

    WHY THIS FEED DISTRUSTS ITS OWN AGENTS

    The agents named "real" are not reliably real. `RealWiFiPositioningAgent`
    scans properly when a radio is present, and otherwise falls back to
    `_simulate_networks()` and `_simulate_position()` -- while still returning
    `status: ACTIVE`. Its `is_available()` reads, verbatim:

        return True  # Always available (falls back to simulation)

    `RealCellularPositioningAgent` does the same. `RealPhoneSensorAgent`
    reports `sensors_available: ['gps_sim', 'accel_sim', ...]`. `GNSSAgent`
    returns a hardcoded 13.0827, 80.2707 with a 5 m accuracy claim and no
    provenance at all.

    Trusting `is_available()` would mean laundering invented data through the
    path labelled "real", which is worse than inventing it openly: at least a
    simulated layer is understood to be simulated. So this feed checks the
    provenance stamped on each reading and drops anything that does not
    positively identify itself as measured. Default deny, for the same reason
    the landmark layer whitelists map sources rather than blacklisting the bad
    ones.

    On a bare server this feed will therefore report nothing available. That is
    the correct output, and `rejections()` says exactly why for each agent.
    """

    name = "real"
    is_simulated = False

    def __init__(self, agents: Optional[List] = None):
        self._agents = list(agents) if agents is not None else self._discover()
        self._available_cache: Dict[str, bool] = {}

    @staticmethod
    def _discover() -> List:
        """Construct whichever real agents import and build on this host."""
        found = []
        specs = [
            ("upin.agents.real_wifi_agent", "RealWiFiPositioningAgent"),
            ("upin.agents.real_cellular_agent", "RealCellularPositioningAgent"),
            ("upin.agents.gnss_agent", "GNSSAgent"),
            ("upin.agents.real_phone_sensor_agent", "RealPhoneSensorAgent"),
        ]
        for module_name, cls_name in specs:
            try:
                mod = __import__(module_name, fromlist=[cls_name])
                found.append(getattr(mod, cls_name)())
            except Exception:
                # An agent that will not import on this platform is simply not
                # one of this host's senses.
                continue
        return found

    @property
    def agents(self) -> List:
        return list(self._agents)

    def available(self) -> bool:
        """True only if some agent can show a genuinely measured reading."""
        return bool(self.readings())

    def _is_available(self, agent) -> bool:
        key = getattr(agent, "agent_id", repr(agent))
        if key not in self._available_cache:
            try:
                self._available_cache[key] = bool(agent.is_available())
            except Exception:
                self._available_cache[key] = False
        return self._available_cache[key]

    @staticmethod
    def provenance_of(reading: Dict) -> str:
        """Why this reading is, or is not, a real measurement.

        Returns one of the REAL_SOURCES, or a string beginning "rejected:".
        """
        if not isinstance(reading, dict):
            return "rejected: not a reading"
        if reading.get("status") != "ACTIVE":
            return f"rejected: status {reading.get('status')!r}"

        source = reading.get("source")
        if source is not None:
            if _looks_simulated(source):
                return f"rejected: source {source!r} is simulated"
            if str(source).lower() in REAL_SOURCES:
                return str(source).lower()
            return f"rejected: source {source!r} is not a known real source"

        # No source field. Some agents describe their senses instead.
        sensors = reading.get("sensors_available")
        if sensors is not None:
            if any(_looks_simulated(s) for s in sensors):
                return f"rejected: sensors {list(sensors)} are simulated"
            return "device"

        return ("rejected: no provenance — the reading does not say where it "
                "came from")

    def rejections(self) -> Dict[str, str]:
        """Per agent, why its reading was not accepted. Empty when all passed."""
        out: Dict[str, str] = {}
        for agent in self._agents:
            agent_id = getattr(agent, "agent_id", repr(agent))
            if not self._is_available(agent):
                out[agent_id] = "rejected: is_available() is False"
                continue
            try:
                r = agent.get_reading()
            except Exception as exc:
                out[agent_id] = f"rejected: get_reading() raised {type(exc).__name__}"
                continue
            why = self.provenance_of(r)
            if why.startswith("rejected"):
                out[agent_id] = why
        return out

    def recheck(self):
        """Forget cached availability, e.g. after a radio is switched on."""
        self._available_cache.clear()

    def readings(self) -> List[Dict]:
        """Every agent reading that proves it came from a real measurement.

        An agent that cannot show provenance is skipped, however confidently
        it reports itself available.
        """
        out = []
        for agent in self._agents:
            if not self._is_available(agent):
                continue
            try:
                r = agent.get_reading()
            except Exception:
                continue
            why = self.provenance_of(r)
            if why.startswith("rejected"):
                continue
            r = dict(r)
            r["provenance"] = why
            out.append(r)
        return out

    def kinds(self) -> List[str]:
        kinds = []
        if self.readings():
            kinds.append(Observation.AGENT_POSITION)
        return kinds

    def observation(self, kind: str) -> Optional[Any]:
        if kind == Observation.AGENT_POSITION:
            readings = self.readings()
            return readings or None
        if kind == Observation.IMU:
            for r in self.readings():
                if r.get("accel") and r.get("gyro"):
                    return {"accel": r["accel"], "gyro": r["gyro"],
                            "mag": r.get("mag"),
                            "heading_deg": r.get("heading_deg")}
            return None
        if kind == Observation.BAROMETRIC_PRESSURE:
            for r in self.readings():
                if r.get("pressure_hpa"):
                    return float(r["pressure_hpa"])
            return None
        return None


class NullFeed(Feed):
    """Nothing is connected. Used by OFF mode, and honest about it."""

    name = "none"
    is_simulated = False

    def available(self) -> bool:
        return False

    def kinds(self) -> List[str]:
        return []

    def observation(self, kind: str) -> Optional[Any]:
        return None
