"""SIMULATED power for CI, Docker and machines without power sensors.

P = P_idle + W_per_core x (CPU-seconds used by this process and its finished children / wall seconds) + noise.
The CPU time is real (so a workload that does less work really scores lower); the watts are a stated model.
The noise is seeded so runs are reproducible.
"""
from __future__ import annotations

import random
import resource
import time

from joule import config
from joule.provenance import Provenance
from joule.sensors.base import PowerReading, Sensor


def _cpu_seconds() -> float:
    s, c = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    return s.ru_utime + s.ru_stime + c.ru_utime + c.ru_stime


class SimulatedSensor(Sensor):
    name = "simulated"
    provenance = Provenance.SIMULATED
    description = "Simulation model: P = P_idle + W_per_core x process CPU-seconds per second + seeded noise"

    def __init__(self, seed: int = 42, idle_w: float | None = None, w_per_core: float | None = None,
                 noise_w: float = 0.05, clock=time.time, cpu_clock=_cpu_seconds):
        a = config.Assumptions()
        self.idle_w = a.sim_idle_w if idle_w is None else idle_w
        self.w_per_core = a.sim_w_per_core if w_per_core is None else w_per_core
        self.noise_w = noise_w
        self.rng = random.Random(seed)
        self.clock, self.cpu_clock = clock, cpu_clock
        self._last = (self.clock(), self.cpu_clock())

    def read(self) -> PowerReading:
        now, cpu = self.clock(), self.cpu_clock()
        t0, c0 = self._last
        self._last = (now, cpu)
        cores = (cpu - c0) / (now - t0) if now > t0 else 0.0
        watts = max(0.0, self.idle_w + self.w_per_core * cores + self.rng.gauss(0.0, self.noise_w))
        return PowerReading(ts=now, watts=watts, source=self.name, provenance=self.provenance,
                            cpu_util=cores, detail={"busy_cores": round(cores, 4)})
