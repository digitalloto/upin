"""
What every layer needs, including the ones that do not work yet.

Five layers declare their requirements on their own class (`REQUIRES`),
because they were rebuilt to the no-fabrication contract and take real input.
The other 135 still simulate internally. This catalogue records, for each of
those, what it would need to work for real: the hardware, the live inputs,
any reference data, and the conditions under which it can produce anything.

It is documentation of requirements, not a claim of capability. A layer listed
here does not become real by being listed; its README says plainly whether it
has an input path today.

Rules the entries follow:

  * no prices -- nothing here was quoted by a supplier, and an invented figure
    is the thing this project forbids
  * no feed_method on a legacy layer -- it has none yet, and naming one would
    make the declaration lie
  * every entry carries an operating class, so nobody has to read the physics
    to learn that an X-ray pulsar receiver is not going on a quadcopter, or
    that OMEGA's transmitters were switched off in 1997

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

from typing import Dict, Optional

from upin.core.sensor_requirements import (
    DataInput, Hardware, ReferenceData, SensorRequirement,
)


class OperatingClass:
    DRONE_READY = "drone-ready"
    SPECIALIST = "specialist"
    LABORATORY = "laboratory"
    PLATFORM_SPECIFIC = "platform-specific"
    NOT_OPERATIONAL = "no longer operational"
    INFRASTRUCTURE = "needs infrastructure"
    SUPPORT = "support function"


CLASS_MEANING = {
    OperatingClass.DRONE_READY:
        "Hardware a drone commonly carries or can easily add.",
    OperatingClass.SPECIALIST:
        "Real, buyable hardware that typical drones do not carry.",
    OperatingClass.LABORATORY:
        "Physics demonstrated in laboratories; not yet deployable on a drone.",
    OperatingClass.PLATFORM_SPECIFIC:
        "Works only on a particular platform -- ships, submarines, ground vehicles.",
    OperatingClass.NOT_OPERATIONAL:
        "The transmitters or infrastructure it depends on no longer exist.",
    OperatingClass.INFRASTRUCTURE:
        "Needs beacons, networks or other people's equipment in place first.",
    OperatingClass.SUPPORT:
        "Does not produce a position itself; monitors or coordinates other layers.",
}


# -- shared hardware ---------------------------------------------------------

def _h(name, why="", part="", common=False):
    return Hardware(name, why=why, typical_part=part, already_on_most_drones=common)


def _i(name, units="", why=""):
    return DataInput(name, feed_method="", units=units, why=why)


def _r(name, source="", why=""):
    return ReferenceData(name, source=source, why=why, bundled=False)


IMU = _h("IMU (3-axis gyroscope + accelerometer)", "rotation and acceleration",
         "flight controller IMU or MEMS breakout", True)
BARO = _h("barometer", "pressure altitude", "flight controller barometer", True)
MAG = _h("magnetometer", "magnetic field / heading", "flight controller compass", True)
CAMERA = _h("camera", "images of the ground or surroundings",
            "global-shutter or Pi-class camera", True)
DOWN_CAMERA = _h("downward camera", "images of the ground below",
                 "downward camera or optical-flow module", True)
RANGEFINDER = _h("downward rangefinder", "height above the ground",
                 "lidar or radar rangefinder", True)
CLOCK = _h("stable clock", "precise time", "GNSS-disciplined or TCXO oscillator", True)
SDR = _h("software-defined radio", "receives and timestamps RF signals",
         "wideband SDR receiver", False)
RF_ANT = _h("antenna for the band", "picks up the signal", "band-appropriate antenna", False)
DF_ARRAY = _h("direction-finding antenna array", "bearing to a transmitter",
              "multi-element array with phase-coherent receiver", False)
GNSS_MC = _h("multi-constellation GNSS receiver", "ranging to that constellation",
             "multi-band receiver with raw measurements", True)
STAR_CAM = _h("star camera", "images of stars", "narrow-field low-noise camera", False)
SUN_SENSOR = _h("sun sensor or sky camera", "sun direction", "sun sensor / camera", False)
SONAR = _h("sonar transducer", "acoustic ranging underwater", "marine transducer", False)
MIC_ARRAY = _h("microphone array", "acoustic time of arrival", "synchronised mic array", False)
THERMAL_CAM = _h("thermal camera", "long-wave infrared images", "LWIR camera core", False)
LIDAR = _h("scanning lidar", "3-D point clouds", "rotating or solid-state lidar", False)
UWB = _h("UWB radio", "time-of-flight ranging", "UWB transceiver module", False)
CHEM = _h("chemical sensor", "concentration of a chemical species",
          "gas or water-chemistry sensor", False)
DEPTH = _h("pressure / depth sensor", "water depth", "marine pressure transducer", False)

INDIAN_MAPS = "Survey of India, Bhuvan or Cartosat (never Google)"
CHARTS = "Indian Naval Hydrographic Office charts"


def _req(hw, inputs=(), refs=(), pre=(), notes=""):
    return SensorRequirement(hardware=list(hw), inputs=list(inputs),
                             reference_data=list(refs), preconditions=tuple(pre),
                             notes=notes)


D, S, L, P, N, F, U = (OperatingClass.DRONE_READY, OperatingClass.SPECIALIST,
                       OperatingClass.LABORATORY, OperatingClass.PLATFORM_SPECIFIC,
                       OperatingClass.NOT_OPERATIONAL, OperatingClass.INFRASTRUCTURE,
                       OperatingClass.SUPPORT)

# layer_id -> (operating class, requirement)
CATALOG: Dict[str, tuple] = {
    # ---- Group A: satellite and celestial ---------------------------------
    "leo_l19": (S, _req([GNSS_MC, _h("LEO signal receiver", "authenticated LEO signals")],
                        [_i("LEO pseudoranges with authentication tags", "metres")],
                        pre=["LEO service with authenticated navigation signals"])),
    "xnav_l29": (L, _req([_h("X-ray detector", "pulsar photon timing",
                             "large-area X-ray timing detector"), CLOCK],
                         [_i("photon arrival times", "seconds")],
                         [_r("pulsar timing ephemerides")],
                         ["above the atmosphere: X-rays do not reach low altitude"],
                         "Spacecraft technique; not usable on a drone.")),
    "stellar_l46": (S, _req([STAR_CAM, IMU], [_i("star images")],
                            [_r("star catalogue")], ["clear night sky"])),
    "skygrad_l47": (S, _req([_h("sky radiance camera", "sky brightness gradient")],
                            [_i("sky brightness images")], pre=["daylight sky visible"])),
    "glonass_a07": (D, _req([GNSS_MC], [_i("GLONASS pseudoranges", "metres")],
                            pre=["four or more GLONASS satellites"])),
    "galileo_a08": (D, _req([GNSS_MC], [_i("Galileo pseudoranges", "metres")],
                            pre=["four or more Galileo satellites"])),
    "beidou_a09": (D, _req([GNSS_MC], [_i("BeiDou pseudoranges", "metres")],
                           pre=["four or more BeiDou satellites"])),
    "qzss_a10": (D, _req([GNSS_MC], [_i("QZSS pseudoranges", "metres")],
                         pre=["inside the QZSS service area (Asia-Oceania)"])),
    "lunardist_a11": (S, _req([STAR_CAM, CLOCK], [_i("Moon-star angular distances", "degrees")],
                              [_r("lunar and star almanac")], ["Moon and stars visible"])),
    "chronometer_a12": (S, _req([CLOCK, STAR_CAM], [_i("celestial sight times")],
                                [_r("nautical almanac")])),
    "gagan_a13": (D, _req([GNSS_MC], [_i("GAGAN SBAS corrections")],
                          pre=["GAGAN geostationary satellites in view (India)"],
                          notes="Improves GPS; does nothing when GPS itself is jammed.")),
    "iriddop_a14": (S, _req([SDR, RF_ANT], [_i("LEO signal Doppler shifts", "Hz")],
                            [_r("LEO satellite orbits")])),
    "polaris_a15": (S, _req([STAR_CAM, IMU], [_i("Polaris altitude", "degrees")],
                            pre=["northern hemisphere, clear night sky"])),
    "noonsight_a16": (S, _req([SUN_SENSOR, IMU, CLOCK], [_i("sun altitude at noon")],
                              [_r("solar almanac")])),
    "sunazimuth_a17": (D, _req([SUN_SENSOR, CLOCK], [_i("sun bearing", "degrees")],
                               pre=["sun visible"], notes="Gives heading, not position.")),
    "planets_a18": (S, _req([STAR_CAM, IMU, CLOCK], [_i("planet altitude and azimuth")],
                            [_r("planetary almanac")], ["clear sky"])),
    "refraction_a19": (U, _req([BARO, _h("temperature sensor", "air density")],
                               [_i("pressure and temperature")],
                               notes="Corrects celestial sights; no position of its own.")),
    "startrack_l4": (S, _req([STAR_CAM, IMU], [_i("star images")], [_r("star catalogue")],
                             ["sky visible; daytime tracking needs short-wave IR"])),

    # ---- Group B: inertial and timing -------------------------------------
    "ins_l3": (D, _req([IMU], [_i("angular rate and specific force", "rad/s, m/s^2")],
                       pre=["initial position, velocity and attitude"],
                       notes="Drifts quickly on MEMS sensors; a short-term bridge. "
                             "Strapdown INS exists in upin/core/strapdown_ins.py and "
                             "is to be wired in (spec item 4).")),
    "baro_l11": (D, _req([BARO], [_i("static pressure", "hPa")],
                         pre=["reference pressure (QNH) for absolute altitude"],
                         notes="Altitude only, no horizontal position.")),
    "doppler_l12": (S, _req([_h("Doppler velocity radar", "ground velocity")],
                            [_i("Doppler shifts", "Hz")])),
    "laserdop_l18": (S, _req([_h("laser Doppler velocimeter", "3-D ground velocity")],
                             [_i("velocity vector", "m/s")])),
    "qclock_l27": (L, _req([_h("optical atomic clock", "precision time")],
                           [_i("clock time")], notes="Timing only; laboratory hardware.")),
    "opticflow_l43": (D, _req([DOWN_CAMERA, RANGEFINDER, IMU],
                              [_i("image flow", "pixels/s"), _i("height above ground", "m")],
                              pre=["textured ground", "known height"],
                              notes="To be rebuilt as L3 (spec item 8).")),
    "nmrgyro_l57": (L, _req([_h("NMR gyroscope", "rotation rate")], [_i("rotation rate")])),
    "serfgyro_l58": (L, _req([_h("SERF atomic gyroscope", "rotation rate")],
                             [_i("rotation rate")])),
    "radaralt_b09": (S, _req([RANGEFINDER], [_i("height above ground", "m")],
                             notes="Height only; feeds terrain matching (spec item 10).")),
    "depthpres_b10": (P, _req([DEPTH], [_i("water pressure", "Pa")],
                              notes="Submerged platforms only.")),
    "vhorizon_b11": (U, _req([IMU], [_i("vertical reference")],
                             notes="Supports celestial sights; no position of its own.")),

    # ---- Group C: magnetic and quantum ------------------------------------
    "magano_l6": (S, _req([_h("scalar magnetometer", "total field intensity",
                              "optically pumped or fluxgate magnetometer")],
                          [_i("magnetic field", "nT")],
                          [_r("magnetic anomaly map", "national geophysical surveys")],
                          ["anomaly map of the area", "platform magnetic noise compensated"])),
    "dualqmag_l17": (L, _req([_h("quantum magnetometer", "field direction and intensity")],
                             [_i("magnetic field vector", "nT")])),
    "magmap_l23": (S, _req([MAG], [_i("magnetic field", "nT")],
                           [_r("magnetic signature map")], ["map of the area"])),
    "eminduct_l24": (S, _req([_h("induction coil sensor", "induced voltage")],
                             [_i("induced voltage", "uV")])),
    "nvdiamond_l30": (L, _req([_h("NV-diamond magnetometer", "vector magnetic field")],
                              [_i("magnetic field vector", "nT")])),
    "bicoord_l44": (P, _req([MAG, CHEM], [_i("magnetic field"), _i("chemical gradient")],
                            [_r("magnetic and chemical maps")], notes="Marine.")),
    "efield_c07": (L, _req([_h("electric field sensor", "ambient E-field gradient")],
                           [_i("electric field", "V/m")])),
    "qcompass_c08": (L, _req([_h("cold-atom interferometer", "rotation sensing")],
                             [_i("rotation rate")])),
    "magindoor_c09": (D, _req([MAG], [_i("magnetic field", "uT")],
                              [_r("indoor magnetic fingerprint survey")],
                              ["building surveyed beforehand"])),

    # ---- Group D: RF and terrestrial --------------------------------------
    "groundrf_l7": (S, _req([SDR, DF_ARRAY], [_i("signal times or bearings")],
                            [_r("emitter locations")], ["three or more known emitters"])),
    "wifi_l8": (D, _req([_h("WiFi radio", "access-point signal strength", "", True)],
                        [_i("access-point RSSI", "dBm")],
                        [_r("access-point location database")],
                        ["access points with known positions"])),
    "celltower_l9": (S, _req([_h("cellular modem", "tower IDs, timing advance, RSSI")],
                             [_i("cell measurements")], [_r("cell tower database")])),
    "eloran_l41": (F, _req([_h("eLORAN receiver", "100 kHz ground-wave timing"),
                            _h("H-field antenna", "eLORAN reception")],
                           [_i("time differences", "microseconds")],
                           pre=["an operating eLORAN transmitter chain in range"])),
    "soop_l42": (S, _req([SDR, RF_ANT], [_i("satellite signal Doppler", "Hz")],
                         [_r("satellite orbits")], ["signals of opportunity overhead"])),
    "uwb_d06": (F, _req([UWB], [_i("ranges to anchors", "m")], [_r("anchor positions")],
                        ["three or more UWB anchors installed"],
                        "To be rebuilt for swarm ranging (spec item 11).")),
    "lora_d07": (F, _req([_h("LoRa radio", "RSSI / time of flight")],
                         [_i("LoRa ranges or RSSI")], [_r("gateway positions")])),
    "bluetooth_d08": (F, _req([_h("Bluetooth 5.1 AoA array", "angle of arrival")],
                              [_i("angles of arrival", "degrees")],
                              [_r("beacon positions")], ["AoA beacons installed"])),
    "ais_d09": (P, _req([_h("AIS receiver", "vessel broadcasts")],
                        [_i("AIS messages")], notes="Maritime.")),
    "adsb_d10": (D, _req([_h("ADS-B receiver (1090 MHz)", "aircraft broadcasts", "", False)],
                         [_i("ADS-B messages")],
                         notes="Positions of other aircraft, which use GNSS themselves.")),
    "tacan_d11": (F, _req([_h("TACAN receiver", "UHF bearing and distance")],
                          [_i("bearing and range")], [_r("TACAN station list")],
                          ["military TACAN station in range"])),
    "vordme_d12": (F, _req([_h("VOR/DME receiver", "bearing and distance")],
                           [_i("radial and DME range")], [_r("VOR/DME station list")],
                           ["station in line of sight"])),
    "ils_d13": (F, _req([_h("ILS receiver", "localiser and glideslope")],
                        [_i("course deviation")], pre=["on an ILS approach"])),
    "pseudolite_d14": (F, _req([GNSS_MC], [_i("pseudolite pseudoranges", "m")],
                               [_r("pseudolite positions")], ["pseudolites deployed"])),
    "omega_d15": (N, _req([_h("VLF receiver", "10-14 kHz phase")],
                          notes="OMEGA was shut down in 1997. No transmitters exist; "
                                "this layer can never receive data.")),
    "decca_d16": (N, _req([_h("Decca receiver", "phase comparison")],
                          notes="Decca Navigator closed in 2000. No transmitters exist.")),
    "consol_d17": (N, _req([_h("LF/MF receiver", "beacon dot-dash count")],
                           notes="Consol/Sonne stations are closed. No transmitters exist.")),
    "rdf_d18": (S, _req([DF_ARRAY], [_i("bearings to transmitters", "degrees")],
                        [_r("transmitter locations")], ["two or more known transmitters"])),
    "aprs_d19": (F, _req([_h("144.39 MHz receiver", "APRS packets")], [_i("APRS packets")],
                         notes="Reports from other stations, who use GNSS themselves.")),
    "dopbeacon_d20": (F, _req([SDR], [_i("Doppler shift", "Hz")], [_r("beacon positions")])),
    "ecid_d21": (S, _req([_h("cellular modem", "cell ID, timing advance")],
                         [_i("serving cell and TA")], [_r("cell database")])),
    "otdoa_d22": (F, _req([_h("LTE modem with OTDOA", "time differences")],
                          [_i("RSTD measurements")], pre=["operator OTDOA support"])),
    "fiveg_d23": (F, _req([_h("5G NR modem with positioning", "ranges/angles")],
                          [_i("NR positioning measurements")], pre=["operator support"])),
    "wifirtt_d24": (F, _req([_h("WiFi radio with 802.11mc FTM", "round-trip time")],
                            [_i("RTT ranges", "m")], [_r("responder positions")])),
    "rfid_d25": (F, _req([_h("RFID/NFC reader", "tag reads")], [_i("tag IDs")],
                         [_r("tag positions")], ["tags installed"])),
    "vlc_d26": (F, _req([_h("photodiode receiver", "LED light codes")],
                        [_i("LED IDs and signal strength")], [_r("LED positions")])),

    # ---- Group E: optical and vision --------------------------------------
    "terrain_l5": (D, _req([DOWN_CAMERA], [_i("ground images")],
                           [_r("georeferenced imagery", INDIAN_MAPS)],
                           ["daylight, textured terrain"],
                           "To be rebuilt as landmark matching (spec item 9).")),
    "polsky_l25a": (S, _req([_h("polarisation camera", "sky polarisation pattern")],
                            [_i("polarisation images")], pre=["sky visible"],
                            notes="Heading, not position.")),
    "polwater_l25b": (P, _req([_h("underwater polarisation sensor", "light polarisation")],
                              [_i("polarisation")], notes="Underwater.")),
    "vslam_l31": (D, _req([CAMERA, IMU], [_i("camera frames"), _i("IMU")],
                          pre=["textured, lit surroundings"],
                          notes="Relative motion; drifts without loop closure.")),
    "vio_l32": (D, _req([CAMERA, IMU], [_i("camera frames"), _i("IMU")],
                        pre=["textured, lit surroundings"])),
    "lidar_l33": (S, _req([LIDAR, IMU], [_i("point clouds")])),
    "thermal_l38": (S, _req([THERMAL_CAM], [_i("thermal images")])),
    "hyperspec_l39": (S, _req([_h("hyperspectral camera", "12-16 spectral bands")],
                              [_i("hyperspectral images")])),
    "monarch_e10": (D, _req([SUN_SENSOR, CLOCK], [_i("sun azimuth")],
                            notes="Heading, not position.")),
    "owl_e11": (D, _req([CAMERA, IMU, BARO], [_i("passive sensor data")],
                        notes="Zero-emission mode: passive sensors only.")),
    "eagle_e12": (D, _req([CAMERA, IMU], [_i("high-resolution frames")])),
    "eagleeye_e13": (D, _req([_h("stereo camera pair", "stereo disparity", "", False)],
                             [_i("stereo frames")], pre=["textured ground"])),
    "enc_e14": (P, _req([_h("marine radar or sonar", "coastline / feature detection")],
                        [_i("detected features")],
                        [_r("electronic navigational charts", CHARTS)], notes="Maritime.")),
    "dted_e15": (D, _req([RANGEFINDER, BARO], [_i("terrain profile")],
                         [_r("digital elevation model", "Survey of India / national DEM")],
                         ["terrain with relief"],
                         "To be rebuilt as terrain matching (spec item 10).")),
    "lighthouse_e16": (P, _req([CAMERA], [_i("light flash timing")],
                               [_r("list of lights", CHARTS)], notes="Coastal.")),
    "buoy_e17": (P, _req([CAMERA], [_i("buoy detections")],
                         [_r("buoyage charts", CHARTS)], notes="Coastal.")),
    "threefix_e18": (D, _req([CAMERA, IMU], [_i("bearings to landmarks", "degrees")],
                             [_r("charted landmarks", INDIAN_MAPS)],
                             ["three landmarks with a good cut angle"],
                             "Same method as the clean landmark-chain layer (lmkchain_e23).")),
    "pilotage_e19": (P, _req([CAMERA], [_i("coastal feature detections")],
                             [_r("coastal pilot descriptions", CHARTS)])),
    "leadlight_e20": (P, _req([CAMERA], [_i("transit alignment")],
                              [_r("leading light positions", CHARTS)])),
    "sextant_e21": (S, _req([CAMERA, IMU], [_i("horizontal / vertical angles")],
                            [_r("charted landmarks", INDIAN_MAPS)])),
    "polynesian_e22": (P, _req([CAMERA, IMU], [_i("wave and sky observations")],
                               notes="Traditional ocean wayfinding cues; marine.")),

    # ---- Group F: acoustic -------------------------------------------------
    "acoustic_l10": (S, _req([MIC_ARRAY, CLOCK], [_i("acoustic arrival times")],
                             [_r("source positions")])),
    "sonar_l34": (P, _req([SONAR], [_i("sonar returns")], notes="Underwater / close range.")),
    "focsonar_l35": (P, _req([SONAR], [_i("beamformed returns")], notes="Underwater.")),
    "bathymetry_f04": (P, _req([SONAR, DEPTH], [_i("depth profile")],
                               [_r("bathymetric chart", CHARTS)], notes="Underwater.")),
    "seabed_f05": (P, _req([SONAR], [_i("depth and seabed type")],
                           [_r("seabed charts", CHARTS)], notes="Marine.")),
    "airsonar_f06": (F, _req([_h("ultrasonic transceivers", "time of flight")],
                             [_i("ultrasonic ranges")], [_r("beacon positions")],
                             ["indoor beacons installed"])),

    # ---- Group G: gravity --------------------------------------------------
    "gravgrad_l28a": (L, _req([_h("gravity gradiometer", "gravity gradient tensor")],
                              [_i("gravity gradients", "Eotvos")],
                              [_r("gravity gradient map")])),
    "gravimeter_l28b": (L, _req([_h("quantum gravimeter", "gravity magnitude")],
                                [_i("gravity", "mGal")], [_r("gravity anomaly map")],
                                notes="Demonstrated on ships; too heavy for small drones.")),

    # ---- Group H: chemical, seismic, flow ---------------------------------
    "chemgrad_l26": (P, _req([CHEM], [_i("chemical concentrations")],
                             [_r("chemical gradient map")], notes="Marine.")),
    "seismic_l36": (P, _req([_h("geophone", "ground vibration")], [_i("seismic signals")],
                            notes="Ground platforms.")),
    "hydrowake_l37": (P, _req([_h("flow sensors", "water velocity")], [_i("flow field")],
                              notes="Underwater.")),
    "tactile_l45": (P, _req([_h("hull pressure array", "pressure field")],
                            [_i("pressure readings")], notes="Underwater.")),
    "latline_l48": (P, _req([_h("pressure sensor array", "near-field flow")],
                            [_i("pressure readings")], notes="Underwater.")),
    "ionosphere_l49": (S, _req([GNSS_MC], [_i("dual-frequency TEC")],
                               [_r("ionospheric maps")])),
    "odometer_l60": (P, _req([_h("wheel encoder or pedometer", "distance travelled")],
                             [_i("wheel ticks or steps")], notes="Ground vehicles / people.")),
    "salmon_h08": (P, _req([MAG, CHEM], [_i("magnetic field"), _i("chemical gradient")],
                           [_r("magnetic map")], notes="Marine.")),
    "oceancurrent_h09": (P, _req([], [_i("estimated position")],
                                 [_r("ocean current atlas")],
                                 notes="Dead-reckoning correction for vessels.")),
    "tidaltiming_h10": (P, _req([DEPTH, CLOCK], [_i("water level series")],
                                [_r("tide tables", CHARTS)], notes="Coastal.")),
    "tidalstream_h11": (P, _req([], [_i("estimated position")],
                                [_r("tidal stream atlas", CHARTS)], notes="Coastal.")),
    "plume_h12": (S, _req([CHEM], [_i("concentration readings")],
                          notes="Tracks a plume to its source; not a position fix.")),
    "thermalmicro_h13": (S, _req([_h("temperature sensor", "air temperature cycle")],
                                 [_i("temperature series")],
                                 [_r("thermal climatology map")])),

    # ---- Group I: cosmic and atmospheric ----------------------------------
    "pulsar_l29b": (L, _req([_h("radio telescope receiver", "pulsar timing")],
                            [_i("pulse arrival times")], [_r("pulsar ephemerides")],
                            notes="Needs very large antennas; not drone hardware.")),
    "muon_l40": (L, _req([_h("muon detector", "cosmic-ray muon flux")],
                         [_i("muon counts")], [_r("muon reference stations")])),
    "schumann_l59": (L, _req([_h("ELF magnetic antenna", "7.83 Hz resonance")],
                             [_i("ELF spectrum")])),
    "infrasoundmap_i04": (S, _req([MIC_ARRAY], [_i("infrasound spectra")],
                                  [_r("infrasound map")])),
    "presspattern_i05": (D, _req([BARO], [_i("pressure series", "hPa")],
                                 [_r("regional pressure analysis")])),
    "sferics_i06": (S, _req([_h("VLF sferics receiver", "lightning pulse timing")],
                            [_i("sferic arrival times")],
                            pre=["lightning activity in the region"])),

    # ---- Group J: human and crowd ------------------------------------------
    "beacon_l20": (F, _req([_h("radio link to ground beacons", "beacon ranges")],
                           [_i("beacon messages")], [_r("beacon positions")],
                           ["ground beacons deployed"])),
    "spoofmap_l21": (U, _req([_h("data link", "crowd-sourced anomaly reports")],
                             [_i("spoofing reports")],
                             notes="Warns of spoofed areas; no position of its own.")),
    "radius_l22": (F, _req([_h("radio link to perimeter devices", "ranges")],
                           [_i("perimeter ranges")], pre=["devices placed around the area"])),

    # ---- Group K: systems intelligence ------------------------------------
    "antenna_l13": (U, _req([IMU], [_i("attitude")],
                            notes="Points antennas; produces heading, not position.")),
    "cascade_l14": (U, _req([], [_i("other layers' health")],
                            notes="Monitors failure cascades; no position.")),
    "swarmrel_l15": (F, _req([UWB], [_i("peer ranges")], pre=["other drones in range"],
                             notes="To be rebuilt for swarm ranging (spec item 11).")),
    "rfanomaly_l16": (U, _req([SDR], [_i("RF spectrum")],
                              notes="Early spoof warning; no position.")),
    "tern_k05": (U, _req([], [_i("other layers' readings")],
                         notes="Cross-layer agreement monitor; no position.")),
    "wolf_k06": (F, _req([_h("inter-drone data link", "shared estimates")],
                         [_i("peer positions")], pre=["other drones in the pack"])),
    "terrainfp_k07": (D, _req([MAG, BARO], [_i("magnetic, pressure and RF samples")],
                              [_r("fingerprint map recorded beforehand")])),
    "predtower_k08": (S, _req([_h("cellular modem", "tower RSSI")], [_i("tower RSSI")],
                              [_r("cell tower database")])),
    "dirtower_k09": (S, _req([_h("cellular modem", "tower measurements")],
                             [_i("tower measurements")], [_r("cell tower database")])),
    "circumfx_k10": (U, _req([], [_i("ranges from other layers")],
                             notes="Intersects range circles supplied by other layers.")),
    "univbeacon_k11": (F, _req([SDR], [_i("beacon readings")], [_r("beacon positions")],
                               ["beacons deployed"])),
    "rffingerprint_k12": (S, _req([SDR], [_i("RF spectrum")],
                                  [_r("RF fingerprint survey")])),

    # ---- Group Q: quantum ---------------------------------------------------
    "qrange_q01": (L, _req([_h("entangled photon source and detectors",
                               "quantum-secured ranging")],
                           [_i("photon coincidence timing")],
                           pre=["cooperating quantum ground stations"])),
    "qsense_q02": (L, _req([_h("networked quantum sensors", "entangled field estimation")],
                           [_i("sensor phases")])),
    "qclocknet_q03": (L, _req([_h("entangled clock network", "synchronisation")],
                              [_i("clock comparisons")])),
    "atomgyro_q04": (L, _req([_h("atom-interferometer gyroscope", "rotation")],
                             [_i("rotation rate")])),
    "qsqueeze_q05": (L, _req([_h("squeezed-light interferometer", "displacement")],
                             [_i("interferometer phase")])),
    "qradar_q06": (L, _req([_h("quantum illumination radar", "target detection")],
                           [_i("radar returns")])),
    "qsecpos_q07": (L, _req([_h("QKD link", "authenticated position exchange")],
                            [_i("peer positions over QKD")])),
    "qfusion_q08": (U, _req([], [_i("other layers' readings")],
                            notes="Fusion support; no sensor of its own.")),
}

# Operating class for the layers that declare REQUIRES on their own class.
DECLARED_CLASS: Dict[str, str] = {
    "gps_l1": D, "navic_l2": D, "cmddr_b12": D, "lmkchain_e23": D,
    "mapclick_b13": D,
}


def catalogue_requirement(layer_id: str) -> Optional[SensorRequirement]:
    entry = CATALOG.get(layer_id)
    return entry[1] if entry else None


def operating_class(layer_id: str) -> Optional[str]:
    if layer_id in DECLARED_CLASS:
        return DECLARED_CLASS[layer_id]
    entry = CATALOG.get(layer_id)
    return entry[0] if entry else None
