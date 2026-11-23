from __future__ import annotations

from dataclasses import dataclass, field

from joule.provenance import Provenance


class SensorUnavailable(RuntimeError):
    """The sensor cannot give a valid reading right now (no sudo, on AC power, not macOS, ...)."""


@dataclass
class PowerReading:
    ts: float
    watts: float
    source: str
    provenance: Provenance
    cpu_w: float | None = None
    gpu_w: float | None = None
    ane_w: float | None = None
    cpu_util: float | None = None      # 0..1, whole machine
    on_battery: bool | None = None
    detail: dict = field(default_factory=dict)


class Sensor:
    name = "base"
    provenance = Provenance.ESTIMATED
    blocking = False          # True when read() itself takes ~one sampling interval
    min_window_s = 0.0        # shortest window over which readings mean something (slow gauges)
    description = ""

    def available(self) -> bool:
        return True

    def read(self) -> PowerReading:
        raise NotImplementedError

    def info(self) -> dict:
        return {"name": self.name, "provenance": str(self.provenance), "description": self.description}
