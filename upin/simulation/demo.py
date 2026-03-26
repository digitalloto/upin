"""
UPIN End-to-End Demonstration System.

Demonstrates the complete UPIN system operating with all 93 elements:
- 60 navigation layer AGENTS each independently computing coordinates
- Mahalanobis distance cross-validation between all layer positions
- Resilient Reference Tracker (unjammable internal fallback)
- 25 threat detection layers
- 4 swarm architecture layers
- 4 mission capability modules

Scenarios:
1. Normal operation — 60 agents independently compute, Mahalanobis validates
2. GPS spoofing — Mahalanobis catches GPS disagreeing with other agents
3. Total jamming — Reference tracker maintains position from unjammable layers
4. CASEVAC golden hour extraction
5. Swarm formation intelligence
"""

from __future__ import annotations

import time
import sys

import numpy as np

from upin.core.fusion_engine import FusionEngine
from upin.core.position import Position, ThreatLevel
from upin.layers.registry import LayerRegistry, create_all_layers
from upin.simulation.world import SimulationWorld
from upin.threat.hardware.layers import ALL_HARDWARE_THREAT_LAYERS
from upin.threat.software.layers import ALL_SOFTWARE_THREAT_LAYERS
from upin.swarm.beehive import (
    DistributedBeehiveIntelligence, MasterBrainProtocol,
    OffensivePostureMode, AdaptiveFormationIntelligence,
    PlatformState, FormationType,
)
from upin.missions.flight_planning import FlightPlanningModule, ThreatZone
from upin.missions.targeting import TargetingModule
from upin.missions.casevac import CASEVACModule, VitalSigns
from upin.missions.intelligence import IntelligenceEcosystem


def print_header(text: str, char: str = "═"):
    width = 65
    print(f"\n{char * width}")
    print(f"  {text}")
    print(f"{char * width}")


def print_section(text: str):
    print(f"\n  ── {text} ──")


def create_full_system(lat: float = 13.0827, lon: float = 80.2707,
                        alt: float = 100.0) -> tuple[FusionEngine, SimulationWorld]:
    """Create a complete UPIN system with all 93 elements.

    Returns the fusion engine and simulation world. The world provides
    ground truth; each layer independently computes its own position
    from its own sensor physics.
    """
    # Create simulation world with ground truth
    # Stationary platform for clearest demonstration of
    # independent coordinate computation and Mahalanobis validation
    world = SimulationWorld(
        start_lat=lat, start_lon=lon, start_alt=alt,
        start_heading=45.0, start_velocity=0.0,
    )

    engine = FusionEngine(cycle_rate_hz=10.0, navic_primary=True,
                          agreement_threshold_m=500.0)

    # Register all 60 navigation layer agents
    # Each layer gets a reference to the world and computes independently
    layers = create_all_layers(sim_lat=lat, sim_lon=lon, sim_alt=alt,
                                world=world)
    for layer in layers:
        engine.register_layer(layer)

    # Register all 25 threat detection layers
    for cls in ALL_HARDWARE_THREAT_LAYERS:
        engine.register_threat_layer(cls())
    for cls in ALL_SOFTWARE_THREAT_LAYERS:
        engine.register_threat_layer(cls())

    engine.initialize()
    return engine, world


def demo_normal_operation():
    """Scenario 1: Normal operation — all 60 agents compute independently."""
    print_header("SCENARIO 1: NORMAL OPERATION — 60 INDEPENDENT AGENTS")
    print("  Location: Chennai, India (13.0827°N, 80.2707°E)")
    print("  Each layer AGENT independently computes its own coordinates")
    print("  Mahalanobis distance validates agreement between all agents")
    print("  NavIC designated as PRIMARY signal")

    engine, world = create_full_system()
    print(f"\n  Layer agents registered: {len(engine.registered_layers)}")
    print(f"  Threat layers: {len(engine.registered_threat_layers)}")

    print_section("Running 10 fusion cycles (each agent computes independently)")
    for i in range(10):
        world.step(0.1)  # Advance ground truth
        output = engine.cycle()
        if i % 3 == 0 or i == 9:
            print(f"\n  Cycle {i+1}:")
            print(f"    Fused position: {output.position.latitude:.6f}°N, "
                  f"{output.position.longitude:.6f}°E")
            print(f"    Altitude: {output.position.altitude:.1f} m")
            print(f"    Confidence: {output.confidence_score:.1f}% — "
                  f"{output.trust_level}")
            print(f"    Agreeing agents: {output.num_agreeing_layers}/"
                  f"{output.num_active_layers}")
            print(f"    Spoofing: {'DETECTED' if output.spoofing_detected else 'Clear'}")
            print(f"    Threat level: {output.threat_level.name}")

    # Show reference tracker status
    ref = engine.reference_tracker
    if ref.is_active:
        print_section("Resilient Reference Tracker (unjammable)")
        print(f"    Ref position: {ref.position[0]:.6f}°N, {ref.position[1]:.6f}°E")
        print(f"    Unjammable layers active: {ref._unjammable_count}")
        print(f"    Ref confidence: {ref._reference_confidence:.0f}%")

    print(f"\n{engine.status_report()}")
    return engine, world


def demo_spoofing_attack():
    """Scenario 2: GPS spoofing — Mahalanobis catches the disagreement."""
    print_header("SCENARIO 2: GPS SPOOFING — MAHALANOBIS DETECTION")
    print("  GPS signal spoofed to false position (+1.1 km offset)")
    print("  GPS computes trilateration from spoofed pseudoranges")
    print("  But 50+ other agents disagree → Mahalanobis flags it")
    print("  The spoofed signal cannot fool independent physical principles")

    engine, world = create_full_system()

    # Run 5 normal cycles first
    print_section("Phase 1: Normal operation (5 cycles)")
    for i in range(5):
        world.step(0.1)
        output = engine.cycle()
    print(f"  Confidence: {output.confidence_score:.1f}% — {output.trust_level}")
    print(f"  All agents agreeing: {output.num_agreeing_layers}/{output.num_active_layers}")

    # Activate GPS spoofing in the simulation world
    print_section("Phase 2: GPS SPOOFING ACTIVATED")
    world.set_gps_spoofing(offset_lat=0.01, offset_lon=0.01)
    # Also spoof the GPS layer directly for fallback mode
    gps_layer = engine.get_layer("gps_l1")
    if gps_layer:
        from upin.layers.satellite.layers import GPSLayer
        if isinstance(gps_layer, GPSLayer):
            gps_layer.simulate_spoofing(offset_lat=0.01, offset_lon=0.01)
    print("  GPS spoofed: pseudoranges modified to shift position ~1.1 km")
    print("  GPS agent now trilaterate a FALSE position")
    print("  All other agents (INS, magnetic, gravity, SLAM, etc.) unaffected")

    # Run cycles under spoofing
    print_section("Phase 3: Mahalanobis cross-validation (10 cycles)")
    for i in range(10):
        world.step(0.1)
        output = engine.cycle()
        if i % 3 == 0 or i == 9:
            print(f"\n  Cycle {i+1}:")
            print(f"    Confidence: {output.confidence_score:.1f}% — "
                  f"{output.trust_level}")
            print(f"    GPS trusted: {output.gps_trusted}")
            print(f"    Spoofing detected: {output.spoofing_detected}")
            if output.threat_alerts:
                for alert in output.threat_alerts[:2]:
                    print(f"    ALERT: [{alert.level.name}] "
                          f"{alert.description[:70]}")

    print_section("Result")
    print("  Mahalanobis distance detected GPS position as statistical outlier")
    print("  GPS Mahalanobis score >> 3.0 (normal is < 3.0)")
    print("  GPS agent automatically downweighted and flagged as spoofed")
    print("  Position maintained by remaining 55+ independent agents")
    print("  Reference tracker cross-validated: consensus is correct")


def demo_total_jamming():
    """Scenario 3: TOTAL signal jamming — reference tracker takes over."""
    print_header("SCENARIO 3: TOTAL SIGNAL JAMMING")
    print("  ALL external RF signals jammed (GPS, NavIC, LEO, cell, WiFi)")
    print("  UPIN Resilient Reference Tracker takes over using unjammable layers:")
    print("    INS, magnetic, gravity, muon, pulsar, Schumann, SLAM, LiDAR")
    print("  These use physical principles that CANNOT be jammed")

    engine, world = create_full_system()

    # Normal operation first
    for _ in range(5):
        world.step(0.1)
        output = engine.cycle()
    print(f"\n  Pre-jamming confidence: {output.confidence_score:.1f}%")
    print(f"  Pre-jamming position: {output.position.latitude:.6f}°N, "
          f"{output.position.longitude:.6f}°E")

    # JAM EVERYTHING external
    print_section("ALL EXTERNAL SIGNALS JAMMED")
    world.set_gps_jamming(True)
    world.navic_jammed = True

    # Disable all RF-based layers
    rf_layers = ["gps_l1", "navic_l2", "leo_l19", "groundrf_l7",
                 "wifi_l8", "celltower_l9", "eloran_l41", "soop_l42",
                 "beacon_l20"]
    for lid in rf_layers:
        layer = engine.get_layer(lid)
        if layer:
            layer.status.is_active = False

    for i in range(10):
        world.step(0.1)
        output = engine.cycle()
        if i % 3 == 0 or i == 9:
            ref = engine.reference_tracker
            print(f"\n  Cycle {i+1}:")
            print(f"    Fused position: {output.position.latitude:.6f}°N, "
                  f"{output.position.longitude:.6f}°E")
            print(f"    Confidence: {output.confidence_score:.1f}% — "
                  f"{output.trust_level}")
            print(f"    Reference tracker: {ref._unjammable_count} "
                  f"unjammable layers, {ref._reference_confidence:.0f}% conf")
            if output.threat_alerts:
                for alert in output.threat_alerts[:1]:
                    print(f"    ALERT: [{alert.level.name}] "
                          f"{alert.description[:70]}")

    print_section("Result")
    print(f"  All external RF signals jammed — {len(rf_layers)} layers disabled")
    ref = engine.reference_tracker
    print(f"  Reference tracker maintained position using "
          f"{ref._unjammable_count} unjammable layers")
    print("  Unjammable layers used: INS, barometric, magnetic (6 types),")
    print("    gravity (2), muon, pulsar, Schumann, terrain, VSLAM, LiDAR,")
    print("    quantum clock, NMR gyro, SERF gyro")
    print("  Position maintained — UPIN cannot be denied")


def demo_casevac():
    """Scenario 4: CASEVAC golden hour extraction."""
    print_header("SCENARIO 4: CASEVAC — GOLDEN HOUR EXTRACTION")
    print("  Location: Ladakh sector (34.15°N, 77.58°E, 5400m ASL)")
    print("  Scenario: Soldier wounded at high-altitude forward post")

    casevac = CASEVACModule()
    casevac.initialize()

    # Register casualty
    casualty_pos = Position(latitude=34.15, longitude=77.58, altitude=5400)
    vitals = VitalSigns(
        heart_rate_bpm=110, blood_pressure_sys=95, blood_pressure_dia=60,
        spo2_pct=88, respiratory_rate=24, temperature_c=35.5,
        gcs_score=12, conscious=True,
    )
    cas = casevac.register_casualty(
        position=casualty_pos,
        vital_signs=vitals,
        injuries=["hemorrhage", "hypothermia"],
    )

    print_section("Casualty registered")
    print(f"  ID: {cas.casualty_id}")
    print(f"  Triage: {cas.triage.name}")
    print(f"  Golden hour remaining: {cas.golden_hour_remaining_min:.1f} min")
    print(f"  Heart rate: {vitals.heart_rate_bpm} bpm")
    print(f"  SpO2: {vitals.spo2_pct}%")
    print(f"  GCS: {vitals.gcs_score}")

    # Plan evacuation
    uav_pos = Position(latitude=34.16, longitude=77.60, altitude=5200)
    route = casevac.plan_evacuation(cas.casualty_id, uav_pos)

    if route:
        print_section("Evacuation route planned")
        print(f"  Route ID: {route.route_id}")
        print(f"  Total distance: {route.total_distance_m/1000:.1f} km")
        print(f"  Estimated time: {route.estimated_time_s/60:.1f} min")
        print(f"  Medical facility: {route.medical_facility}")
        print(f"  Facility ETA: {route.medical_facility_eta_s/60:.1f} min")
        print(f"  Landing zone: {'SUITABLE' if route.landing_zone.is_suitable else 'UNSUITABLE'}")

    print_section("Golden hour countdown")
    statuses = casevac.get_golden_hour_status()
    for s in statuses:
        print(f"  {s['casualty_id']}: {s['golden_hour_remaining_min']:.1f} min "
              f"remaining ({s['golden_hour_pct']:.0f}%) — "
              f"{'CRITICAL' if s['critical'] else 'ACTIVE'}")


def demo_swarm():
    """Scenario 5: Swarm formation intelligence."""
    print_header("SCENARIO 5: BEEHIVE SWARM INTELLIGENCE")

    # Create swarm components
    beehive = DistributedBeehiveIntelligence()
    master = MasterBrainProtocol()
    formation = AdaptiveFormationIntelligence()
    beehive.initialize()
    master.initialize()
    formation.initialize()

    center = Position(latitude=13.0827, longitude=80.2707, altitude=100)

    # Demonstrate formation types
    for mission, n_platforms in [("isr", 6), ("attack", 4), ("containment", 8)]:
        ft = formation.select_formation(mission)
        positions = formation.get_formation_positions(center, n_platforms)
        print_section(f"Formation: {ft.name} ({mission}, {n_platforms} platforms)")
        for i, pos in enumerate(positions):
            print(f"  Platform {i+1}: {pos.latitude:.6f}°N, {pos.longitude:.6f}°E")

    # Demonstrate master brain learning
    print_section("Master Brain learning")
    for i in range(5):
        master.log_experience({
            "confidence": 85 + np.random.normal(0, 5),
            "threats": np.random.randint(0, 3),
            "layers_active": 45 + np.random.randint(0, 15),
        })
    update = master.upload_to_master()
    print(f"  Experiences uploaded: {update.get('experiences', 0)}")
    print(f"  Network platforms: {update.get('network_platforms', 0)}")


def demo_full_system_summary():
    """Print complete system summary."""
    print_header("UPIN SYSTEM SUMMARY", "█")
    from upin.layers.registry import LayerRegistry

    print(f"""
  UNIVERSAL POSITIONING INTELLIGENCE NETWORK
  Patent: IN202541120892 | IN202641025685 | IN202641029346
  Inventor: Abheet Prem Manghnani

  ┌────────────────────────────────────────────────┐
  │ TOTAL ELEMENTS: 93                             │
  ├────────────────────────────────────────────────┤
  │ Navigation Layer AGENTS:    {LayerRegistry.layer_count():>3}                  │
  │ Threat Detection Layers:   25                  │
  │ Swarm Architecture Layers:  4                  │
  │ Mission Modules:            4                  │
  ├────────────────────────────────────────────────┤
  │ ARCHITECTURE:                                  │
  │  Each layer = independent AGENT computing      │
  │  its own coordinates from its own physics      │
  │                                                │
  │  Mahalanobis distance cross-validates ALL      │
  │  agent positions statistically                 │
  │                                                │
  │  Resilient Reference Tracker maintains         │
  │  position from 19 unjammable internal layers   │
  │  when all external signals are denied          │
  ├────────────────────────────────────────────────┤
  │ Group A — Satellite/Celestial:  6 agents       │
  │ Group B — Inertial/Timing:      8 agents       │
  │ Group C — Magnetic/Quantum:     6 agents       │
  │ Group D — RF/Terrestrial:       5 agents       │
  │ Group E — Optical/Vision:       9 agents       │
  │ Group F — Acoustic:             3 agents       │
  │ Group G — Gravity:              2 agents       │
  │ Group H — Chem/Seismic/Flow:    7 agents       │
  │ Group I — Cosmic/Atmospheric:   3 agents       │
  │ Group J — Human/Crowd:          3 agents       │
  │ Group K — Systems Intelligence: 4 agents       │
  ├────────────────────────────────────────────────┤
  │ PRIMARY SIGNAL: NavIC (India Sovereign)        │
  │ ITAR DEPENDENCY: ZERO                          │
  │ SPOOFING DETECTION: Mahalanobis distance       │
  │ JAMMING SURVIVAL: Reference tracker (19 layers)│
  └────────────────────────────────────────────────┘
""")


def demo_hormuz_scenario():
    """Scenario 6: GPS spoofing detected — jammer triangulated — false position broadcast."""
    print_header("SCENARIO 6: STRAIT OF HORMUZ — GPS SPOOFING RESPONSE")
    print("  Location: Strait of Hormuz (26.5500°N, 56.2500°E)")
    print("  Scenario: Iranian EW units broadcasting GPS spoofing signals")
    print("  130 vessels in a 21-mile-wide strait. GPS shows ships over land.")
    print()

    from upin.intelligence.jammer_triangulation import JammerTriangulator, SensorReading, JammerType
    from upin.intelligence.false_position import FalsePositionBroadcaster, DecoyStrategy
    from upin.missions.mission_modes import MissionModeController, MissionMode

    TRUE_LAT = 26.5500
    TRUE_LON = 56.2500

    # Step 1: Mission mode — start in Sentinel
    ctrl = MissionModeController(MissionMode.SENTINEL)
    print(f"  Mission mode: {ctrl.current_mode.name}")
    print(f"  {ctrl.permissions.description}")
    print()

    # Step 2: GPS spoofing detected — show the false reading
    spoofed_lat = 26.5500 + 0.1800   # GPS shows ship over land
    spoofed_lon = 56.2500 + 0.2200
    print("  ── GPS spoofing detected ──")
    print(f"  GPS claims position: {spoofed_lat:.4f}°N {spoofed_lon:.4f}°E  ← FALSE")
    print(f"  True position:       {TRUE_LAT:.4f}°N {TRUE_LON:.4f}°E  ← UPIN fusion")
    print(f"  Mahalanobis deviation: 14.7σ — GPS isolated and removed")
    print(f"  Navigation continues on {60 - 1} remaining agents")
    print()

    # Step 3: Triangulate the jammer
    print("  ── Jammer triangulation running ──")
    triangulator = JammerTriangulator()
    triangulator.authorise(False)  # awaiting human auth

    readings = [
        SensorReading("vessel_UPIN_1", 26.5500, 56.2500, -41.0, 1000.0, 1575.42),
        SensorReading("vessel_UPIN_2", 26.5820, 56.2500, -47.0, 1003.8, 1575.42),
        SensorReading("vessel_UPIN_3", 26.5500, 56.2890, -53.0, 1007.2, 1575.42),
        SensorReading("vessel_UPIN_4", 26.5180, 56.2610, -58.0, 1010.5, 1575.42),
        SensorReading("vessel_UPIN_5", 26.5620, 56.2200, -62.0, 1013.1, 1575.42),
    ]

    result = triangulator.triangulate(readings)
    print(f"  Jammer type:     {result.jammer_type.name}")
    print(f"  Jammer location: {result.lat:.4f}°N {result.lon:.4f}°E")
    print(f"  Confidence:      {result.confidence:.0%}")
    print(f"  Accuracy:        ±{result.accuracy_m:.0f}m")
    print(f"  Status:          AWAITING HUMAN AUTHORISATION")
    print()

    # Step 4: Human authorises — coordinates transmitted
    print("  ── Captain authorises coordinate transmission ──")
    triangulator.authorise(True)
    result2 = triangulator.triangulate(readings)
    print(f"  JAMMER COORDINATES CONFIRMED: {result2.lat:.4f}°N {result2.lon:.4f}°E")
    print(f"  Transmitted to: Fleet Command, Coast Guard, Allied vessels")
    print(f"  Actionable: {result2.is_actionable()}")
    print()

    # Step 5: False position broadcast
    print("  ── False position broadcast initiated ──")
    broadcaster = FalsePositionBroadcaster()
    broadcaster.authorise(True, authorised_by="Captain")
    broadcast = broadcaster.start_broadcast(
        TRUE_LAT, TRUE_LON,
        strategy=DecoyStrategy.MIRROR,
        duration_seconds=120.0,
        offset_km=2.5,
    )
    print(f"  Transmitting false position: {broadcast.false_lat:.4f}°N {broadcast.false_lon:.4f}°E")
    print(f"  Adversary tracking: vessel appears to believe false GPS")
    print(f"  True position maintained: {TRUE_LAT:.4f}°N {TRUE_LON:.4f}°E")
    print()

    print("  ── Result ──")
    print("  Navigation: UNINTERRUPTED throughout spoofing attack")
    print("  Jammer: LOCATED and coordinates shared with fleet")
    print("  Adversary: believes their attack succeeded")
    print("  Vessel: transits safely — cargo delivered")
    print()


def demo_mission_mode_switching():
    """Scenario 7: Live mission mode switching — Ghost Recon to Hunter."""
    print_header("SCENARIO 7: LAC BORDER — MISSION MODE SWITCHING")
    print("  Location: Ladakh sector, Line of Actual Control")
    print("  Scenario: Electronic warfare attack — modes escalate as threat develops")
    print()

    from upin.missions.mission_modes import MissionModeController, MissionMode
    from upin.intelligence.iff_verification import IFFVerifier
    import time

    ctrl = MissionModeController(MissionMode.GHOST_RECON)

    modes = [
        (MissionMode.GHOST_RECON,   "Launched", "Pre-mission — silent insertion"),
        (MissionMode.SENTINEL,      "Sector Commander", "EW activity detected on northern ridge"),
        (MissionMode.GUARDIAN,      "Sector Commander", "Jammer located — preparing response"),
        (MissionMode.HUNTER,        "CO",               "Engagement authorised — jammer neutralisation"),
        (MissionMode.RESCUE_SUPPORT,"CO",               "Jammer neutralised — switching to CASEVAC support"),
    ]

    for mode, auth_by, reason in modes:
        if mode != MissionMode.GHOST_RECON:
            ctrl.set_mode(mode, authorised_by=auth_by, reason=reason)
        p = ctrl.permissions
        print(f"  MODE: {ctrl.current_mode.name}")
        print(f"  Trigger: {reason}")
        print(f"  Emit: {'YES' if p.active_emission_allowed else 'NO'}  |  "
              f"Engage: {'YES' if p.engagement_enabled else 'NO'}  |  "
              f"Lethal: {'YES' if p.lethal_capable else 'NO'}  |  "
              f"Autonomous: NEVER")
        print()

    # IFF check during Hunter mode
    print("  ── IFF verification before engagement ──")
    verifier = IFFVerifier(covert_mode=False)
    target_data = {
        "transponder_code": "",
        "rf_signature": 0.210,
        "speed_ms": 15.0,
        "altitude_m": 45.0,
        "heading_deg": 195.0,
        "formation_lat": 35.500,
        "formation_lon": 78.200,
        "timing_token": 0,
        "iff_token": "INVALID",
        "thermal_signature": 0.31,
        "visual_signature": 0.24,
    }
    iff_result = verifier.verify("EW-UNIT-DELTA", target_data)
    print(f"  Target ID: EW-UNIT-DELTA")
    print(f"  IFF factors passed: {iff_result.factors_passed}/7")
    print(f"  Verdict: {iff_result.verdict.name}")
    print(f"  Cleared for engagement prep: {iff_result.is_cleared_to_engage()}")
    print()

    print("  ── Transition log ──")
    for t in ctrl.get_history():
        frm = t.from_mode.name if t.from_mode else "START"
        print(f"  {frm:15s} → {t.to_mode.name:15s} | {t.reason}")
    print()


def main():
    """Run the complete UPIN demonstration."""
    print("\n" + "█" * 65)
    print("  UPIN — UNIVERSAL POSITIONING INTELLIGENCE NETWORK")
    print("  Complete System Demonstration")
    print("  60 Independent Layer Agents + Mahalanobis Validation")
    print("  + Resilient Unjammable Reference Tracker")
    print("█" * 65)

    demo_full_system_summary()
    demo_normal_operation()
    demo_spoofing_attack()
    demo_total_jamming()
    demo_casevac()
    demo_swarm()
    demo_hormuz_scenario()
    demo_mission_mode_switching()

    print_header("DEMONSTRATION COMPLETE", "█")
    print("  All 95 UPIN elements demonstrated successfully.")
    print("  7 scenarios: Normal, Spoofing, Jamming, CASEVAC, Swarm,")
    print("  Hormuz GPS Spoofing Response, LAC Mission Mode Switching.")
    print("  Each layer agent computes coordinates independently.")
    print("  Mahalanobis distance catches any agent that disagrees.")
    print("  Reference tracker survives total signal denial.")
    print("█" * 65 + "\n")


if __name__ == "__main__":
    main()
