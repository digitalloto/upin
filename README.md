# UPIN — Universal Positioning Intelligence Network

GPS-denied navigation built from many independent layers, each computing a position from a different physical principle, fused and cross-checked against each other.

Patent-pending. AIMCRS / Abheet Prem Manghnani.

## Honest status

This table is measured, not claimed. Every layer below was constructed with nothing attached and read three times; what it did is what is recorded.

| Status | Layers | Meaning |
|---|---:|---|
| **DECLINES** | 10 | Reports no fix when it has no input, and says what is missing. Honours the no-fabrication contract. |
| **PLACEHOLDER** | 13 | Returns the same fixed reading whenever nothing is connected. Not random, but not measured either. |
| **FABRICATES** | 116 | Invents a reading when nothing is connected, and invents a different one each time it is read. |

**10 of 139 layers** currently refuse to invent a position. **2 of 139** have declared what hardware and data they need.

The gap between those numbers and the total is the work tracked in [`FABRICATION_AUDIT.md`](FABRICATION_AUDIT.md), which explains what each fabricating layer does and what it would cost in flight.

> **Not flight-proven.** No claim of jamming resistance or field performance is made here. Layers that cannot yet produce a position say so, per layer, on their own page.

## Documents

| | |
|---|---|
| [`FABRICATION_AUDIT.md`](FABRICATION_AUDIT.md) | Every place the code invents a number, what it costs, and the staged plan to remove it |
| [`UPIN_MASTER.md`](UPIN_MASTER.md) | The full project document |
| [`QUANTUM.md`](QUANTUM.md) | Group Q hardware readiness and patent sequencing |
| [`LAYER_GUIDE.md`](LAYER_GUIDE.md) | Layer-by-layer narrative guide |
| [`LAYER_INDEX.md`](LAYER_INDEX.md) | Generated code index |

## The layers

### Group A — Satellite & Celestial (19 layers, 0 clean)

| # | Layer | ID | Status | Needs declared |
|---:|---|---|---|---|
| 1 | [GPS GNSS](docs/layers/gps_l1.md) | `gps_l1` | fabricates | no |
| 2 | [NavIC Indian Sovereign Signal](docs/layers/navic_l2.md) | `navic_l2` | fabricates | no |
| 19 | [LEO Authenticated Satellite Signals](docs/layers/leo_l19.md) | `leo_l19` | fabricates | no |
| 29 | [X-Ray Pulsar Navigation](docs/layers/xnav_l29.md) | `xnav_l29` | fabricates | no |
| 46 | [Stellar Constellation Pattern Navigation](docs/layers/stellar_l46.md) | `stellar_l46` | fabricates | no |
| 47 | [Diffuse Sky Brightness Gradient Navigation](docs/layers/skygrad_l47.md) | `skygrad_l47` | fabricates | no |
| 73 | [GLONASS](docs/layers/glonass_a07.md) | `glonass_a07` | fabricates | no |
| 74 | [Galileo](docs/layers/galileo_a08.md) | `galileo_a08` | fabricates | no |
| 75 | [BeiDou](docs/layers/beidou_a09.md) | `beidou_a09` | fabricates | no |
| 76 | [QZSS](docs/layers/qzss_a10.md) | `qzss_a10` | fabricates | no |
| 97 | [Lunar Distance Longitude](docs/layers/lunardist_a11.md) | `lunardist_a11` | fabricates | no |
| 98 | [Marine Chronometer Longitude](docs/layers/chronometer_a12.md) | `chronometer_a12` | fabricates | no |
| 105 | [GAGAN Indian SBAS](docs/layers/gagan_a13.md) | `gagan_a13` | fabricates | no |
| 113 | [LEO Satellite Doppler (Iridium)](docs/layers/iriddop_a14.md) | `iriddop_a14` | fabricates | no |
| 121 | [Polaris Altitude Latitude](docs/layers/polaris_a15.md) | `polaris_a15` | fabricates | no |
| 122 | [Solar Noon Sight Latitude](docs/layers/noonsight_a16.md) | `noonsight_a16` | fabricates | no |
| 123 | [Sun Azimuth Compass](docs/layers/sunazimuth_a17.md) | `sunazimuth_a17` | fabricates | no |
| 124 | [Planet Sighting Navigation](docs/layers/planets_a18.md) | `planets_a18` | fabricates | no |
| 125 | [Atmospheric Refraction Correction](docs/layers/refraction_a19.md) | `refraction_a19` | fabricates | no |

### Group B — Inertial & Timing (12 layers, 1 clean)

| # | Layer | ID | Status | Needs declared |
|---:|---|---|---|---|
| 3 | [INS Dead Reckoning](docs/layers/ins_l3.md) | `ins_l3` | fabricates | no |
| 11 | [Barometric Altitude](docs/layers/baro_l11.md) | `baro_l11` | fabricates | no |
| 12 | [Doppler Velocity Radar](docs/layers/doppler_l12.md) | `doppler_l12` | fabricates | no |
| 18 | [Laser Doppler Velocity Sensor](docs/layers/laserdop_l18.md) | `laserdop_l18` | fabricates | no |
| 27 | [Quantum Optical Atomic Clock](docs/layers/qclock_l27.md) | `qclock_l27` | placeholder | no |
| 43 | [Optic Flow Velocity Sensing](docs/layers/opticflow_l43.md) | `opticflow_l43` | fabricates | no |
| 57 | [NMR Gyroscope](docs/layers/nmrgyro_l57.md) | `nmrgyro_l57` | fabricates | no |
| 58 | [SERF Atomic Spin Gyroscope](docs/layers/serfgyro_l58.md) | `serfgyro_l58` | fabricates | no |
| 63 | [Radar Altimeter](docs/layers/radaralt_b09.md) | `radaralt_b09` | fabricates | no |
| 64 | [Depth Pressure Sensor](docs/layers/depthpres_b10.md) | `depthpres_b10` | fabricates | no |
| 126 | [Visual Horizon Reference](docs/layers/vhorizon_b11.md) | `vhorizon_b11` | fabricates | no |
| 143 | [Command-Based Dead Reckoning](docs/layers/cmddr_b12.md) | `cmddr_b12` | clean | yes |

### Group C — Magnetic & Quantum (9 layers, 0 clean)

| # | Layer | ID | Status | Needs declared |
|---:|---|---|---|---|
| 6 | [Magnetic Anomaly Navigation](docs/layers/magano_l6.md) | `magano_l6` | fabricates | no |
| 17 | [Dual Mechanism Quantum Magnetometer](docs/layers/dualqmag_l17.md) | `dualqmag_l17` | fabricates | no |
| 23 | [Magnetic Signature Map Matching](docs/layers/magmap_l23.md) | `magmap_l23` | fabricates | no |
| 24 | [Electromagnetic Induction Navigation](docs/layers/eminduct_l24.md) | `eminduct_l24` | fabricates | no |
| 30 | [NV Diamond Magnetometer](docs/layers/nvdiamond_l30.md) | `nvdiamond_l30` | fabricates | no |
| 44 | [Bicoordinate Geo-Chemical-Magnetic](docs/layers/bicoord_l44.md) | `bicoord_l44` | fabricates | no |
| 65 | [Electric Field Gradient Sensing](docs/layers/efield_c07.md) | `efield_c07` | fabricates | no |
| 127 | [Quantum Compass (Cold Atom)](docs/layers/qcompass_c08.md) | `qcompass_c08` | fabricates | no |
| 128 | [Magnetic Indoor Fingerprint](docs/layers/magindoor_c09.md) | `magindoor_c09` | fabricates | no |

### Group D — RF & Terrestrial (26 layers, 0 clean)

| # | Layer | ID | Status | Needs declared |
|---:|---|---|---|---|
| 7 | [Ground Based Emitters](docs/layers/groundrf_l7.md) | `groundrf_l7` | fabricates | no |
| 8 | [WiFi Military Navigation](docs/layers/wifi_l8.md) | `wifi_l8` | fabricates | no |
| 9 | [Cell Tower Triangulation (Hostile)](docs/layers/celltower_l9.md) | `celltower_l9` | fabricates | no |
| 41 | [eLORAN Terrestrial Navigation](docs/layers/eloran_l41.md) | `eloran_l41` | fabricates | no |
| 42 | [Commercial SOOP](docs/layers/soop_l42.md) | `soop_l42` | fabricates | no |
| 61 | [UWB Precision Positioning](docs/layers/uwb_d06.md) | `uwb_d06` | fabricates | no |
| 62 | [LoRaWAN Node Triangulation](docs/layers/lora_d07.md) | `lora_d07` | fabricates | no |
| 77 | [Bluetooth 5.1 AoA](docs/layers/bluetooth_d08.md) | `bluetooth_d08` | fabricates | no |
| 89 | [AIS Cooperative Maritime](docs/layers/ais_d09.md) | `ais_d09` | fabricates | no |
| 101 | [ADS-B Cooperative Aviation](docs/layers/adsb_d10.md) | `adsb_d10` | fabricates | no |
| 102 | [TACAN Tactical Air Navigation](docs/layers/tacan_d11.md) | `tacan_d11` | fabricates | no |
| 103 | [VOR/DME Civil Aviation](docs/layers/vordme_d12.md) | `vordme_d12` | fabricates | no |
| 104 | [ILS Precision Approach](docs/layers/ils_d13.md) | `ils_d13` | fabricates | no |
| 106 | [Pseudolite Ground GNSS](docs/layers/pseudolite_d14.md) | `pseudolite_d14` | fabricates | no |
| 107 | [OMEGA VLF Navigation](docs/layers/omega_d15.md) | `omega_d15` | fabricates | no |
| 108 | [Decca Navigator](docs/layers/decca_d16.md) | `decca_d16` | fabricates | no |
| 109 | [Consol/Sonne Beacon](docs/layers/consol_d17.md) | `consol_d17` | fabricates | no |
| 110 | [Radio Direction Finding (RDF)](docs/layers/rdf_d18.md) | `rdf_d18` | fabricates | no |
| 111 | [APRS Amateur Radio Position](docs/layers/aprs_d19.md) | `aprs_d19` | fabricates | no |
| 112 | [Doppler Beacon Localisation](docs/layers/dopbeacon_d20.md) | `dopbeacon_d20` | fabricates | no |
| 114 | [Enhanced Cell ID (E-CID)](docs/layers/ecid_d21.md) | `ecid_d21` | fabricates | no |
| 115 | [OTDOA LTE Positioning](docs/layers/otdoa_d22.md) | `otdoa_d22` | fabricates | no |
| 116 | [5G NR Positioning](docs/layers/fiveg_d23.md) | `fiveg_d23` | fabricates | no |
| 117 | [WiFi RTT (802.11mc)](docs/layers/wifirtt_d24.md) | `wifirtt_d24` | fabricates | no |
| 118 | [RFID/NFC Localisation](docs/layers/rfid_d25.md) | `rfid_d25` | fabricates | no |
| 119 | [VLC/Li-Fi Positioning](docs/layers/vlc_d26.md) | `vlc_d26` | fabricates | no |

### Group E — Optical & Vision (23 layers, 1 clean)

| # | Layer | ID | Status | Needs declared |
|---:|---|---|---|---|
| 4 | [Star Tracking (Daytime Capable)](docs/layers/startrack_l4.md) | `startrack_l4` | fabricates | no |
| 5 | [Terrain Matching Vision](docs/layers/terrain_l5.md) | `terrain_l5` | fabricates | no |
| 25 | [Polarised Sky Navigation](docs/layers/polsky_l25a.md) | `polsky_l25a` | fabricates | no |
| 25 | [Underwater Polarised Light Navigation](docs/layers/polwater_l25b.md) | `polwater_l25b` | fabricates | no |
| 31 | [Visual SLAM](docs/layers/vslam_l31.md) | `vslam_l31` | fabricates | no |
| 32 | [Visual Odometry + IMU](docs/layers/vio_l32.md) | `vio_l32` | fabricates | no |
| 33 | [LiDAR Enhanced SLAM](docs/layers/lidar_l33.md) | `lidar_l33` | fabricates | no |
| 38 | [Thermal Infrared Navigation](docs/layers/thermal_l38.md) | `thermal_l38` | fabricates | no |
| 39 | [Hyperspectral Polarised Vision](docs/layers/hyperspec_l39.md) | `hyperspec_l39` | placeholder | no |
| 66 | [Monarch Sun Compass](docs/layers/monarch_e10.md) | `monarch_e10` | fabricates | no |
| 70 | [Owl Silent Approach](docs/layers/owl_e11.md) | `owl_e11` | fabricates | no |
| 72 | [Eagle Thermal Vision](docs/layers/eagle_e12.md) | `eagle_e12` | fabricates | no |
| 78 | [Eagle Eye Stereo Altitude](docs/layers/eagleeye_e13.md) | `eagleeye_e13` | fabricates | no |
| 79 | [ENC Chart Matching](docs/layers/enc_e14.md) | `enc_e14` | fabricates | no |
| 81 | [DTED Terrain Elevation](docs/layers/dted_e15.md) | `dted_e15` | fabricates | no |
| 90 | [Lighthouse Signature ID](docs/layers/lighthouse_e16.md) | `lighthouse_e16` | fabricates | no |
| 91 | [Buoy/Sea Mark Recognition (IALA)](docs/layers/buoy_e17.md) | `buoy_e17` | fabricates | no |
| 92 | [Three-Point Fix (Cocked Hat)](docs/layers/threefix_e18.md) | `threefix_e18` | fabricates | no |
| 93 | [Coastal Visual Pilotage](docs/layers/pilotage_e19.md) | `pilotage_e19` | fabricates | no |
| 94 | [Leading Lights / Transit Bearings](docs/layers/leadlight_e20.md) | `leadlight_e20` | fabricates | no |
| 95 | [Sextant Angle Fix (HSA/VSA)](docs/layers/sextant_e21.md) | `sextant_e21` | fabricates | no |
| 100 | [Polynesian Wayfinding (Wave/Cloud/Bird)](docs/layers/polynesian_e22.md) | `polynesian_e22` | fabricates | no |
| 144 | [Landmark Chain Navigation](docs/layers/lmkchain_e23.md) | `lmkchain_e23` | clean | yes |

### Group F — Acoustic (6 layers, 0 clean)

| # | Layer | ID | Status | Needs declared |
|---:|---|---|---|---|
| 10 | [Passive Acoustic Triangulation](docs/layers/acoustic_l10.md) | `acoustic_l10` | fabricates | no |
| 34 | [Active Sonar Mapping](docs/layers/sonar_l34.md) | `sonar_l34` | fabricates | no |
| 35 | [Focused Sonar Beam Imaging](docs/layers/focsonar_l35.md) | `focsonar_l35` | placeholder | no |
| 80 | [Bathymetric Map Matching](docs/layers/bathymetry_f04.md) | `bathymetry_f04` | fabricates | no |
| 96 | [Seabed Sample Matching](docs/layers/seabed_f05.md) | `seabed_f05` | fabricates | no |
| 134 | [Ultrasonic Air Ranging (Cricket)](docs/layers/airsonar_f06.md) | `airsonar_f06` | fabricates | no |

### Group G — Gravity (2 layers, 0 clean)

| # | Layer | ID | Status | Needs declared |
|---:|---|---|---|---|
| 28 | [Quantum Gravity Gradiometer](docs/layers/gravgrad_l28a.md) | `gravgrad_l28a` | fabricates | no |
| 28 | [Quantum Dual Gravimeter](docs/layers/gravimeter_l28b.md) | `gravimeter_l28b` | fabricates | no |

### Group H — Chemical, Seismic & Flow (13 layers, 0 clean)

| # | Layer | ID | Status | Needs declared |
|---:|---|---|---|---|
| 26 | [Chemical Gradient Navigation](docs/layers/chemgrad_l26.md) | `chemgrad_l26` | fabricates | no |
| 36 | [Seismic Infrasound Sensing](docs/layers/seismic_l36.md) | `seismic_l36` | placeholder | no |
| 37 | [Hydrodynamic Wake Detection](docs/layers/hydrowake_l37.md) | `hydrowake_l37` | placeholder | no |
| 45 | [Distributed Tactile Pressure Array](docs/layers/tactile_l45.md) | `tactile_l45` | placeholder | no |
| 48 | [Lateral Line Pressure Mapping](docs/layers/latline_l48.md) | `latline_l48` | placeholder | no |
| 49 | [Ionospheric Electron Density](docs/layers/ionosphere_l49.md) | `ionosphere_l49` | fabricates | no |
| 60 | [Locomotion Odometer](docs/layers/odometer_l60.md) | `odometer_l60` | fabricates | no |
| 71 | [Salmon Magnetic+Chemical Homing](docs/layers/salmon_h08.md) | `salmon_h08` | fabricates | no |
| 82 | [Ocean Current Drift Correction](docs/layers/oceancurrent_h09.md) | `oceancurrent_h09` | fabricates | no |
| 83 | [Tidal Timing Position](docs/layers/tidaltiming_h10.md) | `tidaltiming_h10` | fabricates | no |
| 99 | [Tidal Stream Atlas](docs/layers/tidalstream_h11.md) | `tidalstream_h11` | placeholder | no |
| 132 | [Chemical Plume Source Tracking](docs/layers/plume_h12.md) | `plume_h12` | fabricates | no |
| 133 | [Thermal Microclimate Fingerprint](docs/layers/thermalmicro_h13.md) | `thermalmicro_h13` | fabricates | no |

### Group I — Cosmic & Atmospheric (6 layers, 0 clean)

| # | Layer | ID | Status | Needs declared |
|---:|---|---|---|---|
| 29 | [Pulsar Extended Navigation](docs/layers/pulsar_l29b.md) | `pulsar_l29b` | fabricates | no |
| 40 | [Cosmic Ray Muon Navigation](docs/layers/muon_l40.md) | `muon_l40` | fabricates | no |
| 59 | [Schumann Resonance ELF Navigation](docs/layers/schumann_l59.md) | `schumann_l59` | fabricates | no |
| 129 | [Infrasound Map Matching](docs/layers/infrasoundmap_i04.md) | `infrasoundmap_i04` | fabricates | no |
| 130 | [Atmospheric Pressure Pattern](docs/layers/presspattern_i05.md) | `presspattern_i05` | fabricates | no |
| 131 | [Lightning Sferics Geolocation](docs/layers/sferics_i06.md) | `sferics_i06` | fabricates | no |

### Group J — Human & Crowd (3 layers, 0 clean)

| # | Layer | ID | Status | Needs declared |
|---:|---|---|---|---|
| 20 | [Human Ground Beacon Network](docs/layers/beacon_l20.md) | `beacon_l20` | fabricates | no |
| 21 | [Crowdsourced GPS Spoofing Map](docs/layers/spoofmap_l21.md) | `spoofmap_l21` | placeholder | no |
| 22 | [Radius Containment and Convergence Lock](docs/layers/radius_l22.md) | `radius_l22` | fabricates | no |

### Group K — Systems Intelligence (12 layers, 0 clean)

| # | Layer | ID | Status | Needs declared |
|---:|---|---|---|---|
| 13 | [Antenna Stabilisation](docs/layers/antenna_l13.md) | `antenna_l13` | placeholder | no |
| 14 | [Cascade Prevention Monitor](docs/layers/cascade_l14.md) | `cascade_l14` | placeholder | no |
| 15 | [Swarm Relative Positioning](docs/layers/swarmrel_l15.md) | `swarmrel_l15` | fabricates | no |
| 16 | [RF Signal Anomaly Detection](docs/layers/rfanomaly_l16.md) | `rfanomaly_l16` | placeholder | no |
| 67 | [Arctic Tern Multi-Cue Monitor](docs/layers/tern_k05.md) | `tern_k05` | fabricates | no |
| 69 | [Wolf Pack Coordination](docs/layers/wolf_k06.md) | `wolf_k06` | fabricates | no |
| 84 | [Terrain Fingerprint (mag+baro+cell+wifi)](docs/layers/terrainfp_k07.md) | `terrainfp_k07` | placeholder | no |
| 85 | [Predictive Tower Verification](docs/layers/predtower_k08.md) | `predtower_k08` | fabricates | no |
| 86 | [Directional Tower GDOP](docs/layers/dirtower_k09.md) | `dirtower_k09` | fabricates | no |
| 87 | [Circumference Intersection](docs/layers/circumfx_k10.md) | `circumfx_k10` | fabricates | no |
| 88 | [Universal Beacon Positioning](docs/layers/univbeacon_k11.md) | `univbeacon_k11` | fabricates | no |
| 120 | [RF Environment Fingerprint](docs/layers/rffingerprint_k12.md) | `rffingerprint_k12` | fabricates | no |

### Group Q — Quantum Navigation (8 layers, 8 clean)

| # | Layer | ID | Status | Needs declared |
|---:|---|---|---|---|
| 135 | [Entangled Photon Ranging](docs/layers/qrange_q01.md) | `qrange_q01` | clean | no |
| 136 | [Distributed Quantum Sensing Network](docs/layers/qsense_q02.md) | `qsense_q02` | clean | no |
| 137 | [Quantum Clock Network](docs/layers/qclocknet_q03.md) | `qclocknet_q03` | clean | no |
| 138 | [Atom Interferometer Gyroscope](docs/layers/atomgyro_q04.md) | `atomgyro_q04` | clean | no |
| 139 | [Squeezed Light Interferometry](docs/layers/qsqueeze_q05.md) | `qsqueeze_q05` | clean | no |
| 140 | [Quantum Illumination Radar](docs/layers/qradar_q06.md) | `qradar_q06` | clean | no |
| 141 | [Quantum-Secured Position Exchange](docs/layers/qsecpos_q07.md) | `qsecpos_q07` | clean | no |
| 142 | [Quantum-Enhanced Fusion](docs/layers/qfusion_q08.md) | `qfusion_q08` | clean | no |

---

*The layer table and every page under `docs/layers/` are generated by `tools/generate_layer_docs.py`. Re-run it after changing any layer.*
