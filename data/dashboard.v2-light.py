"""Streamlit dashboard: .venv/bin/streamlit run joule/dashboard.py

Everything reads the local SQLite database, so the dashboard works with no network (system fonts only, no CDN).
Long jobs (collecting, experiments) run as separate `python -m joule` processes, so the page stays responsive and
nothing is lost if the browser closes.
"""
from __future__ import annotations

import html
from datetime import datetime
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from joule import config, db, energy  # noqa: E402
from joule.analytics import markov, recommend  # noqa: E402
from joule.analytics.knowledge import app_of  # noqa: E402
from joule.analytics.recommend import r  # noqa: E402
from joule.sensors import get_sensor  # noqa: E402
from joule.slm import client, explain  # noqa: E402
from joule.sync import outbox  # noqa: E402
from joule.sync.worker import SyncWorker  # noqa: E402

# Validated reference palette (dataviz skill): slot 1 blue, slot 2 orange; neutral ink; ordinal blue ramp.
BLUE, ORANGE = "#2a78d6", "#eb6834"
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e1"
RAMP = ["#86b6ef", "#5598e7", "#256abf", "#104281"]          # idle -> heavy (ordinal, step 250 and darker)
SCENARIOS = {"idle": "Idle background polling", "batching": "Batching small jobs", "inference": "Model inference"}

st.set_page_config(page_title="Joule Receipts", page_icon="⚡", layout="wide")

CSS = """
<style>
:root {
  --ink:#0b0b0b; --ink2:#52514e; --muted:#8a8984; --line:#e2e1dc; --card:#fcfcfb; --paper:#fffefa;
  --blue:#2a78d6; --orange:#eb6834;
  --mono: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace;
}
.block-container { padding-top: 1.6rem; max-width: 1240px; }
h1, h2, h3, h4 { letter-spacing: -0.01em; }
[data-testid="stMarkdownContainer"] h1 { font-size:1.6rem; }
[data-testid="stMarkdownContainer"] h2 { font-size:1.2rem; margin-top:0.6rem; }
[data-testid="stMarkdownContainer"] h3 { font-size:1.05rem; }
[data-testid="stSidebar"] { background: #efeee9; border-right: 1px solid var(--line); }

/* header */
.jr-head { display:flex; align-items:flex-end; justify-content:space-between; gap:16px; flex-wrap:wrap;
  padding-bottom:14px; border-bottom:1px solid var(--line); margin-bottom:18px; }
.jr-brand { font-size:1.7rem; font-weight:700; color:var(--ink); line-height:1.1; }
.jr-brand span { color:var(--blue); }
.jr-tag { color:var(--ink2); font-size:0.92rem; margin-top:4px; }
.jr-pills { display:flex; gap:8px; flex-wrap:wrap; }
.jr-pill { display:inline-flex; align-items:center; gap:7px; padding:5px 11px; border-radius:999px;
  background:var(--card); border:1px solid var(--line); font-size:0.82rem; color:var(--ink2); white-space:nowrap; }
.jr-pill b { color:var(--ink); font-weight:600; }
.jr-dot { width:8px; height:8px; border-radius:50%; display:inline-block; }
.ok { background:#0ca30c; } .warn { background:#fab219; } .off { background:#b5b4ae; }

/* provenance badge: icon + label, never colour alone */
.prov { display:inline-block; padding:2px 8px; border-radius:6px; font:600 0.72rem/1.5 var(--mono);
  letter-spacing:0.04em; border:1px solid; vertical-align:middle; }
.prov-MEASURED  { color:#006300; background:#e9f5e9; border-color:#bfe0bf; }
.prov-ATTRIBUTED{ color:#1c5cab; background:#eaf2fc; border-color:#b7d3f6; }
.prov-ESTIMATED { color:#7a5200; background:#fdf3dc; border-color:#f3d79a; }
.prov-SIMULATED { color:#52514e; background:#f0efec; border-color:#dddcd6; }

/* hero tiles */
.jr-label { font-size:0.75rem; font-weight:600; text-transform:uppercase; letter-spacing:0.08em; color:var(--muted);
  margin:2px 0 10px; }
.jr-tile { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px 18px; height:100%; }
.jr-tile .t { color:var(--ink2); font-size:0.86rem; font-weight:600; }
.jr-tile .big { font-size:2.5rem; font-weight:700; color:var(--ink); line-height:1.1; margin:6px 0 2px;
  font-variant-numeric: tabular-nums; letter-spacing:-0.02em; }
.jr-tile .big small { font-size:0.95rem; font-weight:500; color:var(--ink2); letter-spacing:0; }
.jr-tile .sub { color:var(--ink2); font-size:0.85rem; font-variant-numeric: tabular-nums; }
.jr-tile .foot { color:var(--muted); font-size:0.78rem; margin-top:10px; }
.jr-tile.empty { background:transparent; border-style:dashed; }
.jr-tile.empty .big { color:var(--muted); font-size:1.6rem; }
.arrow { color:var(--muted); padding:0 4px; }

/* stat row (small) */
.jr-stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; margin:4px 0 8px; }
.jr-stat { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:10px 14px; }
.jr-stat .k { color:var(--muted); font-size:0.76rem; font-weight:600; }
.jr-stat .v { color:var(--ink); font-size:1.35rem; font-weight:700; font-variant-numeric: tabular-nums; }
.jr-stat .v small { font-size:0.8rem; font-weight:500; color:var(--ink2); }

/* receipt paper */
.receipt { background:var(--paper); border:1px solid var(--line); border-radius:4px 4px 0 0; padding:18px 20px 22px;
  font-family:var(--mono); font-size:0.82rem; color:var(--ink); position:relative;
  box-shadow:0 1px 2px rgba(0,0,0,0.04); margin-bottom:14px; }
.receipt::after { content:""; position:absolute; left:-1px; right:-1px; bottom:-9px; height:10px;
  background: linear-gradient(-45deg, transparent 6px, var(--paper) 0) 0 0/12px 10px repeat-x,
              linear-gradient(45deg, transparent 6px, var(--paper) 0) 0 0/12px 10px repeat-x; }
.receipt .hd { text-align:center; font-weight:700; letter-spacing:0.12em; font-size:0.78rem; color:var(--ink2); }
.receipt .ttl { text-align:center; font-weight:700; font-size:0.98rem; margin:4px 0 2px; }
.receipt .meta { text-align:center; color:var(--muted); font-size:0.74rem; }
.receipt hr { border:none; border-top:1px dashed #cfcec8; margin:10px 0; }
.receipt .row { display:flex; justify-content:space-between; gap:12px; padding:1px 0; }
.receipt .row span:first-child { color:var(--ink2); white-space:nowrap; }
.receipt .row span:last-child { text-align:right; font-variant-numeric: tabular-nums; }
.receipt .total { font-size:1.05rem; font-weight:700; }
.receipt .total span:first-child { color:var(--ink); }
.receipt .desc { color:var(--ink2); font-size:0.76rem; line-height:1.45; }
.verdict { display:inline-block; padding:1px 8px; border-radius:4px; font-weight:700; }
.verdict.yes { color:#006300; background:#e9f5e9; } .verdict.no { color:#7a5200; background:#fdf3dc; }
.dot-blue, .dot-orange { display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:6px; }
.dot-blue { background:var(--blue); } .dot-orange { background:var(--orange); }

/* recommendation card bits */
.rec-title { font-size:1.12rem; font-weight:700; color:var(--ink); margin:0; }
.rec-head { color:var(--ink2); margin:4px 0 10px; font-size:0.93rem; }
.status { display:inline-block; padding:2px 10px; border-radius:999px; font-size:0.76rem; font-weight:600;
  border:1px solid var(--line); background:#f3f2ee; color:var(--ink2); text-transform:capitalize; }
.status.accepted { background:#e9f5e9; color:#006300; border-color:#bfe0bf; }
.status.rejected { background:#fbeaea; color:#9b2a2a; border-color:#efc4c4; }
.status.deferred { background:#fdf3dc; color:#7a5200; border-color:#f3d79a; }
.explain { border-left:3px solid var(--blue); background:#f4f8fd; border-radius:0 10px 10px 0;
  padding:12px 16px; color:var(--ink); font-size:0.93rem; line-height:1.55; margin:6px 0 4px; }
.explain-meta { color:var(--muted); font-size:0.78rem; margin-bottom:8px; }

/* sync flow */
.flow { display:flex; align-items:stretch; gap:8px; flex-wrap:wrap; margin:6px 0 14px; }
.flow .step { flex:1; min-width:120px; background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:12px 14px; }
.flow .step .k { color:var(--muted); font-size:0.76rem; font-weight:600; }
.flow .step .v { font-size:1.7rem; font-weight:700; font-variant-numeric: tabular-nums; }
.flow .sep { align-self:center; color:var(--muted); font-size:1.2rem; }
.flow .step.dead .v { color:#9b2a2a; }
.note { color:var(--ink2); font-size:0.88rem; }
.mono { font-family:var(--mono); }
div[data-testid="stTabs"] button p { font-size:0.95rem; font-weight:600; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


@st.cache_resource
def background_sync():
    """One sync 'postman' per dashboard server: checks the cloud every 3 s and drains the outbox automatically
    when it is reachable. Started once, shared by every browser tab, stops with the dashboard."""
    import threading
    stop = threading.Event()
    log_path = config.data_dir() / "sync.log"

    def log(msg: str) -> None:
        with open(log_path, "a") as fh:
            fh.write(f"{time.strftime('%H:%M:%S')}  {msg}\n")

    worker = SyncWorker(log=log)
    threading.Thread(target=worker.run, kwargs={"poll_s": 3.0, "stop": stop}, daemon=True,
                     name="joule-sync").start()
    return stop


background_sync()


# ------------------------------------------------------------------ helpers
def conn():
    return db.connect()


def esc(x) -> str:
    return html.escape(str(x))


def prov(p: str) -> str:
    p = str(p or "ESTIMATED")
    return f'<span class="prov prov-{esc(p)}">{esc(p)}</span>'


def show(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def fmt_p(p) -> str:
    if p is None:
        return "n/a"
    return "p < 0.001" if p < 0.001 else f"p = {p:.2g}"


def mwh(wh: float) -> str:
    return f"{r(wh * 1000)}"


def style(fig: go.Figure, title: str = "", y_title: str = "", x_title: str = "", height: int = 300) -> go.Figure:
    fig.update_layout(
        title={"text": title, "font": {"size": 14, "color": INK}, "x": 0, "xanchor": "left"} if title else None,
        height=height, margin=dict(l=4, r=8, t=44 if title else 8, b=4),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font={"color": INK2, "size": 12, "family": "-apple-system, system-ui, sans-serif"},
        hoverlabel={"bgcolor": "white", "bordercolor": GRID, "font": {"color": INK, "size": 12}},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "x": 0, "title": None, "font": {"size": 12}},
    )
    fig.update_xaxes(title=x_title, showgrid=False, linecolor=GRID, zeroline=False, ticks="")
    fig.update_yaxes(title=y_title, gridcolor=GRID, zeroline=False, rangemode="tozero", ticks="")
    return fig


def spawn(args: list[str]) -> None:
    """Run a joule command in the background (separate process, survives page reloads)."""
    log = config.data_dir() / "jobs.log"
    with open(log, "a") as fh:
        fh.write(f"\n$ joule {' '.join(args)}  ({time.strftime('%H:%M:%S')})\n")
        subprocess.Popen([sys.executable, "-m", "joule", *args], cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT)


def receipts(c) -> list[tuple]:
    return [(row, json.loads(row["body_json"])) for row in c.execute("SELECT * FROM receipts ORDER BY id DESC")]


def best_per_scenario(bodies) -> dict:
    """The strongest evidence per scenario: newest MEASURED + significant, else newest of any kind."""
    best = {}
    for row, b in bodies:                                   # newest first
        cur = best.get(b["scenario"])
        strong = b["provenance"] == "MEASURED" and b["significant"]
        if cur is None or (strong and not (cur[1]["provenance"] == "MEASURED" and cur[1]["significant"])):
            best[b["scenario"]] = (row, b)
    return best


def run_values(c, experiment_id, basis_text: str) -> dict[str, list[float]]:
    col = "net_wh" if "above idle" in (basis_text or "") else "energy_wh"
    out = {"baseline": [], "optimized": []}
    for x in c.execute(f"SELECT variant, {col} AS v FROM experiment_runs WHERE experiment_id=? ORDER BY started",
                       (experiment_id,)):
        out.setdefault(x["variant"], []).append(x["v"])
    return out


# ------------------------------------------------------------------ header
s = config.Settings()
sensor = get_sensor("auto")
slm_ok = client.is_available(settings=s)
cloud_ok = SyncWorker(log=lambda *_: None).online()
pending = outbox.stats(conn())["pending"]

pill = lambda cls, k, v: f'<span class="jr-pill"><span class="jr-dot {cls}"></span>{k} <b>{v}</b></span>'  # noqa: E731
show(f"""
<div class="jr-head">
  <div><div class="jr-brand">⚡ Joule <span>Receipts</span></div>
       <div class="jr-tag">Offline-first energy copilot: it measures, recommends, explains, and proves every saving.</div></div>
  <div class="jr-pills">
    {pill("ok" if sensor.provenance == "MEASURED" else "warn", "Sensor", f"{esc(sensor.name)}")}
    {pill("ok" if slm_ok else "warn", "Local SLM", esc(s.llm_model) if slm_ok else "template fallback")}
    {pill("ok" if cloud_ok else "off", "Cloud", "synced" if cloud_ok and not pending
          else (f"{pending} queued" if pending else "offline"))}
  </div>
</div>""")

# ------------------------------------------------------------------ hero: proven savings
_c = conn()
_best = best_per_scenario(receipts(_c))
show('<div class="jr-label">Proven savings · baseline vs optimized, same work</div>')
cols = st.columns(3)
for col, (key, name) in zip(cols, SCENARIOS.items()):
    with col:
        if key not in _best:
            show(f"""<div class="jr-tile empty"><div class="t">{name}</div><div class="big">Not measured yet</div>
                 <div class="foot mono">sudo python3 -m joule experiment {key} --source powermetrics</div></div>""")
            continue
        row, b = _best[key]
        verdict = ("significant" if b["significant"] else "not significant") + f" · {fmt_p(b.get('p_value'))}"
        show(f"""<div class="jr-tile"><div class="t">{name}</div>
          <div class="big">−{b['saved_pct']:.0f}%<small> energy</small></div>
          <div class="sub"><span class="dot-orange"></span>{mwh(b['baseline_wh'])}<span class="arrow">→</span>
               <span class="dot-blue"></span>{mwh(b['optimized_wh'])} mWh per run</div>
          <div class="foot">{prov(b['provenance'])} &nbsp;{b['repeats']} runs each · {verdict} · receipt #{row['id']}</div>
        </div>""")
st.write("")

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown("### Controls")
    st.caption("Collect readings in the background (a separate process; you can close the page).")
    secs = st.select_slider("Duration", options=[60, 120, 300, 600], value=120, format_func=lambda x: f"{x // 60} min")
    if st.button("Start collecting", width="stretch", type="primary"):
        spawn(["collect", "--seconds", str(secs)])
        st.toast(f"Collecting for {secs // 60} min from {sensor.name}")
    st.divider()
    a = config.Assumptions()
    st.markdown("### Assumptions")
    show(f"""<div class="note">Tariff <b>₹{a.tariff_inr_per_kwh}/kWh</b><br><span style="color:{MUTED}">{esc(a.tariff_source)}</span>
         <br><br>Grid <b>{a.grid_kg_per_kwh} kg CO₂/kWh</b><br><span style="color:{MUTED}">{esc(a.grid_source)}</span>
         <br><br>Projection <b>{a.usage_hours_per_day:g} h/day</b>, 30 days/month</div>""")
    with st.expander("Formulas"):
        for f in energy.FORMULAS.values():
            st.code(f, language=None)
    st.divider()
    st.caption(f"Sensor: {sensor.description}")

tab_proof, tab_recs, tab_live, tab_sync, tab_report = st.tabs(
    ["Receipts", "Recommendations", "Live power", "Sync", "Report"])


# ------------------------------------------------------------------ receipts
def receipt_html(row, b, durations) -> str:
    a_ = b["assumptions"]
    dur = f" ({durations:.0f} s each)" if durations else ""
    sig = (f'<span class="verdict yes">PROVEN</span>' if b["significant"]
           else f'<span class="verdict no">NOT PROVEN</span>')
    pred = b.get("predicted_saved_wh")
    rows = [
        ("Baseline (median)", f"{mwh(b['baseline_wh'])} mWh"),
        ("Optimized (median)", f"{mwh(b['optimized_wh'])} mWh"),
    ]
    body = "".join(f'<div class="row"><span>{esc(k)}</span><span>{v}</span></div>' for k, v in rows)
    when = time.strftime("%d %b %Y · %H:%M", time.localtime(row["created"]))
    return f"""
<div class="receipt">
  <div class="hd">ENERGY RECEIPT #{row['id']:04d}</div>
  <div class="ttl">{esc(b['title'])}</div>
  <div class="meta">{when} · {esc(b['sensor'])} · {prov(b['provenance'])}</div>
  <hr>
  <div class="desc"><span class="dot-orange"></span><b>Before:</b> {esc(b['baseline'])}<br>
       <span class="dot-blue"></span><b>After:</b> {esc(b['optimized'])}</div>
  <hr>
  <div class="row"><span>Runs</span><span>{b['repeats']} + {b['repeats']}, interleaved{dur}</span></div>
  <div class="row"><span>Measured as</span><span>{'energy above idle' if 'above idle' in (b.get('basis') or '') else 'total energy'}</span></div>
  <div class="row"><span>Idle power</span><span>{b['idle_w']} W</span></div>
  <hr>{body}
  <hr>
  <div class="row total"><span>SAVED PER RUN</span><span>{mwh(b['measured_saved_wh'])} mWh · −{b['saved_pct']}%</span></div>
  <div class="row"><span>Verdict</span><span>{sig} {fmt_p(b.get('p_value'))}</span></div>
  <div class="row"><span>Pilot prediction</span><span>{'—' if pred is None else f"{mwh(pred)} mWh (error {b.get('prediction_error_pct')}%)"}</span></div>
  <div class="row"><span>Same work done</span><span>{'yes · checksum match' if b['equivalent_work'] else 'NO'}</span></div>
  <hr>
  <div class="row"><span>Cost saved</span><span>₹{b['saved_inr']:.7f}</span></div>
  <div class="row"><span>CO₂e avoided</span><span>{b['saved_co2_g']:.5f} g</span></div>
  <div class="desc" style="margin-top:6px">at ₹{a_['tariff_inr_per_kwh']}/kWh and {a_['grid_kg_co2_per_kwh']} kg CO₂/kWh</div>
  <hr>
  <div class="desc"><b>Trade-off:</b> {esc(b['tradeoff'])}</div>
</div>"""


def runs_chart(vals: dict[str, list[float]]) -> go.Figure:
    fig = go.Figure()
    for variant, color in (("baseline", ORANGE), ("optimized", BLUE)):
        v = [x * 1000 for x in vals.get(variant, [])]
        if not v:
            continue
        fig.add_scatter(
            x=v, y=[variant] * len(v), mode="markers", name=f"{variant} runs",
            marker={"color": color, "size": 12, "opacity": 0.9, "line": {"color": "#fffefa", "width": 2}},
            customdata=list(range(1, len(v) + 1)),
            hovertemplate=f"{variant} run %{{customdata}}<br><b>%{{x:.3f}} mWh</b><extra></extra>")
        med = statistics.median(v)
        fig.add_scatter(x=[med], y=[variant], mode="markers", showlegend=False,
                        marker={"symbol": "line-ns", "size": 30, "line": {"color": INK, "width": 2}},
                        hovertemplate=f"median {variant}<br><b>%{{x:.3f}} mWh</b><extra></extra>")
        fig.add_annotation(x=med, y=variant, text=f"median {med:.3g}", showarrow=False, yshift=-22,
                           font={"size": 11, "color": INK2})
    fig = style(fig, x_title="mWh per run", height=240)
    fig.update_layout(margin=dict(l=4, r=8, t=34, b=4), legend={"y": 1.12})
    fig.update_yaxes(rangemode="normal", showgrid=False, categoryorder="array",
                     categoryarray=["optimized", "baseline"])
    fig.update_xaxes(showgrid=True, gridcolor=GRID, rangemode="tozero")
    return fig


with tab_proof:
    c = conn()
    bodies = receipts(c)
    if not bodies:
        st.info("No receipts yet. Run an experiment below.")
    else:
        best = best_per_scenario(bodies)
        st.caption("Each receipt compares a **baseline** and an **optimized** version doing identical work. Idle power "
                   "is measured first, runs are interleaved, and a saving counts as proven only when the "
                   "Mann-Whitney test gives p < 0.05.")
        for key in SCENARIOS:
            if key not in best:
                continue
            row, b = best[key]
            with st.container(border=True):
                left, right = st.columns([5, 6], gap="large")
                durs = [x[0] for x in c.execute("SELECT duration_s FROM experiment_runs WHERE experiment_id=?",
                                                (row["experiment_id"],))]
                with left:
                    show(receipt_html(row, b, statistics.median(durs) if durs and "same duration" in
                                      (b.get("basis") or "") else None))
                with right:
                    vals = run_values(c, row["experiment_id"], b.get("basis"))
                    if any(vals.values()):
                        show('<div class="rec-title" style="font-size:0.95rem">Every run is a dot; the black line is the median</div>')
                        st.plotly_chart(runs_chart(vals), width="stretch", key=f"runs{row['id']}")
                        with st.expander("Table view"):
                            st.dataframe([{"variant": k, "run": i + 1, "mWh": round(v * 1000, 4)}
                                          for k, vs in vals.items() for i, v in enumerate(vs)],
                                         hide_index=True, width="stretch")
                    pe = b.get("prediction_error_pct")
                    show(f"""<div class="jr-stats">
                      <div class="jr-stat"><div class="k">Saved per run</div><div class="v">{mwh(b['measured_saved_wh'])}<small> mWh</small></div></div>
                      <div class="jr-stat"><div class="k">Mann-Whitney test</div><div class="v" style="font-size:1.1rem;padding-top:4px">{fmt_p(b.get('p_value'))}</div></div>
                      <div class="jr-stat"><div class="k">Pilot prediction error</div><div class="v">{'—' if pe is None else f"{pe:g}"}<small>{'' if pe is None else ' %'}</small></div></div>
                    </div>""")

        with st.expander(f"All receipts ({len(bodies)}), including noisy and simulated runs"):
            st.dataframe([{"#": row["id"], "scenario": b["scenario"], "evidence": b["provenance"],
                           "sensor": b["sensor"], "runs": b["repeats"],
                           "baseline mWh": round(b["baseline_wh"] * 1000, 3),
                           "optimized mWh": round(b["optimized_wh"] * 1000, 3), "saved %": b["saved_pct"],
                           "proven": "yes" if b["significant"] else "no", "p": b.get("p_value"),
                           "when": time.strftime("%d %b %H:%M", time.localtime(row["created"]))}
                          for row, b in bodies], hide_index=True, width="stretch")

    with st.expander("Run a new experiment"):
        e1, e2, e3, e4 = st.columns(4)
        scen = e1.selectbox("Scenario", list(SCENARIOS), format_func=SCENARIOS.get)
        src = e2.selectbox("Sensor", ["auto", "powermetrics", "battery", "estimate", "simulated"])
        reps = e3.number_input("Repeats", 2, 10, 5)
        quick = e4.checkbox("Quick (small sizes)", value=False)
        st.caption("powermetrics needs sudo, so run it in Terminal: "
                   "`sudo python3 -m joule experiment batching --source powermetrics`. "
                   "The battery gauge refreshes every ~12–33 s, so it uses windows of at least 90 s.")
        if st.button("Start experiment in background"):
            spawn(["experiment", scen, "--source", src, "--repeats", str(reps)] + (["--quick"] if quick else []))
            st.toast("Experiment started; its receipt appears here when it finishes (see data/jobs.log)")


# ------------------------------------------------------------------ recommendations
with tab_recs:
    c = conn()
    top_l, top_r = st.columns([4, 1])
    top_l.caption("The facts and predictions are computed from your readings. The local SLM only writes the "
                  "explanation, and a grounding check rejects any number it makes up.")
    if top_r.button("Refresh from readings", width="stretch"):
        recommend.refresh(c)
        st.rerun()
    recs = db.list_recommendations(c)
    if not recs:
        st.info("No recommendations yet. Collect a few minutes of readings, then refresh.")
    for rec in recs:
        f = rec["facts"]
        pred = f.get("prediction") or {}
        with st.container(border=True):
            review = ' <span class="status deferred">needs review</span>' if rec["needs_review"] else ""
            show(f"""<div style="display:flex;justify-content:space-between;align-items:center;gap:10px">
                 <p class="rec-title">{esc(rec['title'])}</p>
                 <span><span class="status {esc(rec['status'])}">{esc(rec['status'])}</span>{review}</span></div>
                 <div class="rec-head">{esc(f.get('headline', ''))}</div>""")
            if pred:
                show(f"""<div class="jr-stats">
                  <div class="jr-stat"><div class="k">Predicted saving</div><div class="v">{esc(pred['saved_wh_per_day'])}<small> Wh/day</small></div></div>
                  <div class="jr-stat"><div class="k">Cost</div><div class="v">₹{esc(pred['saved_inr_per_month'])}<small> /month</small></div></div>
                  <div class="jr-stat"><div class="k">Carbon</div><div class="v">{esc(pred['saved_co2_g_per_month'])}<small> g CO₂e/month</small></div></div>
                </div><div class="explain-meta">{prov(pred.get('provenance', 'ESTIMATED'))} &nbsp;{esc(pred.get('method', ''))}</div>""")
            last = c.execute("SELECT body, model, grounded FROM reports WHERE rec_id=? AND kind='explanation' "
                             "ORDER BY id DESC LIMIT 1", (rec["id"],)).fetchone()
            if last:
                body = esc(last["body"]).replace("\n", "<br>")
                show(f"""<div class="explain">{body}</div>
                     <div class="explain-meta">Written offline by <b>{esc(last['model'])}</b> · grounding check
                     {'passed: every number matches the facts' if last['grounded'] else 'FAILED'}</div>""")
            b1, b2, b3, b4, _ = st.columns([1.4, 1, 1, 1, 1.6])
            if b1.button("Explain with local SLM", key=f"ex{rec['id']}", type="primary", width="stretch"):
                with st.spinner(f"{s.llm_model} is writing…"):
                    res = explain.explain(f)
                    db.save_report(c, "explanation", res.text, res.model, res.grounded, res.ungrounded,
                                   rec_id=rec["id"], facts=f, latency_s=res.latency_s, tokens=res.tokens)
                st.rerun()
            for col, decision, label in ((b2, "accept", "Accept"), (b3, "reject", "Reject"), (b4, "defer", "Defer")):
                if col.button(label, key=f"{decision}{rec['id']}", width="stretch"):
                    db.record_decision(c, rec["id"], decision, device_id=s.device_id)
                    st.toast(f"{label} saved locally and queued for sync")
                    st.rerun()


# ------------------------------------------------------------------ live
with tab_live:
    @st.fragment(run_every="5s")
    def live():
        c = conn()
        window = st.session_state.get("window_min", 10)
        rows = db.recent_samples(c, time.time() - window * 60)
        replay = ""
        if not rows:                                   # nothing live: show the most recent recorded session instead
            end = c.execute("SELECT MAX(ts) FROM samples").fetchone()[0]
            if end is None:
                st.info("No readings yet. Press **Start collecting** in the sidebar.")
                return
            rows = c.execute("SELECT * FROM samples WHERE ts BETWEEN ? AND ? ORDER BY ts",
                             (end - window * 60, end)).fetchall()
            replay = time.strftime("%d %b, %H:%M", time.localtime(end))
            st.info(f"Not collecting right now, so this shows the last recorded session (ended {replay}). "
                    "Press **Start collecting** in the sidebar for live readings.")
        pts = [(x["ts"], x["watts"]) for x in rows]
        ws = sorted(w for _, w in pts)
        idle_w = ws[int(0.1 * (len(ws) - 1))]
        last = rows[-1]
        show(f"""<div class="jr-stats">
          <div class="jr-stat"><div class="k">Power now</div><div class="v">{last['watts']:.2f}<small> W</small></div></div>
          <div class="jr-stat"><div class="k">Average</div><div class="v">{energy.mean_power(pts):.2f}<small> W</small></div></div>
          <div class="jr-stat"><div class="k">Idle floor (10th pct)</div><div class="v">{idle_w:.2f}<small> W</small></div></div>
          <div class="jr-stat"><div class="k">Energy in this {window} min window</div><div class="v">{energy.integrate_wh(pts) * 1000:.0f}<small> mWh</small></div></div>
        </div><div class="explain-meta">{prov(last['provenance'])} &nbsp;via {esc(last['source'])} · {len(rows)} samples ·
          updated {time.strftime('%H:%M:%S', time.localtime(last['ts']))}</div>""")

        fig = go.Figure(go.Scatter(
            x=[datetime.fromtimestamp(t) for t, _ in pts], y=[w for _, w in pts],
            mode="lines", line={"color": BLUE, "width": 2, "shape": "hv"},
            hovertemplate="%{x|%H:%M:%S}<br><b>%{y:.2f} W</b><extra></extra>"))
        fig.add_hline(y=idle_w, line={"color": INK2, "width": 1, "dash": "dot"}, annotation_position="bottom left",
                      annotation_text=f"idle floor {idle_w:.2f} W", annotation_font_color=INK2)
        fig.update_xaxes(tickformat="%H:%M:%S", nticks=8)
        fig.update_layout(hovermode="x")
        with st.container(border=True):
            st.plotly_chart(style(fig, "Laptop power", "W"), width="stretch")

        left, right = st.columns([3, 2], gap="medium")
        with left, st.container(border=True):
            ids = [x["id"] for x in rows]
            ph = ",".join("?" * len(ids))
            per_app: dict[str, float] = {}
            provs = set()
            for p in c.execute(f"SELECT name, watts, provenance FROM proc_samples WHERE sample_id IN ({ph})", ids):
                app = app_of(p["name"])
                if app:
                    per_app[app] = per_app.get(app, 0.0) + (p["watts"] or 0.0) / len(ids)
                    provs.add(p["provenance"])
            top = sorted(per_app.items(), key=lambda kv: kv[1])[-8:]
            if top:
                bar = go.Figure(go.Bar(
                    x=[v for _, v in top], y=[k for k, _ in top], orientation="h",
                    marker={"color": BLUE, "cornerradius": 4}, width=0.6,
                    text=[f"{v:.2f} W" for _, v in top], textposition="outside", cliponaxis=False,
                    textfont={"color": INK2, "size": 11},
                    hovertemplate="%{y}<br><b>%{x:.3f} W</b> average<extra></extra>"))
                bar = style(bar, "Average power by app", x_title="W", height=320)
                bar.update_yaxes(showgrid=False)
                st.plotly_chart(bar, width="stretch")
                st.caption(f"Per-app power is {', '.join(sorted(provs))}: CPU power split by each app's CPU share.")
                with st.expander("Table view"):
                    st.dataframe([{"app": k, "avg W": round(v, 3)} for k, v in reversed(top)], hide_index=True)
            else:
                st.caption("No per-app data in this window.")
        with right, st.container(border=True):
            summ = markov.summarize(pts, idle_w)
            share = summ.get("share", {})
            st.markdown("**Where the time went** · workload states")
            if share:
                sfig = go.Figure()
                for (state, v), color in zip(share.items(), RAMP):
                    sfig.add_bar(x=[v * 100], y=[""], orientation="h", name=state,
                                 marker={"color": color, "line": {"color": "#fcfcfb", "width": 2}},
                                 hovertemplate=f"{state}<br><b>%{{x:.1f}}%</b> of time<extra></extra>")
                sfig = style(sfig, height=110)
                sfig.update_layout(barmode="stack", legend={"y": -0.35, "yanchor": "top", "traceorder": "normal"},
                                   margin=dict(t=4, b=4))
                sfig.update_xaxes(range=[0, 100], ticksuffix="%", showticklabels=False)
                sfig.update_yaxes(showticklabels=False, showgrid=False)
                st.plotly_chart(sfig, width="stretch")
            show(f"""<div class="jr-stats" style="grid-template-columns:1fr">
              <div class="jr-stat"><div class="k">Typical idle stretch</div><div class="v">{summ.get('expected_idle_run_s', 0):.0f}<small> s</small></div></div>
              <div class="jr-stat"><div class="k">Short bursts per hour</div><div class="v">{summ.get('short_bursts_per_hour', 0):.0f}</div></div>
              <div class="jr-stat"><div class="k">Chance of idle within 60 s</div><div class="v">{summ.get('p_idle_within_60s', 0) * 100:.0f}<small>%</small></div></div>
            </div>""")
            with st.expander("Table view"):
                st.dataframe([{"state": k, "time %": round(v * 100, 1),
                               "mean W": round(summ.get("mean_w", {}).get(k, 0), 2)} for k, v in share.items()],
                             hide_index=True, width="stretch")

    st.segmented_control("Window", [5, 10, 30, 120], default=10, key="window_min",
                         format_func=lambda m: f"{m} min")
    live()


# ------------------------------------------------------------------ sync
with tab_sync:
    @st.fragment(run_every="3s")
    def sync_panel():
        c = conn()
        st_ = outbox.stats(c)
        online = SyncWorker(log=lambda *_: None).online()
        show(f"""<div class="flow">
          <div class="step"><div class="k">Cloud</div><div class="v" style="font-size:1.1rem;padding-top:8px">
            <span class="jr-dot {'ok' if online else 'off'}"></span> {'reachable' if online else 'offline: queueing'}</div></div>
          <div class="sep">·</div>
          <div class="step"><div class="k">Waiting (pending)</div><div class="v">{st_['pending']}</div></div>
          <div class="sep">→</div>
          <div class="step"><div class="k">Sending (in flight)</div><div class="v">{st_['in_flight']}</div></div>
          <div class="sep">→</div>
          <div class="step"><div class="k">Delivered</div><div class="v">{st_['done']}</div></div>
          <div class="sep">·</div>
          <div class="step{' dead' if st_['dead'] else ''}"><div class="k">Rejected (dead letter)</div><div class="v">{st_['dead']}</div></div>
        </div>""")
        if online:
            try:
                import urllib.request
                with urllib.request.urlopen(f"{config.Settings().cloud_url}/stats", timeout=2) as resp:
                    cs = json.loads(resp.read())
                show(f'<div class="note">Cloud server: {cs["events"]} events received · {cs["processed"]} processed · '
                     f'<b>{cs["duplicates_ignored"]} duplicates ignored</b> (idempotency keys)</div>')
            except OSError:
                pass
        st.dataframe([{"#": i["id"], "kind": i["kind"], "status": i["status"], "attempts": i["attempts"],
                       "next try in s": max(0, round(i["next_attempt_at"] - time.time(), 1)),
                       "key": i["idem_key"][:8], "error": i["last_error"] or ""} for i in outbox.items(c, limit=15)],
                     hide_index=True, width="stretch")

    l, rr = st.columns([5, 1])
    l.caption("Every decision, explanation, report and receipt is written to the local outbox in the same transaction "
              "as the data, so nothing is lost on a crash or restart. The dashboard syncs automatically every 3 s "
              "whenever the cloud is reachable (log: data/sync.log).")
    if rr.button("Sync now", width="stretch"):
        res = SyncWorker(log=lambda *_: None).tick(conn())
        st.toast(f"Sync: {res}" if res is not None else "Cloud unreachable: items stay queued")
    sync_panel()


# ------------------------------------------------------------------ report
with tab_report:
    c = conn()
    last = c.execute("SELECT body, model, grounded, created FROM reports WHERE kind='report' ORDER BY id DESC "
                     "LIMIT 1").fetchone()
    l, m, rr = st.columns([3, 1.2, 1.2])
    if last:
        l.caption(f"Latest report: {time.strftime('%d %b %Y, %H:%M', time.localtime(last['created']))} · "
                  f"written by {last['model']} · grounding {'passed' if last['grounded'] else 'failed'}")
    if m.button("Write new report", type="primary", width="stretch"):
        from joule.slm.report import build_report
        with st.spinner("The local SLM is writing the report…"):
            out = build_report(c)
        st.toast(f"Saved {Path(out['path']).name} · grounded: {out['grounded']}")
        st.rerun()
    if last:
        rr.download_button("Download .md", last["body"], file_name="energy-report.md", width="stretch")
        with st.container(border=True):
            st.markdown(last["body"])
    else:
        st.info("No report yet. Press **Write new report**.")
