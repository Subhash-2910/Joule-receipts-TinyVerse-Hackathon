"""Energy maths: power samples -> Wh, cost, CO2e, run statistics and savings. Pure functions, no I/O."""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from itertools import combinations

from joule.config import Assumptions

FORMULAS = {
    "energy": "E (Wh) = sum of 1/2 (P_i + P_i+1) x (t_i+1 - t_i) / 3600   (trapezoidal integration)",
    "net": "Net E (Wh) = E_run - P_idle x t_run / 3600",
    "cost": "Cost (INR) = E (kWh) x tariff (INR/kWh)",
    "co2": "CO2e (g) = E (kWh) x grid factor (kg/kWh) x 1000",
    "saving": "Saving = median(baseline) - median(optimized); significant if the exact Mann-Whitney test gives p < 0.05",
}


def integrate_wh(samples: list[tuple[float, float]]) -> float:
    """Trapezoidal integration of (time_s, watts) samples. Returns watt-hours."""
    pts = sorted(samples)
    joules = 0.0
    for (t0, p0), (t1, p1) in zip(pts, pts[1:]):
        if t1 > t0:
            joules += 0.5 * (p0 + p1) * (t1 - t0)
    return joules / 3600.0


def mean_power(samples: list[tuple[float, float]]) -> float:
    """Time-weighted mean power (W). Falls back to the plain mean for a single sample."""
    pts = sorted(samples)
    if not pts:
        return 0.0
    duration = pts[-1][0] - pts[0][0]
    if duration <= 0:
        return statistics.fmean(p for _, p in pts)
    return integrate_wh(pts) * 3600.0 / duration


def net_wh(run_wh: float, idle_w: float, duration_s: float) -> float:
    return run_wh - idle_w * duration_s / 3600.0


def cost_inr(wh: float, a: Assumptions | None = None) -> float:
    a = a or Assumptions()
    return wh / 1000.0 * a.tariff_inr_per_kwh


def co2_g(wh: float, a: Assumptions | None = None) -> float:
    a = a or Assumptions()
    return wh / 1000.0 * a.grid_kg_per_kwh * 1000.0


@dataclass
class Stats:
    mean: float
    std: float
    n: int

    @classmethod
    def of(cls, values: list[float]) -> "Stats":
        vals = list(values)
        if not vals:
            return cls(0.0, 0.0, 0)
        std = statistics.stdev(vals) if len(vals) > 1 else 0.0
        return cls(statistics.fmean(vals), std, len(vals))


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1          # average rank for ties
        i = j + 1
    return ranks


def mann_whitney_p(x: list[float], y: list[float]) -> float:
    """Exact two-sided Mann-Whitney p-value by enumerating every split (fine for n_x + n_y <= 20).
    Robust to an outlier run, unlike a comparison of means."""
    n, m = len(x), len(y)
    if n < 2 or m < 2:
        return 1.0
    if n + m > 20:
        raise ValueError("exact test limited to 20 runs in total")
    ranks = _ranks(list(x) + list(y))
    mean_u = n * m / 2
    obs = abs(sum(ranks[:n]) - n * (n + 1) / 2 - mean_u)
    total = extreme = 0
    for idx in combinations(range(n + m), n):
        u = sum(ranks[i] for i in idx) - n * (n + 1) / 2
        total += 1
        extreme += abs(u - mean_u) >= obs - 1e-9
    return extreme / total


def compare(baseline: list[float], optimized: list[float], a: Assumptions | None = None) -> dict:
    """Saving of optimized vs baseline energy (Wh per run). Positive = optimized uses less.
    The headline uses medians and an exact rank test, so one disturbed run cannot flip the verdict;
    means and the Welch-style noise band are reported alongside."""
    b, o = Stats.of(baseline), Stats.of(optimized)
    b_med = statistics.median(baseline) if baseline else 0.0
    o_med = statistics.median(optimized) if optimized else 0.0
    saved = b_med - o_med
    se = math.sqrt((b.std ** 2 / b.n if b.n else 0) + (o.std ** 2 / o.n if o.n else 0))
    p = mann_whitney_p(baseline, optimized) if b.n + o.n <= 20 else None
    return {
        "baseline_wh_mean": b.mean, "baseline_wh_std": b.std, "baseline_n": b.n, "baseline_wh_median": b_med,
        "optimized_wh_mean": o.mean, "optimized_wh_std": o.std, "optimized_n": o.n, "optimized_wh_median": o_med,
        "saved_wh": saved,
        "saved_pct": (100.0 * saved / b_med) if b_med else 0.0,
        "saved_wh_mean": b.mean - o.mean,
        "noise_wh": 2 * se,
        "p_value": p,
        "significant": bool(p is not None and p < 0.05),
        "welch_significant": bool(b.n > 1 and o.n > 1 and abs(b.mean - o.mean) > 2 * se),
        "saved_inr": cost_inr(saved, a),
        "saved_co2_g": co2_g(saved, a),
    }


def scale(wh_per_run: float, runs_per_day: float, days: float = 30.0, a: Assumptions | None = None) -> dict:
    """Project a per-run saving to a period. Always reported as ESTIMATED by the caller."""
    wh = wh_per_run * runs_per_day * days
    return {"wh": wh, "kwh": wh / 1000.0, "inr": cost_inr(wh, a), "co2_g": co2_g(wh, a), "days": days}
