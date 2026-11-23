"""Whole-laptop power from the battery fuel gauge (macOS, no sudo). Valid only while running on battery.

watts = Voltage (mV) / 1000 x discharge current (mA) / 1000. The gauge firmware refreshes the current every few
seconds (12-33 s observed on an M3 MacBook), so 1 s reads repeat values. Experiments therefore use windows of
at least `min_window_s` with this sensor; powermetrics (1 s) is preferred for short runs.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time

from joule.provenance import Provenance
from joule.sensors.base import PowerReading, Sensor, SensorUnavailable

_LINE = re.compile(r'^[\s|]*"(\w+)" = (Yes|No|-?\d+)\s*$')


def to_signed64(value: int) -> int:
    """ioreg prints negative currents as unsigned 64-bit integers."""
    return value - (1 << 64) if value >= (1 << 63) else value


def parse_ioreg(text: str) -> dict:
    out: dict = {}
    for line in text.splitlines():
        m = _LINE.match(line)
        if m and m.group(1) not in out:          # first (top-level) occurrence wins
            v = m.group(2)
            out[m.group(1)] = True if v == "Yes" else False if v == "No" else int(v)
    return out


def power_from_fields(fields: dict) -> tuple[float, bool]:
    """Returns (watts, on_battery). Raises SensorUnavailable when the reading cannot be system power."""
    if "Voltage" not in fields:
        raise SensorUnavailable("no battery found")
    external = bool(fields.get("ExternalConnected", False))
    current = fields.get("InstantAmperage", fields.get("Amperage"))
    if current is None:
        raise SensorUnavailable("battery current not reported")
    ma = to_signed64(int(current))
    if external:
        raise SensorUnavailable("on AC power: battery current is not system power (unplug to measure)")
    if ma >= 0:
        raise SensorUnavailable("battery is not discharging")
    return fields["Voltage"] / 1000.0 * (-ma) / 1000.0, True


class BatterySensor(Sensor):
    name = "battery"
    provenance = Provenance.MEASURED
    min_window_s = 90.0       # the M3 gauge refreshed every ~12-33 s in our test
    description = "macOS battery gauge (ioreg AppleSmartBattery): voltage x discharge current, whole laptop"

    def _fields(self) -> dict:
        out = subprocess.run(["ioreg", "-rn", "AppleSmartBattery"], capture_output=True, text=True, timeout=5)
        return parse_ioreg(out.stdout)

    def available(self) -> bool:
        if sys.platform != "darwin" or not shutil.which("ioreg"):
            return False
        try:
            power_from_fields(self._fields())
            return True
        except (SensorUnavailable, subprocess.SubprocessError, OSError):
            return False

    def read(self) -> PowerReading:
        fields = self._fields()
        watts, on_batt = power_from_fields(fields)
        return PowerReading(ts=time.time(), watts=watts, source=self.name, provenance=self.provenance,
                            on_battery=on_batt,
                            detail={"voltage_mv": fields.get("Voltage"),
                                    "current_ma": to_signed64(int(fields.get("InstantAmperage", fields.get("Amperage", 0)))),
                                    "charge_pct": fields.get("CurrentCapacity")})
