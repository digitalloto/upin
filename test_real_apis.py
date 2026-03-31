#!/usr/bin/env python3
"""
UPIN Real API Integration Test

Tests all real sensor agents and shows actual vs simulated results.
Run: python test_real_apis.py
"""

import sys
import time

sys.path.insert(0, ".")


def banner(text):
    print(f"\n{'=' * 70}")
    print(f"  {text}")
    print(f"{'=' * 70}")


def section(text):
    print(f"\n  -- {text} --")


def main():
    banner("UPIN REAL API INTEGRATION TEST")

    results = {}

    # ── 1. WiFi Positioning ───────────────────────────────────────
    section("WiFi Positioning (Mozilla Location Service)")
    from upin.agents.real_wifi_agent import RealWiFiPositioningAgent

    wifi = RealWiFiPositioningAgent()
    networks = wifi.scan_wifi()
    print(f"  Platform:    {wifi._platform}")
    print(f"  WiFi scan:   {len(networks)} networks found")

    if networks:
        print(f"  Data source: REAL HARDWARE")
        for n in networks[:5]:
            print(f"    {n.bssid}  {n.ssid:<20s}  {n.signal_dbm} dBm  ch{n.channel}")
        if len(networks) > 5:
            print(f"    ... and {len(networks) - 5} more")
    else:
        print(f"  Data source: SIMULATED (no WiFi hardware)")

    wifi_pos = wifi.get_position()
    if wifi_pos:
        print(f"  Position:    {wifi_pos.latitude:.6f}N {wifi_pos.longitude:.6f}E")
        print(f"  Accuracy:    +/-{wifi_pos.accuracy_m:.0f}m")
        print(f"  Source:      {wifi_pos.source}")
        print(f"  Networks:    {wifi_pos.networks_used}")
        results["wifi"] = wifi_pos

    # ── 2. Cellular Positioning ───────────────────────────────────
    section("Cellular Positioning (OpenCellID / MLS)")
    from upin.agents.real_cellular_agent import RealCellularPositioningAgent

    cell = RealCellularPositioningAgent()
    towers = cell.scan_cell_towers()
    print(f"  Platform:    {cell._platform}")
    print(f"  API key:     {'set' if cell._api_key else 'not set (MLS fallback)'}")
    print(f"  Tower scan:  {len(towers)} towers found")

    if towers:
        print(f"  Data source: REAL HARDWARE")
        for t in towers[:3]:
            print(f"    MCC={t.mcc} MNC={t.mnc} LAC={t.lac} CID={t.cid} {t.signal_dbm}dBm {t.radio}")
    else:
        print(f"  Data source: SIMULATED (no modem)")

    cell_pos = cell.get_position()
    if cell_pos:
        print(f"  Position:    {cell_pos.latitude:.6f}N {cell_pos.longitude:.6f}E")
        print(f"  Accuracy:    +/-{cell_pos.accuracy_m:.0f}m")
        print(f"  Source:      {cell_pos.source}")
        print(f"  Towers:      {cell_pos.towers_used} | Radio: {cell_pos.primary_radio}")
        results["cellular"] = cell_pos

    # ── 3. Phone Sensors ──────────────────────────────────────────
    section("Phone Sensors (GPS + IMU + Barometer)")
    from upin.agents.real_phone_sensor_agent import RealPhoneSensorAgent

    phone = RealPhoneSensorAgent()
    print(f"  Platform:    {phone._platform}")
    print(f"  Termux:      {phone._is_termux}")
    print(f"  Detected:    {phone._available_sensors or 'none (will simulate)'}")

    snap = phone.get_snapshot()
    real_sensors = [s for s in snap.sensors_available if "_sim" not in s]
    sim_sensors = [s for s in snap.sensors_available if "_sim" in s]

    if real_sensors:
        print(f"  REAL sensors: {real_sensors}")
    if sim_sensors:
        print(f"  Simulated:    {sim_sensors}")

    print(f"  GPS:   {snap.gps.latitude:.6f}N {snap.gps.longitude:.6f}E "
          f"+/-{snap.gps.accuracy_m:.0f}m fix={snap.gps.fix_type} sats={snap.gps.satellites}")
    print(f"  Accel: x={snap.imu.accel_x:+.2f} y={snap.imu.accel_y:+.2f} z={snap.imu.accel_z:+.2f} m/s2")
    print(f"  Gyro:  x={snap.imu.gyro_x:+.1f} y={snap.imu.gyro_y:+.1f} z={snap.imu.gyro_z:+.1f} deg/s")
    print(f"  Mag:   x={snap.imu.mag_x:+.1f} y={snap.imu.mag_y:+.1f} z={snap.imu.mag_z:+.1f} uT  "
          f"heading={snap.imu.heading_deg:.0f} deg")
    print(f"  Baro:  {snap.baro.pressure_hpa:.1f} hPa  {snap.baro.temperature_c:.1f} C  "
          f"alt={snap.baro.altitude_m:.1f}m")
    results["phone_gps"] = snap.gps

    # ── 4. GNSS Agent ─────────────────────────────────────────────
    section("GNSS Agent (multi-constellation + spoof detection)")
    from upin.agents.gnss_agent import GNSSAgent

    gnss = GNSSAgent()
    reading = gnss.get_reading()
    auth_reading = gnss.signal_authentication_log(reading)
    print(f"  Status:          {gnss.status}")
    print(f"  Constellations:  {auth_reading['constellation_data']['available_constellations']}")
    print(f"  Authenticated:   {auth_reading['authentication_status']}")
    print(f"  Auth level:      {auth_reading['constellation_data']['authentication_level']}")

    # ── 5. Accuracy Comparison ────────────────────────────────────
    section("ACCURACY COMPARISON")
    print(f"  {'Source':<20s} {'Latitude':>12s} {'Longitude':>12s} {'Accuracy':>10s} {'Type':>10s}")
    print(f"  {'-'*64}")

    for name, pos in [
        ("WiFi", results.get("wifi")),
        ("Cellular", results.get("cellular")),
    ]:
        if pos:
            print(f"  {name:<20s} {pos.latitude:>12.6f} {pos.longitude:>12.6f} "
                  f"{'+/-' + str(int(pos.accuracy_m)) + 'm':>10s} {pos.source:>10s}")

    gps = results.get("phone_gps")
    if gps and gps.latitude != 0:
        print(f"  {'Phone GPS':<20s} {gps.latitude:>12.6f} {gps.longitude:>12.6f} "
              f"{'+/-' + str(int(gps.accuracy_m)) + 'm':>10s} {gps.fix_type:>10s}")

    # ── 6. UPIN Fusion Integration ────────────────────────────────
    section("UPIN FUSION INTEGRATION")
    all_readings = []

    wifi_reading = wifi.get_reading()
    if wifi_reading.get("status") == "ACTIVE":
        all_readings.append(wifi_reading)
        print(f"  WiFi agent:     conf={wifi_reading['confidence']:.2f}")

    cell_reading = cell.get_reading()
    if cell_reading.get("status") == "ACTIVE":
        all_readings.append(cell_reading)
        print(f"  Cellular agent: conf={cell_reading['confidence']:.2f}")

    phone_reading = phone.get_reading()
    if phone_reading.get("status") == "ACTIVE":
        all_readings.append(phone_reading)
        print(f"  Phone agent:    conf={phone_reading['confidence']:.2f}")

    gnss_reading = gnss.get_reading()
    all_readings.append(gnss_reading)
    print(f"  GNSS agent:     conf={gnss_reading.get('confidence', 'N/A')}")

    print(f"\n  Total agents feeding UPIN fusion: {len(all_readings)}")

    # ── 7. Agent Stats ────────────────────────────────────────────
    section("AGENT STATISTICS")
    for agent, name in [(wifi, "WiFi"), (cell, "Cellular"), (phone, "Phone")]:
        stats = agent.get_stats()
        print(f"  {name}: {stats}")

    # ── Summary ───────────────────────────────────────────────────
    banner("RESULTS SUMMARY")
    real_count = 0
    sim_count = 0

    for name, pos in results.items():
        if hasattr(pos, "source"):
            if pos.source in ("mls", "opencellid"):
                real_count += 1
            else:
                sim_count += 1

    real_hw = [s for s in snap.sensors_available if "_sim" not in s]
    sim_hw = [s for s in snap.sensors_available if "_sim" in s]

    print(f"  Positioning APIs:  {real_count} real, {sim_count} simulated")
    print(f"  Phone sensors:     {len(real_hw)} real, {len(sim_hw)} simulated")
    print(f"  Fusion agents:     {len(all_readings)} active")
    print(f"  All agents:        importable and functional")
    print()

    if real_count > 0 or real_hw:
        print("  REAL HARDWARE DETECTED — APIs returning live data")
    else:
        print("  NO REAL HARDWARE — all agents using simulation fallback")
        print("  (This is expected on a server. On a phone/laptop with")
        print("   WiFi + GPS, you will see real positioning data.)")

    print()
    print("  REAL API INTEGRATION TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
