"""ESTIMATED power from whole-machine CPU utilisation: P = P_idle + (P_max - P_idle) x util.

Utilisation comes from psutil when installed, else `top` (macOS) or /proc/stat (Linux, e.g. Docker).
The constants are assumptions until `joule calibrate` fits them against a MEASURED source.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

from joule import config
from joule.provenance import Provenance
from joule.sensors.base import PowerReading, Sensor, SensorUnavailable

_TOP = re.compile(r"CPU usage:\s*([\d.]+)% user,\s*([\d.]+)% sys,\s*([\d.]+)% idle")


def parse_top(text: str) -> float:
    """Utilisation (0..1) from the LAST 'CPU usage' line (the first `top -l` sample is since boot)."""
    found = _TOP.findall(text)
    if not found:
        raise SensorUnavailable("could not parse top output")
    idle = float(found[-1][2])
    return max(0.0, min(1.0, 1.0 - idle / 100.0))


def _proc_stat() -> tuple[int, int]:
    fields = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
    return idle, sum(fields)


def cpu_utilisation(interval_s: float = 1.0) -> float:
    try:
        import psutil  # optional
        return psutil.cpu_percent(interval=interval_s) / 100.0
    except ImportError:
        pass
    if sys.platform == "darwin":
        out = subprocess.run(["top", "-l", "2", "-n", "0", "-s", str(max(1, round(interval_s)))],
                             capture_output=True, text=True, timeout=10 + interval_s)
        return parse_top(out.stdout)
    if Path("/proc/stat").exists():
        i0, t0 = _proc_stat()
        time.sleep(interval_s)
        i1, t1 = _proc_stat()
        return 0.0 if t1 == t0 else max(0.0, min(1.0, 1.0 - (i1 - i0) / (t1 - t0)))
    raise SensorUnavailable("no way to read CPU utilisation on this platform")


def calibration_path() -> Path:
    return config.data_dir() / "calibration.json"


def load_calibration() -> dict | None:
    p = calibration_path()
    return json.loads(p.read_text()) if p.exists() else None


class CpuEstimateSensor(Sensor):
    name = "estimate"
    provenance = Provenance.ESTIMATED
    blocking = True
    description = "CPU-utilisation power model P = P_idle + (P_max - P_idle) x util (ESTIMATED)"

    def __init__(self, interval_s: float = 1.0, idle_w: float | None = None, max_w: float | None = None):
        a = config.Assumptions()
        cal = load_calibration() or {}
        self.interval_s = interval_s
        self.idle_w = idle_w if idle_w is not None else cal.get("idle_w", a.est_idle_w)
        self.max_w = max_w if max_w is not None else cal.get("max_w", a.est_max_w)
        self.calibrated = "idle_w" in cal and idle_w is None

    def watts_for(self, util: float) -> float:
        return self.idle_w + (self.max_w - self.idle_w) * util

    def read(self) -> PowerReading:
        util = cpu_utilisation(self.interval_s)
        return PowerReading(ts=time.time(), watts=self.watts_for(util), source=self.name,
                            provenance=self.provenance, cpu_util=util,
                            detail={"idle_w": self.idle_w, "max_w": self.max_w, "calibrated": self.calibrated})
