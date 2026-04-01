"""
Environmental & Astronomical Free API Hub — UPIN

Central hub for all free environmental and astronomical APIs that
enhance UPIN positioning layers. Each API is queried only when needed,
results are cached, and graceful fallbacks are provided.

All APIs are FREE with no key required unless noted.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
import math
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple


def _get_json(url: str, timeout: int = 5) -> Optional[Dict]:
    """Helper: GET JSON from URL with timeout."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "UPIN/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _post_json(url: str, data: Dict, timeout: int = 5) -> Optional[Dict]:
    """Helper: POST JSON to URL with timeout."""
    try:
        payload = json.dumps(data).encode()
        req = urllib.request.Request(url, data=payload,
                                      headers={"Content-Type": "application/json",
                                                "User-Agent": "UPIN/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════
#  WEATHER & ATMOSPHERIC APIs
# ══════════════════════════════════════════════════════════════════

class OpenMeteoWeatherAPI:
    """
    Open-Meteo: Free weather API — no key required.
    Temperature, humidity, pressure, wind, precipitation, visibility.
    Source: https://open-meteo.com
    UPIN layers: BarometricAltitude, Chemical Gradient, Optic Flow
    """
    BASE = "https://api.open-meteo.com/v1/forecast"

    def __init__(self):
        self._cache: Dict[str, Dict] = {}

    def get_current_weather(self, lat: float, lon: float) -> Optional[Dict]:
        key = f"{lat:.2f},{lon:.2f}"
        if key in self._cache and time.time() - self._cache[key].get("_ts", 0) < 600:
            return self._cache[key]
        url = (f"{self.BASE}?latitude={lat}&longitude={lon}"
               "&current=temperature_2m,relative_humidity_2m,surface_pressure,"
               "wind_speed_10m,wind_direction_10m,precipitation,visibility,"
               "weather_code")
        data = _get_json(url, timeout=5)
        if data and "current" in data:
            result = data["current"]
            result["_ts"] = time.time()
            self._cache[key] = result
            return result
        return None


class OpenMeteoAirQualityAPI:
    """
    Open-Meteo Air Quality: Free — no key.
    PM2.5, PM10, ozone, NO2, SO2, CO, dust, pollen.
    UPIN layers: ChemicalGradient (chemgrad_l26)
    """
    BASE = "https://air-quality-api.open-meteo.com/v1/air-quality"

    def get_air_quality(self, lat: float, lon: float) -> Optional[Dict]:
        url = (f"{self.BASE}?latitude={lat}&longitude={lon}"
               "&current=pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,"
               "sulphur_dioxide,ozone,dust,uv_index")
        data = _get_json(url)
        return data.get("current") if data else None


class OpenMeteoMarineAPI:
    """
    Open-Meteo Marine: Free — no key.
    Wave height, period, direction, ocean current speed.
    UPIN layers: HydrodynamicWake (hydrowake_l37), LateralLine (latline_l48)
    """
    BASE = "https://marine-api.open-meteo.com/v1/marine"

    def get_marine_conditions(self, lat: float, lon: float) -> Optional[Dict]:
        url = (f"{self.BASE}?latitude={lat}&longitude={lon}"
               "&current=wave_height,wave_direction,wave_period,"
               "ocean_current_velocity,ocean_current_direction")
        data = _get_json(url)
        return data.get("current") if data else None


# ══════════════════════════════════════════════════════════════════
#  SEISMIC & GEOLOGICAL APIs
# ══════════════════════════════════════════════════════════════════

class USGSEarthquakeAPI:
    """
    USGS Earthquake Hazards: Free — no key.
    Real-time earthquake detection worldwide.
    UPIN layers: SeismicInfrasound (seismic_l36)
    """
    BASE = "https://earthquake.usgs.gov/fdsnws/event/1/query"

    def get_recent_earthquakes(self, lat: float, lon: float,
                                radius_km: float = 500,
                                min_magnitude: float = 2.0,
                                hours: int = 24) -> Optional[List[Dict]]:
        url = (f"{self.BASE}?format=geojson"
               f"&latitude={lat}&longitude={lon}"
               f"&maxradiuskm={radius_km}"
               f"&minmagnitude={min_magnitude}"
               f"&starttime=-{hours}hours"
               "&limit=10&orderby=time")
        data = _get_json(url, timeout=10)
        if data and "features" in data:
            return [{
                "magnitude": f["properties"]["mag"],
                "place": f["properties"]["place"],
                "time": f["properties"]["time"],
                "lat": f["geometry"]["coordinates"][1],
                "lon": f["geometry"]["coordinates"][0],
                "depth_km": f["geometry"]["coordinates"][2],
            } for f in data["features"]]
        return None


# ══════════════════════════════════════════════════════════════════
#  SPACE WEATHER & ASTRONOMICAL APIs
# ══════════════════════════════════════════════════════════════════

class NOAASpaceWeatherAPI:
    """
    NOAA SWPC: Free — no key.
    Solar wind, geomagnetic storms, aurora forecast.
    UPIN layers: IonosphericDensity (ionosphere_l49), SchumannResonance (schumann_l59)
    """
    BASE = "https://services.swpc.noaa.gov"

    def get_planetary_k_index(self) -> Optional[Dict]:
        """Kp index — geomagnetic activity (affects GPS accuracy)."""
        url = f"{self.BASE}/products/noaa-planetary-k-index.json"
        data = _get_json(url)
        if data and len(data) > 1:
            latest = data[-1]
            return {"kp": float(latest[1]), "time": latest[0],
                    "gps_impact": "HIGH" if float(latest[1]) >= 5 else
                                  "MODERATE" if float(latest[1]) >= 3 else "LOW"}
        return None

    def get_solar_wind(self) -> Optional[Dict]:
        """Real-time solar wind speed and density."""
        url = f"{self.BASE}/products/solar-wind/plasma-7-day.json"
        data = _get_json(url, timeout=10)
        if data and len(data) > 2:
            latest = data[-1]
            return {"density": latest[1], "speed_km_s": latest[2], "temperature": latest[3]}
        return None

    def get_aurora_forecast(self) -> Optional[str]:
        """Aurora probability forecast (affects magnetic navigation)."""
        url = f"{self.BASE}/text/3-day-forecast.txt"
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                return r.read().decode()[:500]
        except Exception:
            return None


class SunMoonCalculator:
    """
    Sun and Moon position calculator — pure offline math, no API needed.
    UPIN layers: MonarchSunCompass (monarch_e10), PolarisedSky (polsky_l25a),
                 StellarConstellation (stellar_l46)
    """

    @staticmethod
    def sun_position(lat: float, lon: float, timestamp: float = None) -> Dict:
        """Calculate sun azimuth and elevation."""
        t = timestamp or time.time()
        # Julian date
        jd = t / 86400.0 + 2440587.5
        n = jd - 2451545.0

        # Mean longitude and anomaly
        L = (280.460 + 0.9856474 * n) % 360
        g = math.radians((357.528 + 0.9856003 * n) % 360)

        # Ecliptic longitude
        lam = math.radians(L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))

        # Obliquity
        eps = math.radians(23.439 - 0.0000004 * n)

        # Right ascension and declination
        ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
        dec = math.asin(math.sin(eps) * math.sin(lam))

        # Hour angle
        gmst = (280.46061837 + 360.98564736629 * n) % 360
        lmst = math.radians((gmst + lon) % 360)
        ha = lmst - ra

        # Altitude and azimuth
        lat_r = math.radians(lat)
        alt = math.asin(math.sin(lat_r) * math.sin(dec) +
                         math.cos(lat_r) * math.cos(dec) * math.cos(ha))
        az = math.atan2(-math.sin(ha),
                         math.tan(dec) * math.cos(lat_r) - math.sin(lat_r) * math.cos(ha))

        return {
            "azimuth_deg": round(math.degrees(az) % 360, 2),
            "elevation_deg": round(math.degrees(alt), 2),
            "declination_deg": round(math.degrees(dec), 2),
            "is_daytime": math.degrees(alt) > 0,
        }

    @staticmethod
    def moon_phase(timestamp: float = None) -> Dict:
        """Calculate approximate moon phase."""
        t = timestamp or time.time()
        # Synodic month = 29.53059 days
        known_new_moon = 947182440  # Jan 6, 2000 18:14 UTC
        days_since = (t - known_new_moon) / 86400.0
        phase = (days_since % 29.53059) / 29.53059

        names = ["New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
                 "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent"]
        idx = int(phase * 8) % 8
        illumination = 0.5 * (1 - math.cos(2 * math.pi * phase))

        return {
            "phase": round(phase, 3),
            "phase_name": names[idx],
            "illumination": round(illumination, 2),
            "affects_visibility": illumination > 0.7,
        }


class TidalAPI:
    """
    World Tides API: Free tier (500 calls/month).
    UPIN layers: HydrodynamicWake, DepthPressure
    Source: https://www.worldtides.info (free key: demo)
    """

    def get_tide_prediction(self, lat: float, lon: float) -> Optional[Dict]:
        """Get simplified tidal prediction using lunar approximation."""
        # Offline tidal approximation using lunar position
        t = time.time()
        lunar_period_s = 12.4206 * 3600  # Semi-diurnal lunar tide
        phase = (t % lunar_period_s) / lunar_period_s
        height_m = 1.5 * math.sin(2 * math.pi * phase)  # Approximate +/-1.5m

        return {
            "tide_height_m": round(height_m, 2),
            "phase": round(phase, 3),
            "trend": "rising" if math.cos(2 * math.pi * phase) > 0 else "falling",
            "method": "lunar_approximation",
        }


# ══════════════════════════════════════════════════════════════════
#  LIGHTNING & EM ENVIRONMENT
# ══════════════════════════════════════════════════════════════════

class BlitzortungLightningAPI:
    """
    Blitzortung: Free real-time lightning detection network.
    UPIN layers: SeismicInfrasound, RFAnomalyDetection
    Note: Official API requires registration; we use public GeoJSON feed.
    """

    def get_recent_strikes(self, lat: float, lon: float,
                           radius_km: float = 100) -> Optional[List[Dict]]:
        """Approximate lightning density (uses NOAA alternative)."""
        # Use NOAA severe weather alerts as proxy
        url = f"https://api.weather.gov/alerts/active?point={lat},{lon}"
        data = _get_json(url)
        if data and "features" in data:
            alerts = []
            for f in data["features"][:5]:
                props = f["properties"]
                if "thunder" in props.get("event", "").lower() or "lightning" in props.get("description", "").lower():
                    alerts.append({
                        "event": props["event"],
                        "severity": props.get("severity", "unknown"),
                        "headline": props.get("headline", ""),
                    })
            return alerts
        return None


# ══════════════════════════════════════════════════════════════════
#  MASTER API HUB
# ══════════════════════════════════════════════════════════════════

class EnvironmentalAPIHub:
    """
    Central hub that queries all free environmental APIs and returns
    a combined environmental picture for UPIN layer enhancement.
    """

    def __init__(self):
        self.weather = OpenMeteoWeatherAPI()
        self.air_quality = OpenMeteoAirQualityAPI()
        self.marine = OpenMeteoMarineAPI()
        self.seismic = USGSEarthquakeAPI()
        self.space_weather = NOAASpaceWeatherAPI()
        self.sun_moon = SunMoonCalculator()
        self.tidal = TidalAPI()
        self.lightning = BlitzortungLightningAPI()

    def get_full_environment(self, lat: float, lon: float) -> Dict:
        """Query all APIs and return complete environmental picture."""
        result: Dict[str, Any] = {"lat": lat, "lon": lon, "timestamp": time.time()}

        result["weather"] = self.weather.get_current_weather(lat, lon)
        result["air_quality"] = self.air_quality.get_air_quality(lat, lon)
        result["marine"] = self.marine.get_marine_conditions(lat, lon)
        result["earthquakes"] = self.seismic.get_recent_earthquakes(lat, lon)
        result["space_weather"] = self.space_weather.get_planetary_k_index()
        result["sun"] = self.sun_moon.sun_position(lat, lon)
        result["moon"] = self.sun_moon.moon_phase()
        result["tidal"] = self.tidal.get_tide_prediction(lat, lon)

        # Count successful queries
        result["apis_reached"] = sum(1 for k, v in result.items()
                                      if k not in ("lat", "lon", "timestamp", "apis_reached")
                                      and v is not None)
        result["apis_total"] = 8

        return result

    def get_layer_adjustments(self, lat: float, lon: float) -> Dict[str, float]:
        """Get recommended layer weight adjustments from environment."""
        env = self.get_full_environment(lat, lon)
        adjustments: Dict[str, float] = {}

        # GPS degradation from space weather
        sw = env.get("space_weather")
        if sw and sw.get("gps_impact") == "HIGH":
            adjustments["gps_l1"] = 0.5
            adjustments["navic_l2"] = 0.5

        # Visibility affects optical layers
        weather = env.get("weather")
        if weather:
            vis = weather.get("visibility", 10000)
            if vis < 1000:
                adjustments["vslam_l31"] = 0.3
                adjustments["terrain_l5"] = 0.4

        # Seismic activity affects inertial
        quakes = env.get("earthquakes")
        if quakes and len(quakes) > 0:
            adjustments["seismic_l36"] = 1.5  # Boost seismic layer

        return adjustments
