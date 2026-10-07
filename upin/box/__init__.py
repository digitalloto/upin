"""
The UPIN box: a companion computer between the sensors and the flight
controller.

The GNSS receiver plugs into the box, not the flight controller. Every fix is
checked -- physically possible? constellations agree? receiver reports
jamming? consistent with where UPIN expects to be? -- and only then given to
the flight controller. When GNSS cannot be trusted the box sends UPIN's own
estimate with its honest accuracy, or no fix at all so the flight
controller's own failsafe takes over.

  gnss_parser   UBX NAV-PVT / NAV-SAT / MON-RF and NMEA GGA / RMC
  gateway       the per-epoch decision: TRUSTED, DEGRADED or NO_FIX
  mavlink_out   GPS_INPUT to ArduPilot -- UNTESTED until SITL or a bench FC
  replay        drives the gateway from recorded or synthetic epochs

Nothing here has run on hardware. See docs/HARDWARE.md.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""
