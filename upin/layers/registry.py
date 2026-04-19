"""
UPIN Layer Registry — Factory for creating and managing all 60 layers.

Provides a single entry point to instantiate all navigation layers
grouped by their physical principle category. The fusion engine
uses this registry to discover and register available layers.
"""

from __future__ import annotations

from upin.core.layer_base import NavigationLayer

# Group A — Satellite & Celestial
from upin.layers.satellite.layers import (
    GPSLayer, NavICLayer, LEOAuthenticatedLayer,
    XRayPulsarLayer, StellarConstellationLayer, DiffuseSkyLayer,
)
from upin.layers.satellite.missing_constellations import (
    GLONASSLayer, GalileoLayer, BeiDouLayer, QZSSLayer, BluetoothAoALayer,
)
# Group B — Inertial & Timing
from upin.layers.inertial.layers import (
    INSDeadReckoningLayer, BarometricAltitudeLayer, DopplerVelocityLayer,
    LaserDopplerLayer, QuantumAtomicClockLayer, OpticFlowLayer,
    NMRGyroscopeLayer, SERFGyroscopeLayer, RadarAltimeterLayer, DepthPressureSensorLayer,
)
# Group C — Magnetic & Quantum
from upin.layers.magnetic.layers import (
    MagneticAnomalyLayer, DualQuantumMagnetometerLayer,
    MagneticMapMatchingLayer, EMInductionLayer,
    NVDiamondMagnetometerLayer, BiocoordinateGeoChemMagLayer,
    ElectricFieldSensingLayer,
)
# Group D — RF & Terrestrial
from upin.layers.rf.layers import (
    GroundEmitterLayer, WiFiMilitaryNavLayer, CellTowerHostileLayer,
    ELORANLayer, CommercialSOOPLayer, UWBPositioningLayer, LoRaWANNodeLayer,
)
# Group E — Optical & Vision
from upin.layers.optical.layers import (
    StarTrackingLayer, TerrainMatchingLayer, PolarisedSkyLayer,
    UnderwaterPolarisedLayer, VisualSLAMLayer, VisualOdometryLayer,
    LiDARSLAMLayer, ThermalIRLayer, HyperspectralLayer,
    MonarchSunCompassLayer,
)
# Group F — Acoustic
from upin.layers.acoustic.layers import (
    PassiveAcousticLayer, ActiveSonarLayer, FocusedSonarLayer,
)
# Group G — Gravity
from upin.layers.gravity.layers import (
    QuantumGravityGradiometerLayer, QuantumDualGravimeterLayer,
)
# Group H — Chemical, Seismic, Flow, Tactile
from upin.layers.chemical.layers import (
    ChemicalGradientLayer, SeismicInfrasoundLayer,
    HydrodynamicWakeLayer, TactilePressureLayer,
    LateralLineLayer, LocomotionOdometerLayer,
    IonosphericDensityLayer,
)
# Group I — Cosmic & Atmospheric
from upin.layers.cosmic.layers import (
    MuonNavigationLayer, PulsarExtendedLayer, SchumannResonanceLayer,
)
# Group J — Human & Crowd
from upin.layers.human.layers import (
    HumanBeaconNetworkLayer, CrowdsourcedSpoofingMapLayer,
    RadiusContainmentLayer,
)
# Group K — Systems Intelligence
from upin.layers.systems.layers import (
    AntennaStabilisationLayer, CascadePreventionLayer,
    SwarmRelativePositionLayer, RFAnomalyDetectionLayer,
    ArcticTernMultiCueLayer,
)
# Group L — Biological Predator-Prey
from upin.layers.biological.layers import (
    WolfPackCoordinationLayer, OwlSilentApproachLayer,
    SalmonHomingLayer, EagleThermalVisionLayer,
)
# New Group E layers — Eagle Eye stereo + ENC chart + DTED
from upin.layers.optical.eagle_eye import (
    EagleEyeStereoLayer, ENCChartMatchingLayer, DTEDMatchingLayer,
)
# New Group F layer — Bathymetric map matching
from upin.layers.acoustic.bathymetry import BathymetricMatchingLayer
# New Group H layers — Ocean current drift + Tidal timing position
from upin.layers.chemical.nautical import (
    OceanCurrentDriftLayer, TidalTimingPositionLayer,
)
# New Group K layer — Terrain fingerprint (mag+baro+cell+wifi)
from upin.layers.systems.terrain_fp_layer import TerrainFingerprintLayer


# Complete mapping of all 73 layers
ALL_LAYER_CLASSES: dict[str, type[NavigationLayer]] = {
    # Group A — Satellite & Celestial (6)
    "gps_l1": GPSLayer,
    "navic_l2": NavICLayer,
    "leo_l19": LEOAuthenticatedLayer,
    "xnav_l29": XRayPulsarLayer,
    "stellar_l46": StellarConstellationLayer,
    "skygrad_l47": DiffuseSkyLayer,
    "glonass_a07": GLONASSLayer,
    "galileo_a08": GalileoLayer,
    "beidou_a09": BeiDouLayer,
    "qzss_a10": QZSSLayer,
    # Group B — Inertial & Timing (8)
    "ins_l3": INSDeadReckoningLayer,
    "baro_l11": BarometricAltitudeLayer,
    "doppler_l12": DopplerVelocityLayer,
    "laserdop_l18": LaserDopplerLayer,
    "qclock_l27": QuantumAtomicClockLayer,
    "opticflow_l43": OpticFlowLayer,
    "nmrgyro_l57": NMRGyroscopeLayer,
    "serfgyro_l58": SERFGyroscopeLayer,
    "radaralt_b09": RadarAltimeterLayer,
    "depthpres_b10": DepthPressureSensorLayer,
    # Group C — Magnetic & Quantum (6)
    "magano_l6": MagneticAnomalyLayer,
    "dualqmag_l17": DualQuantumMagnetometerLayer,
    "magmap_l23": MagneticMapMatchingLayer,
    "eminduct_l24": EMInductionLayer,
    "nvdiamond_l30": NVDiamondMagnetometerLayer,
    "bicoord_l44": BiocoordinateGeoChemMagLayer,
    "efield_c07": ElectricFieldSensingLayer,
    # Group D — RF & Terrestrial (5)
    "groundrf_l7": GroundEmitterLayer,
    "wifi_l8": WiFiMilitaryNavLayer,
    "celltower_l9": CellTowerHostileLayer,
    "eloran_l41": ELORANLayer,
    "soop_l42": CommercialSOOPLayer,
    "uwb_d06": UWBPositioningLayer,
    "lora_d07": LoRaWANNodeLayer,
    "bluetooth_d08": BluetoothAoALayer,
    # Group E — Optical & Vision (9)
    "startrack_l4": StarTrackingLayer,
    "terrain_l5": TerrainMatchingLayer,
    "polsky_l25a": PolarisedSkyLayer,
    "polwater_l25b": UnderwaterPolarisedLayer,
    "vslam_l31": VisualSLAMLayer,
    "vio_l32": VisualOdometryLayer,
    "lidar_l33": LiDARSLAMLayer,
    "thermal_l38": ThermalIRLayer,
    "hyperspec_l39": HyperspectralLayer,
    "monarch_e10": MonarchSunCompassLayer,
    # Group F — Acoustic (3)
    "acoustic_l10": PassiveAcousticLayer,
    "sonar_l34": ActiveSonarLayer,
    "focsonar_l35": FocusedSonarLayer,
    # Group G — Gravity (2)
    "gravgrad_l28a": QuantumGravityGradiometerLayer,
    "gravimeter_l28b": QuantumDualGravimeterLayer,
    # Group H — Chemical/Seismic/Flow/Tactile (7)
    "chemgrad_l26": ChemicalGradientLayer,
    "seismic_l36": SeismicInfrasoundLayer,
    "hydrowake_l37": HydrodynamicWakeLayer,
    "tactile_l45": TactilePressureLayer,
    "latline_l48": LateralLineLayer,
    "odometer_l60": LocomotionOdometerLayer,
    "ionosphere_l49": IonosphericDensityLayer,
    # Group I — Cosmic & Atmospheric (3)
    "muon_l40": MuonNavigationLayer,
    "pulsar_l29b": PulsarExtendedLayer,
    "schumann_l59": SchumannResonanceLayer,
    # Group J — Human & Crowd (3)
    "beacon_l20": HumanBeaconNetworkLayer,
    "spoofmap_l21": CrowdsourcedSpoofingMapLayer,
    "radius_l22": RadiusContainmentLayer,
    # Group K — Systems Intelligence (4)
    "antenna_l13": AntennaStabilisationLayer,
    "cascade_l14": CascadePreventionLayer,
    "swarmrel_l15": SwarmRelativePositionLayer,
    "rfanomaly_l16": RFAnomalyDetectionLayer,
    "tern_k05": ArcticTernMultiCueLayer,
    # Group L — Biological Predator-Prey (4)
    "wolf_k06": WolfPackCoordinationLayer,
    "owl_e11": OwlSilentApproachLayer,
    "salmon_h08": SalmonHomingLayer,
    "eagle_e12": EagleThermalVisionLayer,
    # New Group E — Eagle Eye + ENC + DTED (3)
    "eagleeye_e13": EagleEyeStereoLayer,
    "enc_e14": ENCChartMatchingLayer,
    "dted_e15": DTEDMatchingLayer,
    # New Group F — Bathymetry (1)
    "bathymetry_f04": BathymetricMatchingLayer,
    # New Group H — Ocean current + Tidal timing (2)
    "oceancurrent_h09": OceanCurrentDriftLayer,
    "tidaltiming_h10": TidalTimingPositionLayer,
    # New Group K — Terrain fingerprint (1)
    "terrainfp_k07": TerrainFingerprintLayer,
}


class LayerRegistry:
    """Central registry for managing UPIN navigation layers."""

    def __init__(self):
        self._layers: dict[str, NavigationLayer] = {}

    def create_layer(self, layer_id: str) -> NavigationLayer:
        """Create a single layer by its ID."""
        if layer_id not in ALL_LAYER_CLASSES:
            raise ValueError(f"Unknown layer ID: {layer_id}")
        layer = ALL_LAYER_CLASSES[layer_id]()
        self._layers[layer_id] = layer
        return layer

    def create_group(self, group_letter: str) -> list[NavigationLayer]:
        """Create all layers in a group (A-K)."""
        from upin.core.layer_base import LayerGroup
        group_map = {g.value: g for g in LayerGroup}
        if group_letter not in group_map:
            raise ValueError(f"Unknown group: {group_letter}")

        target_group = group_map[group_letter]
        layers = []
        for lid, cls in ALL_LAYER_CLASSES.items():
            instance = cls()
            if instance.group == target_group:
                self._layers[lid] = instance
                layers.append(instance)
        return layers

    def create_all(self) -> list[NavigationLayer]:
        """Create all 60 navigation layers."""
        layers = []
        for lid, cls in ALL_LAYER_CLASSES.items():
            instance = cls()
            self._layers[lid] = instance
            layers.append(instance)
        return layers

    def create_minimal(self) -> list[NavigationLayer]:
        """Create minimum viable configuration (8-12 layers).

        Suitable for small drones under 1kg (~150g hardware addition).
        """
        minimal_ids = [
            "gps_l1", "navic_l2", "ins_l3", "baro_l11",
            "vslam_l31", "magano_l6", "rfanomaly_l16",
            "doppler_l12", "terrain_l5", "opticflow_l43",
        ]
        layers = []
        for lid in minimal_ids:
            layers.append(self.create_layer(lid))
        return layers

    def create_underwater(self) -> list[NavigationLayer]:
        """Create all underwater-capable layers."""
        layers = []
        for lid, cls in ALL_LAYER_CLASSES.items():
            instance = cls()
            if instance.is_underwater:
                self._layers[lid] = instance
                layers.append(instance)
        return layers

    def get_layer(self, layer_id: str) -> NavigationLayer | None:
        return self._layers.get(layer_id)

    @property
    def all_layers(self) -> dict[str, NavigationLayer]:
        return dict(self._layers)

    @staticmethod
    def available_layers() -> list[str]:
        return list(ALL_LAYER_CLASSES.keys())

    @staticmethod
    def layer_count() -> int:
        return len(ALL_LAYER_CLASSES)


def create_all_layers(sim_lat: float = 13.0827,
                      sim_lon: float = 80.2707,
                      sim_alt: float = 10.0,
                      world=None) -> list[NavigationLayer]:
    """Convenience: create all 60 layers with simulated position set.

    If a SimulationWorld is provided, each layer will use it for
    physics-based independent coordinate computation. Otherwise
    falls back to simple noise-on-position simulation.
    """
    registry = LayerRegistry()
    layers = registry.create_all()
    for layer in layers:
        layer.set_simulated_position(sim_lat, sim_lon, sim_alt)
        if world is not None:
            layer.set_world(world)
    return layers
