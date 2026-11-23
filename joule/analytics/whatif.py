"""What-if simulator: move a setting, see the predicted energy, cost and CO2 before changing anything.

Each model is fitted to the two MEASURED points of a receipt (baseline and optimized), so a slider between them is
interpolation and outside them is extrapolation (flagged). Results are ESTIMATED: a receipt proves only the two
settings that were actually run.

polling   energy per window E(x) = F + k / x        (F: fixed cost of the window, k: cost of one scan; x = seconds
                                                     between scans)
batching  energy per workload E(b) = W + L * ceil(jobs / b)   (W: the jobs' own work, L: one process launch)
app       saved Wh/day = power x hours/day
"""
from __future__ import annotations

import json
import math

from joule import config, energy


def latest_receipt(conn, scenario: str) -> dict | None:
    """Newest receipt for a scenario, MEASURED preferred, with its experiment parameters."""
    row = conn.execute(
        "SELECT r.id, r.body_json, r.provenance, e.params_json FROM receipts r LEFT JOIN experiments e "
        "ON e.id = r.experiment_id WHERE json_extract(r.body_json,'$.scenario') = ? "
        "ORDER BY (r.provenance = 'MEASURED') DESC, r.id DESC LIMIT 1", (scenario,)).fetchone()
    if not row:
        return None
    return {"receipt_id": row["id"], "body": json.loads(row["body_json"]), "provenance": row["provenance"],
            "params": json.loads(row["params_json"] or "{}")}


def _money(wh_day: float, a: config.Assumptions) -> dict:
    month = energy.scale(wh_day, 1, 30, a)
    return {"wh_per_day": wh_day, "inr_per_month": month["inr"], "co2_g_per_month": month["co2_g"]}


def polling_model(rc: dict) -> dict:
    p, b = rc["params"], rc["body"]
    f, s, dur = float(p["fast_s"]), float(p["slow_s"]), float(p["duration_s"])
    eb, eo = b["baseline_wh"], b["optimized_wh"]
    k = (eb - eo) / (1 / f - 1 / s)
    return {"fixed_wh": eb - k / f, "per_scan_wh": k, "fast_s": f, "slow_s": s, "window_s": dur}


def polling(rc: dict, interval_s: float, hours_per_day: float, a: config.Assumptions | None = None) -> dict:
    a = a or config.Assumptions()
    m = polling_model(rc)
    e = lambda x: m["fixed_wh"] + m["per_scan_wh"] / x                      # noqa: E731
    windows = hours_per_day * 3600 / m["window_s"]
    saved_day = (e(m["fast_s"]) - e(interval_s)) * windows
    return {"energy_per_window_wh": e(interval_s), "baseline_per_window_wh": e(m["fast_s"]),
            "saved_pct": 100 * (1 - e(interval_s) / e(m["fast_s"])), **_money(saved_day, a),
            "max_delay_s": interval_s, "extrapolated": not (m["fast_s"] <= interval_s <= m["slow_s"]),
            "model": m, "fitted_to": rc["receipt_id"], "fit_provenance": rc["provenance"], "provenance": "ESTIMATED"}


def batching_model(rc: dict) -> dict:
    p, b = rc["params"], rc["body"]
    jobs, bs = int(p["jobs"]), int(p["batch_size"])
    n_b, n_o = jobs, math.ceil(jobs / bs)
    launch = (b["baseline_wh"] - b["optimized_wh"]) / (n_b - n_o)
    return {"work_wh": b["baseline_wh"] - launch * n_b, "per_launch_wh": launch, "jobs": jobs, "measured_batch": bs}


def batching(rc: dict, batch_size: int, runs_per_day: float, a: config.Assumptions | None = None) -> dict:
    a = a or config.Assumptions()
    m = batching_model(rc)
    e = lambda b: m["work_wh"] + m["per_launch_wh"] * math.ceil(m["jobs"] / b)   # noqa: E731
    saved_day = (e(1) - e(batch_size)) * runs_per_day
    return {"energy_per_workload_wh": e(batch_size), "baseline_per_workload_wh": e(1),
            "launches": math.ceil(m["jobs"] / batch_size),
            "saved_pct": 100 * (1 - e(batch_size) / e(1)) if e(1) else 0.0, **_money(saved_day, a),
            "extrapolated": not (1 <= batch_size <= m["measured_batch"]), "model": m,
            "fitted_to": rc["receipt_id"], "fit_provenance": rc["provenance"], "provenance": "ESTIMATED"}


def app_pause(power_w: float, hours_per_day: float, a: config.Assumptions | None = None) -> dict:
    a = a or config.Assumptions()
    return {**_money(power_w * hours_per_day, a), "provenance": "ESTIMATED"}
