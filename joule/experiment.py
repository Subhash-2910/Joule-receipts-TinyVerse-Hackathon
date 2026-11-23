"""A/B experiment runner: idle baseline -> interleaved baseline/optimized runs x N -> statistics -> receipt.

Interleaving (B, O, B, O, ...) cancels slow drift (temperature, battery level, background apps).
Energy per run = time-weighted mean power during the run x run duration; net energy subtracts idle power.
"""
from __future__ import annotations

import platform
import statistics
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field

from joule import config, db, energy
from joule.provenance import Provenance, combine
from joule.sensors import Sensor, SensorUnavailable
from joule.workloads import SCENARIOS, Scenario, WorkResult


def hardware_info() -> dict:
    info = {"machine": platform.machine(), "os": f"{platform.system()} {platform.release()}",
            "python": platform.python_version()}
    try:
        info["cpu"] = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True,
                                     text=True, timeout=3).stdout.strip() or platform.processor()
    except (OSError, subprocess.SubprocessError):
        info["cpu"] = platform.processor()
    return info


class Sampler(threading.Thread):
    """Reads the sensor in the background until stopped."""

    def __init__(self, sensor: Sensor, interval_s: float):
        super().__init__(daemon=True)
        self.sensor, self.interval_s = sensor, interval_s
        self.samples: list[tuple[float, float]] = []
        self.provenance: Provenance | None = None
        self.error: str | None = None
        self._stop_evt = threading.Event()

    def _read(self) -> None:
        try:
            r = self.sensor.read()
            self.samples.append((r.ts, r.watts))
            self.provenance = r.provenance
        except SensorUnavailable as e:
            self.error = str(e)

    def run(self):
        if self.sensor.blocking:                      # each read itself spans one interval
            while not self._stop_evt.is_set():
                self._read()
        else:                                         # wait first: a t=0 reading describes the moment before the run
            while not self._stop_evt.wait(self.interval_s):
                self._read()

    def stop(self) -> list[tuple[float, float]]:
        self._stop_evt.set()
        self.join(timeout=15)
        if not self.sensor.blocking or not self.samples:
            self._read()            # a closing reading covers the tail of the run (and very short runs)
        return self.samples


@dataclass
class RunResult:
    variant: str
    run_idx: int
    started: float
    duration_s: float
    n_samples: int
    energy_wh: float
    net_wh: float
    mean_w: float
    std_w: float
    provenance: str
    checksum: str
    work_units: int
    detail: dict = field(default_factory=dict)
    reps: int = 1                  # workload repetitions in this run (energy values are per repetition)


def measure_idle(sensor: Sensor, seconds: float, interval_s: float, settle_s: float = 5.0) -> tuple[float, float, int]:
    """Idle power = MEDIAN of readings after a settle period (a spike from another app barely moves it)."""
    time.sleep(settle_s)
    sampler = Sampler(sensor, interval_s)
    sampler.start()
    time.sleep(seconds)
    samples = sampler.stop()
    if not samples:
        raise SensorUnavailable(sampler.error or "no samples during idle measurement")
    watts = [w for _, w in samples]
    return statistics.median(watts), (statistics.stdev(watts) if len(watts) > 1 else 0.0), len(watts)


def run_once(sensor: Sensor, work, params: dict, variant: str, idx: int, idle_w: float,
             interval_s: float, min_window_s: float = 0.0) -> RunResult:
    """Run the workload (repeated until `min_window_s` has passed, for slow sensors). Energy is per repetition."""
    sensor.read() if not sensor.blocking else None   # resets per-interval state (simulated sensor)
    sampler = Sampler(sensor, interval_s)
    t0 = time.time()
    sampler.start()
    result: WorkResult = work(params)
    reps = 1
    while time.time() - t0 < min_window_s:
        again = work(params)
        if again.checksum != result.checksum:
            raise RuntimeError("workload is not deterministic across repetitions")
        reps += 1
    duration = time.time() - t0
    samples = sampler.stop()
    if not samples:
        raise SensorUnavailable(sampler.error or "no power samples during the run")
    mean_w = energy.mean_power(samples)
    watts = [w for _, w in samples]
    e_wh = mean_w * duration / 3600.0
    return RunResult(variant=variant, run_idx=idx, started=t0, duration_s=duration / reps, n_samples=len(samples),
                     energy_wh=e_wh / reps, net_wh=energy.net_wh(e_wh, idle_w, duration) / reps, mean_w=mean_w,
                     std_w=statistics.stdev(watts) if len(watts) > 1 else 0.0,
                     provenance=str(sampler.provenance or sensor.provenance), checksum=result.checksum,
                     work_units=result.units, detail={**result.detail, "reps": reps}, reps=reps)


def _check_equivalence(scn: Scenario, runs: list[RunResult]) -> dict:
    sums = {r.checksum for r in runs}
    units = {r.work_units for r in runs}
    ok = (len(sums) == 1 if scn.same_checksum else True) and len(units) == 1
    return {"equivalent": ok, "checksums": sorted(sums), "work_units": sorted(units)}


def run_experiment(scenario: str, sensor: Sensor, repeats: int = 5, quick: bool = False, idle_s: float = 10.0,
                   cooldown_s: float = 2.0, interval_s: float = 1.0, params: dict | None = None,
                   predicted_saved_wh: float | None = None, settle_s: float = 5.0, log=print) -> dict:
    scn = SCENARIOS[scenario]
    p = scn.params(quick=quick, **(params or {}))
    window = sensor.min_window_s
    if scn.mode == "fixed_time" and p["duration_s"] < window:
        log(f"[{scenario}] {sensor.name} refreshes slowly: observation window raised to {window:.0f} s")
        p["duration_s"] = window
    log(f"[{scenario}] sensor={sensor.name} ({sensor.provenance}), interval={interval_s}s, repeats={repeats}")
    idle_w, idle_std, idle_n = measure_idle(sensor, max(idle_s, window), interval_s, settle_s)
    log(f"[{scenario}] idle power {idle_w:.3f} W ± {idle_std:.3f} (n={idle_n})")
    runs: list[RunResult] = []
    for i in range(repeats):
        order = [("baseline", scn.baseline), ("optimized", scn.optimized)]
        if i % 2:
            order.reverse()                       # B,O then O,B: cancels order effects
        for variant, work in order:
            r = run_once(sensor, work, p, variant, i, idle_w, interval_s,
                         min_window_s=window if scn.mode == "fixed_work" else 0.0)
            runs.append(r)
            log(f"[{scenario}] run {i + 1}/{repeats} {variant:9s} {r.duration_s:6.2f}s {r.mean_w:6.2f} W "
                f"net {r.net_wh * 1000:8.3f} mWh  {r.detail}")
            time.sleep(cooldown_s)
    # fixed time: both variants last equally long, so total energy is compared directly (no idle subtraction);
    # fixed work: durations differ, so the idle floor is subtracted and only the work's own energy is compared
    basis = "energy_wh" if scn.mode == "fixed_time" else "net_wh"
    base = [getattr(r, basis) for r in runs if r.variant == "baseline"]
    opt = [getattr(r, basis) for r in runs if r.variant == "optimized"]
    cmp = energy.compare(base, opt)
    prov = str(combine(*[r.provenance for r in runs], sensor.provenance))
    units = runs[0].work_units or 1
    result = {
        "scenario": scenario, "title": scn.title, "mode": scn.mode, "unit": scn.unit,
        "baseline": scn.baseline_desc.format(**p), "optimized": scn.optimized_desc.format(**p),
        "tradeoff": scn.tradeoff.format(**p),
        "params": p, "sensor": sensor.info(), "sampling_interval_s": interval_s, "hardware": hardware_info(),
        "provenance": prov, "idle_w": idle_w, "idle_w_std": idle_std,
        "basis": "total energy per run (same duration)" if basis == "energy_wh" else "energy above idle per run",
        "comparison": cmp,
        "per_unit_mwh": {"baseline": cmp["baseline_wh_mean"] / units * 1000,
                         "optimized": cmp["optimized_wh_mean"] / units * 1000},
        "duration_s": {"baseline": statistics.fmean(r.duration_s for r in runs if r.variant == "baseline"),
                       "optimized": statistics.fmean(r.duration_s for r in runs if r.variant == "optimized")},
        "equivalence": _check_equivalence(scn, runs),
        "details": {"baseline": [r.detail for r in runs if r.variant == "baseline"],
                    "optimized": [r.detail for r in runs if r.variant == "optimized"]},
        "assumptions": config.Assumptions().as_dict(), "formulas": energy.FORMULAS,
        "predicted_saved_wh": predicted_saved_wh,
    }
    if predicted_saved_wh is not None and cmp["saved_wh"]:
        result["prediction_error_pct"] = 100.0 * (predicted_saved_wh - cmp["saved_wh"]) / abs(cmp["saved_wh"])
    result["runs"] = [asdict(r) for r in runs]
    return result


def predict_by_pilot(scenario: str, sensor: Sensor, quick: bool = False, interval_s: float = 1.0,
                     idle_s: float = 5.0, params: dict | None = None, settle_s: float = 5.0, log=print) -> dict:
    """Predict the full-size saving from one small pilot pair, extrapolated linearly by work size or time."""
    scn = SCENARIOS[scenario]
    full = scn.params(quick=quick, **(params or {}))
    pilot, factor = scn.pilot_params(full)
    window = sensor.min_window_s
    if scn.mode == "fixed_time":
        full["duration_s"] = max(full["duration_s"], window)
        pilot["duration_s"] = max(pilot["duration_s"], window)
        factor = full["duration_s"] / pilot["duration_s"]
    fw = window if scn.mode == "fixed_work" else 0.0
    idle_w, _, _ = measure_idle(sensor, max(idle_s, window), interval_s, settle_s)
    b = run_once(sensor, scn.baseline, pilot, "baseline", 0, idle_w, interval_s, fw)
    o = run_once(sensor, scn.optimized, pilot, "optimized", 0, idle_w, interval_s, fw)
    key = "energy_wh" if scn.mode == "fixed_time" else "net_wh"
    pred = (getattr(b, key) - getattr(o, key)) * factor
    log(f"[{scenario}] pilot x{factor:.1f}: predicted saving {pred * 1000:.3f} mWh per full run")
    return {"scenario": scenario, "method": f"pilot run at {scn.pilot_scale:.0%} size, extrapolated x{factor:.1f}",
            "predicted_saved_wh": pred, "provenance": str(Provenance.ESTIMATED), "pilot_idle_w": idle_w}


def experiment_and_receipt(conn, scenario: str, sensor: Sensor, repeats: int = 5, quick: bool = False,
                           idle_s: float = 10.0, interval_s: float = 1.0, rec_id: int | None = None,
                           predict: bool = True, params: dict | None = None, log=print) -> tuple[int, int, dict]:
    """Predict (pilot) -> run the experiment -> store it -> store + enqueue the receipt."""
    settle = 0.5 if quick else 5.0
    prediction = predict_by_pilot(scenario, sensor, quick, interval_s, max(2.0, idle_s / 2), params, settle, log) \
        if predict else None
    result = run_experiment(scenario, sensor, repeats, quick, idle_s, interval_s=interval_s, params=params,
                            cooldown_s=0.5 if quick else 2.0, settle_s=settle,
                            predicted_saved_wh=prediction["predicted_saved_wh"] if prediction else None, log=log)
    result["prediction"] = prediction
    runs = [RunResult(**r) for r in result["runs"]]
    eid = db.save_experiment(conn, scenario, sensor.name, result["provenance"], repeats, result["idle_w"],
                             result["params"], runs, {k: v for k, v in result.items() if k != "runs"})
    receipt = receipt_body(result)
    rid = db.save_receipt(conn, receipt, eid, rec_id, receipt["predicted_saved_wh"], receipt["measured_saved_wh"],
                          result["provenance"])
    return eid, rid, receipt


def receipt_body(result: dict) -> dict:
    c = result["comparison"]
    return {
        "scenario": result["scenario"], "title": result["title"], "provenance": result["provenance"],
        "sensor": result["sensor"]["name"], "baseline": result["baseline"], "optimized": result["optimized"],
        "repeats": c["baseline_n"], "idle_w": round(result["idle_w"], 4),
        "basis": result.get("basis", ""),
        "baseline_wh": round(c["baseline_wh_median"], 6), "baseline_wh_std": round(c["baseline_wh_std"], 6),
        "optimized_wh": round(c["optimized_wh_median"], 6), "optimized_wh_std": round(c["optimized_wh_std"], 6),
        "baseline_wh_mean": round(c["baseline_wh_mean"], 6), "optimized_wh_mean": round(c["optimized_wh_mean"], 6),
        "measured_saved_wh": round(c["saved_wh"], 6), "saved_pct": round(c["saved_pct"], 2),
        "saved_wh_mean": round(c["saved_wh_mean"], 6), "p_value": None if c["p_value"] is None else float(f"{c['p_value']:.2g}"),
        "significant": c["significant"], "welch_significant": c["welch_significant"], "noise_wh": round(c["noise_wh"], 6),
        "saved_inr": c["saved_inr"], "saved_co2_g": c["saved_co2_g"],
        "predicted_saved_wh": None if result.get("predicted_saved_wh") is None else round(result["predicted_saved_wh"], 6),
        "prediction_error_pct": None if result.get("prediction_error_pct") is None else round(result["prediction_error_pct"], 1),
        "equivalent_work": result["equivalence"]["equivalent"], "tradeoff": result["tradeoff"],
        "assumptions": result["assumptions"],
    }
