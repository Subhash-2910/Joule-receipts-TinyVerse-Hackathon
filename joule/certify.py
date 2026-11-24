"""Certify your own software: run two versions of any program A/B, measure them, and issue a receipt, an A-G energy
label and a tamper-evident certificate.

    joule certify --name "Prime counter" --baseline "python3 examples/primes_v1.py" \
                  --candidate "python3 examples/primes_v2.py" --source powermetrics

Fast programs are repeated until each measured run lasts at least --min-seconds (default 5 s; powermetrics needs 15 s)
and the energy is divided per program run. Same experiment engine as the built-in scenarios: idle baseline, interleaved runs, medians, exact Mann-Whitney test,
energy above idle (the two versions may take different times). Same work = both versions print identical output
(SHA-256 of stdout), unless --allow-different-output is given (then only a clean exit is required and the label
cannot be CERTIFIED, because equal work is no longer proven).
"""
from __future__ import annotations

import hashlib
import subprocess
import time

from joule import config, db
from joule.workloads import SCENARIOS, Scenario, WorkResult

KEY = "certify"


def _braces(s: str) -> str:
    return s.replace("{", "{{").replace("}", "}}")      # descriptions go through str.format


def run_command(cmd: str, cwd: str | None, timeout_s: float, strict_output: bool) -> WorkResult:
    t0 = time.time()
    out = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, timeout=timeout_s)
    if out.returncode != 0:
        raise RuntimeError(f"command failed (exit {out.returncode}): {cmd}\n{out.stderr.decode(errors='replace')[-400:]}")
    digest = hashlib.sha256(out.stdout).hexdigest()
    return WorkResult(checksum=f"stdout={digest[:16]}" if strict_output else "exit=0", units=1,
                      detail={"stdout_sha256": digest[:16], "stdout_bytes": len(out.stdout),
                              "seconds": round(time.time() - t0, 3)})


def make_scenario(name: str, baseline_cmd: str, candidate_cmd: str, cwd: str | None = None,
                  timeout_s: float = 300.0, allow_different_output: bool = False) -> Scenario:
    strict = not allow_different_output
    return Scenario(
        name=KEY, title=f"Software certificate: {name}", mode="fixed_work",
        baseline_desc=_braces(f"{baseline_cmd}"), optimized_desc=_braces(f"{candidate_cmd}"),
        unit="program run", defaults={}, quick={}, pilot_scale=1.0,
        baseline=lambda p: run_command(baseline_cmd, cwd, timeout_s, strict),
        optimized=lambda p: run_command(candidate_cmd, cwd, timeout_s, strict),
        same_checksum=strict,
        tradeoff=("both versions printed identical output (same work)" if strict else
                  "outputs were allowed to differ, so equal work is NOT proven"))


def certify(conn, name: str, baseline_cmd: str, candidate_cmd: str, sensor, repeats: int = 5, cwd: str | None = None,
            idle_s: float = 10.0, interval_s: float = 1.0, timeout_s: float = 300.0,
            allow_different_output: bool = False, quick: bool = False, min_seconds: float = 5.0,
            log=print) -> tuple[int, int, dict]:
    """Runs the A/B experiment and stores the receipt (hash-chained, queued for sync). Returns (experiment, receipt,
    receipt body)."""
    from joule.experiment import experiment_and_receipt
    scn = make_scenario(name, baseline_cmd, candidate_cmd, cwd, timeout_s, allow_different_output)
    log(f"[certify] checking both versions run: {baseline_cmd!r} / {candidate_cmd!r}")
    a, b = scn.baseline({}), scn.optimized({})                   # fail fast, and warm caches before measuring
    if scn.same_checksum and a.checksum != b.checksum:
        raise ValueError("the two versions print different output, so they do not do the same work. Fix that, or "
                         "pass --allow-different-output (the label then stays PROVISIONAL)")
    # a fast program is repeated until each run lasts >= min_seconds; energy is then divided per program run
    sensor.min_window_s = max(type(sensor).min_window_s, min_seconds)
    previous = SCENARIOS.get(KEY)
    SCENARIOS[KEY] = scn
    try:
        eid, rid, body = experiment_and_receipt(conn, KEY, sensor, repeats, quick, idle_s, interval_s,
                                                predict=False, log=log)
    finally:
        if previous is None:
            SCENARIOS.pop(KEY, None)
        else:
            SCENARIOS[KEY] = previous
    return eid, rid, body


def certificates(conn) -> list[dict]:
    """Every software-certificate receipt, newest first."""
    return [dict(r) for r in conn.execute(
        "SELECT id, created, provenance FROM receipts WHERE json_extract(body_json,'$.scenario') = ? ORDER BY id DESC",
        (KEY,))]


def write_certificate(conn, receipt_id: int) -> str:
    from joule.analytics import label
    out = config.data_dir() / "certificates"
    out.mkdir(exist_ok=True)
    path = out / f"software-{receipt_id}.html"
    path.write_text(label.certificate_html(label.label_for(conn, receipt_id, db.verify_chain(conn)),
                                           config.Settings().device_id))
    config.give_back(out)
    return str(path)
