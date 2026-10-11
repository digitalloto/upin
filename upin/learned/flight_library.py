"""
The flight library: every test flight, the weather it flew in, and every
version of the AI motion predictor -- and the cycle that improves it.

AFTER EACH TEST FLIGHT

  python tools/learn_from_flight.py <flight.bin> --airframe <id> [--notes notes.json]

  1 extract     the autopilot's log: IMU, attitude, throttle, barometer, GPS
  2 weather     measure the flight's wind and gusts with the Wind Learner
                (attitude + GNSS velocity), temperature and pressure from the
                barometer; attach the operator's notes (payload, site, IMD
                report). Saved beside the data.
  3 test        score the current live model on this flight BEFORE learning
                from it -- a flight it has never seen, so an honest score
  4 train       a new version on all training flights; validation flights
                (every third usable flight) are never trained on
  5 promote     the new version goes live only if it is no worse than the
                live one on the validation flights; every version is kept
  6 report      LEARNED_IO.md in the library: this flight's score, the
                learning curve, the weather covered, promoted or not and why

RULES THE LIBRARY ENFORCES

- One airframe per library: a model learns one airframe.
- Simulated and real flights are never mixed in one library.
- A flight whose wind cannot be measured (it never held steady legs on
  different headings) is kept but not trained on, with the reason.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from upin.core.wind_learner import FlightSample, WindLearner
from upin.learned.features import (N_FEATURES, RATE_HZ, STRIDE_S, FlightRecord,
                                   from_heading_frame, input_ranges,
                                   mean_thrust_direction, windows)
from upin.learned.inertial_net import Z95, InertialNet

MIN_WINDOWS = 60
STRETCHES_S = (30, 60, 120)
R95_PER_SIGMA = 2.4477


# -- 1. extraction from an ArduPilot dataflash log -------------------------

LOG_TYPES = ("IMU", "ATT", "GPS", "GPA", "RCOU", "CTUN", "BARO")


def read_dataflash(path: str) -> Dict[str, List[dict]]:
    """Messages from an ArduPilot .bin log, as dicts per type. UNTESTED on a
    real log: field names are ArduPilot's dataflash names (IMU.AccX, ATT.Roll,
    GPS.Spd ...) and must be checked against the firmware that wrote it."""
    try:
        from pymavlink import mavutil  # noqa: WPS433 -- lazy by design
    except ImportError as exc:
        raise SystemExit("needs `pip install pymavlink` (the [box] extra)") from exc
    log = mavutil.mavlink_connection(path)
    out: Dict[str, List[dict]] = {k: [] for k in LOG_TYPES}
    while True:
        m = log.recv_match(type=list(LOG_TYPES))
        if m is None:
            break
        out[m.get_type()].append(m.to_dict())
    return out


def record_from_messages(msgs: Dict[str, List[dict]], flight_id: str,
                         airframe_id: str, source: str) -> FlightRecord:
    """Dataflash messages -> a FlightRecord on a RATE_HZ grid.

    GNSS velocity counts as good only with a 3-D fix, at least 6 satellites,
    HDOP <= 2 and, where the log has GPA, horizontal accuracy <= 3 m."""
    def series(kind, field, instance_ok=lambda m: True):
        rows = [m for m in msgs.get(kind, []) if field in m and instance_ok(m)]
        return (np.array([m["TimeUS"] for m in rows], float) * 1e-6,
                np.array([m[field] for m in rows], float))

    first = lambda m: m.get("I", m.get("Instance", 0)) == 0  # noqa: E731
    t_imu, _ = series("IMU", "AccX", first)
    t_att, _ = series("ATT", "Roll")
    t_gps, _ = series("GPS", "Spd", first)
    if min(len(t_imu), len(t_att), len(t_gps)) < 10:
        raise ValueError("log lacks IMU, ATT or GPS messages")
    t0 = max(t_imu[0], t_att[0], t_gps[0])
    t1 = min(t_imu[-1], t_att[-1], t_gps[-1])
    grid = np.arange(t0, t1, 1.0 / RATE_HZ)

    def interp(kind, field, inst=lambda m: True):
        t, v = series(kind, field, inst)
        return np.interp(grid, t, v)

    acc = np.stack([interp("IMU", f, first) for f in ("AccX", "AccY", "AccZ")], 1)
    gyro = np.stack([interp("IMU", f, first) for f in ("GyrX", "GyrY", "GyrZ")], 1)
    roll = np.radians(interp("ATT", "Roll"))
    pitch = np.radians(interp("ATT", "Pitch"))
    t_y, yaw = series("ATT", "Yaw")
    yaw = np.interp(grid, t_y, np.unwrap(np.radians(yaw))) % (2 * math.pi)

    if msgs.get("CTUN") and "ThO" in msgs["CTUN"][0]:
        throttle = interp("CTUN", "ThO")
    else:
        pwm = np.stack([interp("RCOU", f"C{i}") for i in range(1, 5)], 1)
        throttle = np.clip((pwm.mean(axis=1) - 1000.0) / 1000.0, 0, 1)

    spd, crs = interp("GPS", "Spd", first), np.radians(interp("GPS", "GCrs", first))
    ok = ((interp("GPS", "Status", first) >= 3) & (interp("GPS", "NSats", first) >= 6)
          & (interp("GPS", "HDop", first) <= 2.0))
    if msgs.get("GPA"):
        ok &= interp("GPA", "HAcc", first) <= 3.0
    temp = interp("BARO", "Temp", first) if msgs.get("BARO") else None
    press = interp("BARO", "Press", first) / 100.0 if msgs.get("BARO") else None
    return FlightRecord(flight_id, grid - grid[0], roll, pitch, yaw, acc, gyro,
                        throttle, spd * np.cos(crs), spd * np.sin(crs), ok,
                        temp, press, airframe_id, source)


# -- 2. the flight's weather, measured --------------------------------------

def measure_conditions(rec: FlightRecord) -> dict:
    """Wind and gusts from the Wind Learner, fed one-second averages of
    thrust direction, tilt and GNSS velocity while GNSS is good; temperature
    and pressure from the barometer; what the flight spanned."""
    wl = WindLearner(window_s=1e9)
    n = int(RATE_HZ)
    for e in range(n, len(rec) + 1, n):
        sl = slice(e - n, e)
        if rec.gnss_ok is None or not rec.gnss_ok[sl].all():
            continue
        tilt, d = mean_thrust_direction(rec.roll[sl], rec.pitch[sl], rec.yaw[sl])
        wl.add_sample(FlightSample(float(rec.t[e - 1]), d, tilt,
                                   float(rec.gnss_vn[sl].mean()),
                                   float(rec.gnss_ve[sl].mean()), 0.05))
    est = wl.estimate(float(rec.t[-1]))
    speed = np.hypot(rec.gnss_vn, rec.gnss_ve) if rec.gnss_vn is not None else None
    c = {
        "duration_s": float(rec.t[-1] - rec.t[0]),
        "gnss_good_fraction": float(rec.gnss_ok.mean()) if rec.gnss_ok is not None else 0.0,
        "wind": None if est is None else {
            "north_ms": est.north_ms, "east_ms": est.east_ms,
            "speed_ms": est.speed_ms, "toward_deg": est.toward_deg,
            "sigma_ms": est.sigma_ms, "gust_sigma_ms": est.gust_sigma_ms,
            "samples": est.samples},
        "wind_not_measured_because": None if est is not None else wl.why_not(),
        "temperature_c": None if rec.temperature_c is None else {
            "mean": float(rec.temperature_c.mean()), "min": float(rec.temperature_c.min()),
            "max": float(rec.temperature_c.max())},
        "pressure_hpa": None if rec.pressure_hpa is None else float(rec.pressure_hpa.mean()),
        "max_ground_speed_ms": None if speed is None else float(speed.max()),
        "inputs": input_ranges(rec),
    }
    return c


# -- 3. scoring a model on one flight ----------------------------------------

def predict_ground(model: InertialNet, X, yaw_end, wind) -> Tuple[np.ndarray, np.ndarray]:
    """Ground velocity (N, 2) and the model's own per-axis sigma (N,) for the
    air-velocity part. The wind's sigma is kept separate: a wind error does
    not average out, it is the same for the whole stretch."""
    mu, sig = model.predict(X)
    vn, ve = from_heading_frame(mu[:, 0], mu[:, 1], yaw_end)
    vn, ve = vn + wind["north_ms"], ve + wind["east_ms"]
    return np.stack([vn, ve], 1), sig.max(axis=1)


def error_correlation(model: InertialNet, recs_winds) -> float:
    """Lag-one correlation (one stride apart) of the model's normalised errors
    on the given flights. Errors that persist do not average out over a
    stretch; this measures how much they persist."""
    num = den = 0.0
    for rec, w in recs_winds:
        X, Y, _ = windows(rec, (w["north_ms"], w["east_ms"]))
        if len(X) < 3:
            continue
        mu, sig = model.predict(X)
        z = (Y - mu) / sig
        num += float((z[1:] * z[:-1]).sum())
        den += float((z * z).sum())
    return max(0.0, min(0.98, num / den)) if den else 0.0


def drift_sigma(s_air: np.ndarray, wind_sigma: float, rho: float, dt: float) -> float:
    """Per-axis 1-sigma of the position error after integrating these
    velocity predictions: the model's part, inflated for persistence as an
    AR(1) process, plus the wind error as a constant bias over the stretch."""
    inflation = (1 + rho) / (1 - rho)
    model_var = float((s_air ** 2).sum()) * dt * dt * inflation
    wind_var = (wind_sigma * len(s_air) * dt) ** 2
    return math.sqrt(model_var + wind_var)


def evaluate(model: InertialNet, rec: FlightRecord, wind: dict) -> dict:
    """Velocity error and coverage, and position drift over GNSS-free
    stretches compared with coasting on the last velocity (what the filter
    does with no sensor)."""
    X, _, ends = windows(rec, (wind["north_ms"], wind["east_ms"]))
    if len(X) < MIN_WINDOWS:
        return {"windows": len(X), "error": "too few windows"}
    v_pred, s_air = predict_ground(model, X, rec.yaw[ends], wind)
    s = np.sqrt(s_air ** 2 + wind["sigma_ms"] ** 2)
    rho = float(model.meta.get("error_rho", 0.0))
    v_true = np.stack([rec.gnss_vn[ends], rec.gnss_ve[ends]], 1)
    err = v_pred - v_true
    out = {"windows": int(len(X)),
           "velocity_rms_ms": float(np.sqrt((err ** 2).sum(axis=1).mean())),
           "velocity_coverage95": float(np.mean(np.abs(err) <= Z95 * s[:, None])),
           "error_rho_used": rho, "stretches": {}}
    dt = STRIDE_S
    for L in STRETCHES_S:
        k = int(L / dt)
        if len(err) < k:
            continue
        drift, coast, covered = [], [], 0
        for a in range(0, len(err) - k + 1, max(1, k // 2)):
            e = err[a:a + k].sum(axis=0) * dt
            c = (v_true[a] - v_true[a:a + k]).sum(axis=0) * dt
            r95 = R95_PER_SIGMA * drift_sigma(s_air[a:a + k], wind["sigma_ms"], rho, dt)
            drift.append(float(np.hypot(*e)))
            coast.append(float(np.hypot(*c)))
            covered += np.hypot(*e) <= r95
        out["stretches"][str(L)] = {
            "n": len(drift), "median_drift_m": float(np.median(drift)),
            "median_coast_drift_m": float(np.median(coast)),
            "circle_coverage95": covered / len(drift)}
    return out


# -- the library ------------------------------------------------------------

class FlightLibrary:
    def __init__(self, root: str):
        self.root = Path(root)
        (self.root / "flights").mkdir(parents=True, exist_ok=True)
        (self.root / "models").mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.root / "manifest.json"
        if self.manifest_path.exists():
            self.m = json.loads(self.manifest_path.read_text())
        else:
            self.m = {"airframe_id": None, "kind": None, "flights": [],
                      "models": [], "live": None}

    def _save(self):
        self.manifest_path.write_text(json.dumps(self.m, indent=1))

    # -- access --

    def flights(self, role: Optional[str] = None) -> List[dict]:
        return [f for f in self.m["flights"] if role is None or f["role"] == role]

    def load_flight(self, entry: dict) -> FlightRecord:
        return FlightRecord.load(str(self.root / "flights" / f"{entry['id']}.npz"),
                                 entry["id"], self.m["airframe_id"], entry["source"])

    def live_model(self) -> Optional[InertialNet]:
        v = self.m["live"]
        if v is None:
            return None
        return InertialNet.load(str(self.root / "models" / f"v{v}.npz"))

    def _dataset(self, role: str):
        Xs, Ys = [], []
        for f in self.flights(role):
            w = f["conditions"]["wind"]
            X, Y, _ = windows(self.load_flight(f), (w["north_ms"], w["east_ms"]))
            Xs.append(X)
            Ys.append(Y)
        if not Xs:
            return np.zeros((0, N_FEATURES)), np.zeros((0, 2))
        return np.concatenate(Xs), np.concatenate(Ys)

    def _score_on_validation(self, model: InertialNet) -> Optional[float]:
        X, Y = self._dataset("validation")
        return model.nll(X, Y) if len(X) >= 20 else None

    # -- the cycle --

    def learn_from_flight(self, rec: FlightRecord, notes: Optional[dict] = None,
                          epochs: int = 200, seed: int = 0) -> dict:
        kind = "simulated" if rec.source == "SIMULATED" else "real"
        if self.m["airframe_id"] not in (None, rec.airframe_id):
            raise ValueError(f"library is for airframe {self.m['airframe_id']!r}, "
                             f"flight is {rec.airframe_id!r}")
        if self.m["kind"] not in (None, kind):
            raise ValueError(f"library holds {self.m['kind']} flights; "
                             f"refusing to mix in a {kind} one")
        if any(f["id"] == rec.flight_id for f in self.m["flights"]):
            raise ValueError(f"flight {rec.flight_id} is already in the library")
        self.m["airframe_id"], self.m["kind"] = rec.airframe_id, kind

        cond = measure_conditions(rec)
        if notes:
            cond["operator_notes"] = notes
        X, _, _ = (windows(rec, (cond["wind"]["north_ms"], cond["wind"]["east_ms"]))
                   if cond["wind"] else (np.zeros((0, 1)), None, None))
        report = {"flight": rec.flight_id, "source": rec.source, "conditions": cond,
                  "time": time.strftime("%Y-%m-%d %H:%M")}

        # 3 test the live model first, on this unseen flight
        live = self.live_model()
        if live is not None and cond["wind"] and len(X) >= MIN_WINDOWS:
            report["before_learning"] = evaluate(live, rec, cond["wind"])
            report["before_learning"]["model"] = self.m["live"]

        # role
        usable = [f for f in self.m["flights"] if f["role"] != "unusable"]
        if not cond["wind"]:
            role, why = "unusable", f"wind not measured: {cond['wind_not_measured_because']}"
        elif len(X) < MIN_WINDOWS:
            role, why = "unusable", f"only {len(X)} windows with good GNSS"
        else:
            role = "validation" if len(usable) % 3 == 2 else "train"
            why = ""
        rec.save(str(self.root / "flights" / f"{rec.flight_id}.npz"))
        self.m["flights"].append({"id": rec.flight_id, "source": rec.source,
                                  "role": role, "why": why, "conditions": cond})
        report["role"], report["role_why"] = role, why

        # 4 train a new version
        Xt, Yt = self._dataset("train")
        if len(Xt) >= MIN_WINDOWS and role != "unusable":
            Xv, Yv = self._dataset("validation")
            has_val = len(Xv) >= 20
            net = InertialNet(N_FEATURES, seed=seed)
            hist = net.fit(Xt, Yt, Xv if has_val else None, Yv if has_val else None,
                           epochs=epochs if has_val else min(epochs, 80), seed=seed)
            net.calibrate(Xv if has_val else None, Yv if has_val else None)
            version = len(self.m["models"]) + 1
            net.meta = self._model_meta(version, has_val)
            rho_role = "validation" if has_val else "train"
            net.meta["error_rho"] = error_correlation(
                net, [(self.load_flight(f), f["conditions"]["wind"])
                      for f in self.flights(rho_role)])
            net.meta["error_rho_from"] = rho_role
            net.meta["error_rho_lag_s"] = STRIDE_S
            net.save(str(self.root / "models" / f"v{version}.npz"))
            new_score = self._score_on_validation(net)
            live_score = self._score_on_validation(live) if live is not None else None
            # 5 promote or keep
            if live is None:
                promoted, reason = True, "first model"
            elif new_score is None:
                promoted, reason = False, "no validation flights to compare on yet"
            elif live_score is None or new_score <= live_score:
                promoted, reason = True, (f"validation NLL {new_score:.3f} <= live "
                                          f"{live_score:.3f}" if live_score is not None
                                          else "live model was unvalidated")
            else:
                promoted, reason = False, (f"validation NLL {new_score:.3f} worse than "
                                           f"live {live_score:.3f}; live kept")
            entry = {"version": version, "trained_on": net.meta["trained_on"],
                     "validated_on": net.meta["validated_on"], "epochs": hist.epochs,
                     "validation_nll": new_score, "sigma_scale": net.sigma_scale,
                     "validated": has_val, "promoted": promoted, "reason": reason,
                     "created": report["time"]}
            if has_val:
                entry["validation_coverage95"] = net.coverage95(Xv, Yv)
            self.m["models"].append(entry)
            if promoted:
                self.m["live"] = version
            report["model"] = entry
        else:
            report["model"] = None
        self._save()
        self._write_report(report)
        return report

    def _model_meta(self, version: int, validated: bool) -> dict:
        train = self.flights("train")
        env = {"wind_speed_ms": [], "gust_sigma_ms": [], "temperature_c": [],
               "max_tilt_deg": [], "max_acc_horizontal_ms2": [], "max_gyro_rads": []}
        for f in train:
            c = f["conditions"]
            env["wind_speed_ms"].append(c["wind"]["speed_ms"])
            env["gust_sigma_ms"].append(c["wind"]["gust_sigma_ms"])
            if c["temperature_c"]:
                env["temperature_c"] += [c["temperature_c"]["min"], c["temperature_c"]["max"]]
            for k in ("max_tilt_deg", "max_acc_horizontal_ms2", "max_gyro_rads"):
                env[k].append(c["inputs"][k])
        envelope = {k: [min(v), max(v)] for k, v in env.items() if v}
        return {"version": version, "airframe_id": self.m["airframe_id"],
                "kind": self.m["kind"], "trained_on": [f["id"] for f in train],
                "validated_on": [f["id"] for f in self.flights("validation")],
                "validated": validated, "envelope": envelope}

    # -- 6 report --

    def _write_report(self, r: dict) -> None:
        path = self.root / "LEARNED_IO.md"
        L = []
        if not path.exists():
            L += ["# AI motion predictor: learning record", "",
                  f"Airframe `{self.m['airframe_id']}` · flights: **{self.m['kind']}**.",
                  "Each flight is scored by the live model *before* it is learned "
                  "from: a flight the model has never seen.", ""]
        c = r["conditions"]
        w = c["wind"]
        L += [f"## {r['flight']} — {r['time']}", "",
              f"Source: {r['source']} · {c['duration_s']:.0f} s · role: **{r['role']}**"
              + (f" ({r['role_why']})" if r["role_why"] else ""), "",
              "Weather (measured): " + (
                  f"wind {w['speed_ms']:.1f} m/s toward {w['toward_deg']:.0f}° "
                  f"(±{w['sigma_ms']:.1f}), gusts σ {w['gust_sigma_ms']:.2f} m/s"
                  if w else f"wind not measured — {c['wind_not_measured_because']}")
              + (f"; temperature {c['temperature_c']['mean']:.1f} °C"
                 if c["temperature_c"] else "") + ".", ""]
        b = r.get("before_learning")
        if b and "stretches" in b:
            L += [f"Live model v{b['model']} on this unseen flight: velocity error "
                  f"{b['velocity_rms_ms']:.2f} m/s rms, 95% coverage "
                  f"{b['velocity_coverage95']:.0%}.", "",
                  "| GNSS-free stretch | median drift, AI predictor | median drift, coasting | truth inside stated 95% circle |",
                  "|---|---:|---:|---:|"]
            for k, s in b["stretches"].items():
                L.append(f"| {k} s | {s['median_drift_m']:.1f} m | "
                         f"{s['median_coast_drift_m']:.1f} m | {s['circle_coverage95']:.0%} |")
            L.append("")
        elif self.m["live"] is None or not b:
            L += ["No live model to test on this flight yet.", ""]
        mdl = r.get("model")
        if mdl:
            L += [f"New version v{mdl['version']}: trained on {len(mdl['trained_on'])} "
                  f"flight(s), validated on {len(mdl['validated_on'])}"
                  + ("" if mdl["validated"] else " — **unvalidated** (no held-out flights yet)")
                  + f". {'**Promoted**' if mdl['promoted'] else 'Not promoted'}: {mdl['reason']}.", ""]
        path.write_text((path.read_text() if path.exists() else "") + "\n".join(L) + "\n")
