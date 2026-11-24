"""Energy label (A-G, like an appliance sticker) and a certificate for each receipt.

Grade = energy of the optimized setting as a share of the reference (baseline) setting, for the SAME work on the
SAME machine:  A <= 25%  B <= 40%  C <= 55%  D <= 70%  E <= 85%  F <= 100%  G > 100%
Efficiency = useful work per Wh (jobs per Wh, minutes of watching per Wh, checked answers per Wh).

A label is CERTIFIED only when: the receipt is MEASURED, the saving is significant, both settings did the same
work, and the receipt's hash chain verifies. Anything else is PROVISIONAL, with the reason printed.
"""
from __future__ import annotations

import html
import json
import time

from joule import db

BANDS = [("A", 25), ("B", 40), ("C", 55), ("D", 70), ("E", 85), ("F", 100), ("G", None)]
COLORS = {"A": "#0ca30c", "B": "#5bb318", "C": "#b5c916", "D": "#fab219", "E": "#f08a1c", "F": "#e0561f",
          "G": "#c8241a"}


def grade(ratio_pct: float) -> str:
    for g, limit in BANDS:
        if limit is None or ratio_pct <= limit:
            return g
    return "G"


def efficiency(scenario: str, body: dict, params: dict) -> dict | None:
    """Useful work per Wh for the optimized and the reference setting."""
    ob, bb = body.get("optimized_wh") or 0, body.get("baseline_wh") or 0
    if ob <= 0 or bb <= 0:
        return None
    if scenario == "batching":
        n, unit = params.get("jobs"), "jobs per Wh"
    elif scenario == "idle":
        n, unit = (params.get("duration_s") or 0) / 60.0, "minutes of watching per Wh"
    elif scenario in ("inference", "cascade"):
        n, unit = params.get("prompts"), "explanations per Wh"
    elif scenario == "certify":
        n, unit = 1, "program runs per Wh"
    else:
        return None
    if not n:
        return None
    return {"optimized": n / ob, "baseline": n / bb, "unit": unit}


def label_for(conn, receipt_id: int, chain: dict | None = None) -> dict:
    row = conn.execute("SELECT r.*, e.params_json FROM receipts r LEFT JOIN experiments e ON e.id = r.experiment_id "
                       "WHERE r.id = ?", (receipt_id,)).fetchone()
    if not row:
        raise KeyError(f"no receipt {receipt_id}")
    b = json.loads(row["body_json"])
    params = json.loads(row["params_json"] or "{}")
    bw, ow = b.get("baseline_wh") or 0.0, b.get("optimized_wh") or 0.0
    ratio = 100.0 * max(ow, 0.0) / bw if bw > 0 else 100.0
    chain = chain or db.verify_chain(conn)
    chain_ok = chain["ok"] or (chain["broken_at"] is not None and receipt_id < chain["broken_at"])
    reasons = []
    if b.get("provenance") != "MEASURED":
        reasons.append(f"energy is {b.get('provenance')}, not MEASURED")
    if b.get("p_value") is None:
        reasons.append("older receipt without the exact significance test")
    elif not b.get("significant"):
        reasons.append("saving is not statistically significant")
    if bw <= 0 or ow <= 0:
        reasons.append("energy above idle is at the noise floor, so the ratio cannot be rated")
    if not b.get("equivalent_work"):
        reasons.append("the two settings did not do the same work")
    elif b.get("scenario") == "certify" and "NOT proven" in (b.get("tradeoff") or ""):
        reasons.append("outputs were allowed to differ, so equal work is not proven")
    if not chain_ok:
        reasons.append("hash chain does not verify (a receipt was edited)")
    return {"receipt_id": receipt_id, "scenario": b.get("scenario"), "title": b.get("title"),
            "grade": grade(ratio), "ratio_pct": ratio, "saved_pct": b.get("saved_pct"),
            "efficiency": efficiency(b.get("scenario", ""), b, params), "certified": not reasons, "reasons": reasons,
            "hash": row["hash"], "prev_hash": row["prev_hash"], "chain_ok": chain_ok, "body": b,
            "created": row["created"]}


def certificate_html(lab: dict, device: str = "") -> str:
    """A self-contained one-page certificate (open in a browser, print to PDF)."""
    b, e = lab["body"], html.escape
    bars = []
    for i, (g, limit) in enumerate(BANDS):
        on = g == lab["grade"]
        rng = f"≤ {limit}%" if limit else "> 100%"
        bars.append(f'<div class="bar{" on" if on else ""}" style="width:{38 + i * 8}%;background:{COLORS[g]}">'
                    f'<b>{g}</b><span>{rng}</span>{"<i>◀</i>" if on else ""}</div>')
    eff = lab["efficiency"]
    eff_line = (f"<tr><td>Efficiency</td><td><b>{eff['optimized']:,.0f}</b> {e(eff['unit'])} "
                f"(reference: {eff['baseline']:,.0f})</td></tr>") if eff else ""
    status = ("CERTIFIED" if lab["certified"] else "PROVISIONAL")
    why = "" if lab["certified"] else "<p class='why'>Not certified: " + e("; ".join(lab["reasons"])) + "</p>"
    p = b.get("p_value")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Energy certificate · receipt #{lab['receipt_id']}</title>
<style>body{{font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:720px;margin:32px auto;color:#1a1a19;padding:0 20px}}
h1{{font-size:1.5rem;margin:0}}.sub{{color:#6b6a65;margin:4px 0 22px}}.grid{{display:flex;gap:28px;align-items:flex-start}}
.bars{{flex:1}}.bar{{color:#fff;margin:4px 0;padding:5px 10px;border-radius:0 4px 4px 0;display:flex;gap:10px;align-items:center;opacity:.35}}
.bar.on{{opacity:1;font-size:1.15rem;box-shadow:0 0 0 2px #1a1a19}}.bar i{{margin-left:auto;font-style:normal}}
.big{{font-size:5rem;font-weight:800;line-height:1;color:{COLORS[lab['grade']]}}}.stamp{{display:inline-block;padding:4px 10px;border:2px solid;
border-radius:6px;font-weight:700;letter-spacing:.08em;color:{'#0a7d0a' if lab['certified'] else '#a36a00'}}}
table{{border-collapse:collapse;width:100%;margin-top:22px}}td{{padding:6px 8px;border-bottom:1px solid #e6e5e0;vertical-align:top}}
td:first-child{{color:#6b6a65;width:34%}}code{{font-size:.78rem;word-break:break-all}}.why{{color:#a36a00}}</style></head><body>
<h1>⚡ Joule Receipts · Energy certificate</h1>
<p class="sub">{e(b.get('title', ''))} · receipt #{lab['receipt_id']} · {time.strftime('%d %b %Y %H:%M', time.localtime(lab['created']))}{(' · ' + e(device)) if device else ''}</p>
<div class="grid"><div class="bars">{''.join(bars)}</div>
<div><div class="big">{lab['grade']}</div><p>uses <b>{lab['ratio_pct']:.0f}%</b> of the reference energy</p><span class="stamp">{status}</span></div></div>
{why}<table>
<tr><td>Reference setting</td><td>{e(b.get('baseline', ''))}</td></tr>
<tr><td>Rated setting</td><td>{e(b.get('optimized', ''))}</td></tr>
<tr><td>Energy per run (median)</td><td>{b.get('baseline_wh', 0) * 1000:.3f} → {b.get('optimized_wh', 0) * 1000:.3f} mWh ({e(b.get('basis', ''))})</td></tr>
{eff_line}<tr><td>Evidence</td><td>{b.get('repeats')} interleaved runs each · exact Mann–Whitney p = {p} · same work: {'yes' if b.get('equivalent_work') else 'NO'}</td></tr>
<tr><td>Measured with</td><td>{e(str(b.get('sensor')))} · {e(str(b.get('provenance')))}</td></tr>
<tr><td>Trade-off</td><td>{e(b.get('tradeoff', ''))}</td></tr>
<tr><td>Receipt hash</td><td><code>{lab['hash']}</code></td></tr>
<tr><td>Previous hash</td><td><code>{lab['prev_hash']}</code></td></tr>
<tr><td>Hash chain</td><td>{'verified ✓' if lab['chain_ok'] else 'BROKEN ✗'} (sha256 over the previous hash, id, time and the receipt body)</td></tr>
</table></body></html>"""


def tamper_demo(conn, receipt_id: int | None = None) -> dict:
    """Show what an edit does WITHOUT touching the real database: change one number in a copy and re-verify."""
    rows = [dict(r) for r in conn.execute("SELECT id, created, body_json, prev_hash, hash FROM receipts ORDER BY id")]
    if not rows:
        return {"ok": True, "n": 0, "broken_at": None, "edited": None}
    def saved(r):
        return json.loads(r["body_json"]).get("measured_saved_wh") or 0

    # default: an earlier receipt with a real saving, so the demo shows every LATER receipt failing too
    candidates = [r for r in rows[:-1] if saved(r) > 0] or rows
    target = next((r for r in rows if r["id"] == receipt_id), candidates[-1])
    body = json.loads(target["body_json"])
    old = body.get("measured_saved_wh", 0)
    body["measured_saved_wh"] = round(old * 2 + 0.001, 6)            # "make the saving look twice as big"
    target["body_json"] = db.dumps(body)
    res = db.verify_chain(conn, rows)
    res["edited"] = {"receipt_id": target["id"], "field": "measured_saved_wh", "from": old,
                     "to": body["measured_saved_wh"]}
    return res
