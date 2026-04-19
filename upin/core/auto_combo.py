"""
Auto-Combo Discovery — UPIN

Ported from UPIN phone-demo v5. Evolves combinations of 2-3 formulas
with learned weights. Each combo is a weighted sum of formulas; the
worst combos die and the best reproduce with mutations.

This finds non-obvious high-performing combos like
"0.7 × Step+Compass + 0.3 × MACD" that no human would pick.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class FormulaCombo:
    """A weighted combination of 2 or 3 formulas."""
    combo_id: int
    formula_names: List[str]
    weights: List[float]
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

    def predict(self, formula_outputs: Dict[str, Tuple[float, float]]
                ) -> Optional[Tuple[float, float]]:
        """Given each formula's (lat, lon), produce weighted combo prediction."""
        lat_sum = lon_sum = total_w = 0.0
        for name, w in zip(self.formula_names, self.weights):
            if name not in formula_outputs or formula_outputs[name] is None:
                continue
            lat, lon = formula_outputs[name]
            lat_sum += lat * w
            lon_sum += lon * w
            total_w += w
        if total_w <= 0:
            return None
        return (lat_sum / total_w, lon_sum / total_w)

    def mutate(self, available_formulas: List[str],
               combo_id: int) -> "FormulaCombo":
        """Return a mutated child combo."""
        # 30% chance to replace a formula with random one
        new_formulas = list(self.formula_names)
        if random.random() < 0.3 and len(available_formulas) > 2:
            idx = random.randrange(len(new_formulas))
            replacement = random.choice([f for f in available_formulas
                                          if f not in new_formulas])
            new_formulas[idx] = replacement
        # Jitter weights
        new_weights = [max(0.05, w + random.gauss(0, 0.1))
                       for w in self.weights]
        # Normalize
        s = sum(new_weights)
        if s > 0:
            new_weights = [w / s for w in new_weights]
        return FormulaCombo(
            combo_id=combo_id,
            formula_names=new_formulas,
            weights=new_weights,
            generation=self.generation + 1,
        )


class AutoComboDiscovery:
    """Evolve combinations of 2-3 formulas for best joint performance.

    Maintains a population of combos, scores them against GPS truth,
    kills the worst, and produces mutated offspring from the best.
    """

    def __init__(self, available_formulas: List[str],
                 population_size: int = 20,
                 evolution_interval: int = 20,
                 kill_fraction: float = 0.25):
        self.available_formulas = available_formulas
        self.population_size = population_size
        self.evolution_interval = evolution_interval
        self.kill_fraction = kill_fraction
        self._combos: List[FormulaCombo] = []
        self._next_id = 0
        self._round_count = 0
        self._generation = 0
        self._seed_population()

    def _seed_population(self):
        self._combos = []
        for _ in range(self.population_size):
            self._combos.append(self._make_random_combo())

    def _make_random_combo(self) -> FormulaCombo:
        if len(self.available_formulas) < 2:
            return FormulaCombo(
                combo_id=self._next_id,
                formula_names=list(self.available_formulas),
                weights=[1.0],
            )
        combo_size = random.choice([2, 2, 3])  # Bias toward 2
        combo_size = min(combo_size, len(self.available_formulas))
        formulas = random.sample(self.available_formulas, combo_size)
        weights = [random.random() for _ in range(combo_size)]
        s = sum(weights)
        weights = [w / s for w in weights]
        combo = FormulaCombo(
            combo_id=self._next_id,
            formula_names=formulas,
            weights=weights,
        )
        self._next_id += 1
        return combo

    def score_and_evolve(self, ground_truth: Tuple[float, float],
                         formula_outputs: Dict[str, Tuple[float, float]]):
        gt_lat, gt_lon = ground_truth
        for combo in self._combos:
            pred = combo.predict(formula_outputs)
            if pred is None:
                continue
            err = _haversine_m(gt_lat, gt_lon, pred[0], pred[1])
            combo.score(err)
        self._round_count += 1
        if self._round_count >= self.evolution_interval:
            self._round_count = 0
            self._evolve()

    def _evolve(self):
        scored = sorted(self._combos, key=lambda c: c.avg_error)
        survive_n = max(2, int(len(scored) * (1 - self.kill_fraction)))
        survivors = scored[:survive_n]
        new_pop = list(survivors)
        while len(new_pop) < self.population_size:
            parent = random.choice(survivors[:max(2, len(survivors) // 3)])
            child = parent.mutate(self.available_formulas, self._next_id)
            self._next_id += 1
            new_pop.append(child)
        self._combos = new_pop
        self._generation += 1

    def best_combo(self) -> FormulaCombo:
        return min(self._combos, key=lambda c: c.avg_error)

    def predict_best(self, formula_outputs: Dict[str, Tuple[float, float]]
                     ) -> Optional[Tuple[float, float]]:
        return self.best_combo().predict(formula_outputs)

    def get_stats(self) -> Dict:
        best = self.best_combo()
        return {
            "population_size": len(self._combos),
            "generation": self._generation,
            "best_combo_formulas": best.formula_names,
            "best_combo_weights": [round(w, 3) for w in best.weights],
            "best_avg_error_m": (best.avg_error if best.sample_count else None),
            "best_error_m": (best.best_error if best.best_error != float('inf')
                             else None),
        }


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
