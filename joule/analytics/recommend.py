"""Turn stored readings and experiments into recommendations with explicit, checkable facts and predictions.

Every recommendation carries:
  facts        the only numbers the SLM may use (already rounded for display)
  predictions  stored in the predictions table, each with method and provenance
  confidence   needs_review=True below 0.6 (the 'flag for a person' idea from customer-feedback-analyzer)
"""
from __future__ import annotations

import json
import math
from collections import defaultdict

from joule import config, db, energy
from joule.analytics import anomaly, apriori, knowledge, markov
from joule.provenance import Provenance, combine

REVIEW_BELOW = 0.6


def r(x: float | None, sig: int = 3) -> float | None:
    """Round to `sig` significant figures (what the user and the SLM see)."""
    if x is None or x == 0 or not math.isfinite(x):
        return x
    return round(x, sig - 1 - int(math.floor(math.log10(abs(x)))))


def projection(saved_w: float, a: config.Assumptions) -> dict:
    wh_day = saved_w * a.usage_hours_per_day
    month = energy.scale(wh_day, 1, 30, a)
    return {"saved_w": r(saved_w), "hours_per_day": a.usage_hours_per_day, "saved_wh_per_day": r(wh_day),
            "saved_kwh_per_month": r(month["kwh"]), "saved_inr_per_month": r(month["inr"]),
            "saved_co2_g_per_month": r(month["co2_g"])}


def _predictions(proj: dict, method: str, prov: Provenance) -> list[dict]:
    return [{"metric": "saved_wh_per_day", "value": proj["saved_wh_per_day"] or 0.0, "unit": "Wh/day",
             "method": method, "provenance": str(prov)},
            {"metric": "saved_inr_per_month", "value": proj["saved_inr_per_month"] or 0.0, "unit": "INR/month",
             "method": method, "provenance": str(prov)}]


def _load(conn, since_ts: float):
    samples = db.recent_samples(conn, since_ts)
    procs_by_sample = defaultdict(list)
    for p in db.proc_rows(conn, since_ts):
        procs_by_sample[p["sample_id"]].append(p)
    return samples, procs_by_sample


def background_hogs(samples, procs_by_sample, idle_w, a, min_w=0.15, top=3) -> list[dict]:
    """Apps (helpers grouped) that use the most CPU power while the laptop is idle or lightly used."""
    low = [s for s in samples if markov.classify(s["watts"], idle_w) in ("idle", "light")]
    if len(low) < 20:
        return []
    tot_w, present, provs, members = defaultdict(float), defaultdict(int), defaultdict(set), defaultdict(set)
    for s in low:
        seen = set()
        for p in procs_by_sample.get(s["id"], []):
            app = knowledge.app_of(p["name"])
            if app is None:
                continue
            tot_w[app] += p["watts"] or 0.0
            provs[app].add(p["provenance"])
            members[app].add(p["name"])
            seen.add(app)
        for app in seen:
            present[app] += 1
    recs = []
    for app in sorted(tot_w, key=lambda n: -tot_w[n])[:top]:
        avg_w = tot_w[app] / len(low)
        if avg_w < min_w:
            continue
        adv = knowledge.advice_for(app)
        conf = present[app] / len(low)
        observed_prov = combine(*provs[app])
        pred_prov = combine(observed_prov, Provenance.ESTIMATED)
        proj = projection(avg_w, a)
        recs.append({
            "key": f"background:{app}", "kind": "background", "scenario": "idle",
            "title": adv["title"], "action": adv["action"],
            "confidence": round(conf, 2), "needs_review": conf < REVIEW_BELOW,
            "facts": {
                "title": adv["title"], "kind": "background idle reduction", "app": app,
                "processes": sorted(members[app])[:5], "system_process": adv["system"],
                "headline": (f"While the laptop was idle or lightly used, {app} used about {r(avg_w)} W "
                             f"({observed_prov}). It was active in {r(conf * 100)}% of those seconds."),
                "observed": {"avg_w": r(avg_w), "active_share_pct": r(conf * 100),
                             "idle_power_w": r(idle_w), "observed_minutes": r(len(low) / 60.0),
                             "provenance": str(observed_prov)},
                "prediction": {**proj, "method": f"its power x {a.usage_hours_per_day} h/day x 30 days, if that "
                                                 f"background work stops", "provenance": str(pred_prov)},
                "action": adv["action"], "tradeoff": adv["tradeoff"],
                "verify_with": "idle experiment (polling every 100 ms vs every 2 s)",
            },
            "predictions": _predictions(proj, "attributed power projection", pred_prov),
        })
    return recs


def coactive_sets(samples, procs_by_sample, idle_w, a) -> list[dict]:
    if len(samples) < 50:
        return []
    watts_sorted = sorted(s["watts"] for s in samples)
    p80 = watts_sorted[int(0.8 * (len(watts_sorted) - 1))]
    tx_all, tx_high, high_w = [], [], []
    for s in samples:
        items = {p["name"] for p in procs_by_sample.get(s["id"], []) if p["cpu_pct"] >= 1.0}
        tx_all.append(items)
        if s["watts"] >= p80 and markov.classify(s["watts"], idle_w) in ("busy", "heavy"):
            tx_high.append(items)
            high_w.append(s["watts"])
    if len(tx_high) < 10:
        return []
    found = [c for c in apriori.contrast(tx_high, tx_all, min_support=0.3) if c["lift"] >= 1.3][:1]
    recs = []
    for c in found:
        names = " + ".join(c["items"])
        prov = combine(*(s["provenance"] for s in samples))
        recs.append({
            "key": "coactive:" + "+".join(c["items"]), "kind": "coactive", "scenario": "batching",
            "title": f"{names} spike together", "confidence": round(min(1.0, c["support_high"]), 2),
            "needs_review": True,
            "action": f"Run {names} at the same planned time (for example while charging) instead of letting them "
                      f"wake the laptop separately.",
            "facts": {
                "title": f"{names} spike together", "kind": "co-activity (Apriori)", "processes": c["items"],
                "headline": (f"{names} were active together in {r(c['support_high'] * 100)}% of high-power seconds "
                             f"but only {r(c['support_all'] * 100)}% of all seconds (lift {r(c['lift'])})."),
                "observed": {"support_high_pct": r(c["support_high"] * 100), "support_all_pct": r(c["support_all"] * 100),
                             "lift": r(c["lift"]), "high_power_threshold_w": r(p80), "provenance": str(prov)},
                "prediction": None,
                "action": f"Run {names} at the same planned time instead of separately.",
                "tradeoff": "their work happens in one block instead of whenever they want",
                "verify_with": "batching experiment",
            },
            "predictions": [],
        })
    return recs


def batching_signal(summary: dict, batching_receipt: dict | None, a) -> list[dict]:
    per_hour = summary.get("short_bursts_per_hour", 0.0)
    if per_hour < 30:
        return []
    busy_w = max(summary["mean_w"].get(s, summary["idle_w"]) for s in ("light", "busy", "heavy")
                 if s in summary["mean_w"]) if summary.get("mean_w") else summary["idle_w"]
    burst_wh_per_hour = per_hour * summary["mean_burst_s"] * max(0.0, busy_w - summary["idle_w"]) / 3600.0
    saved_pct = batching_receipt["saved_pct"] if batching_receipt else None
    proj, preds, prov = None, [], Provenance.ESTIMATED
    if saved_pct is not None and saved_pct > 0:
        saved_w = burst_wh_per_hour * saved_pct / 100.0       # Wh per hour == average W
        proj = projection(saved_w, a)
        proj["method"] = f"burst energy x measured batching saving {r(saved_pct)}%"
        proj["provenance"] = str(prov)
        preds = _predictions(proj, proj["method"], prov)
    return [{
        "key": "batching:bursts", "kind": "batching", "scenario": "batching",
        "title": "Batch frequent short wake-ups", "confidence": 0.7 if proj else 0.5, "needs_review": proj is None,
        "action": "Group small jobs (syncs, scripts, uploads) and run them together every few minutes.",
        "facts": {
            "title": "Batch frequent short wake-ups", "kind": "batching / scheduling",
            "headline": (f"The laptop woke into about {r(per_hour)} short bursts per hour, each about "
                         f"{r(summary['mean_burst_s'])} s, using about {r(burst_wh_per_hour)} Wh per hour."),
            "observed": {"short_bursts_per_hour": r(per_hour), "mean_burst_s": r(summary["mean_burst_s"]),
                         "burst_wh_per_hour": r(burst_wh_per_hour)},
            "prediction": proj,
            "action": "Group small jobs and run them together every few minutes.",
            "tradeoff": "each job finishes a little later",
            "verify_with": "batching experiment",
        },
        "predictions": preds,
    }]


def verified_from_receipts(conn, a) -> list[dict]:
    """A significant measured saving becomes a 'verified' recommendation backed by its receipt."""
    recs = []
    rows = conn.execute("SELECT r.* FROM receipts r JOIN (SELECT MAX(id) id FROM receipts GROUP BY "
                        "json_extract(body_json,'$.scenario')) last ON last.id = r.id").fetchall()
    for row in rows:
        b = json.loads(row["body_json"])
        if not (b.get("significant") and b.get("measured_saved_wh", 0) > 0 and b.get("equivalent_work")):
            continue
        facts = {
            "title": f"Verified: {b['optimized']}", "kind": f"verified saving ({b['scenario']})",
            "headline": (f"Measured over {b['repeats']} runs each ({b['provenance']}, {b['sensor']}): "
                         f"{r(b['baseline_wh'] * 1000)} mWh before vs {r(b['optimized_wh'] * 1000)} mWh after, "
                         f"a saving of {r(b['saved_pct'])}% per run."),
            "observed": {"baseline_mwh": r(b["baseline_wh"] * 1000), "optimized_mwh": r(b["optimized_wh"] * 1000),
                         "saved_mwh": r(b["measured_saved_wh"] * 1000), "saved_pct": r(b["saved_pct"]),
                         "noise_mwh": r(b["noise_wh"] * 1000), "repeats": b["repeats"],
                         "predicted_saved_mwh": r((b.get("predicted_saved_wh") or 0) * 1000) or None,
                         "prediction_error_pct": r(b["prediction_error_pct"]) if b.get("prediction_error_pct") is not None else None,
                         "provenance": b["provenance"]},
            "prediction": None, "action": b["optimized"], "tradeoff": b["tradeoff"],
            "receipt_id": row["id"],
        }
        recs.append({"key": f"verified:{b['scenario']}", "kind": "verified", "scenario": b["scenario"],
                     "title": facts["title"], "action": b["optimized"], "confidence": 0.95, "needs_review": False,
                     "facts": facts, "predictions": []})
    return recs


def build(conn, since_ts: float = 0.0, a: config.Assumptions | None = None,
          anomaly_ratio: float | None = None) -> tuple[list[dict], dict]:
    a = a or config.Assumptions()
    if anomaly_ratio is None:
        from joule import policy
        anomaly_ratio = policy.policy(conn)["anomaly_ratio"]
    samples, procs_by_sample = _load(conn, since_ts)
    summary: dict = {}
    recs: list[dict] = []
    if len(samples) >= 20:
        ws = sorted(s["watts"] for s in samples)
        idle_w = ws[int(0.1 * (len(ws) - 1))]
        summary = markov.summarize([(s["ts"], s["watts"]) for s in samples], idle_w)
        alerts = anomaly.detect(samples, procs_by_sample, ratio=anomaly_ratio)
        summary["alerts"] = alerts
        recs += anomaly.as_recommendations(alerts, a, projection)
        recs += background_hogs(samples, procs_by_sample, idle_w, a)
        recs += coactive_sets(samples, procs_by_sample, idle_w, a)
        last_batching = conn.execute("SELECT body_json FROM receipts WHERE json_extract(body_json,'$.scenario')="
                                     "'batching' ORDER BY id DESC LIMIT 1").fetchone()
        recs += batching_signal(summary, json.loads(last_batching[0]) if last_batching else None, a)
    recs += verified_from_receipts(conn, a)
    for rec in recs:
        rec["facts"]["assumptions"] = a.as_dict()
    return recs, summary


def refresh(conn, since_ts: float = 0.0) -> tuple[list[int], dict]:
    recs, summary = build(conn, since_ts)
    ids = [db.upsert_recommendation(conn, rec) for rec in recs]
    live = {rec["key"] for rec in recs if rec["kind"] == "anomaly"}
    with db.tx(conn):                      # an alert that no longer fires is cleared, not left open forever
        for row in conn.execute("SELECT id, key FROM recommendations WHERE kind='anomaly' AND status='open'").fetchall():
            if row["key"] not in live:
                conn.execute("UPDATE recommendations SET status='cleared' WHERE id=?", (row["id"],))
    return ids, summary
