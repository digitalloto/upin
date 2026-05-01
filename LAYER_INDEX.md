# UPIN Codebase Index

Auto-generated reference for the entire UPIN codebase.
Run `python generate_index.py` to regenerate.

## Summary

- **Navigation Layers**: 86
- **Core Modules**: 123 classes
- **Swarm Modules**: 56 classes
- **Detection Modules**: 11 classes
- **Agent Modules**: 31 classes
- **Vision Modules**: 15 classes
- **Total Classes**: 523
- **Total Python Files**: 133
- **Total Lines of Code**: 43,057

---
## Navigation Layers

| # | Layer ID | Class | Description | File | Lines |
|---|----------|-------|-------------|------|-------|
| 1 | `gps_l1` | `GPSLayer` | Layer 1 — GPS GNSS. | `upin/layers/satellite/layers.py` | 94-238 |
| 2 | `navic_l2` | `NavICLayer` | Layer 2 — NavIC Indian Sovereign Signal [NOVEL]. | `upin/layers/satellite/layers.py` | 241-346 |
| 3 | `ins_l3` | `INSDeadReckoningLayer` | Layer 3 — INS Dead Reckoning. | `upin/layers/inertial/layers.py` | 32-216 |
| 4 | `startrack_l4` | `StarTrackingLayer` | Layer 4 — Star Tracking with Daytime Capability. | `upin/layers/optical/layers.py` | 30-134 |
| 5 | `terrain_l5` | `TerrainMatchingLayer` | Layer 5 — Terrain Matching Vision. | `upin/layers/optical/layers.py` | 141-240 |
| 6 | `magano_l6` | `MagneticAnomalyLayer` | Layer 6 — Magnetic Anomaly Navigation. | `upin/layers/magnetic/layers.py` | 65-138 |
| 7 | `groundrf_l7` | `GroundEmitterLayer` | Layer 7 — Ground Based Emitters. | `upin/layers/rf/layers.py` | 124-206 |
| 8 | `wifi_l8` | `WiFiMilitaryNavLayer` | Layer 8 — WiFi Signal Mapping as Military Navigation [NOVEL]... | `upin/layers/rf/layers.py` | 213-340 |
| 9 | `celltower_l9` | `CellTowerHostileLayer` | Layer 9 — Cell Tower Triangulation in Hostile Territory [NOV... | `upin/layers/rf/layers.py` | 347-430 |
| 10 | `acoustic_l10` | `PassiveAcousticLayer` | Layer 10 — Passive Acoustic Triangulation. | `upin/layers/acoustic/layers.py` | 21-109 |
| 11 | `baro_l11` | `BarometricAltitudeLayer` | Layer 11 — Barometric Altitude. | `upin/layers/inertial/layers.py` | 219-304 |
| 12 | `doppler_l12` | `DopplerVelocityLayer` | Layer 12 — Doppler Velocity Radar. | `upin/layers/inertial/layers.py` | 307-382 |
| 13 | `antenna_l13` | `AntennaStabilisationLayer` | Layer 13 — Antenna Stabilisation Layer [NOVEL]. | `upin/layers/systems/layers.py` | 23-110 |
| 14 | `cascade_l14` | `CascadePreventionLayer` | Layer 14 — Cascade Prevention Monitor [NOVEL]. | `upin/layers/systems/layers.py` | 113-178 |
| 15 | `swarmrel_l15` | `SwarmRelativePositionLayer` | Layer 15 — Swarm Relative Positioning [NOVEL]. | `upin/layers/systems/layers.py` | 181-288 |
| 16 | `rfanomaly_l16` | `RFAnomalyDetectionLayer` | Layer 16 — RF Signal Anomaly Detection [NOVEL]. | `upin/layers/systems/layers.py` | 291-351 |
| 17 | `dualqmag_l17` | `DualQuantumMagnetometerLayer` | Layer 17 — Dual Mechanism Quantum Magnetometer [NOVEL, UNDER... | `upin/layers/magnetic/layers.py` | 145-256 |
| 18 | `laserdop_l18` | `LaserDopplerLayer` | Layer 18 — Laser Doppler Velocity Sensor [NOVEL]. | `upin/layers/inertial/layers.py` | 385-465 |
| 19 | `leo_l19` | `LEOAuthenticatedLayer` | Layer 19 — LEO Authenticated Satellite Signals [NOVEL]. | `upin/layers/satellite/layers.py` | 349-446 |
| 20 | `beacon_l20` | `HumanBeaconNetworkLayer` | Layer 20 — Human Ground Beacon Network [NOVEL]. | `upin/layers/human/layers.py` | 21-130 |
| 21 | `spoofmap_l21` | `CrowdsourcedSpoofingMapLayer` | Layer 21 — India Crowdsourced GPS Spoofing Map [NOVEL]. | `upin/layers/human/layers.py` | 133-206 |
| 22 | `radius_l22` | `RadiusContainmentLayer` | Layer 22 — Radius Containment and Convergence Lock [NOVEL]. | `upin/layers/human/layers.py` | 209-313 |
| 23 | `magmap_l23` | `MagneticMapMatchingLayer` | Layer 23 — Magnetic Signature Map Matching [NOVEL, UNDERWATE... | `upin/layers/magnetic/layers.py` | 263-372 |
| 24 | `eminduct_l24` | `EMInductionLayer` | Layer 24 — Electromagnetic Induction Navigation [NOVEL, UNDE... | `upin/layers/magnetic/layers.py` | 379-466 |
| 25 | `polsky_l25a` | `PolarisedSkyLayer` | Layer 25a — Atmospheric Polarised Sky Navigation [NOVEL]. | `upin/layers/optical/layers.py` | 247-304 |
| 25 | `polwater_l25b` | `UnderwaterPolarisedLayer` | Layer 25b — Underwater Polarised Light Navigation [NOVEL, UN... | `upin/layers/optical/layers.py` | 311-370 |
| 26 | `chemgrad_l26` | `ChemicalGradientLayer` | Layer 26 — Chemical Gradient Navigation [NOVEL, UNDERWATER]. | `upin/layers/chemical/layers.py` | 25-115 |
| 27 | `qclock_l27` | `QuantumAtomicClockLayer` | Layer 27 — Quantum Optical Atomic Clock [NOVEL, UNDERWATER]. | `upin/layers/inertial/layers.py` | 468-547 |
| 28 | `gravgrad_l28a` | `QuantumGravityGradiometerLayer` | Layer 28a — Quantum Gravity Gradiometer [NOVEL, UNDERWATER]. | `upin/layers/gravity/layers.py` | 19-101 |
| 28 | `gravimeter_l28b` | `QuantumDualGravimeterLayer` | Layer 28b — Quantum Dual Gravimeter [NOVEL, UNDERWATER]. | `upin/layers/gravity/layers.py` | 104-181 |
| 29 | `pulsar_l29b` | `PulsarExtendedLayer` | Layer 29b — Pulsar-Based Extended Navigation [NOVEL, UNDERWA... | `upin/layers/cosmic/layers.py` | 120-216 |
| 29 | `xnav_l29` | `XRayPulsarLayer` | Layer 29 — X-Ray Pulsar Navigation (XNAV) [NOVEL, UNDERWATER... | `upin/layers/satellite/layers.py` | 449-577 |
| 30 | `nvdiamond_l30` | `NVDiamondMagnetometerLayer` | Layer 30 — Nitrogen-Vacancy Diamond Magnetometer [NOVEL, UND... | `upin/layers/magnetic/layers.py` | 473-544 |
| 31 | `vslam_l31` | `VisualSLAMLayer` | Layer 31 — Visual SLAM Live Environment Mapping. | `upin/layers/optical/layers.py` | 377-504 |
| 32 | `vio_l32` | `VisualOdometryLayer` | Layer 32 — Visual Odometry with IMU Fusion. | `upin/layers/optical/layers.py` | 511-605 |
| 33 | `lidar_l33` | `LiDARSLAMLayer` | Layer 33 — LiDAR Enhanced Visual SLAM. | `upin/layers/optical/layers.py` | 612-702 |
| 34 | `sonar_l34` | `ActiveSonarLayer` | Layer 34 — Active Acoustic Sonar Mapping. | `upin/layers/acoustic/layers.py` | 112-178 |
| 35 | `focsonar_l35` | `FocusedSonarLayer` | Layer 35 — Focused Sonar Beam Imaging [NOVEL, UNDERWATER]. | `upin/layers/acoustic/layers.py` | 181-224 |
| 36 | `seismic_l36` | `SeismicInfrasoundLayer` | Layer 36 — Seismic Infrasound Ground Vibration [NOVEL]. | `upin/layers/chemical/layers.py` | 118-163 |
| 37 | `hydrowake_l37` | `HydrodynamicWakeLayer` | Layer 37 — Hydrodynamic Wake Detection [NOVEL, UNDERWATER]. | `upin/layers/chemical/layers.py` | 166-212 |
| 38 | `thermal_l38` | `ThermalIRLayer` | Layer 38 — Thermal Infrared Navigation [NOVEL]. | `upin/layers/optical/layers.py` | 709-818 |
| 39 | `hyperspec_l39` | `HyperspectralLayer` | Layer 39 — Hyperspectral Polarised Vision [NOVEL, UNDERWATER... | `upin/layers/optical/layers.py` | 825-891 |
| 40 | `muon_l40` | `MuonNavigationLayer` | Layer 40 — Cosmic Ray Muon Navigation (MuWNS) [NOVEL, UNDERW... | `upin/layers/cosmic/layers.py` | 21-117 |
| 41 | `eloran_l41` | `ELORANLayer` | Layer 41 — eLORAN Terrestrial Navigation [NOVEL, UNDERWATER]... | `upin/layers/rf/layers.py` | 437-527 |
| 42 | `soop_l42` | `CommercialSOOPLayer` | Layer 42 — Commercial Satellite Signals of Opportunity [NOVE... | `upin/layers/rf/layers.py` | 534-638 |
| 43 | `opticflow_l43` | `OpticFlowLayer` | Layer 43 — Optic Flow Velocity and Proximity Sensing [NOVEL]... | `upin/layers/inertial/layers.py` | 550-631 |
| 44 | `bicoord_l44` | `BiocoordinateGeoChemMagLayer` | Layer 44 — Bicoordinate Geo-Chemical-Magnetic Positioning [N... | `upin/layers/magnetic/layers.py` | 551-646 |
| 45 | `tactile_l45` | `TactilePressureLayer` | Layer 45 — Distributed Tactile Pressure Array [NOVEL, UNDERW... | `upin/layers/chemical/layers.py` | 215-258 |
| 46 | `stellar_l46` | `StellarConstellationLayer` | Layer 46 — Stellar Constellation Pattern Navigation [NOVEL]. | `upin/layers/satellite/layers.py` | 580-681 |
| 47 | `skygrad_l47` | `DiffuseSkyLayer` | Layer 47 — Diffuse Sky Brightness Gradient Navigation [NOVEL... | `upin/layers/satellite/layers.py` | 684-752 |
| 48 | `latline_l48` | `LateralLineLayer` | Layer 48 — Lateral Line Pressure Field Mapping [NOVEL, UNDER... | `upin/layers/chemical/layers.py` | 261-303 |
| 49 | `ionosphere_l49` | `IonosphericDensityLayer` | Layer 49 — Ionospheric Electron Density Navigation [NOVEL]. | `upin/layers/chemical/layers.py` | 384-468 |
| 57 | `nmrgyro_l57` | `NMRGyroscopeLayer` | Layer 57 — Nuclear Magnetic Resonance Gyroscope [NOVEL, UNDE... | `upin/layers/inertial/layers.py` | 634-709 |
| 58 | `serfgyro_l58` | `SERFGyroscopeLayer` | Layer 58 — SERF Atomic Spin Gyroscope [NOVEL, UNDERWATER]. | `upin/layers/inertial/layers.py` | 712-787 |
| 59 | `schumann_l59` | `SchumannResonanceLayer` | Layer 59 — Schumann Resonance ELF Navigation [NOVEL, UNDERWA... | `upin/layers/cosmic/layers.py` | 219-309 |
| 60 | `odometer_l60` | `LocomotionOdometerLayer` | Layer 60 — Locomotion Odometer Step Counter [NOVEL]. | `upin/layers/chemical/layers.py` | 306-381 |
| 61 | `uwb_d06` | `UWBPositioningLayer` | Ultra-Wideband short-range precision positioning. | `upin/layers/rf/layers.py` | 641-715 |
| 62 | `lora_d07` | `LoRaWANNodeLayer` | Long-Range Wide Area Network positioning via signal triangul... | `upin/layers/rf/layers.py` | 718-784 |
| 63 | `radar_alt_b09` | `RadarAltimeterLayer` | Radar ground-return altimeter for aerial platforms. | `upin/layers/inertial/layers.py` | 790-854 |
| 64 | `depth_pressure_b10` | `DepthPressureSensorLayer` | Underwater depth positioning via hydrostatic pressure measur... | `upin/layers/inertial/layers.py` | 857-922 |
| 65 | `efield_c07` | `ElectricFieldSensingLayer` | Electric field gradient sensing — inspired by electric eel e... | `upin/layers/magnetic/layers.py` | 649-695 |
| 66 | `monarch_e10` | `MonarchSunCompassLayer` | Sun compass heading — inspired by Monarch butterfly migratio... | `upin/layers/optical/layers.py` | 894-950 |
| 67 | `tern_k05` | `ArcticTernMultiCueLayer` | Multi-cue navigation monitoring — inspired by Arctic tern mi... | `upin/layers/systems/layers.py` | 354-405 |
| 69 | `wolf_k06` | `WolfPackCoordinationLayer` | Wolf pack tactical coordination — multi-unit movement patter... | `upin/layers/biological/layers.py` | 34-107 |
| 70 | `owl_e11` | `OwlSilentApproachLayer` | Owl silent approach — noise-minimal stealth navigation. | `upin/layers/biological/layers.py` | 114-182 |
| 71 | `salmon_h08` | `SalmonHomingLayer` | Salmon magnetic + chemical homing — combined navigation. | `upin/layers/biological/layers.py` | 189-263 |
| 72 | `eagle_e12` | `EagleThermalVisionLayer` | Eagle thermal vision — high-acuity threat detection + visual... | `upin/layers/biological/layers.py` | 270-345 |
| 73 | `glonass_a07` | `GLONASSLayer` | GLONASS — Russian GNSS constellation (24 satellites, FDMA). | `upin/layers/satellite/missing_constellations.py` | 21-37 |
| 74 | `galileo_a08` | `GalileoLayer` | Galileo — European GNSS constellation (30 satellites, highes... | `upin/layers/satellite/missing_constellations.py` | 40-56 |
| 75 | `beidou_a09` | `BeiDouLayer` | BeiDou — Chinese GNSS constellation (35 satellites, global +... | `upin/layers/satellite/missing_constellations.py` | 59-75 |
| 76 | `qzss_a10` | `QZSSLayer` | QZSS — Japanese regional GNSS (4 satellites, Asia-Pacific, s... | `upin/layers/satellite/missing_constellations.py` | 78-94 |
| 77 | `bluetooth_d08` | `BluetoothAoALayer` | Bluetooth 5.1 Angle of Arrival positioning — sub-metre indoo... | `upin/layers/satellite/missing_constellations.py` | 97-114 |
| 78 | `eagleeye_e13` | `EagleEyeStereoLayer` | Layer 78 — Eagle Eye Stereo Camera Passive Altitude. | `upin/layers/optical/eagle_eye.py` | 29-165 |
| 79 | `enc_e14` | `ENCChartMatchingLayer` | Layer 79 — Electronic Navigational Chart Feature Matching. | `upin/layers/optical/eagle_eye.py` | 172-274 |
| 80 | `bathymetry_f04` | `BathymetricMatchingLayer` | Layer 80 — Bathymetric Seafloor Profile Matching. | `upin/layers/acoustic/bathymetry.py` | 23-141 |
| 81 | `dted_e15` | `DTEDMatchingLayer` | Layer 81 — Digital Terrain Elevation Data Matching. | `upin/layers/optical/eagle_eye.py` | 281-370 |
| 82 | `oceancurrent_h09` | `OceanCurrentDriftLayer` | Layer 82 — Ocean Current Drift Correction. | `upin/layers/chemical/nautical.py` | 24-122 |
| 83 | `tidaltiming_h10` | `TidalTimingPositionLayer` | Layer 83 — Coastal Position from Tidal Signature Matching. | `upin/layers/chemical/nautical.py` | 125-244 |
| 84 | `terrainfp_k07` | `TerrainFingerprintLayer` | Layer 84 — Multi-sensor Terrain Fingerprint Matching. | `upin/layers/systems/terrain_fp_layer.py` | 25-140 |
| 85 | `predtower_k08` | `PredictiveTowerVerificationLayer` | Layer 85 — Predictive Tower Verification. | `upin/layers/systems/predictive_tower_layer.py` | 207-294 |
| 86 | `dirtower_k09` | `DirectionalTowerLayer` | Layer 86 — Directional Tower Selection (GDOP Optimised). | `upin/layers/systems/directional_tower_layer.py` | 173-264 |
| 87 | `circumfx_k10` | `CircumferenceIntersectionLayer` | Layer 87 — Circumference Intersection Position. | `upin/layers/systems/circumference_layer.py` | 165-256 |
| 88 | `univbeacon_k11` | `UniversalBeaconLayer` | Layer 88 — Universal Beacon Positioning. | `upin/layers/rf/universal_beacon.py` | 328-425 |
|  | `` | `LayerEvent` | One layer management event. | `upin/layers/layer_manager.py` | 22-27 |
|  | `` | `LayerManager` | Interactive layer management for UPIN. | `upin/layers/layer_manager.py` | 30-398 |
|  | `` | `LayerRegistry` | Central registry for managing UPIN navigation layers. | `upin/layers/registry.py` | 207-284 |

---
## Core Modules

| Class | Description | File | Lines |
|-------|-------------|------|-------|
| `FormulaCombo` | A weighted combination of 2 or 3 formulas. | `upin/core/auto_combo.py` | 23-82 |
| `AutoComboDiscovery` | Evolve combinations of 2-3 formulas for best joint performance. | `upin/core/auto_combo.py` | 85-176 |
| `VisualFeatures` | Visual features extracted from camera data. | `upin/core/cnn_gru_compensation.py` | 36-64 |
| `IMUSequence` | IMU sensor sequence data. | `upin/core/cnn_gru_compensation.py` | 68-85 |
| `_NumpyCNNGRU` | Lightweight CNN-GRU using only numpy (portable fallback). | `upin/core/cnn_gru_compensation.py` | 97-147 |
| `CNNGRUGNSSCompensation` | CNN-GRU GNSS Outage Compensation System. | `upin/core/cnn_gru_compensation.py` | 188-360 |
| `_TorchCNNGRU` |  | `upin/core/cnn_gru_compensation.py` | 153-183 |
| `LayerAgreement` | Result of checking whether a layer agrees with consensus. | `upin/core/confidence.py` | 27-34 |
| `ConfidenceResult` | Full confidence analysis output. | `upin/core/confidence.py` | 38-47 |
| `ConfidenceScorer` | Implements the UPIN confidence scoring algorithm. | `upin/core/confidence.py` | 50-243 |
| `ConstraintCircle` | The fused constraint area — intersection of all bounds. | `upin/core/constraint_calibrator.py` | 42-52 |
| `FormulaScore` | Tracking how well a formula stays inside the constraint. | `upin/core/constraint_calibrator.py` | 56-77 |
| `ConstraintCalibrator` | Fuses cell triangulation + PUE + sensors into a constraint circle, | `upin/core/constraint_calibrator.py` | 80-350 |
| `ValidationResult` | One validation cycle result. | `upin/core/continuous_learning.py` | 40-49 |
| `BackgroundValidator` | Every 30 seconds, each algorithm predicts "where will we be in 30s?" | `upin/core/continuous_learning.py` | 52-163 |
| `SensorAutoCalibrator` | Learns your specific phone's sensor biases by comparing sensor data | `upin/core/continuous_learning.py` | 170-269 |
| `FishSchoolConfig` |  | `upin/core/continuous_learning.py` | 277-283 |
| `FishSchoolGridSearch` | 6 fish schools, each running the same formula with different parameter... | `upin/core/continuous_learning.py` | 286-388 |
| `UserProfile` | Saves all learned parameters to disk so the system remembers | `upin/core/continuous_learning.py` | 395-457 |
| `ContinuousLearningEngine` | Master engine that runs background validation, sensor calibration, | `upin/core/continuous_learning.py` | 464-545 |
| `LayerPerformanceTracker` | Tracks one layer's prediction accuracy over time. | `upin/core/continuous_learning.py` | 552-594 |
| `UniversalLayerTrainer` | Wraps ALL 67 navigation layers and trains them continuously. | `upin/core/continuous_learning.py` | 597-698 |
| `AlgorithmTournament` | ALL 10 fusion algorithms + financial indicators + unconventional math | `upin/core/continuous_learning.py` | 705-813 |
| `EnvironmentState` | Current environment state for DRL decision making. | `upin/core/drl_algorithm_selector.py` | 38-64 |
| `_NumpyPPO` | Lightweight PPO implementation using only numpy. | `upin/core/drl_algorithm_selector.py` | 78-131 |
| `DRLAlgorithmSelector` | Deep Reinforcement Learning Algorithm Selector using PPO. | `upin/core/drl_algorithm_selector.py` | 161-373 |
| `_TorchPPO` |  | `upin/core/drl_algorithm_selector.py` | 137-156 |
| `BaselineSample` | One GPS-confirmed baseline sample. | `upin/core/financial_indicator_nav.py` | 94-105 |
| `BaselineRecorder` | Records baseline while GPS is active. Like collecting candles on a cha... | `upin/core/financial_indicator_nav.py` | 108-178 |
| `PositionStrategy` | Base class for a prediction strategy using indicator combos. | `upin/core/financial_indicator_nav.py` | 183-219 |
| `TrendStrategy` | Fast SMA(5) + EMA(0.25) — catches turns quickly. Like fast crossover. | `upin/core/financial_indicator_nav.py` | 222-234 |
| `SmoothStrategy` | Slow SMA(30) + EMA(0.05) — filters noise, stable. Like 200-period MA. | `upin/core/financial_indicator_nav.py` | 237-249 |
| `MACDStrategy` | MACD velocity + RSI heading — predicts turns and acceleration. | `upin/core/financial_indicator_nav.py` | 252-265 |
| `BollingerStrategy` | Bollinger mean reversion — assumes position reverts to average. | `upin/core/financial_indicator_nav.py` | 268-285 |
| `AdaptiveStrategy` | Auto-tunes alpha and window based on previous drill errors. | `upin/core/financial_indicator_nav.py` | 288-318 |
| `FinancialIndicatorNav` | Main engine that combines baseline recording + 5 strategy layers. | `upin/core/financial_indicator_nav.py` | 323-484 |
| `AgentParams` | Sensor parameter tweaks one agent applies before running its formula. | `upin/core/formula_agents.py` | 26-77 |
| `Agent` | A single agent running a given formula with specific params. | `upin/core/formula_agents.py` | 85-108 |
| `FormulaAgentPool` | Per-formula pool of agents evolving sensor parameters. | `upin/core/formula_agents.py` | 111-182 |
| `FormulaAgentManager` | Manages a pool per formula — the full multi-formula agent system. | `upin/core/formula_agents.py` | 185-214 |
| `ExtendedKalmanFilter` | Extended Kalman Filter for multi-layer sensor fusion. | `upin/core/fusion_engine.py` | 33-115 |
| `AnomalyDetector` | ML-based anomaly detection using Mahalanobis distance. | `upin/core/fusion_engine.py` | 118-280 |
| `ResilientReferenceTracker` | UPIN Internal Reference Tracker — the unjammable fallback. | `upin/core/fusion_engine.py` | 283-437 |
| `FusionEngine` | The UPIN AI Fusion Engine. | `upin/core/fusion_engine.py` | 440-1002 |
| `TowerCalibration` | GPS-calibrated data for one cell tower. | `upin/core/gps_calibrated_ranging.py` | 42-59 |
| `TowerCircle` | A circle centered on a tower with measured radius. | `upin/core/gps_calibrated_ranging.py` | 63-71 |
| `GPSCalibratedTowerRanging` | GPS-calibrated cell tower distance measurement. | `upin/core/gps_calibrated_ranging.py` | 74-316 |
| `NavigationState` | Complete navigation state with error tracking. | `upin/core/gps_physics_engine.py` | 180-188 |
| `RealisticNavigationEKF` | EKF with realistic GPS physics: pseudoranges, atmospheric errors, | `upin/core/gps_physics_engine.py` | 191-313 |
| `FilterState` |  | `upin/core/improved_adaptive_ekf.py` | 31-36 |
| `SensorHealthMetrics` |  | `upin/core/improved_adaptive_ekf.py` | 40-46 |
| `IAEKFEnvironment` |  | `upin/core/improved_adaptive_ekf.py` | 50-58 |
| `_NumpyNoiseNet` | Lightweight adaptive noise estimator (numpy only). | `upin/core/improved_adaptive_ekf.py` | 73-98 |
| `ImprovedAdaptiveEKF` | Improved Adaptive Extended Kalman Filter with neural-network-based | `upin/core/improved_adaptive_ekf.py` | 123-377 |
| `_TorchNoiseNet` |  | `upin/core/improved_adaptive_ekf.py` | 104-118 |
| `LayerGroup` | Groups as defined in the patent specification Section 6.2. | `upin/core/layer_base.py` | 21-33 |
| `LayerCapability` | What a layer can provide. | `upin/core/layer_base.py` | 36-44 |
| `LayerStatus` | Runtime status of a layer. | `upin/core/layer_base.py` | 48-58 |
| `LayerReading` | A single reading from a positioning layer. | `upin/core/layer_base.py` | 62-74 |
| `NavigationLayer` | Abstract base class for all 60 UPIN navigation/positioning layers. | `upin/core/layer_base.py` | 77-194 |
| `ThreatLayer` | Abstract base class for all 25 UPIN threat detection layers. | `upin/core/layer_base.py` | 197-240 |
| `SwarmLayer` | Abstract base class for swarm architecture layers SW1-SW4. | `upin/core/layer_base.py` | 243-268 |
| `MissionModule` | Abstract base class for mission capability modules MC1-MC4. | `upin/core/layer_base.py` | 271-296 |
| `PathDot` | A single dot on the predictive path. | `upin/core/live_predictive_path.py` | 49-62 |
| `PredictivePath` | The complete dotted predictive path at one instant. | `upin/core/live_predictive_path.py` | 66-73 |
| `LivePredictivePathEngine` | Generates and updates the predictive dotted path every tick. | `upin/core/live_predictive_path.py` | 76-316 |
| `ManeuverSignature` | A recorded maneuver with its sensor fingerprint. | `upin/core/maneuver_recognition.py` | 25-36 |
| `ManeuverRecognizer` | Online maneuver detection + library for fingerprint matching. | `upin/core/maneuver_recognition.py` | 39-188 |
| `RoadSegment` | A segment of road in the local road network. | `upin/core/map_matching.py` | 39-46 |
| `MatchResult` | Result of snapping a position to the road network. | `upin/core/map_matching.py` | 50-59 |
| `MapMatcher` | Snap GPS/predicted positions to the nearest road. | `upin/core/map_matching.py` | 62-147 |
| `TerrainPoint` | An elevation data point. | `upin/core/map_matching.py` | 155-159 |
| `TerrainFollower` | Terrain-following flight path generator. | `upin/core/map_matching.py` | 162-249 |
| `Waypoint` | A waypoint along a route. | `upin/core/map_matching.py` | 257-267 |
| `Route` | A complete route from origin to destination. | `upin/core/map_matching.py` | 271-287 |
| `DestinationRouter` | Route planning and progress tracking. | `upin/core/map_matching.py` | 290-412 |
| `FlightPathPredictor` | Unified forward path prediction that fuses map matching, | `upin/core/map_matching.py` | 419-501 |
| `SystemMode` |  | `upin/core/master_optimizer.py` | 31-37 |
| `ConfidenceLevel` |  | `upin/core/master_optimizer.py` | 40-45 |
| `UPINConfiguration` |  | `upin/core/master_optimizer.py` | 49-62 |
| `SystemPerformanceMetrics` |  | `upin/core/master_optimizer.py` | 66-78 |
| `UPINMasterOptimizer` | Master UPIN Integration and Performance Optimizer. | `upin/core/master_optimizer.py` | 81-491 |
| `NavigationRecommendation` |  | `upin/core/navigation_confidence.py` | 18-22 |
| `NavigationConfidence` | Navigation confidence calculator and mission advisor. | `upin/core/navigation_confidence.py` | 25-221 |
| `NLLSTrilateration` | Gauss-Newton NLLS for multi-tower position estimation. | `upin/core/nlls_trilateration.py` | 23-98 |
| `PositionDomain` | Domain in which the position was determined. | `upin/core/position.py` | 17-24 |
| `ThreatLevel` | Threat assessment levels. | `upin/core/position.py` | 27-33 |
| `Position` | A position estimate from a single layer or the fusion engine. | `upin/core/position.py` | 37-76 |
| `ThreatAlert` | A threat detected by the threat detection subsystem. | `upin/core/position.py` | 80-90 |
| `LayerDiagnostic` | Health and status of a single positioning layer. | `upin/core/position.py` | 94-104 |
| `NavigationOutput` | Complete output from the UPIN Fusion Engine at each cycle. | `upin/core/position.py` | 108-145 |
| `AccelerationTrend` | Determines if the platform is cruising, accelerating, or decelerating | `upin/core/predictive_positioning.py` | 33-106 |
| `Prediction` | A forward position prediction. | `upin/core/predictive_positioning.py` | 114-124 |
| `PredictionResult` | Result of a prediction validation. | `upin/core/predictive_positioning.py` | 128-135 |
| `PredictiveModel` | Core predictive positioning model. | `upin/core/predictive_positioning.py` | 138-264 |
| `Checkpoint` | A known waypoint along a pre-loaded route/flight plan. | `upin/core/predictive_positioning.py` | 272-282 |
| `CheckpointValidator` | Pre-loaded waypoints from a flight/route plan. | `upin/core/predictive_positioning.py` | 285-353 |
| `MultiModelPredictor` | Run multiple predictive models in parallel, score them all. | `upin/core/predictive_positioning.py` | 360-436 |
| `PUEState` | Current state of the Position Uncertainty Envelope. | `upin/core/pue_constraint.py` | 25-37 |
| `PositionUncertaintyEnvelope` | PUE — limits how far the platform could have moved since last GPS fix. | `upin/core/pue_constraint.py` | 40-95 |
| `SmartConstraintEngine` | Smart Constraint Engine — 4 layers that SHRINK the search radius. | `upin/core/pue_constraint.py` | 98-212 |
| `RouteSample` | One sample along a learned route. | `upin/core/route_dtw.py` | 24-32 |
| `LearnedRoute` | A complete learned route. | `upin/core/route_dtw.py` | 36-50 |
| `RouteDTWLearning` | Record routes with GPS; match live sensors during GPS denial via DTW. | `upin/core/route_dtw.py` | 53-210 |
| `CorrelationSample` | One recorded moment: all sensors + confirmed position + movement. | `upin/core/sensor_position_correlator.py` | 35-73 |
| `SensorPositionLogger` | Logs every sensor reading alongside GPS position. | `upin/core/sensor_position_correlator.py` | 78-158 |
| `SensorMovementCorrelator` | Learns the mapping: sensor_readings → actual_movement. | `upin/core/sensor_position_correlator.py` | 163-433 |
| `IMUGrade` | Hardware grade profiles. The SAME math runs on all — | `upin/core/strapdown_ins.py` | 52-131 |
| `Quaternion` | Unit quaternion for 3D rotation — no gimbal lock, unlike Euler angles. | `upin/core/strapdown_ins.py` | 136-201 |
| `INSState` | Complete inertial navigation state. | `upin/core/strapdown_ins.py` | 227-260 |
| `StrapdownINS` | Full strapdown inertial navigation system. | `upin/core/strapdown_ins.py` | 263-532 |
| `GlobusINSReading` | Wraps StrapdownINS as a UPIN-compatible position source. | `upin/core/strapdown_ins.py` | 537-580 |
| `UPINSystemIntegrator` | Central wiring that connects all UPIN modules. | `upin/core/system_integrator.py` | 25-379 |
| `TerrainFingerprint` | A single fingerprint sample taken at a known GPS position. | `upin/core/terrain_fingerprint.py` | 27-61 |
| `TerrainFingerprintMap` | Records and matches terrain fingerprints. | `upin/core/terrain_fingerprint.py` | 64-145 |
| `TrainingConstraint` | Leash formulas to within N metres of GPS during training. | `upin/core/training_constraint.py` | 23-57 |
| `FourierMovementAnalyzer` | Decomposes movement into frequency components using FFT. | `upin/core/unconventional_math.py` | 30-113 |
| `MarkovMovementPredictor` | Models movement as a Markov Chain with states: | `upin/core/unconventional_math.py` | 120-199 |
| `BezierPathExtrapolator` | Fits cubic Bezier curves to recent path, extrapolates forward. | `upin/core/unconventional_math.py` | 206-257 |
| `WaveletDenoiser` | Separates GPS noise from real movement at different timescales. | `upin/core/unconventional_math.py` | 264-325 |
| `EntropyConfidence` | Measures how predictable your movement is using Shannon entropy. | `upin/core/unconventional_math.py` | 332-386 |
| `TerrainSlopeConstraint` | Uses accelerometer tilt angle to determine terrain slope. | `upin/core/unconventional_math.py` | 393-469 |
| `UnconventionalPredictor` | Combines all 6 unconventional math approaches into one predictor. | `upin/core/unconventional_math.py` | 476-544 |

---
## Swarm & Nature Tactics

| Class | Description | File | Lines | Status |
|-------|-------------|------|-------|--------|
| `MiroFishHierarchy` | Hierarchical architecture for scaling swarm from 60 to milli... | `upin/swarm/advanced_behaviours.py` | 29-155 | IMPLEMENTED |
| `NETRATacticalLayer` | Edge-first AI processing with sub-100ms anomaly detection. | `upin/swarm/advanced_behaviours.py` | 162-282 | IMPLEMENTED |
| `AIIntelInterface` | Natural language mission input and strategy adaptation. | `upin/swarm/advanced_behaviours.py` | 289-408 | IMPLEMENTED |
| `TermiteConstruction` | Collaborative task coordination for swarm operations. | `upin/swarm/advanced_behaviours.py` | 415-499 | IMPLEMENTED |
| `FormationType` | Standard swarm formations. | `upin/swarm/beehive.py` | 29-37 | IMPLEMENTED |
| `PlatformState` | State of a single platform in the swarm. | `upin/swarm/beehive.py` | 41-51 | IMPLEMENTED |
| `SwarmCommand` | A command from the swarm intelligence to a platform. | `upin/swarm/beehive.py` | 55-62 | IMPLEMENTED |
| `DistributedBeehiveIntelligence` | SW1 — Distributed Beehive Intelligence. | `upin/swarm/beehive.py` | 65-125 | IMPLEMENTED |
| `MasterBrainProtocol` | SW2 — Master Brain Upload Protocol. | `upin/swarm/beehive.py` | 128-195 | IMPLEMENTED |
| `OffensivePostureMode` | SW3 — Offensive Posture Mode. | `upin/swarm/beehive.py` | 198-266 | IMPLEMENTED |
| `AdaptiveFormationIntelligence` | SW4 — Adaptive Formation Intelligence. | `upin/swarm/beehive.py` | 269-362 | IMPLEMENTED |
| `RangingMethod` |  | `upin/swarm/cooperative_mesh.py` | 40-45 | IMPLEMENTED |
| `PeerDevice` | A device in the cooperative mesh. | `upin/swarm/cooperative_mesh.py` | 49-58 | IMPLEMENTED |
| `MeshRanging` | One distance measurement between two devices. | `upin/swarm/cooperative_mesh.py` | 62-71 | IMPLEMENTED |
| `CooperativeMeshPositioning` | Cooperative mesh positioning using peer-to-peer ranging. | `upin/swarm/cooperative_mesh.py` | 76-528 | IMPLEMENTED |
| `SwarmMeshController` | Manages a swarm of devices as a cooperative positioning mesh... | `upin/swarm/cooperative_mesh.py` | 533-611 | IMPLEMENTED |
| `DroneRole` | Available drone roles in a swarm. | `upin/swarm/drone_roles.py` | 38-47 | IMPLEMENTED |
| `Equipment` | Physical equipment a drone carries for its role. | `upin/swarm/drone_roles.py` | 51-56 | IMPLEMENTED |
| `RoleProfile` | Complete profile for a drone role. | `upin/swarm/drone_roles.py` | 60-82 | IMPLEMENTED |
| `DroneInstance` | A specific drone in the swarm with an assigned role. | `upin/swarm/drone_roles.py` | 359-376 | IMPLEMENTED |
| `SwarmRoleManager` | Manages role assignment and specialisation for a drone swarm... | `upin/swarm/drone_roles.py` | 379-492 | IMPLEMENTED |
| `(stub)` | Acoustic — 50m air / 5km underwater, unjammable. TODO: imple... | `upin/swarm/mesh_comms/acoustic.py` | 1-1 | STUB |
| `(stub)` | Bluetooth 5 — 200m, low power mesh data. TODO: implement. | `upin/swarm/mesh_comms/bluetooth.py` | 1-1 | STUB |
| `(stub)` | Frequency Hopping Spread Spectrum — anti-jam overlay for any... | `upin/swarm/mesh_comms/freq_hopping.py` | 1-1 | STUB |
| `(stub)` | IR/Laser — 1km LOS, unjammable, stealth mode. TODO: implemen... | `upin/swarm/mesh_comms/ir_laser.py` | 1-1 | STUB |
| `(stub)` | 915MHz ISM — 2km, medium bandwidth mesh backbone. TODO: impl... | `upin/swarm/mesh_comms/ism_915.py` | 1-1 | STUB |
| `(stub)` | LoRa 900MHz — 15km, low bandwidth, frequency hopping. TODO: ... | `upin/swarm/mesh_comms/lora.py` | 1-1 | STUB |
| `(stub)` | UWB (Ultra-Wideband) — 100m, 10cm ranging accuracy. TODO: im... | `upin/swarm/mesh_comms/uwb.py` | 1-1 | STUB |
| `(stub)` | WiFi Direct — 300m, high bandwidth video/bulk relay. TODO: i... | `upin/swarm/mesh_comms/wifi_direct.py` | 1-1 | STUB |
| `MeshNodeStatus` |  | `upin/swarm/mesh_swarm_os.py` | 33-38 | IMPLEMENTED |
| `MeshNode` | One drone in the swarm mesh. | `upin/swarm/mesh_swarm_os.py` | 42-62 | IMPLEMENTED |
| `MeshMessage` | An encrypted message passed through the mesh. | `upin/swarm/mesh_swarm_os.py` | 66-76 | IMPLEMENTED |
| `SwarmMeshOS` | The swarm mesh operating system. | `upin/swarm/mesh_swarm_os.py` | 79-407 | IMPLEMENTED |
| `AgentPersonality` | Each MiroFish agent has a unique personality that evolves. | `upin/swarm/mirofish_personalities.py` | 34-166 | IMPLEMENTED |
| `MiroFishPopulation` | Population of MiroFish agents with natural selection. | `upin/swarm/mirofish_personalities.py` | 169-294 | IMPLEMENTED |
| `IntelIngestionPipeline` | Takes HUMINT, SIGINT, IMINT and continuously adjusts fusion ... | `upin/swarm/mirofish_personalities.py` | 301-419 | IMPLEMENTED |
| `RuViewInterface` | Stub interface for RuView WiFi DensePose integration. | `upin/swarm/mirofish_personalities.py` | 426-503 | IMPLEMENTED |
| `RadioType` |  | `upin/swarm/multi_radio_mesh.py` | 31-38 | IMPLEMENTED |
| `RadioConfig` |  | `upin/swarm/multi_radio_mesh.py` | 42-52 | IMPLEMENTED |
| `CommLink` | An active communication link between two nodes. | `upin/swarm/multi_radio_mesh.py` | 75-82 | IMPLEMENTED |
| `MultiRadioMesh` | Multi-radio mesh with automatic failover. | `upin/swarm/multi_radio_mesh.py` | 85-202 | IMPLEMENTED |
| `(stub)` | Army Ant Tactics — living bridge, leaderless emergence. TODO... | `upin/swarm/nature_tactics/ant.py` | 1-1 | STUB |
| `(stub)` | Cuttlefish Camouflage — dynamic signature morphing for decoy... | `upin/swarm/nature_tactics/cuttlefish.py` | 1-1 | STUB |
| `(stub)` | Dolphin Tactics — mud ring jamming, echolocation nav. TODO: ... | `upin/swarm/nature_tactics/dolphin.py` | 1-1 | STUB |
| `(stub)` | Firefly Synchronization — leaderless time sync across mesh. ... | `upin/swarm/nature_tactics/firefly.py` | 1-1 | STUB |
| `(stub)` | Goose V-Formation — energy drafting, leadership rotation. TO... | `upin/swarm/nature_tactics/goose.py` | 1-1 | STUB |
| `WaveParticipant` | A drone participating in a wave wash attack. | `upin/swarm/nature_tactics/orca.py` | 37-43 | IMPLEMENTED |
| `OrcaWaveWash` | Coordinated synchronized attack — EW resonance. | `upin/swarm/nature_tactics/orca.py` | 46-149 | IMPLEMENTED |
| `CarouselSlot` | A position slot in the carousel rotation. | `upin/swarm/nature_tactics/orca.py` | 157-165 | IMPLEMENTED |
| `OrcaCarousel` | Carousel feeding — encircle and rotate. | `upin/swarm/nature_tactics/orca.py` | 168-274 | IMPLEMENTED |
| `OrcaPodDialect` | Pod-specific encrypted communication protocol. | `upin/swarm/nature_tactics/orca.py` | 281-347 | IMPLEMENTED |
| `SwarmKnowledge` | Transferable knowledge package from experienced swarm. | `upin/swarm/nature_tactics/orca.py` | 355-372 | IMPLEMENTED |
| `OrcaTeaching` | Knowledge transfer between experienced and new swarm members... | `upin/swarm/nature_tactics/orca.py` | 375-449 | IMPLEMENTED |
| `OrcaTactics` | Combined orca-inspired tactical suite. | `upin/swarm/nature_tactics/orca.py` | 456-502 | IMPLEMENTED |
| `(stub)` | Starling Murmuration — 3-rule flocking, predator evasion flo... | `upin/swarm/nature_tactics/starling.py` | 1-1 | STUB |
| `(stub)` | Wolf Pack Tactics — relay chase, flanking, howl coordination... | `upin/swarm/nature_tactics/wolf.py` | 1-1 | STUB |

---
## Detection & Security

| Class | Description | File | Lines |
|-------|-------------|------|-------|
| `SpoofAlert` | One detected spoofing indicator. | `upin/detection/anti_spoof.py` | 30-36 |
| `AntiSpoofDetector` | Multi-check GPS spoofing detector. | `upin/detection/anti_spoof.py` | 39-135 |
| `RFFieldMonitor` | RF Field Monitor — baseline + anomaly detection. | `upin/detection/anti_spoof.py` | 138-227 |
| `ConsensusValidator` | Multi-source position voting — consensus determines truth. | `upin/detection/anti_spoof.py` | 230-311 |
| `AnomalyType` |  | `upin/detection/mahalanobis_detector.py` | 25-31 |
| `AnomalyDetection` | One detected anomaly from Mahalanobis analysis. | `upin/detection/mahalanobis_detector.py` | 35-44 |
| `MahalanobisDetector` | Real-time anomaly detection using Mahalanobis distance. | `upin/detection/mahalanobis_detector.py` | 47-236 |
| `SignalClassification` |  | `upin/detection/signal_identifier.py` | 34-39 |
| `ModulationType` |  | `upin/detection/signal_identifier.py` | 42-52 |
| `SignalSignature` | Complete signature of a detected signal. | `upin/detection/signal_identifier.py` | 56-72 |
| `SignalIdentifier` | Classify unknown signals by frequency, modulation, power, timing. | `upin/detection/signal_identifier.py` | 124-245 |

---
## Vision & Object Detection

| Class | Description | File | Lines |
|-------|-------------|------|-------|
| `DroneType` |  | `upin/vision/drone_recognition.py` | 23-31 |
| `ThreatLevel` |  | `upin/vision/drone_recognition.py` | 34-38 |
| `DroneDetection` | One detected drone from vision analysis. | `upin/vision/drone_recognition.py` | 42-67 |
| `DroneRecognizer` | Vision AI system for real-time drone recognition. | `upin/vision/drone_recognition.py` | 70-342 |
| `Detection` | A single object detection result. | `upin/vision/rf_detr_extractor.py` | 41-46 |
| `RFDETRExtractor` | RF-DETR feature extractor with lazy loading and graceful fallback. | `upin/vision/rf_detr_extractor.py` | 49-201 |
| `DetectedLandmark` | An object detected by camera that can confirm position. | `upin/vision/visual_intelligence.py` | 46-58 |
| `GroundObjectDetector` | Detect and classify objects on the ground from camera feed. | `upin/vision/visual_intelligence.py` | 81-173 |
| `MapMarker` | A known object on the satellite/map image. | `upin/vision/visual_intelligence.py` | 181-187 |
| `SatelliteImageMatcher` | Match live camera detections against pre-loaded satellite imagery. | `upin/vision/visual_intelligence.py` | 190-292 |
| `RouteCheckpoint` | An expected landmark along the flight path. | `upin/vision/visual_intelligence.py` | 300-309 |
| `FlightPathVerifier` | Verify flight path by confirming expected landmarks along the route. | `upin/vision/visual_intelligence.py` | 312-381 |
| `TrackedTarget` | A target being actively tracked across frames. | `upin/vision/visual_intelligence.py` | 389-403 |
| `TargetTracker` | Track detected objects across frames for homing/targeting. | `upin/vision/visual_intelligence.py` | 406-572 |
| `VisualIntelligenceSystem` | Unified visual intelligence combining all RF-DETR capabilities. | `upin/vision/visual_intelligence.py` | 579-649 |

---
## Sensor Agents & API Integrations

| Class | Description | File | Lines |
|-------|-------------|------|-------|
| `BaseAgent` | Abstract base class for all UPIN agents. | `upin/agents/base_agent.py` | 18-49 |
| `OpenMeteoWeatherAPI` | Open-Meteo: Free weather API — no key required. | `upin/agents/environmental_api_hub.py` | 50-76 |
| `OpenMeteoAirQualityAPI` | Open-Meteo Air Quality: Free — no key. | `upin/agents/environmental_api_hub.py` | 79-92 |
| `OpenMeteoMarineAPI` | Open-Meteo Marine: Free — no key. | `upin/agents/environmental_api_hub.py` | 95-108 |
| `USGSEarthquakeAPI` | USGS Earthquake Hazards: Free — no key. | `upin/agents/environmental_api_hub.py` | 115-143 |
| `NOAASpaceWeatherAPI` | NOAA SWPC: Free — no key. | `upin/agents/environmental_api_hub.py` | 150-185 |
| `SunMoonCalculator` | Sun and Moon position calculator — pure offline math, no API needed. | `upin/agents/environmental_api_hub.py` | 188-255 |
| `TidalAPI` | World Tides API: Free tier (500 calls/month). | `upin/agents/environmental_api_hub.py` | 258-278 |
| `BlitzortungLightningAPI` | Blitzortung: Free real-time lightning detection network. | `upin/agents/environmental_api_hub.py` | 285-309 |
| `EnvironmentalAPIHub` | Central hub that queries all free environmental APIs and returns | `upin/agents/environmental_api_hub.py` | 316-377 |
| `OpenElevationAPI` | Free elevation data from SRTM/DEM datasets. | `upin/agents/free_api_integrations.py` | 25-109 |
| `NOAAMagneticModel` | NOAA World Magnetic Model — magnetic declination, inclination, intensi... | `upin/agents/free_api_integrations.py` | 114-200 |
| `IPGeolocation` | Free IP-based geolocation (coarse, city-level ~5-50km accuracy). | `upin/agents/free_api_integrations.py` | 205-258 |
| `HYGStarDatabase` | Reference to the HYG stellar database (120,000+ stars). | `upin/agents/free_api_integrations.py` | 263-331 |
| `GNSSAgent` | GNSS positioning agent with multi-constellation support. | `upin/agents/gnss_agent.py` | 21-154 |
| `Find3WiFiFingerprinting` | Find3: Open-source indoor positioning via WiFi fingerprint matching. | `upin/agents/indoor_positioning.py` | 26-128 |
| `PedestrianDeadReckoning` | Step-counting IMU navigation for GPS-denied indoor/underground. | `upin/agents/indoor_positioning.py` | 135-261 |
| `LEO_PNT_Agent` | Low Earth Orbit Positioning Navigation and Timing Agent. | `upin/agents/leo_pnt_agent.py` | 21-94 |
| `FishSchoolParameters` | Parameters for a single fish school | `upin/agents/multi_layer_fish_schooling.py` | 20-30 |
| `MultiLayerFishSchooling` | Multi-Layer Fish Schooling with Adaptive Parameter Learning | `upin/agents/multi_layer_fish_schooling.py` | 32-415 |
| `CellTower` | One detected cell tower. | `upin/agents/real_cellular_agent.py` | 32-41 |
| `CellPosition` | Position result from cell tower positioning. | `upin/agents/real_cellular_agent.py` | 45-53 |
| `RealCellularPositioningAgent` | Real cellular positioning using tower scan + OpenCellID / MLS APIs. | `upin/agents/real_cellular_agent.py` | 56-451 |
| `GPSReading` |  | `upin/agents/real_phone_sensor_agent.py` | 26-35 |
| `IMUReading` |  | `upin/agents/real_phone_sensor_agent.py` | 39-50 |
| `BaroReading` |  | `upin/agents/real_phone_sensor_agent.py` | 54-58 |
| `SensorSnapshot` | Complete snapshot of all phone sensors at one moment. | `upin/agents/real_phone_sensor_agent.py` | 62-69 |
| `RealPhoneSensorAgent` | Accesses real device sensors: GPS, accelerometer, gyroscope, | `upin/agents/real_phone_sensor_agent.py` | 72-510 |
| `WiFiNetwork` | One detected WiFi network. | `upin/agents/real_wifi_agent.py` | 30-36 |
| `WiFiPosition` | Position result from WiFi-based positioning. | `upin/agents/real_wifi_agent.py` | 40-47 |
| `RealWiFiPositioningAgent` | Real WiFi positioning using device WiFi scan + Mozilla Location Servic... | `upin/agents/real_wifi_agent.py` | 50-385 |

---
*Generated automatically. 86 layers, 523 classes, 43,057 lines of code.*
