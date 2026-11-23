"""Power sources, best first: powermetrics (MEASURED, sudo) -> battery (MEASURED, unplugged) -> CPU estimate."""
from __future__ import annotations

from joule.sensors.base import PowerReading, Sensor, SensorUnavailable
from joule.sensors.battery import BatterySensor
from joule.sensors.cpu_estimate import CpuEstimateSensor
from joule.sensors.powermetrics import PowermetricsSensor
from joule.sensors.simulated import SimulatedSensor

NAMES = ("auto", "powermetrics", "battery", "estimate", "simulated")


def get_sensor(name: str = "auto", interval_s: float = 1.0, seed: int = 42) -> Sensor:
    if name == "powermetrics":
        return PowermetricsSensor(interval_s)
    if name == "battery":
        return BatterySensor()
    if name == "estimate":
        return CpuEstimateSensor(interval_s)
    if name == "simulated":
        return SimulatedSensor(seed=seed)
    if name != "auto":
        raise ValueError(f"unknown sensor {name!r}; choose from {NAMES}")
    for candidate in (PowermetricsSensor(interval_s), BatterySensor()):
        if candidate.available():
            return candidate
    return CpuEstimateSensor(interval_s)


__all__ = ["PowerReading", "Sensor", "SensorUnavailable", "get_sensor", "NAMES", "BatterySensor",
           "CpuEstimateSensor", "PowermetricsSensor", "SimulatedSensor"]
