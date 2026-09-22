"""
The harness: the one place that decides what, if anything, feeds a layer.

Before this existed, every layer carried its own simulator. 122 of them
invented a different reading each time they were read, and the only way to
stop one was to switch it off entirely, at which point it raised. Simulation
was not a mode; it was a property of the code, on by default, impossible to
audit because it was everywhere.

The harness moves that decision to a single object with three settings:

    SIMULATION   layers are fed observations derived from a SimulationWorld
    REAL         layers are fed by the platform scanners, if any prove real
    OFF          nothing is fed to anything

A layer cannot tell which it is in. It is handed observations through the
input methods its SensorRequirement declares, or it is handed nothing, and in
the second case it says so. That is the entire contract, and it is what makes
the code path exercised in simulation the same one that flies.

THE LEGACY BRIDGE

129 layers have not been converted yet and still simulate internally. The
harness drives them the old way in SIMULATION mode -- `set_simulated_position`
and `set_world`, exactly as `create_all_layers` always did -- so nothing that
works today stops working. In REAL mode it turns their simulation off and
lets them raise, which the fusion engine already catches and drops.

`coverage()` counts the three populations, so the number of layers still on
the bridge is visible at all times. It starts at 129 and the job is finished
when it reaches zero.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence

import numpy as np

from upin.simulation.adapters import ADAPTERS, Adapter, adapter_for
from upin.simulation.feeds import AgentFeed, Feed, NullFeed, Observation, WorldFeed

DEG_M = 111_320.0


class Mode(Enum):
    SIMULATION = "simulation"
    REAL = "real"
    OFF = "off"


@dataclass
class Coverage:
    """Who is being fed, and how honestly."""
    mode: str
    native: List[str] = field(default_factory=list)
    """Layers driven through their own input methods by an adapter. The
    honest population."""
    legacy: List[str] = field(default_factory=list)
    """Layers still simulating internally, driven the old way. The work
    remaining."""
    unfed: List[str] = field(default_factory=list)
    """Layers nothing is feeding. In REAL mode with no hardware this is
    almost everything, and that is correct."""

    @property
    def total(self) -> int:
        return len(self.native) + len(self.legacy) + len(self.unfed)

    def summary(self) -> str:
        return (f"{self.mode}: {len(self.native)} fed natively, "
                f"{len(self.legacy)} on the legacy bridge, "
                f"{len(self.unfed)} unfed, {self.total} total")

    def as_dict(self) -> Dict:
        return {"mode": self.mode, "native": list(self.native),
                "legacy": list(self.legacy), "unfed": list(self.unfed),
                "native_count": len(self.native),
                "legacy_count": len(self.legacy),
                "unfed_count": len(self.unfed), "total": self.total}


class NavigationHarness:
    """Drives a set of layers from a chosen source.

    `seed` makes a simulation run reproducible. The randomness lives here, in
    the harness, which is the only place the contract permits it: sensor noise
    injected at a layer's input by the test rig, never inside the layer.
    """

    def __init__(self, layers: Sequence, mode: Mode = Mode.SIMULATION,
                 world=None, agent_feed: Optional[AgentFeed] = None,
                 seed: int = 0, legacy_bridge: bool = True):
        self._layers = list(layers)
        self._by_id = {getattr(L, "layer_id", str(i)): L
                       for i, L in enumerate(self._layers)}
        self._world = world
        self._agent_feed = agent_feed
        self._rng = np.random.default_rng(seed)
        self._seed = seed
        # SimulationWorld draws its sensor noise from module-level np.random
        # rather than an injected generator, so seeding the harness alone
        # leaves the world free-running and a "reproducible" run is not.
        # Seeding globally here is blunt, but it is the only thing that
        # actually makes a seeded run reproducible until the world takes a
        # generator of its own.
        np.random.seed(seed)
        self._legacy_bridge = legacy_bridge
        self._mode = None
        self._feed: Feed = NullFeed()
        self._ticks = 0
        self._provisioned: List[str] = []
        self.set_mode(mode)

    # -- mode -------------------------------------------------------

    @property
    def mode(self) -> Mode:
        return self._mode

    @property
    def feed(self) -> Feed:
        return self._feed

    def set_mode(self, mode: Mode):
        """Switch source. Reconfigures every layer for the new mode."""
        self._mode = mode
        if mode is Mode.SIMULATION:
            self._feed = WorldFeed(self._world) if self._world is not None \
                else NullFeed()
        elif mode is Mode.REAL:
            if self._agent_feed is None:
                self._agent_feed = AgentFeed()
            self._feed = self._agent_feed
        else:
            self._feed = NullFeed()
        self._configure_layers()
        self.provision()

    def _configure_layers(self):
        """Put each layer into the state this mode requires.

        In SIMULATION the unconverted layers keep their internal simulator, so
        the demos keep working. In REAL and OFF it is switched off, and a layer
        that then raises is a layer with no honest answer -- which the fusion
        engine handles by dropping it.
        """
        simulating = (self._mode is Mode.SIMULATION and self._legacy_bridge)
        for layer in self._layers:
            if adapter_for(getattr(layer, "layer_id", "")) is not None:
                # Converted layers never simulate internally. There is nothing
                # to switch.
                continue
            setter = getattr(layer, "set_simulation_mode", None)
            if callable(setter):
                setter(simulating)
            if simulating and self._world is not None:
                world_setter = getattr(layer, "set_world", None)
                if callable(world_setter):
                    world_setter(self._world)
                pos_setter = getattr(layer, "set_simulated_position", None)
                if callable(pos_setter):
                    pos_setter(self._world.true_lat, self._world.true_lon,
                               self._world.true_alt)

    def provision(self) -> List[str]:
        """Give converted layers the reference data a deployment would have.

        A landmark layer needs a surveyed chart; a dead-reckoning layer needs
        an airframe fitted to real flight logs. Neither is a sensor reading,
        and neither should be invented by the layer itself -- so in simulation
        the harness supplies them, once, and records which layers it had to
        set up. In REAL mode nothing is provisioned, because a real deployment
        loads its own chart and flies its own calibration.
        """
        if self._mode is not Mode.SIMULATION or not self._feed.available():
            return []
        done = []
        for layer_id, adapter in ADAPTERS.items():
            layer = self._by_id.get(layer_id)
            if layer is None or adapter.provision is None:
                continue
            try:
                if adapter.provision(layer, self._feed, self._rng):
                    done.append(layer_id)
            except Exception:
                continue
        # Record what was provisioned, but never erase an earlier record: a
        # second call legitimately provisions nothing, and reporting that as
        # "nothing was ever set up" would be wrong.
        for layer_id in done:
            if layer_id not in self._provisioned:
                self._provisioned.append(layer_id)
        return done

    @property
    def provisioned(self) -> List[str]:
        return list(self._provisioned)

    # -- driving ----------------------------------------------------

    def tick(self, dt: float = 0.1) -> Coverage:
        """Advance the world if there is one, then feed every layer that can be."""
        if self._mode is Mode.SIMULATION and self._world is not None:
            self._world.step(dt)
            self._configure_legacy_positions()

        cov = Coverage(mode=self._mode.value)
        for layer in self._layers:
            layer_id = getattr(layer, "layer_id", "")
            adapter = adapter_for(layer_id)
            if adapter is not None:
                fed = False
                if self._feed.available():
                    try:
                        fed = bool(adapter.drive(layer, self._feed, dt, self._rng))
                    except Exception:
                        fed = False
                (cov.native if fed else cov.unfed).append(layer_id)
            elif self._mode is Mode.SIMULATION and self._legacy_bridge:
                cov.legacy.append(layer_id)
            else:
                cov.unfed.append(layer_id)

        self._ticks += 1
        return cov

    def _configure_legacy_positions(self):
        """Keep the bridged layers pointed at the world's current position."""
        for layer in self._layers:
            if adapter_for(getattr(layer, "layer_id", "")) is not None:
                continue
            setter = getattr(layer, "set_simulated_position", None)
            if callable(setter):
                setter(self._world.true_lat, self._world.true_lon,
                       self._world.true_alt)

    def coverage(self) -> Coverage:
        """Who would be fed, without advancing anything."""
        cov = Coverage(mode=self._mode.value)
        for layer in self._layers:
            layer_id = getattr(layer, "layer_id", "")
            if adapter_for(layer_id) is not None:
                (cov.native if self._feed.available() else cov.unfed).append(layer_id)
            elif self._mode is Mode.SIMULATION and self._legacy_bridge:
                cov.legacy.append(layer_id)
            else:
                cov.unfed.append(layer_id)
        return cov

    # -- keeping the adapters honest --------------------------------

    def audit_adapters(self, ticks: int = 30, dt: float = 0.1,
                       flat_tolerance_m: float = 0.05) -> Dict[str, str]:
        """Catch an adapter that hands a layer the answer instead of an observation.

        An adapter may read true state to derive a geometry -- the bearing from
        here to a charted tower. It may not pass true position through as a
        measurement. That is the original bug moved one file across, and it
        would be invisible in an ordinary test, because the layer would simply
        look superb.

        Absolute error is the wrong test. Honest dead reckoning from a fresh
        anchor tracks truth to centimetres for the first second, and a strict
        threshold would condemn it. What separates measurement from
        hand-over is not how small the error is but whether it *grows*: a
        layer integrating real observations accumulates error, while a layer
        handed ground truth stays pinned to it no matter how far the platform
        flies.

        So this runs a short experiment -- it advances the simulation by
        `ticks` -- and flags any layer whose error stayed flat while the
        platform travelled a meaningful distance. Reported, not raised,
        because a human should look at what it finds.
        """
        findings: Dict[str, str] = {}
        if self._mode is not Mode.SIMULATION or self._world is None:
            return findings

        start = (self._world.true_lat, self._world.true_lon)
        errors: Dict[str, List[float]] = {lid: [] for lid in ADAPTERS}

        for _ in range(max(2, ticks)):
            self.tick(dt)
            for layer_id in ADAPTERS:
                layer = self._by_id.get(layer_id)
                if layer is None:
                    continue
                try:
                    reading = layer.read()
                except Exception:
                    continue
                if (reading is None or reading.position is None
                        or not reading.is_valid):
                    continue
                errors[layer_id].append(self._error_from_truth(reading.position))

        travelled = self._distance_m(start, (self._world.true_lat,
                                             self._world.true_lon))
        if travelled < 10.0:
            return findings          # platform barely moved; nothing to learn

        for layer_id, series in errors.items():
            if len(series) < 2:
                continue
            spread = max(series) - min(series)
            if max(series) < flat_tolerance_m and spread < flat_tolerance_m:
                findings[layer_id] = (
                    f"error stayed within {max(series):.3f} m of ground truth "
                    f"across {len(series)} reads while the platform flew "
                    f"{travelled:.0f} m. An error that never grows is not a "
                    f"measurement — the adapter is likely handing this layer "
                    f"the answer")
        return findings

    def _error_from_truth(self, position) -> float:
        dn = (position.latitude - self._world.true_lat) * DEG_M
        de = ((position.longitude - self._world.true_lon) * DEG_M
              * math.cos(math.radians(self._world.true_lat)))
        return math.hypot(dn, de)

    @staticmethod
    def _distance_m(a, b) -> float:
        dn = (b[0] - a[0]) * DEG_M
        de = (b[1] - a[1]) * DEG_M * math.cos(math.radians(a[0]))
        return math.hypot(dn, de)

    # -- convenience ------------------------------------------------

    @property
    def layers(self) -> List:
        return list(self._layers)

    def layer(self, layer_id: str):
        return self._by_id.get(layer_id)

    @property
    def ticks(self) -> int:
        return self._ticks

    def status(self) -> Dict:
        """Everything a UI needs to show a real/simulation toggle honestly."""
        cov = self.coverage()
        out = cov.as_dict()
        out["feed"] = self._feed.name
        out["feed_available"] = self._feed.available()
        out["is_simulated"] = self._feed.is_simulated
        out["ticks"] = self._ticks
        out["provisioned"] = list(self._provisioned)
        if isinstance(self._feed, AgentFeed):
            out["rejected_agents"] = self._feed.rejections()
        return out
