"""Background collector: one power reading + per-process attribution per interval, stored in SQLite."""
from __future__ import annotations

import os
import time
import uuid

from joule import db
from joule.provenance import Provenance
from joule.sensors import CpuEstimateSensor, Sensor, SensorUnavailable
from joule.sensors import procs as procs_mod


def cpu_power(reading, procs: list[tuple[str, float]], model: CpuEstimateSensor) -> tuple[float, Provenance]:
    """CPU power to split between processes: measured when the sensor reports it, else the CPU model."""
    if reading.cpu_w is not None:
        return reading.cpu_w, Provenance(reading.provenance)
    util = reading.cpu_util if reading.cpu_util is not None else \
        min(1.0, sum(p for _, p in procs) / (100.0 * (os.cpu_count() or 1)))
    return (model.max_w - model.idle_w) * util, Provenance.ESTIMATED


def collect(conn, sensor: Sensor, seconds: float, interval_s: float = 1.0, with_procs: bool = True,
            log=print, proc_source=procs_mod.snapshot) -> dict:
    """Collect for `seconds`: one reading + per-process shares of CPU power per interval."""
    session = uuid.uuid4().hex[:8]
    model = CpuEstimateSensor()
    stored, errors = 0, 0
    end = time.time() + seconds
    while time.time() < end:
        tick = time.time()
        try:
            r = sensor.read()
        except SensorUnavailable as e:
            errors += 1
            log(f"sensor unavailable: {e}")
            time.sleep(interval_s)
            continue
        shares = []
        if with_procs:
            procs = proc_source()
            power_w, prov = cpu_power(r, procs, model)
            shares = procs_mod.attribute(procs, power_w, prov)
        db.insert_sample(conn, r, session, shares)
        stored += 1
        top = ", ".join(f"{s.name} {s.watts:.2f}W" for s in shares[:3])
        log(f"{time.strftime('%H:%M:%S')}  {r.watts:6.2f} W  [{r.provenance}/{r.source}]  {top}")
        if not sensor.blocking:
            time.sleep(max(0.0, interval_s - (time.time() - tick)))
    return {"session": session, "stored": stored, "errors": errors}
