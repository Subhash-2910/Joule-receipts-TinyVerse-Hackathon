"""Anomaly alerts: something is using far more power than it usually does.

For each app (helpers grouped), usual power = its mean attributed power over the earlier readings from the SAME
sensor; recent power = its mean over the last `recent_s` seconds. An alert fires when recent >= ratio x usual and
the extra power is at least `min_extra_w` (so 0.01 W -> 0.05 W does not count). The ratio comes from the Goal switch.
The whole machine is checked the same way on its resting power (10th percentile), which catches hidden background
work that no single app explains.
"""
from __future__ import annotations

import statistics
from collections import defaultdict

from joule import config
from joule.analytics import knowledge
from joule.provenance import Provenance, combine

USUAL_FLOOR_W = 0.05


def _pct(values: list[float], q: float) -> float:
    s = sorted(values)
    return s[int(q * (len(s) - 1))]


def detect(samples, procs_by_sample, ratio: float = 3.0, recent_s: float = 60.0, min_extra_w: float = 0.3,
           min_baseline: int = 30, min_recent: int = 8) -> list[dict]:
    """samples: rows with id, ts, watts, source, provenance (time order). Returns alert dicts, worst first."""
    if not samples:
        return []
    last = samples[-1]
    same = [s for s in samples if s["source"] == last["source"]]
    recent = [s for s in same if s["ts"] >= last["ts"] - recent_s]
    base = [s for s in same if s["ts"] < last["ts"] - recent_s]
    if len(base) < min_baseline or len(recent) < min_recent:
        return []

    def per_app(rows):
        tot, provs = defaultdict(float), defaultdict(set)
        for s in rows:
            for p in procs_by_sample.get(s["id"], []):
                app = knowledge.app_of(p["name"])
                if app:
                    tot[app] += p["watts"] or 0.0
                    provs[app].add(p["provenance"])
        return {a: w / len(rows) for a, w in tot.items()}, provs

    usual, _ = per_app(base)
    now, provs = per_app(recent)
    alerts = []
    for app, w in now.items():
        u = usual.get(app, 0.0)
        times = w / max(u, USUAL_FLOOR_W)
        if times >= ratio and w - u >= min_extra_w:
            prov = combine(*provs[app])
            alerts.append({"subject": app, "kind": "app", "recent_w": w, "usual_w": u, "times": times,
                           "extra_w": w - u, "provenance": str(prov), "recent_s": recent_s,
                           "baseline_n": len(base), "recent_n": len(recent), "sensor": last["source"]})
    rest_now = _pct([s["watts"] for s in recent], 0.1)
    rest_usual = _pct([s["watts"] for s in base], 0.1)
    machine_ratio = 1 + (ratio - 1) / 4                     # 3x per app -> 1.5x for the whole machine
    if rest_usual > 0 and rest_now / rest_usual >= machine_ratio and rest_now - rest_usual >= min_extra_w:
        alerts.append({"subject": "whole laptop (resting power)", "kind": "machine", "recent_w": rest_now,
                       "usual_w": rest_usual, "times": rest_now / rest_usual, "extra_w": rest_now - rest_usual,
                       "provenance": str(combine(*(s["provenance"] for s in recent))), "recent_s": recent_s,
                       "baseline_n": len(base), "recent_n": len(recent), "sensor": last["source"]})
    return sorted(alerts, key=lambda a: -a["extra_w"])


def as_recommendations(alerts: list[dict], a: config.Assumptions, projection) -> list[dict]:
    from joule.analytics.recommend import r
    recs = []
    for al in alerts:
        app = al["subject"]
        pred_prov = combine(al["provenance"], Provenance.ESTIMATED)
        proj = projection(al["extra_w"], a)
        if al["kind"] == "machine":
            title = "Resting power is higher than usual"
            action = ("Open Activity Monitor > CPU, sort by % CPU and quit anything you did not start "
                      "(a stuck update, indexer or browser tab).")
            tradeoff = "the app you quit stops whatever it was doing"
        else:
            title = f"Unusual power: {app}"
            action = (f"Check what {app} is doing right now; if nothing you need is running, quit or restart it.")
            tradeoff = f"closing {app} ends what it was doing"
        recs.append({
            "key": f"anomaly:{app}", "kind": "anomaly", "scenario": "idle", "title": title, "action": action,
            "confidence": 0.8 if al["recent_n"] >= 20 else 0.6, "needs_review": al["recent_n"] < 20,
            "facts": {
                "title": title, "kind": "anomaly alert", "app": app,
                "headline": (f"In the last {r(al['recent_s'])} s, {app} used about {r(al['recent_w'])} W "
                             f"({al['provenance']}), {r(al['times'])} times its usual {r(al['usual_w'])} W."),
                "observed": {"recent_w": r(al["recent_w"]), "usual_w": r(al["usual_w"]), "times_usual": r(al["times"]),
                             "extra_w": r(al["extra_w"]), "recent_seconds": r(al["recent_s"]),
                             "baseline_readings": al["baseline_n"], "provenance": al["provenance"]},
                "prediction": {**proj, "method": f"the extra power x {a.usage_hours_per_day} h/day x 30 days, if it "
                                                 f"kept going", "provenance": str(pred_prov)},
                "action": action, "tradeoff": tradeoff,
                "verify_with": "collect again after acting: the alert clears when power is back to usual",
            },
            "predictions": [],
        })
    return recs
