"""Apple silicon SoC power from `powermetrics` (needs root). Each read samples a 1 s window.

Measures CPU + GPU + ANE power of the chip. Does not include the display, SSD or Wi-Fi.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time

from joule.provenance import Provenance
from joule.sensors.base import PowerReading, Sensor, SensorUnavailable

_PART = re.compile(r"^\s*(CPU|GPU|ANE) Power:\s*([\d.]+)\s*mW", re.M)
_COMBINED = re.compile(r"Combined Power \(CPU \+ GPU \+ ANE\):\s*([\d.]+)\s*mW")


def parse_powermetrics(text: str) -> dict:
    parts = {k.lower(): float(v) / 1000.0 for k, v in _PART.findall(text)}
    m = _COMBINED.search(text)
    if m:
        parts["combined"] = float(m.group(1)) / 1000.0
    elif parts:
        parts["combined"] = sum(parts.values())
    if "combined" not in parts:
        raise SensorUnavailable("could not parse powermetrics output")
    return parts


class PowermetricsSensor(Sensor):
    name = "powermetrics"
    provenance = Provenance.MEASURED
    blocking = True
    min_window_s = 15.0       # each read is a 1 s window: runs shorter than ~15 s are repeated to fill it
    description = "Apple powermetrics (cpu_power, gpu_power samplers): M-series CPU+GPU+ANE power"

    def __init__(self, interval_s: float = 1.0):
        self.interval_ms = max(100, int(interval_s * 1000))

    def available(self) -> bool:
        return sys.platform == "darwin" and shutil.which("powermetrics") is not None and os.geteuid() == 0

    def read(self) -> PowerReading:
        if not self.available():
            raise SensorUnavailable("powermetrics needs macOS and root (run the collector with sudo)")
        t0 = time.time()
        out = subprocess.run(["powermetrics", "--samplers", "cpu_power,gpu_power", "-i", str(self.interval_ms),
                              "-n", "1"], capture_output=True, text=True, timeout=10 + self.interval_ms / 1000)
        parts = parse_powermetrics(out.stdout)
        return PowerReading(ts=(t0 + time.time()) / 2, watts=parts["combined"], source=self.name,
                            provenance=self.provenance, cpu_w=parts.get("cpu"), gpu_w=parts.get("gpu"),
                            ane_w=parts.get("ane"))
