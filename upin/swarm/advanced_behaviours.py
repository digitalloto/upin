"""
Advanced Swarm Behaviours — UPIN

Four new subsystems for the next evolution of UPIN swarm intelligence:

1. MiroFish Scaling — hierarchical architecture to scale from 60 agents to millions
2. NETRA Tactical Layer — edge-first AI processing with sub-100ms anomaly detection
3. AI Intel Interface — natural language mission input and strategy adaptation
4. Termite Construction — collaborative task coordination for swarm operations

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np


# ══════════════════════════════════════════════════════════════════
#  1. MIROFISH SCALING — 60 agents to millions
# ══════════════════════════════════════════════════════════════════

class MiroFishHierarchy:
    """
    Hierarchical architecture for scaling swarm from 60 to millions.

    Structure (like a military chain of command):
      Level 0: Individual fish (sensor agent)           — millions
      Level 1: School (10 fish)                         — 100,000s
      Level 2: Pod (10 schools = 100 fish)              — 10,000s
      Level 3: Shoal (10 pods = 1000 fish)              — 1,000s
      Level 4: Fleet (10 shoals = 10,000 fish)          — 100s
      Level 5: Swarm Commander (all fleets)             — 1

    Each level only communicates with adjacent levels.
    Emergent intelligence arises from simple local rules at scale.
    """

    LEVELS = ["fish", "school", "pod", "shoal", "fleet", "commander"]

    def __init__(self, total_agents: int = 60):
        self.total_agents = total_agents
        self._hierarchy: Dict[str, Dict] = {}
        self._level_counts: Dict[int, int] = {}
        self._build_hierarchy()

    def _build_hierarchy(self):
        """Build hierarchical tree from total agents."""
        n = self.total_agents
        self._level_counts = {0: n}

        # Each higher level groups 10 of the level below
        level = 0
        while n > 1:
            level += 1
            n = max(1, n // 10)
            self._level_counts[level] = n

        # Create nodes
        for level, count in self._level_counts.items():
            level_name = self.LEVELS[min(level, len(self.LEVELS) - 1)]
            for i in range(count):
                node_id = f"L{level}_{level_name}_{i}"
                self._hierarchy[node_id] = {
                    "id": node_id,
                    "level": level,
                    "type": level_name,
                    "children": [],
                    "parent": None,
                    "position": None,
                    "consensus_position": None,
                    "status": "active",
                }

    def propagate_up(self, fish_positions: List[Tuple[float, float]]) -> Dict:
        """
        Bottom-up consensus: individual fish positions aggregate
        up through the hierarchy to produce global consensus.
        """
        if not fish_positions:
            return {"consensus": None, "levels_processed": 0}

        # Level 0: fish positions
        current_positions = list(fish_positions)
        levels_processed = 0

        # Aggregate up each level
        for level in range(1, max(self._level_counts.keys()) + 1):
            if len(current_positions) <= 1:
                break

            # Group into sets of 10
            next_positions = []
            for i in range(0, len(current_positions), 10):
                group = current_positions[i:i + 10]
                if group:
                    avg_lat = np.mean([p[0] for p in group])
                    avg_lon = np.mean([p[1] for p in group])
                    next_positions.append((float(avg_lat), float(avg_lon)))

            current_positions = next_positions
            levels_processed += 1

        consensus = current_positions[0] if current_positions else None
        return {
            "consensus": consensus,
            "levels_processed": levels_processed,
            "hierarchy_depth": max(self._level_counts.keys()),
            "total_agents": self.total_agents,
        }

    def propagate_down(self, command: Dict) -> List[Dict]:
        """
        Top-down command: commander issues order, propagates
        down through hierarchy to individual fish.
        """
        orders = []
        for level in sorted(self._level_counts.keys()):
            count = self._level_counts[level]
            level_name = self.LEVELS[min(level, len(self.LEVELS) - 1)]
            for i in range(count):
                orders.append({
                    "recipient": f"L{level}_{level_name}_{i}",
                    "command": command.get("action", "hold"),
                    "priority": command.get("priority", "normal"),
                    "propagation_delay_ms": level * 10,  # 10ms per level
                })
        return orders

    def scale_to(self, new_total: int) -> Dict:
        """Dynamically scale the swarm to a new size."""
        old_total = self.total_agents
        self.total_agents = new_total
        self._hierarchy.clear()
        self._build_hierarchy()
        return {
            "scaled_from": old_total,
            "scaled_to": new_total,
            "new_levels": max(self._level_counts.keys()),
            "nodes_created": len(self._hierarchy),
        }

    def get_stats(self) -> Dict:
        return {
            "total_agents": self.total_agents,
            "hierarchy_levels": len(self._level_counts),
            "level_counts": self._level_counts,
            "total_nodes": len(self._hierarchy),
        }


# ══════════════════════════════════════════════════════════════════
#  2. NETRA TACTICAL LAYER — edge-first AI, sub-100ms
# ══════════════════════════════════════════════════════════════════

class NETRATacticalLayer:
    """
    Edge-first AI processing with sub-100ms anomaly detection.

    NETRA = Navigation Enhanced Tactical Response Architecture

    Runs on the edge device (not cloud) for:
    - Sub-100ms anomaly detection (GPS spoofing, jamming, intrusion)
    - Real-time threat classification
    - Autonomous response triggering
    - Sensor fusion at wire speed

    Uses lightweight models that fit in device memory.
    """

    def __init__(self):
        self._anomaly_detectors: Dict[str, Callable] = {}
        self._response_actions: Dict[str, Callable] = {}
        self._detection_log: deque = deque(maxlen=500)
        self._latency_history: deque = deque(maxlen=100)
        self._threat_patterns: Dict[str, Dict] = {}

        # Register default anomaly detectors
        self._register_default_detectors()

    def _register_default_detectors(self):
        """Register built-in anomaly detectors."""
        self._anomaly_detectors["gps_spoofing"] = self._detect_gps_spoofing
        self._anomaly_detectors["rf_jamming"] = self._detect_rf_jamming
        self._anomaly_detectors["position_jump"] = self._detect_position_jump
        self._anomaly_detectors["sensor_tampering"] = self._detect_sensor_tampering
        self._anomaly_detectors["timing_anomaly"] = self._detect_timing_anomaly

    def process_tick(self, sensor_data: Dict) -> Dict:
        """
        Process one tick of sensor data through all detectors.
        Target: complete in <100ms.
        """
        start_ns = time.time_ns()
        detections = []

        for detector_name, detector_func in self._anomaly_detectors.items():
            try:
                result = detector_func(sensor_data)
                if result and result.get("detected"):
                    detections.append({
                        "type": detector_name,
                        **result,
                        "timestamp": time.time(),
                    })
            except Exception:
                pass

        elapsed_ms = (time.time_ns() - start_ns) / 1_000_000
        self._latency_history.append(elapsed_ms)

        if detections:
            self._detection_log.extend(detections)

        return {
            "detections": detections,
            "threat_count": len(detections),
            "processing_ms": round(elapsed_ms, 2),
            "under_100ms": elapsed_ms < 100,
            "detectors_active": len(self._anomaly_detectors),
        }

    def _detect_gps_spoofing(self, data: Dict) -> Optional[Dict]:
        gps = data.get("gps", {})
        if gps.get("accuracy_m", 0) > 50:
            return {"detected": True, "severity": "HIGH",
                    "detail": f"GPS accuracy degraded to {gps['accuracy_m']}m"}
        return {"detected": False}

    def _detect_rf_jamming(self, data: Dict) -> Optional[Dict]:
        rf = data.get("rf", {})
        if rf.get("noise_floor_dbm", -100) > -50:
            return {"detected": True, "severity": "CRITICAL",
                    "detail": f"RF noise floor elevated to {rf['noise_floor_dbm']}dBm"}
        return {"detected": False}

    def _detect_position_jump(self, data: Dict) -> Optional[Dict]:
        jump_m = data.get("position_jump_m", 0)
        if jump_m > 100:
            return {"detected": True, "severity": "HIGH",
                    "detail": f"Position jumped {jump_m:.0f}m in one tick"}
        return {"detected": False}

    def _detect_sensor_tampering(self, data: Dict) -> Optional[Dict]:
        accel = data.get("accel_magnitude", 9.81)
        if accel < 5 or accel > 15:
            return {"detected": True, "severity": "MEDIUM",
                    "detail": f"Accelerometer reads {accel:.1f} m/s² (expected ~9.81)"}
        return {"detected": False}

    def _detect_timing_anomaly(self, data: Dict) -> Optional[Dict]:
        clock_offset_ms = data.get("clock_offset_ms", 0)
        if abs(clock_offset_ms) > 50:
            return {"detected": True, "severity": "MEDIUM",
                    "detail": f"Clock offset {clock_offset_ms}ms"}
        return {"detected": False}

    def register_detector(self, name: str, detector_func: Callable):
        """Register a custom anomaly detector."""
        self._anomaly_detectors[name] = detector_func

    def get_avg_latency_ms(self) -> float:
        if not self._latency_history:
            return 0.0
        return float(np.mean(list(self._latency_history)))

    def get_stats(self) -> Dict:
        return {
            "detectors": len(self._anomaly_detectors),
            "total_detections": len(self._detection_log),
            "avg_latency_ms": round(self.get_avg_latency_ms(), 2),
            "max_latency_ms": round(max(self._latency_history), 2) if self._latency_history else 0,
            "under_100ms_rate": round(
                sum(1 for l in self._latency_history if l < 100) / max(len(self._latency_history), 1), 3
            ),
        }


# ══════════════════════════════════════════════════════════════════
#  3. AI INTEL INTERFACE — natural language mission input
# ══════════════════════════════════════════════════════════════════

class AIIntelInterface:
    """
    Natural language mission input and strategy adaptation.

    Parses mission commands like:
      "Patrol the northern border at 200m altitude"
      "Switch to covert mode and avoid the spoofing zone at 13.085N"
      "Deploy 3 scouts to investigate thermal contact bearing 045"

    Translates to UPIN actions: mode changes, layer presets, waypoints,
    swarm formations, and threat responses.
    """

    # Command patterns → UPIN actions
    COMMAND_PATTERNS = {
        "patrol": {"action": "set_mission", "mission": "patrol"},
        "recon": {"action": "set_mission", "mission": "recon"},
        "strike": {"action": "set_mission", "mission": "strike"},
        "casevac": {"action": "set_mission", "mission": "casevac"},
        "rescue": {"action": "set_mode", "mode": "RESCUE_SUPPORT"},
        "covert": {"action": "set_mode", "mode": "COVERT_ISR"},
        "ghost": {"action": "set_mode", "mode": "GHOST_RECON"},
        "silent": {"action": "set_mode", "mode": "GHOST_RECON"},
        "hunter": {"action": "set_mode", "mode": "HUNTER"},
        "engage": {"action": "set_mode", "mode": "HUNTER"},
        "sentinel": {"action": "set_mode", "mode": "SENTINEL"},
        "guard": {"action": "set_mode", "mode": "GUARDIAN"},
        "scout": {"action": "deploy_scouts", "count": 3},
        "investigate": {"action": "investigate"},
        "avoid": {"action": "add_no_go_zone"},
        "return": {"action": "return_to_base"},
        "rtb": {"action": "return_to_base"},
        "deploy": {"action": "deploy_units"},
        "formation": {"action": "set_formation"},
        "diamond": {"action": "set_formation", "formation": "diamond"},
        "line": {"action": "set_formation", "formation": "line"},
        "spread": {"action": "set_formation", "formation": "spread"},
    }

    def __init__(self):
        self._command_history: deque = deque(maxlen=100)
        self._active_missions: List[Dict] = []

    def parse_command(self, command_text: str) -> Dict:
        """
        Parse natural language command into UPIN actions.
        """
        words = command_text.lower().split()
        actions = []
        parameters = {}

        # Extract coordinates if present
        for i, word in enumerate(words):
            try:
                val = float(word.rstrip("°nsew,"))
                if 0 < val < 90 and "lat" not in parameters:
                    parameters["lat"] = val
                elif 60 < val < 180:
                    parameters["lon"] = val
            except ValueError:
                pass

            # Extract altitude
            if word.endswith("m") and i > 0 and words[i - 1] in ("at", "altitude"):
                try:
                    parameters["altitude_m"] = float(word.rstrip("m"))
                except ValueError:
                    pass

            # Extract bearing
            if word == "bearing" and i + 1 < len(words):
                try:
                    parameters["bearing_deg"] = float(words[i + 1])
                except ValueError:
                    pass

            # Extract count
            if word.isdigit():
                parameters["count"] = int(word)

        # Match command patterns
        for keyword, action_template in self.COMMAND_PATTERNS.items():
            if keyword in words:
                action = dict(action_template)
                action["parameters"] = parameters
                action["source_command"] = command_text
                actions.append(action)

        if not actions:
            actions.append({
                "action": "unknown",
                "source_command": command_text,
                "parameters": parameters,
                "suggestion": "Try: patrol, recon, strike, covert, scout, rtb, formation diamond",
            })

        result = {
            "command": command_text,
            "actions": actions,
            "parameters": parameters,
            "timestamp": time.time(),
        }

        self._command_history.append(result)
        return result

    def get_command_history(self) -> List[Dict]:
        return list(self._command_history)

    def get_suggested_commands(self) -> List[str]:
        return [
            "patrol northern border at 200m altitude",
            "switch to covert mode",
            "deploy 3 scouts bearing 045",
            "formation diamond",
            "investigate thermal contact at 13.085 80.275",
            "avoid spoofing zone at 13.090 80.280",
            "return to base",
            "hunter mode engage",
        ]


# ══════════════════════════════════════════════════════════════════
#  4. TERMITE CONSTRUCTION — collaborative task coordination
# ══════════════════════════════════════════════════════════════════

class TermiteConstruction:
    """
    Collaborative task coordination for swarm operations.
    Inspired by termite mound construction — no central plan,
    emergent structure from local rules.

    Applied to UPIN: distributed task allocation where each unit
    picks up tasks locally, building toward a collective objective
    without central coordination.
    """

    def __init__(self):
        self._tasks: Dict[str, Dict] = {}
        self._completed: List[Dict] = []
        self._workers: Dict[str, str] = {}  # unit_id → task_id

    def add_task(self, task_id: str, task_type: str,
                 position: Tuple[float, float],
                 priority: int = 5, requires: Optional[List[str]] = None):
        """Add a task that any swarm unit can pick up."""
        self._tasks[task_id] = {
            "id": task_id,
            "type": task_type,
            "position": position,
            "priority": priority,
            "requires": requires or [],
            "status": "pending",
            "assigned_to": None,
            "created": time.time(),
        }

    def assign_task(self, unit_id: str, unit_position: Tuple[float, float]) -> Optional[Dict]:
        """
        Unit requests a task — gets the nearest unassigned task it can do.
        Like a termite picking up the nearest piece of mud.
        """
        best_task = None
        best_dist = float("inf")

        for tid, task in self._tasks.items():
            if task["status"] != "pending":
                continue

            dist = math.sqrt(
                ((unit_position[0] - task["position"][0]) * 111320) ** 2 +
                ((unit_position[1] - task["position"][1]) * 111320) ** 2
            )

            # Prioritise by distance × inverse priority
            score = dist / max(task["priority"], 1)
            if score < best_dist:
                best_dist = score
                best_task = tid

        if best_task:
            self._tasks[best_task]["status"] = "assigned"
            self._tasks[best_task]["assigned_to"] = unit_id
            self._workers[unit_id] = best_task
            return self._tasks[best_task]

        return None

    def complete_task(self, unit_id: str) -> Optional[Dict]:
        """Unit reports task completion."""
        task_id = self._workers.pop(unit_id, None)
        if task_id and task_id in self._tasks:
            task = self._tasks.pop(task_id)
            task["status"] = "completed"
            task["completed_by"] = unit_id
            task["completed_at"] = time.time()
            self._completed.append(task)
            return task
        return None

    def get_progress(self) -> Dict:
        pending = sum(1 for t in self._tasks.values() if t["status"] == "pending")
        assigned = sum(1 for t in self._tasks.values() if t["status"] == "assigned")
        return {
            "pending": pending,
            "assigned": assigned,
            "completed": len(self._completed),
            "total": pending + assigned + len(self._completed),
            "workers_active": len(self._workers),
            "completion_rate": round(len(self._completed) / max(1, pending + assigned + len(self._completed)), 3),
        }
