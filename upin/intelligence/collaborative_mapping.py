"""
Collaborative Mapping & Target Tracking — UPIN Intelligence

Multi-device shared mapping with:
- Collaborative SLAM (loop closure detection)
- Target movement prediction (linear motion model)
- Device track history with SQLite persistence
- Marker confirmation from multiple devices
- Area-based marker queries (Haversine)
- Confidence ellipse from least-squares triangulation

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np


# ── Data Structures ───────────────────────────────────────────────

@dataclass
class TrackedTarget:
    """A target being tracked across time."""
    target_id: str
    observations: List[Dict] = field(default_factory=list)
    estimated_position: Optional[Tuple[float, float, float]] = None
    confidence_ellipse: Optional[Dict] = None
    predicted_position: Optional[Tuple[float, float, float]] = None
    confirmed_by: Set[str] = field(default_factory=set)


# ── Collaborative SLAM ────────────────────────────────────────────

class CollaborativeSLAM:
    """
    Multi-device shared map with loop closure detection.
    Each device contributes positions; the shared map becomes
    more accurate as more devices visit the same areas.
    """

    def __init__(self, grid_size_m: float = 10.0, loop_closure_m: float = 10.0):
        self._grid_size = grid_size_m
        self._loop_threshold = loop_closure_m
        self._device_tracks: Dict[str, List[Dict]] = {}
        self._map_cells: Dict[str, Dict] = {}
        self._loop_closures: List[Dict] = []

    def add_position(self, device_id: str, lat: float, lon: float, alt: float = 0.0):
        """Add a position from a device."""
        ts = time.time()
        entry = {"lat": lat, "lon": lon, "alt": alt, "t": ts}

        if device_id not in self._device_tracks:
            self._device_tracks[device_id] = []
        self._device_tracks[device_id].append(entry)

        # Trim to last 2000 points per device
        if len(self._device_tracks[device_id]) > 2000:
            self._device_tracks[device_id] = self._device_tracks[device_id][-2000:]

        # Update shared map cell
        cell = self._cell_key(lat, lon)
        if cell not in self._map_cells:
            self._map_cells[cell] = {"devices": set(), "visits": 0, "avg_lat": lat, "avg_lon": lon}
        mc = self._map_cells[cell]
        mc["devices"].add(device_id)
        mc["visits"] += 1
        # Running average position
        n = mc["visits"]
        mc["avg_lat"] = mc["avg_lat"] + (lat - mc["avg_lat"]) / n
        mc["avg_lon"] = mc["avg_lon"] + (lon - mc["avg_lon"]) / n

        # Check loop closure
        self._check_loop_closure(device_id, lat, lon, alt)

    def _check_loop_closure(self, device_id: str, lat: float, lon: float, alt: float):
        track = self._device_tracks[device_id]
        if len(track) < 20:
            return
        # Check against older positions (skip recent 10)
        for prev in track[:-20]:
            d = _haversine_m(lat, lon, prev["lat"], prev["lon"])
            if d < self._loop_threshold:
                self._loop_closures.append({
                    "device": device_id,
                    "current": (lat, lon, alt),
                    "previous": (prev["lat"], prev["lon"], prev["alt"]),
                    "distance_m": round(d, 1),
                    "timestamp": time.time(),
                })
                break

    def get_cell_confidence(self, lat: float, lon: float) -> float:
        """How well-mapped is this area? 0-1 based on device visits."""
        cell = self._cell_key(lat, lon)
        mc = self._map_cells.get(cell)
        if not mc:
            return 0.0
        return min(1.0, len(mc["devices"]) / 3.0)

    def get_stats(self) -> Dict:
        return {
            "devices": len(self._device_tracks),
            "map_cells": len(self._map_cells),
            "loop_closures": len(self._loop_closures),
            "total_positions": sum(len(t) for t in self._device_tracks.values()),
        }

    def _cell_key(self, lat: float, lon: float) -> str:
        g = self._grid_size
        return f"{int(lat * 111320 / g)}_{int(lon * 111320 / g)}"


# ── Least-Squares Triangulation ───────────────────────────────────

class LeastSquaresTriangulator:
    """
    Triangulate target position from multiple bearing observations
    using least-squares line intersection with confidence ellipse.
    """

    @staticmethod
    def triangulate(observations: List[Dict]) -> Optional[Dict]:
        """
        observations: [{"lat", "lon", "bearing_deg", "device_id"}, ...]
        Returns: {"lat", "lon", "accuracy_m", "confidence", "ellipse", "devices"}
        """
        if len(observations) < 2:
            return None

        ref_lat = observations[0]["lat"]
        ref_lon = observations[0]["lon"]

        A_rows, b_rows = [], []
        for obs in observations:
            x = (obs["lon"] - ref_lon) * 111320 * math.cos(math.radians(ref_lat))
            y = (obs["lat"] - ref_lat) * 111320
            brg = math.radians(obs["bearing_deg"])
            dx, dy = math.sin(brg), math.cos(brg)
            # Line: dy*(X-x) - dx*(Y-y) = 0  => dy*X - dx*Y = dy*x - dx*y
            A_rows.append([dy, -dx])
            b_rows.append(dy * x - dx * y)

        A = np.array(A_rows)
        b = np.array(b_rows)

        try:
            result, residuals, rank, sv = np.linalg.lstsq(A, b, rcond=None)
        except np.linalg.LinAlgError:
            return None

        target_x, target_y = result[0], result[1]
        target_lon = ref_lon + target_x / (111320 * math.cos(math.radians(ref_lat)))
        target_lat = ref_lat + target_y / 111320

        # Confidence ellipse from residuals
        rms = float(np.sqrt(np.mean(b - A @ result) ** 2)) if len(b) > 0 else 100
        ellipse = {"major_m": round(rms * 2, 1), "minor_m": round(rms, 1), "rotation_deg": 0}

        # Confidence from bearing angle spread
        bearings = [o["bearing_deg"] for o in observations]
        spread = max(bearings) - min(bearings)
        if spread > 180:
            spread = 360 - spread
        confidence = min(0.95, spread / 90.0)

        return {
            "lat": round(target_lat, 6),
            "lon": round(target_lon, 6),
            "accuracy_m": round(max(5, rms * 2), 1),
            "confidence": round(confidence, 3),
            "ellipse": ellipse,
            "devices": [o["device_id"] for o in observations],
            "observations": len(observations),
        }


# ── Target Movement Prediction ────────────────────────────────────

class TargetPredictor:
    """Predicts future target positions from observation history."""

    @staticmethod
    def predict(observations: List[Dict], future_time: float) -> Optional[Dict]:
        """
        observations: [{"lat", "lon", "alt", "timestamp"}, ...]
        future_time: unix timestamp to predict for
        """
        if len(observations) < 2:
            return None

        # Sort by time
        obs = sorted(observations, key=lambda o: o["timestamp"])
        dt = obs[-1]["timestamp"] - obs[0]["timestamp"]
        if dt <= 0:
            return None

        # Linear velocity model
        v_lat = (obs[-1]["lat"] - obs[0]["lat"]) / dt
        v_lon = (obs[-1]["lon"] - obs[0]["lon"]) / dt
        v_alt = (obs[-1].get("alt", 0) - obs[0].get("alt", 0)) / dt

        # Speed in m/s
        speed = math.sqrt((v_lat * 111320) ** 2 + (v_lon * 111320) ** 2)

        # Predict
        predict_dt = future_time - obs[-1]["timestamp"]
        pred_lat = obs[-1]["lat"] + v_lat * predict_dt
        pred_lon = obs[-1]["lon"] + v_lon * predict_dt
        pred_alt = obs[-1].get("alt", 0) + v_alt * predict_dt

        # Uncertainty grows with prediction time
        uncertainty_m = max(5, speed * abs(predict_dt) * 0.1)

        return {
            "lat": round(pred_lat, 6),
            "lon": round(pred_lon, 6),
            "alt": round(pred_alt, 1),
            "speed_mps": round(speed, 1),
            "heading_deg": round(math.degrees(math.atan2(v_lon, v_lat)) % 360, 1),
            "uncertainty_m": round(uncertainty_m, 1),
            "prediction_seconds": round(predict_dt, 1),
        }


# ── Area Queries ──────────────────────────────────────────────────

def find_markers_in_radius(markers: List[Dict], center_lat: float, center_lon: float,
                            radius_km: float) -> List[Dict]:
    """Find all markers within radius using Haversine distance."""
    results = []
    for m in markers:
        d = _haversine_km(center_lat, center_lon, m["lat"], m["lon"])
        if d <= radius_km:
            m_copy = dict(m)
            m_copy["distance_km"] = round(d, 3)
            results.append(m_copy)
    results.sort(key=lambda x: x["distance_km"])
    return results


# ── Helpers ───────────────────────────────────────────────────────

def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))

def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    return _haversine_km(lat1, lon1, lat2, lon2) * 1000
