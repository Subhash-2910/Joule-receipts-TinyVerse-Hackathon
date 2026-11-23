"""Readable Markdown report: measurement method, readings, recommendations (with SLM explanations), receipts,
assumptions and formulas. The executive summary is written by the local SLM from a facts digest and grounded."""
from __future__ import annotations

import json
import time
from collections import Counter

from joule import config, db, energy
from joule.analytics import markov
from joule.analytics.recommend import r
from joule.experiment import hardware_info
from joule.slm import explain as explain_mod


def _fmt_ts(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def digest(conn, since_ts: float = 0.0) -> dict:
    samples = db.recent_samples(conn, since_ts)
    d: dict = {"samples": len(samples)}
    if samples:
        pts = [(s["ts"], s["watts"]) for s in samples]
        ws = sorted(w for _, w in pts)
        idle_w = ws[int(0.1 * (len(ws) - 1))]
        summ = markov.summarize(pts, idle_w)
        d.update({
            "from": _fmt_ts(samples[0]["ts"]), "to": _fmt_ts(samples[-1]["ts"]),
            "minutes": r((samples[-1]["ts"] - samples[0]["ts"]) / 60),
            "mean_w": r(energy.mean_power(pts)), "idle_w": r(idle_w), "peak_w": r(ws[-1]),
            "energy_wh": r(energy.integrate_wh(pts)),
            "sources": dict(Counter(f"{s['source']} ({s['provenance']})" for s in samples)),
            "time_share_pct": {k: r(v * 100) for k, v in summ.get("share", {}).items()},
        })
    recs = db.list_recommendations(conn)
    d["recommendations"] = [{"title": x["title"], "status": x["status"],
                             "saved_wh_per_day": (x["facts"].get("prediction") or {}).get("saved_wh_per_day")}
                            for x in recs]
    d["receipts"] = [json.loads(row["body_json"]) for row in
                     conn.execute("SELECT body_json FROM receipts ORDER BY id DESC LIMIT 5").fetchall()]
    return d


def build_report(conn, since_ts: float = 0.0, use_slm: bool = True, model: str | None = None) -> dict:
    a = config.Assumptions()
    d = digest(conn, since_ts)
    receipts_short = [{"scenario": x["scenario"], "saved_pct": x["saved_pct"],
                       "saved_mwh": r(x["measured_saved_wh"] * 1000), "significant": x["significant"],
                       "provenance": x["provenance"]} for x in d["receipts"]]
    summary_facts = {k: v for k, v in d.items() if k not in ("receipts",)} | {"receipts": receipts_short}
    summary_facts["headline"] = (f"Over {d.get('minutes', 0)} minutes the laptop averaged {d.get('mean_w', 0)} W "
                                 f"with an idle floor of {d.get('idle_w', 0)} W.") if d["samples"] else "No readings yet."
    res = explain_mod.explain(summary_facts, model=model, max_tokens=260) if use_slm else \
        explain_mod.ExplainResult(text=explain_mod.template(summary_facts), model="template", grounded=True, fallback=True)

    L = [f"# Energy report — {_fmt_ts(time.time())}", "",
         f"_Written by: **{res.model}** · grounding check: **{'passed' if res.grounded else 'FAILED'}**_", "",
         "## Summary", "", res.text, ""]
    L += ["## How this was measured", "", "| | |", "|---|---|",
          f"| Hardware | {hardware_info().get('cpu', '')} · {hardware_info()['os']} |",
          f"| Sources (samples) | {', '.join(f'{k}: {v}' for k, v in d.get('sources', {}).items()) or '—'} |",
          f"| Sampling interval | {config.Settings().sample_interval_s} s |",
          f"| Window | {d.get('from', '—')} → {d.get('to', '—')} ({d.get('minutes', 0)} min) |", "",
          "Provenance: **MEASURED** = hardware sensor, **ATTRIBUTED** = measured total split by CPU share, "
          "**ESTIMATED** = model with stated constants, **SIMULATED** = simulation model.", ""]
    if d["samples"]:
        L += ["## Readings", "", "| Mean | Idle floor | Peak | Energy in window |", "|---|---|---|---|",
              f"| {d['mean_w']} W | {d['idle_w']} W | {d['peak_w']} W | {d['energy_wh']} Wh |", "",
              "Time in each state: " + ", ".join(f"{k} {v}%" for k, v in d["time_share_pct"].items()), ""]
    L += ["## Recommendations", ""]
    for rec in db.list_recommendations(conn):
        last = conn.execute("SELECT body, model, grounded FROM reports WHERE rec_id=? AND kind='explanation' "
                            "ORDER BY id DESC LIMIT 1", (rec["id"],)).fetchone()
        pred = rec["facts"].get("prediction") or {}
        L += [f"### {rec['id']}. {rec['title']}  `{rec['status']}`"
              + ("  ⚠️ needs review" if rec["needs_review"] else ""), "",
              (last["body"] if last else explain_mod.template(rec["facts"])), ""]
        if pred:
            L += [f"Prediction ({pred.get('provenance')}): {pred.get('saved_wh_per_day')} Wh/day · "
                  f"₹{pred.get('saved_inr_per_month')}/month · {pred.get('saved_co2_g_per_month')} g CO₂e/month — "
                  f"{pred.get('method', '')}", ""]
    L += ["## Receipts (baseline vs optimized)", "",
          "| Scenario | Baseline (mWh/run) | Optimized (mWh/run) | Saved | Predicted | Significant | Provenance |",
          "|---|---|---|---|---|---|---|"]
    for x in d["receipts"]:
        pred = "—" if x.get("predicted_saved_wh") is None else f"{r(x['predicted_saved_wh'] * 1000)} mWh"
        L.append(f"| {x['scenario']} | {r(x['baseline_wh'] * 1000)} ± {r(x['baseline_wh_std'] * 1000)} | "
                 f"{r(x['optimized_wh'] * 1000)} ± {r(x['optimized_wh_std'] * 1000)} | "
                 f"{r(x['measured_saved_wh'] * 1000)} mWh ({x['saved_pct']}%) | {pred} | "
                 f"{'yes' if x['significant'] else 'no'} | {x['provenance']} |")
    L += ["", "## Assumptions and formulas", "",
          f"- Tariff: ₹{a.tariff_inr_per_kwh}/kWh — {a.tariff_source}",
          f"- Grid emission factor: {a.grid_kg_per_kwh} kg CO₂/kWh — {a.grid_source}",
          f"- Usage for projections: {a.usage_hours_per_day} h/day, 30 days/month", ""]
    L += [f"- `{v}`" for v in energy.FORMULAS.values()]
    body = "\n".join(L) + "\n"
    out_dir = config.data_dir() / "reports"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"report-{time.strftime('%Y%m%d-%H%M%S')}.md"
    path.write_text(body)
    rid = db.save_report(conn, "report", body, res.model, res.grounded, res.ungrounded, facts=summary_facts,
                         latency_s=res.latency_s, tokens=res.tokens)
    return {"report_id": rid, "path": str(path), "model": res.model, "grounded": res.grounded}
