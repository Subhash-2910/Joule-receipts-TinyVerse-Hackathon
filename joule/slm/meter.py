"""Energy meter for one block of work (e.g. one SLM explanation): samples the power sensor in the background.

energy_j  = time-weighted mean power during the block x its duration      (whole machine, CPU+GPU on powermetrics)
net_j     = energy_j - idle power x duration                               (only when an idle power is known)
The provenance is the sensor's: MEASURED with powermetrics, ESTIMATED with the CPU model (which cannot see the GPU,
so it UNDER-counts Ollama on Apple silicon - the dashboard says so).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from joule import energy
from joule.sensors import Sensor, SensorUnavailable


@dataclass
class Metered:
    seconds: float
    energy_j: float | None
    net_j: float | None
    mean_w: float | None
    n_samples: int
    provenance: str
    sensor: str

    def as_dict(self) -> dict:
        return {"seconds": round(self.seconds, 3),
                "energy_j": None if self.energy_j is None else round(self.energy_j, 3),
                "net_j": None if self.net_j is None else round(self.net_j, 3),
                "mean_w": None if self.mean_w is None else round(self.mean_w, 3),
                "n_samples": self.n_samples, "provenance": self.provenance, "sensor": self.sensor}


class EnergyMeter:
    """with EnergyMeter(sensor, idle_w) as m: ...work...   then m.result (a Metered)."""

    def __init__(self, sensor: Sensor | None, idle_w: float | None = None, interval_s: float = 0.5):
        self.sensor, self.idle_w, self.interval_s = sensor, idle_w, interval_s
        self.result: Metered | None = None

    def __enter__(self):
        from joule.experiment import Sampler          # local import: experiment imports workloads -> slm
        self._t0 = time.time()
        self._sampler = None
        if self.sensor is not None:
            self._sampler = Sampler(self.sensor, self.interval_s)
            self._sampler.start()
        return self

    def __exit__(self, *exc):
        dt = time.time() - self._t0
        name = self.sensor.name if self.sensor else "none"
        if self._sampler is None:
            self.result = Metered(dt, None, None, None, 0, "UNMEASURED", name)
            return False
        try:
            samples = self._sampler.stop()
        except SensorUnavailable:
            samples = []
        if not samples:
            self.result = Metered(dt, None, None, None, 0, "UNMEASURED", name)
            return False
        mean_w = energy.mean_power(samples)
        e_j = mean_w * dt
        net = None if self.idle_w is None else max(0.0, e_j - self.idle_w * dt)
        self.result = Metered(dt, e_j, net, mean_w, len(samples),
                              str(self._sampler.provenance or self.sensor.provenance), name)
        return False
