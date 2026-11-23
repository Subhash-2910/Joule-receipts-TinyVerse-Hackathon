"""Least-squares power model and calibration of the CPU estimate against a MEASURED source.

Calibration runs 0, 1, 2 and 4 busy processes in turn, pairs CPU utilisation with measured watts and fits
P = a + b x util. Saved to data/calibration.json; the CPU-estimate sensor then uses idle_w=a, max_w=a+b.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import statistics
import time

from joule.sensors import Sensor
from joule.sensors.cpu_estimate import calibration_path, cpu_utilisation


def fit_linear(xs: list[float], ys: list[float]) -> dict:
    n = len(xs)
    if n < 2 or len(set(xs)) < 2:
        raise ValueError("need at least two distinct x values")
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = my - slope * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    return {"slope": slope, "intercept": intercept, "r2": 1 - ss_res / ss_tot if ss_tot else 1.0, "n": n}


def _spin(stop_at: float) -> None:
    x = 0
    while time.time() < stop_at:
        x += 1


def calibrate(measured: Sensor, seconds_per_level: float = 15.0, levels=(0, 1, 2, 4), log=print) -> dict:
    xs, ys = [], []
    for k in levels:
        stop_at = time.time() + seconds_per_level
        procs = [mp.Process(target=_spin, args=(stop_at,), daemon=True) for _ in range(k)]
        for p in procs:
            p.start()
        time.sleep(1.0)  # let power settle
        while time.time() < stop_at - 1.0:
            util = cpu_utilisation(1.0)
            watts = measured.read().watts
            xs.append(util)
            ys.append(watts)
        for p in procs:
            p.join()
        log(f"level {k} busy processes: util {statistics.fmean(xs[-3:]):.2f}, {statistics.fmean(ys[-3:]):.2f} W")
    fit = fit_linear(xs, ys)
    cal = {"idle_w": fit["intercept"], "max_w": fit["intercept"] + fit["slope"], "r2": fit["r2"], "n": fit["n"],
           "measured_source": measured.name, "created": time.time()}
    calibration_path().write_text(json.dumps(cal, indent=2))
    return cal
