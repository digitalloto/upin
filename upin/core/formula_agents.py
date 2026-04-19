"""
Formula Agents — UPIN

Ported from UPIN phone-demo v5. Each formula (Kalman, SMA, step-counter,
financial indicator, etc.) runs with N agents, each applying a different
set of sensor parameter tweaks (accel scale, gyro scale, compass offset,
speed multiplier, heading offset). Agents are scored against GPS truth;
worst agents die, best agents reproduce with mutations.

This gives per-formula sensor calibration — every formula gets optimal
parameters for THIS specific device's sensor errors.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import copy
import math
import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple


@dataclass
class AgentParams:
    """Sensor parameter tweaks one agent applies before running its formula."""
    accel_scale: float = 1.0      # 0.5 - 1.5
    accel_bias_x: float = 0.0     # -0.1 - 0.1
    accel_bias_y: float = 0.0     # -0.1 - 0.1
    gyro_scale: float = 1.0       # 0.5 - 1.5
    compass_offset_deg: float = 0.0  # -5 - 5
    speed_multiplier: float = 1.0    # 0.7 - 1.3
    heading_offset_deg: float = 0.0  # -4 - 4

    def apply_to_sensors(self, sensors: Dict) -> Dict:
        """Return a NEW sensor dict with this agent's tweaks applied."""
        out = dict(sensors)
        if "accel_x" in out:
            out["accel_x"] = out["accel_x"] * self.accel_scale + self.accel_bias_x
        if "accel_y" in out:
            out["accel_y"] = out["accel_y"] * self.accel_scale + self.accel_bias_y
        if "gyro_z" in out:
            out["gyro_z"] = out["gyro_z"] * self.gyro_scale
        if "heading_deg" in out:
            out["heading_deg"] = ((out["heading_deg"] + self.compass_offset_deg)
                                   % 360.0)
        if "speed_ms" in out:
            out["speed_ms"] = out["speed_ms"] * self.speed_multiplier
        return out

    def mutate(self, sigma: float = 0.05) -> "AgentParams":
        """Return a mutated copy."""
        return AgentParams(
            accel_scale=_clamp(self.accel_scale + random.gauss(0, sigma), 0.5, 1.5),
            accel_bias_x=_clamp(self.accel_bias_x + random.gauss(0, 0.02), -0.1, 0.1),
            accel_bias_y=_clamp(self.accel_bias_y + random.gauss(0, 0.02), -0.1, 0.1),
            gyro_scale=_clamp(self.gyro_scale + random.gauss(0, sigma), 0.5, 1.5),
            compass_offset_deg=_clamp(
                self.compass_offset_deg + random.gauss(0, 1.0), -5, 5),
            speed_multiplier=_clamp(
                self.speed_multiplier + random.gauss(0, 0.03), 0.7, 1.3),
            heading_offset_deg=_clamp(
                self.heading_offset_deg + random.gauss(0, 0.8), -4, 4),
        )

    @staticmethod
    def random() -> "AgentParams":
        return AgentParams(
            accel_scale=random.uniform(0.7, 1.3),
            accel_bias_x=random.uniform(-0.05, 0.05),
            accel_bias_y=random.uniform(-0.05, 0.05),
            gyro_scale=random.uniform(0.7, 1.3),
            compass_offset_deg=random.uniform(-3, 3),
            speed_multiplier=random.uniform(0.85, 1.15),
            heading_offset_deg=random.uniform(-2, 2),
        )


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


@dataclass
class Agent:
    """A single agent running a given formula with specific params."""
    agent_id: int
    params: AgentParams
    total_error: float = 0.0
    sample_count: int = 0
    best_error: float = float('inf')
    generation: int = 0

    @property
    def avg_error(self) -> float:
        if self.sample_count == 0:
            return float('inf')
        return self.total_error / self.sample_count

    def score(self, error_m: float):
        self.total_error += error_m
        self.sample_count += 1
        if error_m < self.best_error:
            self.best_error = error_m

    def reset_score(self):
        self.total_error = 0.0
        self.sample_count = 0


class FormulaAgentPool:
    """Per-formula pool of agents evolving sensor parameters.

    Each formula gets N agents (default 10). Every score round, the
    worst agents die and the best reproduce with mutations.
    """

    def __init__(self, formula_name: str, agent_count: int = 10,
                 evolution_interval: int = 10,
                 kill_fraction: float = 0.2):
        self.formula_name = formula_name
        self.agent_count = agent_count
        self.evolution_interval = evolution_interval
        self.kill_fraction = kill_fraction
        self.agents: List[Agent] = [
            Agent(agent_id=i, params=AgentParams.random())
            for i in range(agent_count)
        ]
        self._round_count = 0
        self._generation = 0

    def score_all(self, ground_truth_lat: float, ground_truth_lon: float,
                  predictions: List[Tuple[float, float]]):
        """Given each agent's predicted (lat, lon), score them against truth."""
        for agent, pred in zip(self.agents, predictions):
            if pred is None:
                continue
            err = _haversine_m(ground_truth_lat, ground_truth_lon,
                               pred[0], pred[1])
            agent.score(err)
        self._round_count += 1
        if self._round_count >= self.evolution_interval:
            self._round_count = 0
            self.evolve()

    def evolve(self):
        """Kill worst, clone best with mutations."""
        scored = sorted(self.agents, key=lambda a: a.avg_error)
        survive_n = max(1, int(len(scored) * (1 - self.kill_fraction)))
        survivors = scored[:survive_n]
        new_agents = list(survivors)
        next_id = max(a.agent_id for a in self.agents) + 1
        while len(new_agents) < self.agent_count:
            parent = random.choice(survivors[:max(2, len(survivors) // 3)])
            child = Agent(agent_id=next_id,
                          params=parent.params.mutate(),
                          generation=self._generation + 1)
            new_agents.append(child)
            next_id += 1
        self.agents = new_agents
        self._generation += 1

    def best_agent(self) -> Agent:
        return min(self.agents, key=lambda a: a.avg_error)

    def get_stats(self) -> Dict:
        best = self.best_agent()
        return {
            "formula": self.formula_name,
            "generation": self._generation,
            "agent_count": len(self.agents),
            "best_avg_error_m": (best.avg_error if best.sample_count else None),
            "best_error_m": (best.best_error if best.best_error != float('inf')
                             else None),
            "best_params": {
                "accel_scale": best.params.accel_scale,
                "gyro_scale": best.params.gyro_scale,
                "compass_offset_deg": best.params.compass_offset_deg,
                "speed_multiplier": best.params.speed_multiplier,
                "heading_offset_deg": best.params.heading_offset_deg,
            },
        }


class FormulaAgentManager:
    """Manages a pool per formula — the full multi-formula agent system."""

    def __init__(self, agents_per_formula: int = 10):
        self._pools: Dict[str, FormulaAgentPool] = {}
        self._agents_per_formula = agents_per_formula

    def register_formula(self, formula_name: str):
        if formula_name not in self._pools:
            self._pools[formula_name] = FormulaAgentPool(
                formula_name=formula_name,
                agent_count=self._agents_per_formula,
            )

    def get_pool(self, formula_name: str) -> Optional[FormulaAgentPool]:
        return self._pools.get(formula_name)

    def get_summary(self) -> Dict:
        stats = [pool.get_stats() for pool in self._pools.values()]
        total_agents = sum(p.agent_count for p in self._pools.values())
        improved = sum(1 for s in stats
                       if s["best_avg_error_m"] is not None
                       and s["best_avg_error_m"] < 50)
        return {
            "formulas_tracked": len(self._pools),
            "agents_per_formula": self._agents_per_formula,
            "total_agents": total_agents,
            "formulas_improving": improved,
            "per_formula": stats,
        }


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
