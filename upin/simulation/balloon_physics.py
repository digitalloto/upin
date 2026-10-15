"""
Balloon physics for deciding, not for claiming. Every constant is a
labelled assumption at sea level, 15 C; replace with measured values.

  helium_net_lift_kg_per_m3   buoyancy of helium in air minus the gas itself
  sphere_drag_n               drag on a sphere of diameter d at speed v
  balloon_for_payload         the diameter that lifts a payload and still
                              climbs at a chosen rate (drag balances the
                              spare lift at that speed)
  gas_cylinder_mass_kg        what it weighs to carry that gas compressed
  aerostat_blowdown           how far a tethered balloon leans in wind

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from typing import Dict, Tuple

RHO_AIR = 1.225          # kg/m^3, sea level 15 C
RHO_HELIUM = 0.1786      # kg/m^3 at 1 atm, 0 C (slightly less lift when warm)
G = 9.80665
CD_SPHERE = 0.47         # **Assumption.** Subcritical; at high Reynolds number it can fall to ~0.2
ENVELOPE_KG_PER_M2 = 0.06
"""**Assumption.** Latex/mylar envelope mass per square metre of surface."""
CYLINDER_KG_PER_LITRE = 1.2
"""**Assumption.** A small steel 200-bar cylinder weighs about this per litre
of water capacity, valve included. Composite is lighter, dearer."""
CYLINDER_BAR = 200.0


def helium_net_lift_kg_per_m3() -> float:
    return RHO_AIR - RHO_HELIUM


def sphere_drag_n(diameter_m: float, speed_ms: float, cd: float = CD_SPHERE) -> float:
    area = math.pi * diameter_m ** 2 / 4.0
    return 0.5 * RHO_AIR * speed_ms ** 2 * cd * area


def envelope_mass_kg(diameter_m: float) -> float:
    return ENVELOPE_KG_PER_M2 * math.pi * diameter_m ** 2


def balloon_for_payload(payload_kg: float, ascent_ms: float = 5.0) -> Dict[str, float]:
    """Smallest sphere whose lift carries the payload and its own envelope
    with enough spare lift that drag at ascent_ms balances it."""
    lo, hi = 0.1, 10.0
    for _ in range(60):
        d = 0.5 * (lo + hi)
        volume = math.pi * d ** 3 / 6.0
        lift_n = helium_net_lift_kg_per_m3() * volume * G
        need_n = (payload_kg + envelope_mass_kg(d)) * G + sphere_drag_n(d, ascent_ms)
        if lift_n >= need_n:
            hi = d
        else:
            lo = d
    d = hi
    volume = math.pi * d ** 3 / 6.0
    return {"diameter_m": d, "volume_m3": volume, "envelope_kg": envelope_mass_kg(d),
            "helium_kg": RHO_HELIUM * volume,
            "gross_lift_kg": helium_net_lift_kg_per_m3() * volume}


def gas_cylinder_mass_kg(volume_m3_at_1atm: float) -> Dict[str, float]:
    litres_water = volume_m3_at_1atm * 1000.0 / CYLINDER_BAR
    return {"cylinder_litres": litres_water,
            "cylinder_kg": litres_water * CYLINDER_KG_PER_LITRE,
            "gas_kg": RHO_HELIUM * volume_m3_at_1atm}


def hover_thrust_n(mass_kg: float) -> float:
    return mass_kg * G


def aerostat_blowdown(tether_m: float, diameter_m: float, net_lift_n: float,
                      wind_ms: float) -> Tuple[float, float, float]:
    """(horizontal offset m, altitude m, tether angle deg) of a tethered
    sphere in steady wind: tan(angle) = drag / net lift. A simple model: a
    straight tether, no tether drag, steady wind."""
    drag = sphere_drag_n(diameter_m, wind_ms)
    angle = math.atan2(drag, max(net_lift_n, 1e-6))
    return tether_m * math.sin(angle), tether_m * math.cos(angle), math.degrees(angle)


def blowdown_sigma_m(tether_m: float, diameter_m: float, net_lift_n: float,
                     wind_ms: float, wind_sigma_ms: float) -> float:
    """How far the offset moves for a one-sigma change in wind."""
    off = lambda v: aerostat_blowdown(tether_m, diameter_m, net_lift_n, v)[0]  # noqa: E731
    return abs(off(wind_ms + wind_sigma_ms) - off(max(wind_ms - wind_sigma_ms, 0.0))) / 2.0
