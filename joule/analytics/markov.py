"""Workload states and a first-order Markov chain over them (the learning-path-predictor baseline, reused).

States come from dynamic power (watts above idle). The chain gives: how long idle stretches last, how often the
machine wakes into short bursts (a batching signal), and the chance of being idle soon (a scheduling signal).
"""
from __future__ import annotations

import statistics
import time
from collections import Counter, defaultdict

STATES = ("idle", "light", "busy", "heavy")
THRESHOLDS_W = (0.5, 2.0, 6.0)   # dynamic watts: <0.5 idle, <2 light, <6 busy, else heavy


def classify(watts: float, idle_w: float, thresholds=THRESHOLDS_W) -> str:
    d = watts - idle_w
    for state, limit in zip(STATES, thresholds):
        if d < limit:
            return state
    return STATES[-1]


def transition_matrix(states: list[str], smoothing: float = 1.0) -> dict[str, dict[str, float]]:
    counts: dict[str, Counter] = defaultdict(Counter)
    for a, b in zip(states, states[1:]):
        counts[a][b] += 1
    matrix = {}
    for a in STATES:
        total = sum(counts[a].values()) + smoothing * len(STATES)
        matrix[a] = {b: (counts[a][b] + smoothing) / total for b in STATES}
    return matrix


def p_reach_within(matrix, start: str, target: str, steps: int) -> float:
    """P(the chain visits `target` within `steps` steps from `start`)."""
    if start == target:
        return 1.0
    prob = {s: (1.0 if s == start else 0.0) for s in STATES}
    reached = 0.0
    for _ in range(steps):
        nxt = {s: 0.0 for s in STATES}
        for a, pa in prob.items():
            if pa:
                for b, pab in matrix[a].items():
                    nxt[b] += pa * pab
        reached += nxt[target]
        nxt[target] = 0.0           # absorb
        prob = nxt
    return reached


def expected_run_steps(matrix, state: str) -> float:
    stay = matrix[state][state]
    return 1.0 / (1.0 - stay) if stay < 1 else float("inf")


def bursts(states: list[str]) -> list[int]:
    """Lengths of non-idle stretches that start and end in idle."""
    out, cur, seen_idle = [], 0, False
    for s in states:
        if s == "idle":
            if cur and seen_idle:
                out.append(cur)
            cur, seen_idle = 0, True
        else:
            cur += 1
    return out


def summarize(samples: list[tuple[float, float]], idle_w: float, interval_s: float = 1.0) -> dict:
    """samples: (ts, watts) in time order."""
    if len(samples) < 2:
        return {}
    states = [classify(w, idle_w) for _, w in samples]
    matrix = transition_matrix(states)
    share = Counter(states)
    by_state = defaultdict(list)
    for (_, w), s in zip(samples, states):
        by_state[s].append(w)
    hours = max(1e-9, (samples[-1][0] - samples[0][0]) / 3600.0)
    b = bursts(states)
    short = [x for x in b if x * interval_s <= 10]
    hourly = defaultdict(list)
    for (ts, _), s in zip(samples, states):
        hourly[time.localtime(ts).tm_hour].append(s == "idle")
    idle_by_hour = {h: statistics.fmean(v) for h, v in hourly.items() if len(v) >= 30}
    return {
        "n": len(states), "idle_w": idle_w,
        "share": {s: share[s] / len(states) for s in STATES},
        "mean_w": {s: statistics.fmean(v) for s, v in by_state.items()},
        "matrix": matrix,
        "expected_idle_run_s": expected_run_steps(matrix, "idle") * interval_s,
        "short_bursts_per_hour": len(short) / hours,
        "mean_burst_s": statistics.fmean(b) * interval_s if b else 0.0,
        "current_state": states[-1],
        "p_idle_within_60s": p_reach_within(matrix, states[-1], "idle", max(1, int(60 / interval_s))),
        "idle_share_by_hour": idle_by_hour,
    }
