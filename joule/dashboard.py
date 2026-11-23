"""Streamlit dashboard: .venv/bin/streamlit run joule/dashboard.py

Everything reads the local SQLite database, so the dashboard works with no network. Long jobs (collecting,
experiments) run as separate `python -m joule` processes, so the page stays responsive and nothing is lost if
the browser closes.
"""
from __future__ import annotations

import json
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

# Validated reference palette (dataviz skill): slot 1 blue, slot 2 orange; neutral text and grid.
BLUE, ORANGE = "#2a78d6", "#eb6834"
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
PROV_BADGE = {"MEASURED": "🟢 MEASURED", "ATTRIBUTED": "🔵 ATTRIBUTED", "ESTIMATED": "🟡 ESTIMATED",
              "SIMULATED": "⚪ SIMULATED"}

st.set_page_config(page_title="Joule Receipts", page_icon="⚡", layout="wide")


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


def conn():
    return db.connect()


def badge(prov: str) -> str:
    return PROV_BADGE.get(prov, prov)


def style(fig: go.Figure, title: str, y_title: str = "", x_title: str = "", height: int = 320) -> go.Figure:
    fig.update_layout(
        title={"text": title, "font": {"size": 16, "color": INK}}, height=height, margin=dict(l=10, r=10, t=48, b=10),
        plot_bgcolor=SURFACE, paper_bgcolor=SURFACE, font={"color": INK2, "size": 13},
        hoverlabel={"bgcolor": "white", "font": {"color": INK}},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0, "title": None},
    )
    fig.update_xaxes(title=x_title, showgrid=False, linecolor=GRID, zeroline=False)
    fig.update_yaxes(title=y_title, gridcolor=GRID, zeroline=False, rangemode="tozero")
    return fig


def spawn(args: list[str]) -> None:
    """Run a joule command in the background (separate process, survives page reloads)."""
    log = config.data_dir() / "jobs.log"
    with open(log, "a") as fh:
        fh.write(f"\n$ joule {' '.join(args)}  ({time.strftime('%H:%M:%S')})\n")
        subprocess.Popen([sys.executable, "-m", "joule", *args], cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT)


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.title("⚡ Joule Receipts")
    st.caption("Offline-first energy copilot · PS 04")
    s = config.Settings()
    sensor = get_sensor("auto")
    slm_ok = client.is_available(settings=s)
    cloud_ok = SyncWorker(log=lambda *_: None).online()
    st.markdown(f"**Sensor:** {sensor.name} · {badge(str(sensor.provenance))}")
    st.markdown(f"**Local SLM:** {s.llm_model} · {'✅ running' if slm_ok else '⚠️ offline (template fallback)'}")
    st.markdown(f"**Cloud sync:** {'✅ reachable' if cloud_ok else '📴 offline (queueing)'}")
    a = config.Assumptions()
    with st.expander("Assumptions", expanded=False):
        st.markdown(f"- Tariff: **₹{a.tariff_inr_per_kwh}/kWh** — {a.tariff_source}\n"
                    f"- Grid factor: **{a.grid_kg_per_kwh} kg CO₂/kWh** — {a.grid_source}\n"
                    f"- Projection: **{a.usage_hours_per_day} h/day**, 30 days/month")
        for f in energy.FORMULAS.values():
            st.code(f, language=None)
    st.divider()
    st.caption("Collect readings in the background")
    secs = st.select_slider("Duration", options=[60, 120, 300, 600], value=120, format_func=lambda x: f"{x // 60} min")
    if st.button("Start collecting", width="stretch"):
        spawn(["collect", "--seconds", str(secs)])
        st.toast(f"Collecting for {secs // 60} min from {sensor.name}")

tab_live, tab_recs, tab_proof, tab_sync, tab_report = st.tabs(
    ["📈 Live", "💡 Recommendations", "🧾 Receipts", "🔄 Sync", "📄 Report"])


# ------------------------------------------------------------------ live
with tab_live:
    @st.fragment(run_every="5s")
    def live():
        c = conn()
        window = st.session_state.get("window_min", 10)
        rows = db.recent_samples(c, time.time() - window * 60)
        if not rows:
            st.info("No readings in this window yet. Use **Start collecting** in the sidebar, or run "
                    "`python3 -m joule collect --seconds 120`.")
            return
        pts = [(x["ts"], x["watts"]) for x in rows]
        ws = sorted(w for _, w in pts)
        idle_w = ws[int(0.1 * (len(ws) - 1))]
        last = rows[-1]
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Power now", f"{last['watts']:.2f} W", help=f"{last['source']} · {last['provenance']}")
        k2.metric("Average", f"{energy.mean_power(pts):.2f} W")
        k3.metric("Idle floor (10th pct)", f"{idle_w:.2f} W")
        k4.metric(f"Energy, last {window} min", f"{energy.integrate_wh(pts) * 1000:.0f} mWh")
        st.caption(f"Source: {badge(last['provenance'])} via **{last['source']}** · "
                   f"{len(rows)} samples · updated {time.strftime('%H:%M:%S', time.localtime(last['ts']))}")

        fig = go.Figure(go.Scatter(
            x=[time.strftime("%H:%M:%S", time.localtime(t)) for t, _ in pts], y=[w for _, w in pts],
            mode="lines", line={"color": BLUE, "width": 2, "shape": "hv"},
            hovertemplate="%{x}<br><b>%{y:.2f} W</b><extra></extra>"))
        fig.add_hline(y=idle_w, line={"color": INK2, "width": 1, "dash": "dot"},
                      annotation_text=f"idle floor {idle_w:.2f} W", annotation_font_color=INK2)
        st.plotly_chart(style(fig, "Laptop power (W)", "W"), width="stretch")

        left, right = st.columns([3, 2])
        with left:
            ids = [x["id"] for x in rows]
            ph = ",".join("?" * len(ids))
            per_app: dict[str, float] = {}
            prov = set()
            for p in c.execute(f"SELECT name, watts, provenance FROM proc_samples WHERE sample_id IN ({ph})", ids):
                app = app_of(p["name"])
                if app:
                    per_app[app] = per_app.get(app, 0.0) + (p["watts"] or 0.0) / len(ids)
                    prov.add(p["provenance"])
            top = sorted(per_app.items(), key=lambda kv: kv[1])[-8:]
            if top:
                bar = go.Figure(go.Bar(
                    x=[v for _, v in top], y=[k for k, _ in top], orientation="h",
                    marker={"color": BLUE, "cornerradius": 4},
                    hovertemplate="%{y}<br><b>%{x:.3f} W</b> average<extra></extra>"))
                st.plotly_chart(style(bar, f"Average power by app ({', '.join(sorted(prov))})", x_title="W",
                                      height=340), width="stretch")
                with st.expander("Table view"):
                    st.dataframe([{"app": k, "avg W": round(v, 3)} for k, v in reversed(top)], hide_index=True)
        with right:
            summ = markov.summarize(pts, idle_w)
            st.markdown("**Workload states** (Markov chain over 1 s states)")
            share = summ.get("share", {})
            st.dataframe([{"state": k, "time %": round(v * 100, 1),
                           "mean W": round(summ["mean_w"].get(k, 0), 2) if k in summ.get("mean_w", {}) else None}
                          for k, v in share.items()], hide_index=True, width="stretch")
            st.markdown(f"- Typical idle stretch: **{summ.get('expected_idle_run_s', 0):.0f} s**\n"
                        f"- Short bursts per hour: **{summ.get('short_bursts_per_hour', 0):.0f}**\n"
                        f"- Chance of idle within 60 s: **{summ.get('p_idle_within_60s', 0) * 100:.0f}%**")

    st.radio("Window", [5, 10, 30, 120], index=1, horizontal=True, key="window_min",
             format_func=lambda m: f"{m} min")
    live()


# ------------------------------------------------------------------ recommendations
with tab_recs:
    c = conn()
    top_l, top_r = st.columns([3, 1])
    top_l.caption("Facts and predictions are computed; the local SLM only writes the explanation, and a grounding "
                  "check rejects any number it invents.")
    if top_r.button("Refresh from readings", width="stretch"):
        recommend.refresh(c)
        st.rerun()
    recs = db.list_recommendations(c)
    if not recs:
        st.info("No recommendations yet: collect a few minutes of readings, then refresh.")
    for rec in recs:
        f = rec["facts"]
        pred = f.get("prediction") or {}
        with st.container(border=True):
            h1, h2 = st.columns([4, 1])
            h1.subheader(f"{rec['title']}")
            h2.markdown(f"`{rec['status']}`" + ("  \n⚠️ **needs review**" if rec["needs_review"] else ""))
            st.write(f.get("headline", ""))
            if pred:
                m1, m2, m3 = st.columns(3)
                m1.metric("Predicted saving", f"{pred['saved_wh_per_day']} Wh/day")
                m2.metric("Cost", f"₹{pred['saved_inr_per_month']}/month")
                m3.metric("Carbon", f"{pred['saved_co2_g_per_month']} g CO₂e/month")
                st.caption(f"{badge(pred.get('provenance', 'ESTIMATED'))} · {pred.get('method', '')}")
            last = c.execute("SELECT body, model, grounded FROM reports WHERE rec_id=? AND kind='explanation' "
                             "ORDER BY id DESC LIMIT 1", (rec["id"],)).fetchone()
            if last:
                st.info(last["body"].replace("\n", "  \n"))
                st.caption(f"Explained by **{last['model']}** · grounding check "
                           f"{'✅ passed' if last['grounded'] else '❌ failed'}")
            b1, b2, b3, b4 = st.columns(4)
            if b1.button("🧠 Explain (local SLM)", key=f"ex{rec['id']}"):
                with st.spinner(f"{s.llm_model} is writing…"):
                    res = explain.explain(f)
                    db.save_report(c, "explanation", res.text, res.model, res.grounded, res.ungrounded,
                                   rec_id=rec["id"], facts=f, latency_s=res.latency_s, tokens=res.tokens)
                st.rerun()
            for col, decision, label in ((b2, "accept", "✅ Accept"), (b3, "reject", "✖ Reject"),
                                         (b4, "defer", "⏸ Defer")):
                if col.button(label, key=f"{decision}{rec['id']}"):
                    db.record_decision(c, rec["id"], decision, device_id=s.device_id)
                    st.toast(f"{label} saved locally and queued for sync")
                    st.rerun()


# ------------------------------------------------------------------ receipts
with tab_proof:
    c = conn()
    st.markdown("Each receipt compares a **baseline** and an **optimized** run doing identical work: idle power "
                "measured first, runs interleaved B/O/O/B, mean ± standard deviation, saving significant only if "
                "it beats 2× the combined noise.")
    with st.expander("Run a new experiment", expanded=False):
        e1, e2, e3, e4 = st.columns(4)
        scen = e1.selectbox("Scenario", ["batching", "idle", "inference"])
        src = e2.selectbox("Sensor", ["auto", "powermetrics", "battery", "estimate", "simulated"])
        reps = e3.number_input("Repeats", 2, 10, 5)
        quick = e4.checkbox("Quick (small sizes)", value=False)
        st.caption("powermetrics needs sudo: run `sudo python3 -m joule experiment batching --source powermetrics` "
                   "in a terminal instead. The battery gauge refreshes every ~12–33 s, so it uses ≥ 90 s windows.")
        if st.button("Start experiment in background"):
            spawn(["experiment", scen, "--source", src, "--repeats", str(reps)] + (["--quick"] if quick else []))
            st.toast("Experiment started; its receipt appears here when it finishes (see data/jobs.log)")
    rows = c.execute("SELECT * FROM receipts ORDER BY id DESC").fetchall()
    if not rows:
        st.info("No receipts yet.")
    else:
        bodies = [(row, json.loads(row["body_json"])) for row in rows]
        latest = {}
        for row, b in bodies:
            latest.setdefault(b["scenario"], (row, b))
        names = list(latest)
        fig = go.Figure()
        for variant, color, key in (("baseline", ORANGE, "baseline_wh"), ("optimized", BLUE, "optimized_wh")):
            fig.add_bar(name=variant, x=names, y=[latest[n][1][key] * 1000 for n in names],
                        error_y={"type": "data", "array": [latest[n][1][key + "_std"] * 1000 for n in names],
                                 "color": INK2, "thickness": 1.5},
                        marker={"color": color, "cornerradius": 4},
                        hovertemplate=f"%{{x}} · {variant}<br><b>%{{y:.3f}} mWh</b> per run<extra></extra>")
        fig.update_layout(barmode="group", bargap=0.35, bargroupgap=0.08)
        st.plotly_chart(style(fig, "Energy per run, latest receipt per scenario (mWh, mean ± std)", "mWh"),
                        width="stretch")
        for row, b in bodies:
            with st.container(border=True):
                st.markdown(f"#### 🧾 Receipt {row['id']} · {b['title']}  ·  {badge(b['provenance'])} via {b['sensor']}")
                q1, q2, q3, q4 = st.columns(4)
                q1.metric("Baseline", f"{r(b['baseline_wh'] * 1000)} mWh", f"± {r(b['baseline_wh_std'] * 1000)}",
                          delta_color="off")
                q2.metric("Optimized", f"{r(b['optimized_wh'] * 1000)} mWh", f"± {r(b['optimized_wh_std'] * 1000)}",
                          delta_color="off")
                q3.metric("Saved per run", f"{r(b['measured_saved_wh'] * 1000)} mWh", f"{b['saved_pct']}%")
                pred = b.get("predicted_saved_wh")
                q4.metric("Predicted (pilot)", "—" if pred is None else f"{r(pred * 1000)} mWh",
                          None if b.get("prediction_error_pct") is None else f"error {b['prediction_error_pct']}%",
                          delta_color="off")
                st.markdown(f"**Baseline:** {b['baseline']}  \n**Optimized:** {b['optimized']}  \n"
                            f"**Same work:** {'✅ yes (checksum)' if b['equivalent_work'] else '❌ no'} · "
                            f"**Significant:** {'✅ yes' if b['significant'] else '❌ no'} "
                            f"(noise ±{r(b['noise_wh'] * 1000)} mWh) · **Trade-off:** {b['tradeoff']}  \n"
                            f"**Per run:** ₹{b['saved_inr']:.7f} · {b['saved_co2_g']:.5f} g CO₂e "
                            f"(₹{b['assumptions']['tariff_inr_per_kwh']}/kWh, "
                            f"{b['assumptions']['grid_kg_co2_per_kwh']} kg/kWh)")


# ------------------------------------------------------------------ sync
with tab_sync:
    @st.fragment(run_every="3s")
    def sync_panel():
        c = conn()
        st_ = outbox.stats(c)
        online = SyncWorker(log=lambda *_: None).online()
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Cloud", "reachable" if online else "offline")
        m2.metric("Pending", st_["pending"])
        m3.metric("In flight", st_["in_flight"])
        m4.metric("Delivered", st_["done"])
        m5.metric("Dead (rejected)", st_["dead"])
        st.dataframe([{"#": i["id"], "kind": i["kind"], "status": i["status"], "attempts": i["attempts"],
                       "next try in s": max(0, round(i["next_attempt_at"] - time.time(), 1)),
                       "key": i["idem_key"][:8], "error": i["last_error"] or ""} for i in outbox.items(c, limit=15)],
                     hide_index=True, width="stretch")
        if online:
            try:
                import urllib.request
                with urllib.request.urlopen(f"{config.Settings().cloud_url}/stats", timeout=2) as resp:
                    cs = json.loads(resp.read())
                st.caption(f"Server: {cs['events']} events · {cs['processed']} processed · "
                           f"**{cs['duplicates_ignored']} duplicates ignored** · {cs['by_kind']}")
            except OSError:
                pass

    st.caption("Decisions, explanations, reports and receipts are written to the local outbox in the same "
               "transaction as the data. The dashboard syncs automatically every 3 s whenever the cloud is reachable (log: data/sync.log).")
    if st.button("Sync now"):
        res = SyncWorker(log=lambda *_: None).tick(conn())
        st.toast(f"Sync: {res}" if res is not None else "Cloud unreachable: items stay queued")
    sync_panel()


# ------------------------------------------------------------------ report
with tab_report:
    c = conn()
    if st.button("Write a new report (local SLM summary)"):
        from joule.slm.report import build_report
        with st.spinner("Writing report…"):
            out = build_report(c)
        st.toast(f"Saved {Path(out['path']).name} · grounded: {out['grounded']}")
    last = c.execute("SELECT body, model, grounded, created FROM reports WHERE kind='report' ORDER BY id DESC "
                     "LIMIT 1").fetchone()
    if last:
        st.caption(f"Latest report: {time.strftime('%Y-%m-%d %H:%M', time.localtime(last['created']))}")
        st.markdown(last["body"])
        st.download_button("Download Markdown", last["body"], file_name="energy-report.md")
    else:
        st.info("No report yet.")
