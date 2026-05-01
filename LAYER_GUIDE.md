# UPIN Layer Guide — What Each Layer Does

Plain-English reference for every layer and module in UPIN.
Each entry explains what it does, how it works, and gives a real example.

Run `python generate_index.py` for the technical index with line numbers.

---

## Group A — Satellite & Celestial

### Layer 1: GPS (gps_l1)
**What it does:** Standard GPS positioning from US satellite constellation.
**How:** Receives signals from 31 satellites at 20,200km altitude. Measures signal travel time → distance to each satellite. 4+ satellites → trilaterate your position.
**Example:** Your phone getting a GPS fix — accuracy ~3-5m outdoors.
**File:** `layers/satellite/layers.py`

### Layer 2: NavIC (navic_l2)
**What it does:** Indian regional satellite navigation — sovereign signal not controlled by foreign nations.
**How:** 7 satellites (3 geostationary + 4 geosynchronous) over Indian Ocean. Higher accuracy over India (~1m) because satellites are directly overhead.
**Example:** Indian military using NavIC instead of GPS so that the US can't switch it off during conflict.
**File:** `layers/satellite/layers.py`

### Layer 19: LEO Authenticated (leo_l19)
**What it does:** Low Earth Orbit satellite signals that are cryptographically authenticated — impossible to spoof.
**How:** LEO satellites at 1,200km (vs GPS at 20,200km) produce 1000× stronger signals. Each signal is digitally signed so you can verify it's real, not from a ground-based spoofer.
**Example:** Xona Pulsar constellation — military-grade GPS alternative that a jammer can't fake.
**File:** `layers/satellite/layers.py`

### Layer 29: X-Ray Pulsar Navigation (xnav_l29)
**What it does:** Navigate using millisecond pulsars — natural lighthouses in space that are impossible to jam or spoof.
**How:** Pulsars emit X-ray pulses with atomic-clock precision. Measure timing differences between pulsars → compute your position in the solar system. No ground infrastructure needed.
**Example:** Deep space navigation for spacecraft. On Earth: backup positioning that works even if every satellite is destroyed.
**File:** `layers/satellite/layers.py`

### Layer 46: Stellar Constellation (stellar_l46)
**What it does:** Determine position from star patterns — like ancient sailors but with modern cameras.
**How:** Camera identifies star patterns, matches against star catalogue, computes your latitude from star altitude angles and longitude from star hour angles.
**Example:** Night navigation when GPS is jammed — look up, identify Polaris, its altitude = your latitude.
**File:** `layers/satellite/layers.py`

### GLONASS (glonass_a07), Galileo (galileo_a08), BeiDou (beidou_a09), QZSS (qzss_a10)
**What they do:** Russian, European, Chinese, and Japanese satellite navigation systems. Same principle as GPS but independent constellations.
**Example:** If GPS is jammed, switch to Galileo or BeiDou — different satellites, different frequencies, harder to jam all simultaneously.
**File:** `layers/satellite/missing_constellations.py`

---

## Group B — Inertial & Timing

### Layer 3: INS Dead Reckoning (ins_l3)
**What it does:** Track position using accelerometer + gyroscope — no external signals needed.
**How:** Measure acceleration in 3 axes, double-integrate to get position change. Gyroscope tracks rotation. Completely self-contained — works underground, underwater, in a Faraday cage.
**Example:** You're walking in a tunnel with no GPS. The accelerometer counts your steps and direction → estimates position. Drifts ~1% of distance travelled.
**File:** `layers/inertial/layers.py`

### Layer 11: Barometric Altitude (baro_l11)
**What it does:** Measure altitude from air pressure — no satellites needed.
**How:** Air pressure drops ~12 Pa per metre of altitude. A barometer measures this pressure change and converts to altitude. Can detect floor changes in buildings (~0.12 hPa per floor).
**Example:** Your phone's barometer knows you're on the 3rd floor of a building, even without GPS.
**File:** `layers/inertial/layers.py`

### Layer 12: Doppler Velocity (doppler_l12)
**What it does:** Measure your speed by bouncing radar off the ground.
**How:** Transmit a radar signal downward. The reflected signal shifts in frequency proportional to your speed (Doppler effect). No GPS needed.
**Example:** A drone measuring its ground speed by radar — works in complete GPS denial.
**File:** `layers/inertial/layers.py`

### Layer 27: Quantum Atomic Clock (qclock_l27)
**What it does:** Ultra-precise timing for position computation — drift of only 1 second per billion years.
**How:** Uses quantum effects in trapped atoms to keep time. When your clock is this precise, you can compute range to any signal source from the signal's travel time.
**Example:** Military submarine maintaining precise time for weeks without GPS sync — enables position computation from any received signal.
**File:** `layers/inertial/layers.py`

---

## Group C — Magnetic & Quantum

### Layer 6: Magnetic Anomaly (magano_l6)
**What it does:** Navigate using Earth's magnetic field variations — each location has a unique magnetic fingerprint.
**How:** Measure magnetic field intensity, inclination, and declination. Compare against a magnetic map database. The best match = your position.
**Example:** Iron ore deposits create strong magnetic anomalies. If your magnetometer reads 48,500 nT and the map shows that value only near a specific mountain → you're near that mountain.
**File:** `layers/magnetic/layers.py`

### Layer 23: Magnetic Map Matching (magmap_l23)
**What it does:** Match measured magnetic field against a pre-loaded magnetic map — like terrain matching but with magnetic data.
**How:** Sweep a grid of candidate positions, compute expected magnetic field at each, find best match to measured field.
**Example:** Submarine navigating underwater by comparing measured magnetic field against a stored magnetic chart of the ocean floor.
**File:** `layers/magnetic/layers.py`

---

## Group D — RF & Terrestrial

### Layer 8: WiFi Military Navigation (wifi_l8)
**What it does:** Position from WiFi access point signal strengths — works indoors where GPS fails.
**How:** Measure RSSI from multiple WiFi APs with known positions. Stronger signal = closer to that AP. 3+ APs → trilaterate position.
**Example:** Navigating inside a building by measuring WiFi signal strength from 5 different routers — accuracy ~5-15m.
**File:** `layers/rf/layers.py`

### Layer 9: Cell Tower Triangulation (celltower_l9)
**What it does:** Position from cell tower signals — works everywhere with cellular coverage.
**How:** Measure signal strength from visible cell towers. Each tower has a known GPS position. Signal strength → estimated distance. 3+ towers → trilaterate.
**Example:** Your phone showing approximate location even with GPS off — it uses cell tower signals. Accuracy ~100-500m.
**File:** `layers/rf/layers.py`

### Layer 88: Universal Beacon (univbeacon_k11)
**What it does:** Triangulation from ANY signal source — LoRa, VHF, IR, acoustic, seismic. Same math, different physics.
**How:** Deploy beacons at known positions. Measure signal strength or time-of-arrival. The geometry is identical to cell tower triangulation — just swap the signal type.
**Example:** Drop 3 solar-powered LoRa beacons on mountain tops → instant positioning grid for 15km radius. Cost ~$20 per beacon.
**File:** `layers/rf/universal_beacon.py`

---

## Group E — Optical & Vision

### Layer 5: Terrain Matching (terrain_l5)
**What it does:** Match camera view of terrain against a stored database — know where you are by what you see.
**How:** Camera captures terrain features (rivers, roads, ridges). Compare against a database of known features. Best match = position.
**Example:** Cruise missile following a river valley — the camera sees a river bend that matches the database at coordinates 13.08, 80.27 → position confirmed.
**File:** `layers/optical/layers.py`

### Layer 31: Visual SLAM (vslam_l31)
**What it does:** Build a 3D map of your surroundings AND track your position within it — simultaneously.
**How:** Camera detects visual features (corners, edges). Track how features move between frames → compute camera motion. Build a map of feature positions. Loop closure corrects drift.
**Example:** A drone navigating inside a warehouse with no GPS — SLAM builds a map of shelves and walls while tracking the drone's position within that map.
**File:** `layers/optical/layers.py`

### Layer 32: Visual Odometry (vio_l32)
**What it does:** Measure how far you've moved by tracking visual features between camera frames.
**How:** Detect features in frame 1, find them again in frame 2, compute how they moved → compute how YOU moved. Fuse with IMU for robustness.
**Example:** Self-driving car estimating its speed and direction by watching road markings slide past the camera.
**File:** `layers/optical/layers.py`

### Layer 78: Eagle Eye Stereo Camera (eagleeye_e13)
**What it does:** Passive altitude measurement from stereo camera overlap — no radar emission, completely unjammable.
**How:** Two cameras at known separation. Measure image overlap ratio. altitude = d / ((1-k) × 2 × tan(θ)). Also uses known object sizing, horizon detection, and temporal stereo from motion.
**Example:** Drone at 100m altitude — cameras show 99% overlap. At 10m altitude — cameras show 80% overlap. The overlap ratio gives exact altitude without emitting any signal.
**File:** `layers/optical/eagle_eye.py`

### Layer 79: ENC Chart Matching (enc_e14)
**What it does:** Match observed features against nautical chart database — buoys, coastlines, depth soundings.
**How:** Sonar measures depth, camera sees buoys and landmarks. Compare against IHO S-57/S-100 electronic chart. Feature matches → position fix.
**Example:** Ship approaching port — sonar reads 15m depth, camera sees red buoy at bearing 045°. Chart shows that depth + buoy combination only at one location → position confirmed.
**File:** `layers/optical/eagle_eye.py`

### Layer 81: DTED Terrain Elevation (dted_e15)
**What it does:** Match altitude-above-ground against terrain elevation database.
**How:** Radar altimeter says "50m above ground". Barometer says "350m MSL". Therefore ground elevation = 300m. Search SRTM/DTED database for locations where elevation = 300m → position constraint.
**Example:** Aircraft flying over hills — the barometer/radar altitude combination constrains which hills you could be over.
**File:** `layers/optical/eagle_eye.py`

---

## Group F — Acoustic

### Layer 10: Passive Acoustic (acoustic_l10)
**What it does:** Position from underwater acoustic beacons — critical where all satellite signals fail.
**How:** 3+ acoustic beacons on the seafloor transmit pulses. Measure time-of-arrival at your position. Sound speed in water (1500 m/s) × time = distance. Trilaterate.
**Example:** Submarine positioning from seafloor transponder beacons — no satellite signals penetrate water.
**File:** `layers/acoustic/layers.py`

### Layer 80: Bathymetric Map Matching (bathymetry_f04)
**What it does:** Match sonar depth profile against seafloor topography database.
**How:** Collect sonar depth readings as you move → build a depth profile. Slide this profile against a GEBCO/ETOPO bathymetric grid. Best correlation = your position.
**Example:** Submarine recording seafloor depths: 120m, 95m, 110m, 130m. This profile matches the database at only one location along a specific undersea ridge.
**File:** `layers/acoustic/bathymetry.py`

---

## Group G — Gravity

### Layer 28a: Quantum Gravity Gradiometer (gravgrad_l28a)
**What it does:** Navigate by measuring tiny variations in gravitational pull — each location on Earth has a unique gravity signature.
**How:** Atom interferometry measures gravity gradient to extreme precision. Compare against a gravity map → position match. Detects underground tunnels and structures as a bonus.
**Example:** Gravity is slightly stronger over dense rock and weaker over voids. A gravity map matching system works underwater, underground, and is impossible to jam.
**File:** `layers/gravity/layers.py`

---

## Group H — Chemical, Seismic, Flow

### Layer 82: Ocean Current Drift (oceancurrent_h09)
**What it does:** Correct dead-reckoning drift by subtracting known ocean current vectors.
**How:** Look up ocean current speed and direction at your estimated position from a pre-loaded atlas. Compute how much the current has pushed you. Subtract from dead reckoning.
**Example:** Ship navigating in the Gulf Stream — current pushes you northeast at 2 m/s. Without correction, you'd drift 7.2km per hour off course.
**File:** `layers/chemical/nautical.py`

### Layer 83: Tidal Timing Position (tidaltiming_h10)
**What it does:** Determine coastal position from tidal patterns — each location has a unique tidal signature.
**How:** Record water depth over time. Extract tidal period, amplitude, and phase. Compare against tide table database. The phase offset and amplitude combination is unique per location.
**Example:** You measure a 1.8m tidal range with high tide at 14:32. The tide tables show this pattern matches only locations near the Strait of Hormuz → coarse position fix.
**File:** `layers/chemical/nautical.py`

---

## Group K — Systems Intelligence

### Layer 84: Terrain Fingerprint (terrainfp_k07)
**What it does:** Record a unique sensor fingerprint (magnetometer + barometer + cell towers + WiFi) at each position. During GPS denial, match current sensors against the stored map.
**How:** Every 10m with GPS, record: magnetic field = 45,200nT, pressure = 1013.2hPa, tower CID:247 = -82dBm, WiFi "Starbucks" = -65dBm. During denial, current readings match one stored fingerprint → position.
**Example:** You drive the same route daily. The system learns that at the intersection near your office, the magnetic field is 45,200nT and tower CID:247 is -82dBm. GPS goes down — sensors read those exact values → you're at that intersection.
**File:** `layers/systems/terrain_fp_layer.py`

### Layer 85: Predictive Tower Verification (predtower_k08)
**What it does:** Predict tower distances at T+3s, T+5s, T+5m, then verify with actual RSSI changes. Proves the motion model works.
**How:** "In 5 seconds, tower A should be 50m closer (RSSI should increase by 2dBm)." Wait 5 seconds. Check. Correct? → model validated. Repeat 1000 times → model proven → trusted in GPS denial.
**Example:** You're driving north at 60km/h. System predicts: "Tower to the north should get 2dBm stronger in 3 seconds." 3 seconds later, it did → prediction model confirmed.
**File:** `layers/systems/predictive_tower_layer.py`

### Layer 86: Directional Tower GDOP (dirtower_k09)
**What it does:** Select cell towers from all cardinal directions (N/S/E/W) for best geometric accuracy.
**How:** If all towers are to the south, you have good north-south accuracy but terrible east-west. By picking one tower from each direction, circle intersections are tight in ALL directions.
**Example:** 12 towers visible but 8 are to the south. System picks: 1 north, 1 south, 1 east, 1 west → GDOP score drops from 8.5 (poor) to 1.8 (excellent).
**File:** `layers/systems/directional_tower_layer.py`

### Layer 87: Circumference Intersection (circumfx_k10)
**What it does:** Find the exact point where multiple tower circle circumferences cross — pure geometry, no estimation.
**How:** Each GPS-calibrated tower circle passes through your position. Compute pairwise circle-circle intersection points. Cluster the intersection points → densest cluster center = your position.
**Example:** 7 towers, each with GPS-measured exact radius. Draw all 7 circles → 21 intersection pairs → all cluster at one point → that's you. Accuracy: <1m with good geometry.
**File:** `layers/systems/circumference_layer.py`

### Layer 88: Universal Beacon (univbeacon_k11)
**What it does:** Triangulation from ANY signal source — LoRa on mountain tops, FM radio towers, IR beacons, lightning strikes. Same math, different physics.
**How:** Deploy beacons at known positions. Measure distance (from signal strength, time-of-arrival, or bearing). 3+ beacons → trilaterate. Works with 16 signal types.
**Example:** Mountains with no cell coverage: drop 3 solar LoRa beacons on peaks → instant 15km positioning grid. Cost: $20 per beacon.
**File:** `layers/rf/universal_beacon.py`

---

## Group L — Biological

### Layer 69: Wolf Pack Coordination (wolf_k06)
**What it does:** Multi-unit geometric position refinement — like wolves narrowing prey position through pack coordination.
**How:** Multiple drones share position estimates. The geometric spread of the swarm reduces position uncertainty faster than any single unit.
**Example:** 4 drones at different positions each estimate a target location. Their combined geometric solution is 4× more accurate than any individual estimate.
**File:** `layers/biological/layers.py`

### Layer 72: Eagle Thermal Vision (eagle_e12)
**What it does:** High-acuity visual SLAM with thermal threat detection — eagle-inspired 8× human visual resolution.
**How:** Combines high-resolution visual tracking (for SLAM positioning) with thermal signature detection (for threats). Resolution scales with altitude.
**Example:** Drone at 200m altitude spots a vehicle by its thermal signature at 800m range while simultaneously tracking visual landmarks for position.
**File:** `layers/biological/layers.py`

---

## Core Modules (not layers — supporting systems)

### PUE — Position Uncertainty Envelope
**What it does:** Limits how far you COULD have moved since last GPS fix. Physics says: max_distance = speed × time + ½ × accel × time².
**Example:** GPS lost 30 seconds ago, you were going 60km/h → you can't be more than 500m from last fix. Any formula predicting beyond 500m is wrong.
**File:** `core/pue_constraint.py`

### Smart Constraint Engine
**What it does:** 4 layers that SHRINK the search area: physics max, speed decay, ZUPT stop detection, cell tower bound. Final radius = MIN of all four.
**Example:** PUE says 500m. But accelerometer shows you're decelerating → speed decay says 300m. Then you stopped → ZUPT freezes at 300m. Cell tower says within 200m → final radius: 200m.
**File:** `core/pue_constraint.py`

### Route DTW Learning
**What it does:** Record sensor fingerprints along a route with GPS. During GPS denial on that same route, Dynamic Time Warping matches current sensors to stored route.
**Example:** You drive home every day. The system records compass/mag/baro every 10m. Next time GPS is denied on that route, it recognises "this sensor pattern = the turn near the school" → position fix.
**File:** `core/route_dtw.py`

### Maneuver Recognition
**What it does:** Detect turns (45°, 90°, U-turn), stops, accelerations from IMU data. One confirmed 90° turn = exact heading fix.
**Example:** Gyro shows 1.5 rad/s for 1 second → system classifies: "90° right turn". During GPS denial, this eliminates heading drift completely at the moment of recognition.
**File:** `core/maneuver_recognition.py`

### Predictive Positioning Engine
**What it does:** Predict where you'll be in 5 seconds, then confirm with sensors. A validated predictor is trusted during GPS denial.
**Example:** "In 5 seconds you'll be 83m ahead at bearing 045°." 5 seconds later, tower RSSI confirms you moved 83m northeast → prediction model is PROVEN correct.
**File:** `core/predictive_positioning.py`

### Live Predictive Path
**What it does:** Dotted path extending T+3s, T+5s, T+30s, T+1m, T+5m, T+10m ahead. Updates every tick from live sensors. Follows roads (ground) or terrain (air).
**Example:** Cruising at 60km/h — path extends 10km along the road. Hit the brakes → path compresses to 90m. Turn right → path curves. Confidence fades from 0.99 (T+3s) to 0.14 (T+10m).
**File:** `core/live_predictive_path.py`

### Constraint-Fused Calibrator
**What it does:** Cell towers give a circle, PUE gives a radius, heading gives a cone. Intersection = tiny area. Every formula must predict INSIDE. Correct → reward. Wrong → penalise. Over time, formulas learn.
**Example:** After 200 ticks: Kalman is 99.5% inside (weight 2.0, trusted). INS is 35.5% inside (weight 0.1, not trusted). System learned which formulas work for THIS device.
**File:** `core/constraint_calibrator.py`

### GPS-Calibrated Tower Ranging
**What it does:** Use GPS-measured EXACT distances as circle radii (not RSSI guesses). All circles intersect at your GPS position — 0.5m error vs 500m with RSSI.
**Example:** GPS says you're exactly 1,247m from tower A → circle radius = 1,247m. During GPS denial, RSSI change tells you the distance changed → update radius → trilaterate.
**File:** `core/gps_calibrated_ranging.py`

### Map Matching + Terrain Following + Destination Routing
**What it does:** Snap position to nearest road (ground vehicles). Follow terrain contours at safe altitude (aircraft). Track progress toward destination with ETA.
**Example:** Ground: predicted path follows Anna Salai road, curves at intersection. Air: flight path rises over a hill at 50m AGL. Both: "35% done, 2.3km remaining, ETA 4 minutes."
**File:** `core/map_matching.py`

### Formula Agents
**What it does:** 10 agents per formula, each with different sensor parameter tweaks (accel scale, gyro scale, compass offset). Worst die, best reproduce. Per-formula calibration.
**Example:** Kalman formula runs with 10 agents. Agent #3 has compass_offset=+2.1° and accel_scale=0.95. It's consistently the most accurate → its parameters become the formula's calibration.
**File:** `core/formula_agents.py`

### Auto-Combo Discovery
**What it does:** Evolve weighted combinations of 2-3 formulas. Finds non-obvious high-performing combos.
**Example:** "70% Step+Compass + 30% MACD" outperforms both individually. No human would pick this combination — the system discovers it through evolution.
**File:** `core/auto_combo.py`

### Training Constraint (10m Leash)
**What it does:** During GPS recording, pull every formula's prediction to within 10m of GPS truth. Forces fast convergence.
**Example:** Without leash: formulas take 100 generations to reach 18m accuracy. With 10m leash: 50 generations to reach 3m accuracy — 2× faster, 6× better.
**File:** `core/training_constraint.py`

---

## Swarm Systems

### Drone Role Specialization
**What it does:** 8 drone roles with specific equipment loadouts and UPIN layer configs.
**Example:** Strike mission with 10 drones: 3 decoys (lens magnifiers to look bigger), 2 spotters (4K camera + laser rangefinder), 2 strike (payload + precision nav), 1 EW (jammer), 1 relay, 1 scout.
**File:** `swarm/drone_roles.py`

### Defensive Jammer Shield
**What it does:** Downward-pointing jammer creates electronic dome below the swarm. Enemy loses GPS/comms. UPIN drones unaffected because they don't need GPS.
**Example:** Swarm at 500m altitude activates DOME mode → everything below within 500m radius loses GPS, WiFi, cell. Enemy drone attacking from below goes blind. Your swarm keeps navigating on 83 layers.
**File:** `intelligence/defensive_jammer.py`

### Orca Tactics
**What it does:** 4 killer whale hunting strategies for drone swarms.
**Example — Wave Wash:** 4 drones synchronize jamming pulses → arrive at target simultaneously → 4× stronger than individual jamming (constructive interference).
**Example — Carousel:** 6 drones form a ring around a target. Each rotates position every 5 minutes so no drone exhausts battery. Target gets continuous pressure.
**Example — Pod Dialect:** Swarm encryption re-keys when a drone is captured. Captured drone's old key is useless — remaining swarm has new encryption.
**Example — Teaching:** New drone joins → receives all learned routes, sensor calibrations, threat intel from experienced drones. Immediately as smart as the swarm.
**File:** `swarm/nature_tactics/orca.py`

### Swarm Mesh OS
**What it does:** Central nervous system tying mesh positioning + roles + jammer + UPIN nav. Self-healing — if a drone is destroyed, mesh re-forms.
**Example:** Eagle-1 gets GPS fix → propagates absolute coordinates to all 6 drones through mesh ranges. Eagle-3 is destroyed → mesh automatically re-routes through remaining nodes.
**File:** `swarm/mesh_swarm_os.py`

---

## Detection & Security

### Anti-Spoof Detection
**What it does:** Catches fake GPS by cross-checking against 5 independent sources. Spoof score 0-100, above 40 = reject GPS.
**Example:** GPS signal suddenly jumps to -60dBm (real GPS is -130dBm) → SIGNAL_SPIKE alert. GPS says you teleported 100km in 1 second → TELEPORT alert. Score hits 45 → GPS REJECTED, fall back to UPIN layers.
**File:** `detection/anti_spoof.py`

### RF Field Monitor
**What it does:** Learns your normal RF environment, then detects any disturbance. States: LEARNING → NORMAL → ALERT → HOSTILE.
**Example:** Normal: 8 signals at -75dBm average. Suddenly: 0 signals → TOTAL_LOSS → state goes HOSTILE → system knows it's under active jamming → switch to sensor-only navigation.
**File:** `detection/anti_spoof.py`

### Signal Identifier
**What it does:** Classify unknown signals by frequency, modulation, power, timing. Hostile triggers defense. Opportunity feeds to beacon engine.
**Example:** Unknown signal at 9.5 GHz with chirp modulation → classified as "X-band fire control radar" → HOSTILE threat level CRITICAL. But also USABLE for positioning — enemy radar reveals their location.
**File:** `detection/signal_identifier.py`

### Consensus Validator
**What it does:** Multi-source position voting. GPS + cell + IMU + predictor vote. If 3 agree but 1 is wildly different → that 1 is wrong.
**Example:** GPS says Mumbai, cell tower says Chennai, IMU says Chennai, predictor says Chennai → 3/4 agree Chennai. GPS is spoofed → REJECT. Consensus position = Chennai.
**File:** `detection/anti_spoof.py`

---

## Vision

### RF-DETR Feature Extractor
**What it does:** Real-time object detection using Roboflow's RF-DETR model (Apache 2.0). Lazy import — UPIN works without it.
**Example:** Camera frame → RF-DETR detects: car at bearing 045°, bridge at bearing 090°, tank at bearing 180°. Each detection feeds SLAM, threat ID, and satellite image matching.
**File:** `vision/rf_detr_extractor.py`

### Visual Intelligence System
**What it does:** Unified system: ground object detection + satellite image matching + flight path verification + target tracking/homing + threat identification.
**Example:** Camera detects a bridge → matches map marker "Adyar Bridge" at (13.082, 80.272) → POSITION FIX confirmed. Simultaneously: tank detected at bearing 180° → THREAT CRITICAL → homing signal locked.
**File:** `vision/visual_intelligence.py`

---

*Run `python generate_index.py` for the technical index with exact line numbers.*
*This guide covers the architecture — the index covers the code.*
