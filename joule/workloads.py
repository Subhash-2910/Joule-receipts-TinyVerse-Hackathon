"""Reproducible baseline / optimized workloads. Each pair completes the SAME work, checked by a checksum.

idle      fixed time: a folder-sync poller scans + hashes a folder every 100 ms vs every 2 s (a change is planted
          halfway; both must detect it - the trade-off is detection latency)
batching  fixed work: 200 hashing jobs, one process launch per job vs 10 launches of 20 jobs
inference fixed work: the same prompts answered by a larger vs smaller model / token cap (needs Ollama)
cascade   fixed work: the same prompts, always the 1.5B model vs the small model first with the grounding check as
          the gate (escalate to 1.5B only when it fails) - the copilot measuring its own AI (needs Ollama)
"""
from __future__ import annotations

import hashlib
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class WorkResult:
    checksum: str
    units: int
    detail: dict = field(default_factory=dict)


@dataclass
class Scenario:
    name: str
    title: str
    mode: str                      # "fixed_work" or "fixed_time"
    baseline_desc: str
    optimized_desc: str
    unit: str
    defaults: dict
    quick: dict
    pilot_scale: float             # pilot run size relative to the full run (for the prediction)
    baseline: Callable[[dict], WorkResult]
    optimized: Callable[[dict], WorkResult]
    same_checksum: bool = True     # inference answers differ in wording; equivalence = same prompts answered
    tradeoff: str = ""

    def params(self, quick: bool = False, **overrides) -> dict:
        p = dict(self.defaults)
        if quick:
            p.update(self.quick)
        p.update({k: v for k, v in overrides.items() if v is not None})
        return p

    def pilot_params(self, params: dict) -> tuple[dict, float]:
        """A smaller copy of the run, and the factor that scales its result up to the full run."""
        p = dict(params)
        if self.mode == "fixed_time":
            p["duration_s"] = max(1.0, params["duration_s"] * self.pilot_scale)
            return p, params["duration_s"] / p["duration_s"]
        key = "jobs" if "jobs" in params else "prompts"
        p[key] = max(params.get("batch_size", 1), int(params[key] * self.pilot_scale))
        return p, params[key] / p[key]


# ---------------------------------------------------------------- idle / background polling

def make_folder(root: Path, files: int, size: int, seed: int = 7) -> Path:
    rng = random.Random(seed)
    root.mkdir(parents=True, exist_ok=True)
    for i in range(files):
        (root / f"doc_{i:04d}.txt").write_bytes(rng.randbytes(size))
    return root


def _scan(folder: Path) -> str:
    h = hashlib.sha256()
    for entry in sorted(os.scandir(folder), key=lambda e: e.name):
        h.update(entry.name.encode())
        h.update(Path(entry.path).read_bytes())
    return h.hexdigest()


def poll_folder(params: dict, interval_s: float) -> WorkResult:
    """Poll a folder for changes for `duration_s`; a 'user' edits one file at the halfway point."""
    duration = float(params["duration_s"])
    with tempfile.TemporaryDirectory(prefix="joule-idle-") as tmp:
        folder = make_folder(Path(tmp) / "docs", params["files"], params["file_kb"] * 1024)
        target = folder / "doc_0000.txt"
        state = {"changed_at": None}

        def user_edit():
            target.write_bytes(b"edited by the user")
            state["changed_at"] = time.monotonic()

        timer = threading.Timer(duration / 2, user_edit)
        start = time.monotonic()
        timer.start()
        last, scans, detected_at = _scan(folder), 1, None
        try:
            while (elapsed := time.monotonic() - start) < duration:
                time.sleep(min(interval_s, max(0.0, duration - elapsed)))
                if time.monotonic() - start >= duration and detected_at:
                    break
                digest = _scan(folder)
                scans += 1
                if digest != last and detected_at is None:
                    detected_at = time.monotonic()
                last = digest
        finally:
            timer.cancel()
        latency = (detected_at - state["changed_at"]) if (detected_at and state["changed_at"]) else None
        return WorkResult(checksum=f"detected={detected_at is not None};final={last[:16]}", units=1,
                          detail={"scans": scans, "detect_latency_s": None if latency is None else round(latency, 3)})


# ---------------------------------------------------------------- batching / process launches

JOB_CODE = (
    "import hashlib,sys\n"
    "for a in sys.argv[1:]:\n"
    "    i=int(a); d=hashlib.sha256(str(i).encode()).digest()\n"
    "    for _ in range({rounds}): d=hashlib.sha256(d*64).digest()\n"
    "    print(i, d.hex())\n"
)


def run_jobs(params: dict, batch_size: int) -> WorkResult:
    jobs, rounds = int(params["jobs"]), int(params["rounds"])
    code = JOB_CODE.format(rounds=rounds)
    digests: dict[int, str] = {}
    launches = 0
    for start in range(0, jobs, batch_size):
        ids = [str(i) for i in range(start, min(jobs, start + batch_size))]
        out = subprocess.run([sys.executable, "-I", "-c", code, *ids], capture_output=True, text=True, check=True)
        launches += 1
        for line in out.stdout.splitlines():
            i, d = line.split()
            digests[int(i)] = d
    total = hashlib.sha256("".join(digests[i] for i in sorted(digests)).encode()).hexdigest()
    return WorkResult(checksum=total, units=len(digests), detail={"process_launches": launches})


# ---------------------------------------------------------------- inference settings (needs Ollama)

def answer_prompts(params: dict, model: str, max_tokens: int) -> WorkResult:
    from joule.slm import explain  # imported lazily: only this scenario needs the SLM
    facts_list = explain.sample_facts()[: int(params["prompts"])]
    grounded, tokens = 0, 0
    for facts in facts_list:
        res = explain.explain(facts, model=model, max_tokens=max_tokens, allow_fallback=False, retries=0)
        grounded += int(res.grounded)
        tokens += res.tokens or 0
    return WorkResult(checksum=f"prompts={len(facts_list)}", units=len(facts_list),
                      detail={"model": model, "max_tokens": max_tokens, "grounded": grounded,
                              "grounded_rate": round(grounded / max(1, len(facts_list)), 3), "tokens": tokens})


def answer_cascade(params: dict, models: list[str], max_tokens: int) -> WorkResult:
    from joule.slm import explain
    facts_list = explain.sample_facts()[: int(params["prompts"])]
    grounded = escalated = tokens = 0
    for facts in facts_list:
        res = explain.explain_cascade(facts, models=models, max_tokens=max_tokens, allow_fallback=False)
        grounded += int(res.grounded)
        escalated += int(res.escalated)
        tokens += res.tokens or 0
    n = max(1, len(facts_list))
    return WorkResult(checksum=f"prompts={len(facts_list)}", units=len(facts_list),
                      detail={"models": "->".join(models), "grounded": grounded, "grounded_rate": round(grounded / n, 3),
                              "escalated": escalated, "tokens": tokens})


SCENARIOS: dict[str, Scenario] = {
    "idle": Scenario(
        name="idle", title="Idle / background activity", mode="fixed_time",
        baseline_desc="Folder-sync poller re-scans and hashes {files} files every {fast_s} s",
        optimized_desc="Same poller every {slow_s} s",
        unit="observation window", pilot_scale=0.25,
        defaults={"duration_s": 60.0, "files": 200, "file_kb": 64, "fast_s": 0.1, "slow_s": 2.0},
        quick={"duration_s": 4.0, "files": 40, "file_kb": 16},
        baseline=lambda p: poll_folder(p, p["fast_s"]),
        optimized=lambda p: poll_folder(p, p["slow_s"]),
        tradeoff="a change is noticed up to {slow_s} s later (see detect_latency_s)"),
    "batching": Scenario(
        name="batching", title="Batching / scheduling", mode="fixed_work",
        baseline_desc="{jobs} hashing jobs, one process launch per job",
        optimized_desc="Same {jobs} jobs in batches of {batch_size}",
        unit="job", pilot_scale=0.2,
        defaults={"jobs": 200, "rounds": 200, "batch_size": 20},
        quick={"jobs": 20, "rounds": 50, "batch_size": 10},
        baseline=lambda p: run_jobs(p, 1),
        optimized=lambda p: run_jobs(p, p["batch_size"]),
        tradeoff="the first result arrives after a whole batch instead of after one job"),
    "inference": Scenario(
        name="inference", title="Model inference settings", mode="fixed_work",
        baseline_desc="{big_model}, up to {big_tokens} output tokens",
        optimized_desc="{small_model}, up to {small_tokens} output tokens",
        unit="explanation", pilot_scale=0.34, same_checksum=True,
        defaults={"prompts": 6, "big_model": "qwen2.5:1.5b", "big_tokens": 400,
                  "small_model": "qwen2.5:0.5b", "small_tokens": 160},
        quick={"prompts": 2},
        baseline=lambda p: answer_prompts(p, p["big_model"], p["big_tokens"]),
        optimized=lambda p: answer_prompts(p, p["small_model"], p["small_tokens"]),
        tradeoff="quality = share of explanations that pass the grounding check (grounded_rate)"),
    "cascade": Scenario(
        name="cascade", title="Self-measuring AI (model cascade)", mode="fixed_work",
        baseline_desc="Always {big_model} for every explanation",
        optimized_desc="{small_model} first; {big_model} only when the fact check fails",
        unit="explanation", pilot_scale=0.34, same_checksum=True,
        defaults={"prompts": 6, "big_model": "qwen2.5:1.5b", "small_model": "qwen2.5:0.5b", "max_tokens": 180},
        quick={"prompts": 2},
        baseline=lambda p: answer_cascade(p, [p["big_model"]], p["max_tokens"]),
        optimized=lambda p: answer_cascade(p, [p["small_model"], p["big_model"]], p["max_tokens"]),
        tradeoff="quality is held by the fact check: compare grounded_rate; escalated = answers that needed the "
                 "larger model"),
}
