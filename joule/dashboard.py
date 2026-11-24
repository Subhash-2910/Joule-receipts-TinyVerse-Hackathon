"""Streamlit dashboard: .venv/bin/streamlit run joule/dashboard.py

Everything reads the local SQLite database, so the dashboard works with no network (system fonts only, no CDN).
Long jobs (collecting, experiments) run as separate `python -m joule` processes, so the page stays responsive and
nothing is lost if the browser closes.
"""
from __future__ import annotations

import html
import json
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from joule import config, db, energy, policy  # noqa: E402
from joule.analytics import anomaly, label, markov, recommend, whatif  # noqa: E402
from joule.analytics.knowledge import app_of  # noqa: E402
from joule.analytics.recommend import r  # noqa: E402
from joule.sensors import get_sensor  # noqa: E402
from joule.slm import client  # noqa: E402
from joule.sync import outbox  # noqa: E402
from joule.sync.worker import SyncWorker  # noqa: E402

# Validated reference palette (dataviz skill), DARK steps: slot 1 blue, slot 2 orange; neutral ink; ordinal ramp.
BLUE, ORANGE = "#3987e5", "#d95926"
INK, INK2, MUTED, GRID, SURF = "#f0efec", "#c3c2b7", "#8a8984", "#2c2c2a", "#1a1a19"
RAMP = ["#184f95", "#2a78d6", "#5598e7", "#9ec5f4"]          # idle -> heavy, dark mode: brighter = more load
SCENARIOS = {"idle": "Idle background polling", "batching": "Batching small jobs",
             "cascade": "Self-measuring AI", "inference": "Model inference"}
HERO = ("idle", "batching", "cascade")                         # the three proofs on the Overview
PAGES = ["Overview", "Receipts", "Certify", "Advice", "What-if", "Live", "Sync", "Report"]

st.set_page_config(page_title="Joule Receipts", page_icon="⚡", layout="wide", initial_sidebar_state="collapsed")

CSS = """
<style>
:root {
  --ink:#f0efec; --ink2:#c3c2b7; --muted:#8a8984; --line:#2c2c2a; --card:#161615; --card2:#1d1d1b;
  --blue:#3987e5; --blue-hi:#86b6ef; --orange:#d95926; --good:#0ca30c; --warn:#fab219;
  --mono: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace;
}
.stApp { background:
  radial-gradient(900px 420px at 8% -8%, rgba(57,135,229,0.22), transparent 70%),
  radial-gradient(700px 380px at 100% 0%, rgba(217,89,38,0.10), transparent 70%), #0e0e0d; }
.block-container { padding-top: 1.4rem; max-width: 1320px; }
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] { display:none; }
h1, h2, h3, h4 { letter-spacing:-0.01em; }
[data-testid="stMarkdownContainer"] h1 { font-size:1.6rem; }
[data-testid="stMarkdownContainer"] h2 { font-size:1.2rem; margin-top:0.6rem; }
[data-testid="stMarkdownContainer"] h3 { font-size:1.05rem; }

/* cards: every st.container(key="card-...") */
[class*="st-key-card"] { background:linear-gradient(180deg, var(--card2), var(--card)); border:1px solid var(--line);
  border-radius:18px; padding:18px 20px 16px; transition:border-color .2s, transform .2s, box-shadow .2s; }
[class*="st-key-card"]:hover { border-color:#3a3a37; box-shadow:0 10px 40px rgba(0,0,0,0.35); }
[class*="st-key-cardglow"] { border-color:rgba(57,135,229,0.45);
  box-shadow:0 0 0 1px rgba(57,135,229,0.15), 0 20px 60px rgba(57,135,229,0.12); }

/* top bar */
.brand { display:flex; align-items:center; gap:12px; }
.logo { width:42px; height:42px; border-radius:12px; display:grid; place-items:center; font-size:22px;
  background:linear-gradient(135deg,#3987e5,#184f95); box-shadow:0 6px 24px rgba(57,135,229,0.45); }
.brand .name { font-size:1.35rem; font-weight:800; color:var(--ink); line-height:1; letter-spacing:-0.02em; }
.brand .tag { color:var(--muted); font-size:0.8rem; margin-top:4px; }
.pills { display:flex; gap:8px; justify-content:flex-end; flex-wrap:wrap; padding-top:6px; }
.pill { display:inline-flex; align-items:center; gap:7px; padding:6px 12px; border-radius:999px;
  background:rgba(255,255,255,0.03); border:1px solid var(--line); font-size:0.78rem; color:var(--muted); }
.pill b { color:var(--ink); font-weight:600; }
.dot { width:8px; height:8px; border-radius:50%; display:inline-block; flex:none; }
.dot.ok { background:var(--good); box-shadow:0 0 0 0 rgba(12,163,12,0.6); animation:pulse 2.4s infinite; }
.dot.warn { background:var(--warn); } .dot.off { background:#5b5a56; }
@keyframes pulse { 0% { box-shadow:0 0 0 0 rgba(12,163,12,0.55); } 70% { box-shadow:0 0 0 8px rgba(12,163,12,0); }
  100% { box-shadow:0 0 0 0 rgba(12,163,12,0); } }

/* navigation dock + goal switch (segmented controls restyled as one rounded dock with spaced pills) */
.st-key-nav [role="radiogroup"], .st-key-goal [role="radiogroup"], .st-key-rscn [role="radiogroup"], .st-key-window_min [role="radiogroup"] {
  display:flex; flex-wrap:nowrap; gap:4px; padding:4px; width:fit-content; border-radius:999px;
  background:rgba(255,255,255,0.035); border:1px solid var(--line); box-shadow:inset 0 1px 0 rgba(255,255,255,0.04); }
.st-key-nav [role="radiogroup"] button, .st-key-goal [role="radiogroup"] button, .st-key-rscn [role="radiogroup"] button, .st-key-window_min [role="radiogroup"] button {
  border:none !important; border-radius:999px !important; background:transparent !important; margin:0 !important;
  padding:6px 15px !important; min-height:0 !important; color:var(--ink2) !important; font-weight:600;
  transition:background .2s ease, color .2s ease, box-shadow .2s ease; }
.st-key-nav [role="radiogroup"] button p, .st-key-goal [role="radiogroup"] button p, .st-key-rscn [role="radiogroup"] button p, .st-key-window_min [role="radiogroup"] button p { font-size:0.86rem; white-space:nowrap; }
.st-key-nav [role="radiogroup"] button:hover, .st-key-goal [role="radiogroup"] button:hover, .st-key-rscn [role="radiogroup"] button:hover, .st-key-window_min [role="radiogroup"] button:hover {
  background:rgba(255,255,255,0.06) !important; color:var(--ink) !important; }
.st-key-nav [role="radiogroup"] button[aria-checked="true"], .st-key-rscn [role="radiogroup"] button[aria-checked="true"], .st-key-window_min [role="radiogroup"] button[aria-checked="true"] {
  background:linear-gradient(180deg, rgba(57,135,229,0.34), rgba(57,135,229,0.18)) !important; color:#fff !important;
  box-shadow:inset 0 0 0 1px rgba(57,135,229,0.6), 0 4px 16px rgba(57,135,229,0.22); }
.st-key-goal [role="radiogroup"] button[aria-checked="true"] {
  background:linear-gradient(180deg, rgba(12,163,12,0.30), rgba(12,163,12,0.14)) !important; color:#fff !important;
  box-shadow:inset 0 0 0 1px rgba(12,163,12,0.55), 0 4px 16px rgba(12,163,12,0.18); }
.st-key-nav [role="radiogroup"] button:focus-visible, .st-key-goal [role="radiogroup"] button:focus-visible,
.stButton button:focus-visible, .stDownloadButton button:focus-visible {
  outline:2px solid var(--blue-hi) !important; outline-offset:2px; }
.st-key-nav, .st-key-goal { margin-top:14px; }
[data-testid="stPopover"] { margin-top:14px; }
[data-testid="stPopover"] > div > button, [data-testid="stPopover"] button[data-testid="stPopoverButton"] {
  border-radius:999px !important; background:rgba(255,255,255,0.035) !important; border:1px solid var(--line) !important;
  min-height:0 !important; padding:9px 16px !important; transition:background .2s, border-color .2s; }
[data-testid="stPopover"] button:hover { background:rgba(255,255,255,0.07) !important; border-color:#3a3a37 !important; }
/* browser surfaces carry the palette too */
::selection { background:rgba(57,135,229,0.38); color:#fff; }
input, textarea, [contenteditable] { caret-color:var(--blue-hi); }
* { scrollbar-width:thin; scrollbar-color:#34342f transparent; }
::-webkit-scrollbar { width:10px; height:10px; } ::-webkit-scrollbar-track { background:transparent; }
::-webkit-scrollbar-thumb { background:#2c2c28; border-radius:10px; border:2px solid #0e0e0d; }
::-webkit-scrollbar-thumb:hover { background:#3d3d38; }
a { text-underline-offset:3px; }
.stat .v, .step .v, .node .v, .wi-big, .alert-x, .hashline { font-variant-numeric:tabular-nums; }
.ico { display:inline-block; vertical-align:-3px; flex:none; }
.step .ic { color:var(--ink2); } .step.done .ic { color:#7fdc7f; }
.node .k .ico { vertical-align:-2px; margin-right:3px; color:var(--ink2); }
.node.dead .k .ico { color:#f08a8a; }
.alert-ic { color:#fbc552; }
.ai .who .ico { vertical-align:-2px; }
.goal-label { font-size:0.66rem; font-weight:700; letter-spacing:0.14em; text-transform:uppercase; color:var(--muted);
  text-align:right; margin:0 6px 4px 0; }

/* typography helpers */
.eyebrow { font-size:0.7rem; font-weight:700; text-transform:uppercase; letter-spacing:0.14em; color:var(--muted); }
.h-hero { font-size:2.1rem; font-weight:800; line-height:1.1; letter-spacing:-0.03em; color:var(--ink); margin:8px 0 4px; }
.h-hero em { font-style:normal; color:var(--blue-hi); }
.lead { color:var(--ink2); font-size:0.95rem; line-height:1.5; max-width:62ch; }
.note { color:var(--muted); font-size:0.82rem; line-height:1.5; }
.mono { font-family:var(--mono); }
code.cmd { font-family:var(--mono); font-size:0.75rem; color:var(--ink2); background:#0b0b0a; border:1px solid var(--line);
  padding:6px 8px; border-radius:8px; display:block; white-space:pre-wrap; }

/* count-up numbers */
@property --num { syntax:'<integer>'; initial-value:0; inherits:false; }
.count { counter-reset:num var(--num); animation:1.6s cubic-bezier(.16,1,.3,1) 0.15s both; }
.count::after { content:counter(num); }

/* saving tiles */
.wins { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-top:16px; }
.win { background:rgba(255,255,255,0.025); border:1px solid var(--line); border-radius:14px; padding:14px 16px; }
.win .t { color:var(--ink2); font-size:0.82rem; font-weight:600; }
.win .big { font-size:3rem; font-weight:800; letter-spacing:-0.04em; line-height:1.05; color:var(--ink);
  font-variant-numeric:tabular-nums; margin:6px 0 4px; }
.win .big small { font-size:1rem; color:var(--muted); font-weight:600; letter-spacing:0; }
.win .sub { color:var(--ink2); font-size:0.8rem; font-variant-numeric:tabular-nums; }
.win .foot { margin-top:10px; color:var(--muted); font-size:0.74rem; }
.win.empty { border-style:dashed; background:transparent; }
.win.empty .big { color:#5b5a56; font-size:1.5rem; padding:10px 0 4px; }
.bar2 { height:6px; border-radius:6px; background:#2a2a28; margin:10px 0 2px; overflow:hidden; display:flex; }
.bar2 i { display:block; height:100%; background:var(--blue); border-radius:6px; animation:grow 1.4s cubic-bezier(.16,1,.3,1) both; }
@keyframes grow { from { width:0; } }
.dot-b, .dot-o { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:5px; }
.dot-b { background:var(--blue); } .dot-o { background:var(--orange); }

/* pipeline stepper */
.steps { display:flex; flex-direction:column; gap:4px; margin-top:12px; }
.step { display:grid; grid-template-columns:34px 1fr auto; align-items:center; gap:12px; padding:9px 10px;
  border-radius:12px; position:relative; }
.step:hover { background:rgba(255,255,255,0.03); }
.step .ic { width:34px; height:34px; border-radius:10px; display:grid; place-items:center; font-size:15px;
  background:#22221f; border:1px solid var(--line); }
.step.done .ic { background:rgba(12,163,12,0.14); border-color:rgba(12,163,12,0.4); }
.step .k { color:var(--ink); font-weight:700; font-size:0.92rem; }
.step .d { color:var(--muted); font-size:0.78rem; }
.step .v { font-family:var(--mono); color:var(--ink); font-size:0.95rem; font-weight:700; text-align:right; }
.step .v small { display:block; color:var(--muted); font-weight:500; font-size:0.68rem; }
.step:not(:last-child)::after { content:""; position:absolute; left:26px; top:43px; height:12px; width:2px; background:var(--line); }

/* stat chips */
.stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:10px; margin:6px 0 8px; }
.stat { background:rgba(255,255,255,0.025); border:1px solid var(--line); border-radius:12px; padding:10px 14px; }
.stat .k { color:var(--muted); font-size:0.72rem; font-weight:600; }
.stat .v { color:var(--ink); font-size:1.35rem; font-weight:800; font-variant-numeric:tabular-nums; letter-spacing:-0.02em; }
.stat .v small { font-size:0.78rem; font-weight:500; color:var(--muted); }
.power-now { font-size:3.4rem; font-weight:800; letter-spacing:-0.04em; font-variant-numeric:tabular-nums; line-height:1; }
.power-now small { font-size:1.1rem; color:var(--muted); font-weight:600; }

/* provenance + status badges: word + colour, never colour alone */
.prov { display:inline-block; padding:2px 8px; border-radius:6px; font:700 0.68rem/1.6 var(--mono); letter-spacing:0.05em;
  border:1px solid; vertical-align:middle; }
.prov-MEASURED  { color:#7fdc7f; background:rgba(12,163,12,0.12); border-color:rgba(12,163,12,0.4); }
.prov-ATTRIBUTED{ color:#9ec5f4; background:rgba(57,135,229,0.12); border-color:rgba(57,135,229,0.4); }
.prov-ESTIMATED { color:#fbc552; background:rgba(250,178,25,0.10); border-color:rgba(250,178,25,0.35); }
.prov-SIMULATED { color:#c3c2b7; background:rgba(255,255,255,0.05); border-color:#3a3a37; }
.status { display:inline-block; padding:3px 10px; border-radius:999px; font-size:0.72rem; font-weight:700;
  border:1px solid var(--line); color:var(--ink2); text-transform:capitalize; }
.status.accepted { color:#7fdc7f; background:rgba(12,163,12,0.12); border-color:rgba(12,163,12,0.4); }
.status.rejected { color:#f08a8a; background:rgba(208,59,59,0.12); border-color:rgba(208,59,59,0.4); }
.status.deferred, .status.review { color:#fbc552; background:rgba(250,178,25,0.10); border-color:rgba(250,178,25,0.35); }

/* recommendation */
.rec-title { font-size:1.15rem; font-weight:800; color:var(--ink); margin:0; letter-spacing:-0.01em; }
.rec-head { color:var(--ink2); margin:6px 0 12px; font-size:0.92rem; line-height:1.5; }
.ai { position:relative; border:1px solid rgba(57,135,229,0.35); background:rgba(57,135,229,0.07);
  border-radius:14px; padding:14px 16px 12px; color:var(--ink); font-size:0.92rem; line-height:1.6; margin:8px 0 4px; }
.ai .who { display:flex; align-items:center; gap:8px; color:var(--blue-hi); font-size:0.74rem; font-weight:700;
  letter-spacing:0.06em; text-transform:uppercase; margin-bottom:6px; }
.ai .who .chk { color:#7fdc7f; text-transform:none; letter-spacing:0; font-weight:600; margin-left:auto; }

/* receipt paper (light paper on a dark desk), prints in */
.receipt { background:#fbfaf5; color:#111; border-radius:6px 6px 0 0; padding:20px 22px 24px; font-family:var(--mono);
  font-size:0.8rem; position:relative; box-shadow:0 30px 60px rgba(0,0,0,0.45); margin:4px 4px 18px;
  animation:print 1.1s cubic-bezier(.16,1,.3,1) both; transform-origin:top; }
@keyframes print { from { clip-path:inset(0 0 100% 0); transform:translateY(-14px); } to { clip-path:inset(0 0 -20px 0); } }
.receipt::after { content:""; position:absolute; left:0; right:0; bottom:-10px; height:10px;
  background:linear-gradient(-45deg, transparent 6px, #fbfaf5 0) 0 0/12px 10px repeat-x,
             linear-gradient(45deg, transparent 6px, #fbfaf5 0) 0 0/12px 10px repeat-x; }
.receipt .hd { text-align:center; font-weight:700; letter-spacing:0.16em; font-size:0.72rem; color:#555; }
.receipt .ttl { text-align:center; font-weight:800; font-size:1rem; margin:4px 0 2px; }
.receipt .meta { text-align:center; color:#777; font-size:0.72rem; }
.receipt hr { border:none; border-top:1px dashed #c9c8c1; margin:10px 0; }
.receipt .row { display:flex; justify-content:space-between; gap:12px; padding:1px 0; }
.receipt .row span:first-child { color:#555; white-space:nowrap; }
.receipt .row span:last-child { text-align:right; font-variant-numeric:tabular-nums; }
.receipt .total { font-size:1.05rem; font-weight:800; } .receipt .total span:first-child { color:#111; }
.receipt .desc { color:#444; font-size:0.74rem; line-height:1.5; }
.receipt .stamp { position:absolute; left:16px; top:14px; transform:rotate(-12deg); border:2px solid #1d7a1d;
  color:#1d7a1d; font-weight:900; letter-spacing:0.12em; padding:2px 8px; border-radius:4px; font-size:0.72rem;
  opacity:0.85; animation:stamp .5s 1s cubic-bezier(.2,2,.4,1) both; }
.receipt .stamp.no { border-color:#9a6a00; color:#9a6a00; }
@keyframes stamp { from { transform:rotate(-12deg) scale(2.2); opacity:0; } }
.receipt .prov-MEASURED { color:#0b5d0b; background:#e5f3e5; border-color:#b9dcb9; }
.receipt .prov-SIMULATED { color:#555; background:#eee; border-color:#ddd; }
.receipt .prov-ESTIMATED { color:#7a5200; background:#fdf3dc; border-color:#f3d79a; }

/* sync flow */
.flow { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin:4px 0 6px; }
.node { flex:1; min-width:110px; background:rgba(255,255,255,0.025); border:1px solid var(--line); border-radius:14px; padding:12px 14px; }
.node .k { color:var(--muted); font-size:0.72rem; font-weight:600; }
.node .v { font-size:1.8rem; font-weight:800; font-variant-numeric:tabular-nums; }
.node.dead .v { color:#f08a8a; }
.wire { flex:0 0 36px; height:2px; background:repeating-linear-gradient(90deg,var(--blue) 0 6px,transparent 6px 12px);
  background-size:24px 2px; animation:flow 0.8s linear infinite; }
.wire.idle { background:repeating-linear-gradient(90deg,#3a3a37 0 6px,transparent 6px 12px); animation:none; }
@keyframes flow { to { background-position:24px 0; } }
.cloud-big { display:flex; align-items:center; gap:12px; font-size:1.4rem; font-weight:800; }
.log { font-family:var(--mono); font-size:0.74rem; color:var(--ink2); background:#0b0b0a; border:1px solid var(--line);
  border-radius:12px; padding:10px 12px; line-height:1.7; max-height:230px; overflow:auto; }
.log .t { color:var(--muted); } .log .ok { color:#7fdc7f; } .log .off { color:#fbc552; }



/* anomaly alert banner (icon + words, never colour alone) */
[class*="st-key-cardalert"] { border-color:rgba(250,178,25,0.5); background:linear-gradient(180deg, rgba(250,178,25,0.10), rgba(250,178,25,0.03)); }
.alert-row { display:flex; gap:14px; align-items:center; }
.alert-ic { width:40px; height:40px; border-radius:12px; display:grid; place-items:center; font-size:20px; flex:none;
  background:rgba(250,178,25,0.16); border:1px solid rgba(250,178,25,0.45); animation:pulsew 2.4s infinite; }
@keyframes pulsew { 0% { box-shadow:0 0 0 0 rgba(250,178,25,0.45); } 70% { box-shadow:0 0 0 10px rgba(250,178,25,0); } 100% { box-shadow:0 0 0 0 rgba(250,178,25,0); } }
.alert-t { color:var(--ink); font-weight:800; font-size:1rem; }
.alert-d { color:var(--ink2); font-size:0.85rem; }
.alert-x { font-family:var(--mono); font-weight:800; font-size:1.6rem; color:#fbc552; margin-left:auto; white-space:nowrap; }

/* AI energy chip on every explanation */
.ai .meter { display:flex; flex-wrap:wrap; gap:6px; margin-top:10px; }
.chip { display:inline-flex; align-items:center; gap:6px; padding:3px 10px; border-radius:999px; font:600 0.72rem/1.6 var(--mono);
  border:1px solid var(--line); color:var(--ink2); background:rgba(0,0,0,0.25); }
.chip.j { color:#fbc552; border-color:rgba(250,178,25,0.35); }
.chip.ok { color:#7fdc7f; border-color:rgba(12,163,12,0.4); } .chip.no { color:#f08a8a; border-color:rgba(208,59,59,0.4); }

/* energy label (A-G) */
.elabel { display:flex; gap:18px; align-items:center; }
.ebars { flex:1; display:flex; flex-direction:column; gap:3px; }
.ebar { height:20px; border-radius:0 5px 5px 0; color:#fff; font:800 0.74rem/20px var(--mono); padding-left:8px; opacity:0.42;
  display:flex; justify-content:space-between; padding-right:8px; }
.ebar.on { opacity:1; height:26px; line-height:26px; font-size:0.9rem; box-shadow:0 0 0 2px var(--ink); animation:grow 1s cubic-bezier(.16,1,.3,1) both; }
.egrade { font-size:4.6rem; font-weight:900; line-height:0.9; letter-spacing:-0.04em; }
.cert { display:inline-block; margin-top:8px; padding:3px 10px; border-radius:6px; font:800 0.72rem/1.6 var(--mono); letter-spacing:0.1em; border:2px solid; }
.cert.yes { color:#7fdc7f; border-color:rgba(12,163,12,0.6); } .cert.no { color:#fbc552; border-color:rgba(250,178,25,0.5); }
.hashline { font-family:var(--mono); font-size:0.74rem; color:var(--ink2); background:#0b0b0a; border:1px solid var(--line);
  border-radius:10px; padding:8px 10px; margin:10px 0; line-height:1.7; word-break:break-all; }
.hashline .ok { color:#7fdc7f; } .hashline .bad { color:#f08a8a; }
.receipt .hash { font-size:0.66rem; color:#666; word-break:break-all; text-align:center; }

/* what-if */
.wi-big { font-size:2.6rem; font-weight:800; letter-spacing:-0.04em; line-height:1.05; font-variant-numeric:tabular-nums; color:var(--ink); }
.wi-big small { font-size:0.95rem; color:var(--muted); font-weight:600; letter-spacing:0; }
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


ICONS = {   # one drawn family (Lucide geometry), 1.75 stroke, currentColor
    "measure": '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    "recommend": '<circle cx="11" cy="11" r="7.5"/><path d="m20.5 20.5-4.2-4.2"/>',
    "explain": '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/>'
               '<path d="M15 2v2M15 20v2M2 15h2M2 9h2M20 15h2M20 9h2M9 2v2M9 20v2"/>',
    "prove": '<path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z"/>'
             '<path d="M8 8h8M8 12h8M8 16h5"/>',
    "sync": '<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>',
    "waiting": '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    "sending": '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
    "delivered": '<circle cx="12" cy="12" r="10"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
    "rejected": '<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
    "alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4M12 17h.01"/>',
}


def ico(name: str, size: int = 18) -> str:
    return (f'<svg class="ico" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>')


def esc(x) -> str:
    return html.escape(str(x))


def show(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def show_flat(markup: str) -> None:
    """For HTML built from optional parts: no blank or indented lines, so Markdown never turns it into a code block."""
    import re
    st.markdown(re.sub(r"\n\s*", " ", markup), unsafe_allow_html=True)


def prov(p: str) -> str:
    p = str(p or "ESTIMATED")
    return f'<span class="prov prov-{esc(p)}">{esc(p)}</span>'


def fmt_p(p) -> str:
    if p is None:
        return "n/a"
    return "p < 0.001" if p < 0.001 else f"p = {p:.2g}"


def mwh(wh: float) -> str:
    return f"{r(wh * 1000)}"


def count(n: float) -> str:
    """An integer that counts up from 0 when it first appears (CSS @property; shows the final value if unsupported)."""
    n = int(round(n))
    return (f'<style>@keyframes c{n} {{ from {{ --num:0 }} to {{ --num:{n} }} }}</style>'
            f'<span class="count" style="--num:{n};animation-name:c{n}"></span>')


def goto(page: str):
    st.session_state.nav = page


def style(fig: go.Figure, title: str = "", y_title: str = "", x_title: str = "", height: int = 300) -> go.Figure:
    fig.update_layout(
        title={"text": title, "font": {"size": 14, "color": INK}, "x": 0, "xanchor": "left"} if title else None,
        height=height, margin=dict(l=4, r=8, t=44 if title else 8, b=4),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font={"color": INK2, "size": 12, "family": "-apple-system, system-ui, sans-serif"},
        hoverlabel={"bgcolor": SURF, "bordercolor": GRID, "font": {"color": INK, "size": 12}},
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


def strong(b) -> bool:
    return b["provenance"] == "MEASURED" and b["significant"]


def best_per_scenario(bodies) -> dict:
    """The strongest evidence per scenario: newest MEASURED + significant, else newest of any kind."""
    best = {}
    for row, b in bodies:                                   # newest first
        cur = best.get(b["scenario"])
        if cur is None or (strong(b) and not strong(cur[1])):
            best[b["scenario"]] = (row, b)
    return best


def run_values(c, experiment_id, basis_text: str) -> dict[str, list[float]]:
    col = "net_wh" if "above idle" in (basis_text or "") else "energy_wh"
    out = {"baseline": [], "optimized": []}
    for x in c.execute(f"SELECT variant, {col} AS v FROM experiment_runs WHERE experiment_id=? ORDER BY started",
                       (experiment_id,)):
        out.setdefault(x["variant"], []).append(x["v"])
    return out


def window_rows(c, minutes: int):
    """Readings from the last `minutes`; if nothing is being collected, the most recent recorded session."""
    rows = db.recent_samples(c, time.time() - minutes * 60)
    if rows:
        return rows, ""
    end = c.execute("SELECT MAX(ts) FROM samples").fetchone()[0]
    if end is None:
        return [], ""
    rows = c.execute("SELECT * FROM samples WHERE ts BETWEEN ? AND ? ORDER BY ts", (end - minutes * 60, end)).fetchall()
    return rows, time.strftime("%d %b, %H:%M", time.localtime(end))


def power_line(pts, idle_w=None, height=260, fill=True) -> go.Figure:
    fig = go.Figure(go.Scatter(
        x=[datetime.fromtimestamp(t) for t, _ in pts], y=[w for _, w in pts], mode="lines",
        line={"color": BLUE, "width": 2, "shape": "hv"}, fill="tozeroy" if fill else None,
        fillcolor="rgba(57,135,229,0.12)", hovertemplate="%{x|%H:%M:%S}<br><b>%{y:.2f} W</b><extra></extra>"))
    if idle_w is not None:
        fig.add_hline(y=idle_w, line={"color": MUTED, "width": 1, "dash": "dot"}, annotation_position="bottom left",
                      annotation_text=f"idle floor {idle_w:.2f} W", annotation_font_color=MUTED)
    fig = style(fig, y_title="W", height=height)
    fig.update_xaxes(tickformat="%H:%M:%S", nticks=7)
    fig.update_layout(hovermode="x")
    return fig


# ------------------------------------------------------------------ state shared by all pages
s = config.Settings()
a = config.Assumptions()
sensor = get_sensor("auto")
slm_ok = client.is_available(settings=s)
cloud_ok = SyncWorker(log=lambda *_: None).online()
C = conn()
qstats = outbox.stats(C)
BODIES = receipts(C)
BEST = best_per_scenario(BODIES)
POL = policy.policy(C)
GOAL_LABELS = {k: v["label"] for k, v in policy.GOALS.items()}


def live_alerts(c) -> list[dict]:
    """Anomalies on the latest readings, at the sensitivity the Goal sets."""
    rows = c.execute("SELECT * FROM samples ORDER BY ts").fetchall()
    procs: dict[int, list] = {}
    for p in c.execute("SELECT * FROM proc_samples"):
        procs.setdefault(p["sample_id"], []).append(p)
    return anomaly.detect(rows, procs, ratio=POL["anomaly_ratio"])


def ai_meter(rep) -> str:
    """Chips under an explanation: its own energy, the models tried, and the fact check."""
    if rep is None:
        return ""
    keys = rep.keys()
    steps = json.loads(rep["cascade_json"]) if "cascade_json" in keys and rep["cascade_json"] else []
    chips = []
    if "energy_j" in keys and rep["energy_j"] is not None:
        chips.append(f'<span class="chip j">⚡ {rep["energy_j"]:.1f} J</span>{prov(rep["energy_prov"])}')
    ran = [st_ for st_ in steps if "skipped" not in st_]
    if ran:
        path = " → ".join(f'{esc(st_["model"].split(":")[-1].upper())} {"✓" if st_.get("grounded") else "✗"}' for st_ in ran)
        chips.append(f'<span class="chip {"ok" if ran[-1].get("grounded") else "no"}">{path}</span>')
        if len(ran) > 1:
            chips.append('<span class="chip">escalated: small model failed the fact check</span>')
    return f'<div class="meter">{"".join(chips)}</div>' if chips else ""

# ------------------------------------------------------------------ top bar
tl, tr = st.columns([5, 6], vertical_alignment="center")
with tl:
    show("""<div class="brand"><div class="logo">⚡</div><div><div class="name">Joule Receipts</div>
         <div class="tag">Offline-first energy copilot · PS 04</div></div></div>""")
with tr:
    pill = lambda cls, k, v: f'<span class="pill"><span class="dot {cls}"></span>{k} <b>{v}</b></span>'  # noqa: E731
    cloud_txt = ("synced" if not qstats["pending"] else f"{qstats['pending']} queued") if cloud_ok else \
        (f"offline · {qstats['pending']} queued" if qstats["pending"] else "offline")
    show(f"""<div class="pills">
      {pill("ok" if sensor.provenance == "MEASURED" else "warn", "Sensor", esc(sensor.name))}
      {pill("ok" if slm_ok else "warn", "Local AI", " → ".join(m.split(":")[-1].upper() for m in POL["models"]) if slm_ok else "fallback")}
      {pill("ok" if cloud_ok else "off", "Cloud", cloud_txt)}</div>""")

def _goal_changed():
    g = st.session_state.get("goal")
    if g:
        changed = policy.set_goal(conn(), g)
        if changed:
            st.toast(f"Goal: {GOAL_LABELS[g]} · {policy.GOALS[g]['blurb']} (saved, queued for sync)")
    else:                                                  # clicking the active option again keeps it
        st.session_state.goal = policy.get_goal(conn())


if "goal" not in st.session_state:
    st.session_state.goal = POL["goal"]
nl, ng, nr = st.columns([6.6, 3.1, 1.5], vertical_alignment="center")
with nl:
    page = st.segmented_control("Page", PAGES, default="Overview", key="nav", label_visibility="collapsed") or "Overview"
with ng:
    st.segmented_control("Goal", list(policy.GOALS), format_func=GOAL_LABELS.get, key="goal",
                         on_change=_goal_changed, label_visibility="collapsed",
                         help="One setting tunes the copilot: which AI model explains, how sensitive alerts are, "
                              "and which savings are worth showing.")
with nr:
    with st.popover("Controls", icon=":material/tune:", width="stretch"):
        st.markdown("**Collect readings**")
        st.caption("Runs as a separate background process, so you can close this page.")
        secs = st.select_slider("Duration", options=[60, 120, 300, 600], value=120,
                                format_func=lambda x: f"{x // 60} min")
        if st.button("Start collecting", width="stretch", type="primary"):
            spawn(["collect", "--seconds", str(secs)])
            st.toast(f"Collecting for {secs // 60} min from {sensor.name}")
        st.divider()
        st.markdown("**Assumptions** (printed on every cost and CO₂ figure)")
        st.markdown(f"- Tariff **₹{a.tariff_inr_per_kwh}/kWh**: {a.tariff_source}\n"
                    f"- Grid **{a.grid_kg_per_kwh} kg CO₂/kWh**: {a.grid_source}\n"
                    f"- Projection **{a.usage_hours_per_day:g} h/day**, 30 days/month")
        st.caption(f"Sensor: {sensor.description}")
        for f in energy.FORMULAS.values():
            st.code(f, language=None)
st.write("")


# ================================================================== OVERVIEW
def alert_banner(c, key: str):
    alerts = live_alerts(c)
    if not alerts:
        return
    al = alerts[0]
    more = f" · +{len(alerts) - 1} more" if len(alerts) > 1 else ""
    with st.container(key=f"cardalert-{key}"):
        a1, a2 = st.columns([6, 1.3], vertical_alignment="center")
        a1.markdown(f"""<div class="alert-row"><div class="alert-ic">{ico("alert", 20)}</div><div>
            <div class="alert-t">Unusual power: {esc(al['subject'])}</div>
            <div class="alert-d">Last {al['recent_s']:.0f} s: {al['recent_w']:.2f} W vs its usual {al['usual_w']:.2f} W
            {prov(al['provenance'])} · alert at {POL['anomaly_ratio']:g}× usual ({esc(POL['label'])} goal){more}</div></div>
            <div class="alert-x">{al['times']:.1f}×</div></div>""", unsafe_allow_html=True)
        if a2.button("What to do →", key=f"alert-go-{key}", width="stretch"):
            recommend.refresh(c)
            goto("Advice")
            st.rerun()


def page_overview():
    c = C
    alert_banner(c, "ov")
    left, right = st.columns([7, 4], gap="medium")
    with left, st.container(key="cardglow-hero"):
        proven = sum(1 for k in HERO if k in BEST and strong(BEST[k][1]))
        show(f"""<div class="h-hero" style="margin-top:2px">Same work. <em>Far less energy.</em></div>
          <div class="lead">Every saving below is a receipt from this laptop: baseline and optimized runs, interleaved, measured with powermetrics, and
          tested for significance, including the energy of the copilot's own AI. {proven} of 3 are proven so far.</div>""")
        tiles = []
        for key in HERO:
            name = SCENARIOS[key]
            if key not in BEST:
                tiles.append(f"""<div class="win empty"><div class="t">{name}</div><div class="big">Not measured yet</div>
                  <code class="cmd">sudo python3 -m joule experiment {key} --source powermetrics</code></div>""")
                continue
            row, b = BEST[key]
            keep = max(0.0, min(100.0, 100 - b["saved_pct"]))
            tiles.append(f"""<div class="win"><div class="t">{name}</div>
              <div class="big">−{count(b['saved_pct'])}<small>%</small></div>
              <div class="sub"><span class="dot-o"></span>{mwh(b['baseline_wh'])} → <span class="dot-b"></span>{mwh(b['optimized_wh'])} mWh / run</div>
              <div class="bar2" title="optimized uses {keep:.0f}% of the baseline energy"><i style="width:{keep:.1f}%"></i></div>
              <div class="foot">{prov(b['provenance'])} &nbsp;{'proven' if b['significant'] else 'not proven'} · {fmt_p(b.get('p_value'))}</div>
            </div>""")
        show(f'<div class="wins">{"".join(tiles)}</div>')
        st.write("")
        st.button("Open the receipts →", on_click=goto, args=("Receipts",), type="primary")

    with right, st.container(key="card-pipeline"):
        n_samples = c.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
        last_src = (c.execute("SELECT source FROM samples ORDER BY ts DESC LIMIT 1").fetchone() or [sensor.name])[0]
        recs = db.list_recommendations(c)
        n_open = sum(1 for x in recs if x["status"] == "open")
        ex = c.execute("SELECT COUNT(*), SUM(grounded) FROM reports WHERE kind='explanation'").fetchone()
        n_ex, n_gr = ex[0] or 0, ex[1] or 0
        n_rc = len(BODIES)
        n_proven = sum(1 for _, b in BODIES if b["significant"] and b["provenance"] == "MEASURED")

        def step(ic, k, d, v, sub, done):
            return (f'<div class="step{" done" if done else ""}"><div class="ic">{ic}</div>'
                    f'<div><div class="k">{k}</div><div class="d">{d}</div></div>'
                    f'<div class="v">{v}<small>{sub}</small></div></div>')
        show(f"""<div class="eyebrow">How it works · live status</div><div class="steps">
          {step(ico("measure"), "Measure", f"{esc(last_src)} sensor, 1 s samples", f"{n_samples:,}", "readings", n_samples > 0)}
          {step(ico("recommend"), "Recommend", "Markov states + Apriori patterns", len(recs), f"{n_open} open", bool(recs))}
          {step(ico("explain"), "Explain", " → ".join(m.split(":")[-1].upper() for m in POL["models"]) + " cascade, offline, self-metered", n_ex, f"{n_gr}/{n_ex} grounded", n_ex > 0)}
          {step(ico("prove"), "Prove", "A/B runs + Mann-Whitney + hash chain", n_rc, f"{sum(1 for k in HERO if k in BEST and strong(BEST[k][1]))} of 3 proven", n_proven > 0)}
          {step(ico("sync"), "Sync", "outbox, retries, no duplicates", qstats['done'], f"{qstats['pending']} waiting", qstats['done'] > 0)}
        </div>""")

    l2, m2, r2 = st.columns([4, 4, 3], gap="medium")
    with l2, st.container(key="card-live"):
        @st.fragment(run_every="5s")
        def mini_live():
            rows, replay = window_rows(conn(), 10)
            show('<div class="eyebrow">Laptop power' + (f' · last session {replay}' if replay else ' · live') + '</div>')
            if not rows:
                st.caption("No readings yet: Controls → Start collecting.")
                return
            pts = [(x["ts"], x["watts"]) for x in rows]
            show(f'<div class="power-now" style="margin-top:8px">{rows[-1]["watts"]:.2f}<small> W</small></div>'
                 f'<div class="note">{prov(rows[-1]["provenance"])} &nbsp;avg {energy.mean_power(pts):.2f} W · '
                 f'{energy.integrate_wh(pts) * 1000:.0f} mWh in 10 min</div>')
            fig = power_line(pts, height=130)
            fig.update_yaxes(showticklabels=False, showgrid=False, title=None)
            fig.update_xaxes(showticklabels=False)
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        mini_live()
        st.button("Open live view →", on_click=goto, args=("Live",), key="go-live")

    with m2, st.container(key="card-advice"):
        recs = db.list_recommendations(c)
        top = next((x for x in recs if x["status"] == "open"), recs[0] if recs else None)
        show('<div class="eyebrow">Top advice</div>')
        if not top:
            st.caption("No advice yet: collect a few minutes of readings.")
        else:
            pred = top["facts"].get("prediction") or {}
            show(f"""<p class="rec-title" style="margin-top:8px">{esc(top['title'])}</p>
              <div class="rec-head">{esc(top['facts'].get('headline', ''))}</div>
              <div class="stats"><div class="stat"><div class="k">Could save</div><div class="v">{esc(pred.get('saved_wh_per_day', '—'))}<small> Wh/day</small></div></div>
              <div class="stat"><div class="k">Per month</div><div class="v">₹{esc(pred.get('saved_inr_per_month', '—'))}</div></div></div>
              <div class="note">{prov(pred.get('provenance', 'ESTIMATED'))} &nbsp;<span class="status {esc(top['status'])}">{esc(top['status'])}</span></div>""")
            st.write("")
            st.button("See all advice →", on_click=goto, args=("Advice",), key="go-advice")

    with r2, st.container(key="card-sync"):
        show(f"""<div class="eyebrow">Cloud sync</div>
          <div class="cloud-big" style="margin-top:10px"><span class="dot {'ok' if cloud_ok else 'off'}"></span>
            {'Online' if cloud_ok else 'Offline'}</div>
          <div class="note" style="margin:6px 0 10px">{'Queue drains automatically every 3 s.' if cloud_ok else
            'Working offline. Everything is kept in the local outbox and sent when the cloud returns.'}</div>
          <div class="stats"><div class="stat"><div class="k">Waiting</div><div class="v">{qstats['pending']}</div></div>
          <div class="stat"><div class="k">Delivered</div><div class="v">{qstats['done']}</div></div></div>""")
        st.button("Open sync →", on_click=goto, args=("Sync",), key="go-sync")


# ================================================================== RECEIPTS
def receipt_html(row, b, dur_s) -> str:
    a_ = b["assumptions"]
    pred = b.get("predicted_saved_wh")
    when = time.strftime("%d %b %Y · %H:%M", time.localtime(row["created"]))
    stamp = '<div class="stamp">PROVEN</div>' if b["significant"] else '<div class="stamp no">NOT PROVEN</div>'
    basis = "energy above idle" if "above idle" in (b.get("basis") or "") else "total energy"
    dur = f" · {dur_s:.0f} s each" if dur_s else ""
    return f"""
<div class="receipt">{stamp}
  <div class="hd">⚡ JOULE RECEIPTS · #{row['id']:04d}</div>
  <div class="ttl">{esc(b['title'])}</div>
  <div class="meta">{when} · {esc(b['sensor'])} · {prov(b['provenance'])}</div>
  <hr>
  <div class="desc"><span class="dot-o"></span><b>BEFORE</b> {esc(b['baseline'])}<br>
       <span class="dot-b"></span><b>AFTER</b> &nbsp;{esc(b['optimized'])}</div>
  <hr>
  <div class="row"><span>Runs</span><span>{b['repeats']} + {b['repeats']} interleaved{dur}</span></div>
  <div class="row"><span>Measured as</span><span>{basis}</span></div>
  <div class="row"><span>Idle power</span><span>{b['idle_w']} W</span></div>
  <hr>
  <div class="row"><span>Baseline (median)</span><span>{mwh(b['baseline_wh'])} mWh</span></div>
  <div class="row"><span>Optimized (median)</span><span>{mwh(b['optimized_wh'])} mWh</span></div>
  <hr>
  <div class="row total"><span>SAVED / RUN</span><span>{mwh(b['measured_saved_wh'])} mWh  −{b['saved_pct']}%</span></div>
  <div class="row"><span>Significance</span><span>Mann-Whitney {fmt_p(b.get('p_value'))}</span></div>
  <div class="row"><span>Pilot prediction</span><span>{'—' if pred is None else f"{mwh(pred)} mWh ({b.get('prediction_error_pct')}% off)"}</span></div>
  <div class="row"><span>Same work done</span><span>{'yes, checksum match' if b['equivalent_work'] else 'NO'}</span></div>
  <hr>
  <div class="row"><span>Cost saved</span><span>₹{energy.cost_inr(b['measured_saved_wh'], a):.7f}</span></div>
  <div class="row"><span>CO₂e avoided</span><span>{b['saved_co2_g']:.5f} g</span></div>
  <div class="desc" style="margin-top:4px">@ ₹{a.tariff_inr_per_kwh:g}/kWh · {a_['grid_kg_co2_per_kwh']} kg CO₂/kWh{'' if abs(a_['tariff_inr_per_kwh'] - a.tariff_inr_per_kwh) < 1e-9 else f" · recorded at ₹{a_['tariff_inr_per_kwh']:g}/kWh"}</div>
  <hr>
  <div class="desc"><b>TRADE-OFF</b> {esc(b['tradeoff'])}</div>
  <div class="desc" style="text-align:center;margin-top:12px;letter-spacing:0.2em">THANK YOU FOR SAVING ENERGY</div>
  {f'<hr><div class="hash">SHA-256 {esc(row["hash"])}<br>chained to {esc((row["prev_hash"] or "")[:16])}…</div>' if "hash" in row.keys() and row["hash"] else ""}
</div>"""


def runs_chart(vals: dict[str, list[float]]) -> go.Figure:
    fig = go.Figure()
    for variant, color in (("baseline", ORANGE), ("optimized", BLUE)):
        v = [x * 1000 for x in vals.get(variant, [])]
        if not v:
            continue
        fig.add_scatter(
            x=v, y=[variant] * len(v), mode="markers", name=f"{variant} runs",
            marker={"color": color, "size": 13, "line": {"color": SURF, "width": 2}},
            customdata=list(range(1, len(v) + 1)),
            hovertemplate=f"{variant} run %{{customdata}}<br><b>%{{x:.3f}} mWh</b><extra></extra>")
        med = statistics.median(v)
        fig.add_scatter(x=[med], y=[variant], mode="markers", showlegend=False,
                        marker={"symbol": "line-ns", "size": 32, "line": {"color": INK, "width": 2}},
                        hovertemplate=f"median {variant}<br><b>%{{x:.3f}} mWh</b><extra></extra>")
        fig.add_annotation(x=med, y=variant, text=f"median {med:.3g}", showarrow=False, yshift=-24,
                           font={"size": 11, "color": INK2})
    fig = style(fig, x_title="mWh per run", height=250)
    fig.update_layout(margin=dict(l=4, r=8, t=34, b=4), legend={"y": 1.12})
    fig.update_yaxes(rangemode="normal", showgrid=False, categoryorder="array", categoryarray=["optimized", "baseline"])
    fig.update_xaxes(showgrid=True, gridcolor=GRID, rangemode="tozero")
    return fig


def label_card(c, row):
    chain = db.verify_chain(c)
    lab = label.label_for(c, row["id"], chain)
    with st.container(key="card-label"):
        bars = []
        for i, (g, limit) in enumerate(label.BANDS):
            on = g == lab["grade"]
            rng = f"≤ {limit}%" if limit else "> 100%"
            bars.append(f'<div class="ebar{" on" if on else ""}" style="width:{40 + i * 9}%;background:{label.COLORS[g]}">'
                        f'<span>{g}</span><span>{rng}{"  ◀" if on else ""}</span></div>')
        eff = lab["efficiency"]
        eff_html = (f'<div class="stat"><div class="k">Efficiency ({esc(eff["unit"])})</div><div class="v">'
                    f'{eff["optimized"]:,.0f}<small> vs {eff["baseline"]:,.0f}</small></div></div>') if eff else ""
        why = "" if lab["certified"] else f'<div class="note" style="margin-top:6px">Why provisional: {esc("; ".join(lab["reasons"]))}</div>'
        show_flat(f"""<div class="eyebrow">Energy label · like an appliance sticker</div>
          <div class="elabel" style="margin-top:10px"><div class="ebars">{''.join(bars)}</div>
            <div style="text-align:center"><div class="egrade" style="color:{label.COLORS[lab['grade']]}">{lab['grade']}</div>
            <div class="note">uses {lab['ratio_pct']:.0f}% of<br>the reference energy</div>
            <span class="cert {'yes' if lab['certified'] else 'no'}">{'CERTIFIED' if lab['certified'] else 'PROVISIONAL'}</span></div></div>
          {why}
          <div class="stats" style="margin-top:10px">{eff_html}
            <div class="stat"><div class="k">Hash chain</div><div class="v">{'✓ intact' if chain['ok'] else '✗ broken'}<small> {chain['n']} receipts</small></div></div></div>
          <div class="hashline">receipt #{row['id']} <span class="{'ok' if lab['chain_ok'] else 'bad'}">sha256 {esc(lab['hash'] or '')}</span><br>
            ← previous {esc((lab['prev_hash'] or '')[:24])}…</div>""")
        b1, b2 = st.columns(2)
        b1.download_button("Certificate (HTML)", icon=":material/download:", data=label.certificate_html(lab, s.device_id),
                           file_name=f"energy-certificate-{row['id']}.html", mime="text/html", width="stretch",
                           key=f"cert{row['id']}")
        if b2.button("Try to fake a number", icon=":material/edit:", width="stretch", key=f"tamper{row['id']}",
                     help="Edits a COPY of the receipts in memory and re-checks the chain. Your data is not touched."):
            st.session_state.tamper = label.tamper_demo(c, row["id"])
        t = st.session_state.get("tamper")
        if t and t.get("edited") and t["edited"]["receipt_id"] == row["id"]:
            ed = t["edited"]
            show_flat(f"""<div class="hashline"><b>Tamper test (in memory only)</b><br>
              receipt #{ed['receipt_id']}: saved {mwh(ed['from'])} → {mwh(ed['to'])} mWh<br>
              <span class="bad">✗ chain BROKEN at receipt #{t['broken_at']}</span>: its hash no longer matches, and every
              receipt after it points to a hash that does not exist. The cloud keeps its own copy of the chain, so a
              local edit cannot hide.</div>""")


def page_receipts():
    c = C
    if not BODIES:
        st.info("No receipts yet. Run an experiment below.")
    keys = [k for k in SCENARIOS if k in BEST]
    if keys:
        pick = st.segmented_control("Scenario", keys, default=keys[0], format_func=SCENARIOS.get, key="rscn",
                                    label_visibility="collapsed") or keys[0]
        row, b = BEST[pick]
        left, right = st.columns([5, 6], gap="large")
        durs = [x[0] for x in c.execute("SELECT duration_s FROM experiment_runs WHERE experiment_id=?",
                                        (row["experiment_id"],))]
        with left:
            show(receipt_html(row, b, statistics.median(durs) if durs and "same duration" in (b.get("basis") or "")
                              else None))
        with right:
            label_card(c, row)
            st.write("")
            with st.container(key="card-runs"):
                show('<p class="rec-title" style="margin:0">'
                     'Every run is a dot. The white line is the median.</p>')
                vals = run_values(c, row["experiment_id"], b.get("basis"))
                if any(vals.values()):
                    st.plotly_chart(runs_chart(vals), width="stretch", key=f"runs{row['id']}",
                                    config={"displayModeBar": False})
                pe = b.get("prediction_error_pct")
                nb, no = len(vals.get("baseline", [])), len(vals.get("optimized", []))
                below = sum(1 for o in vals.get("optimized", []) for x in vals.get("baseline", []) if o < x)
                show(f"""<div class="stats">
                  <div class="stat"><div class="k">Saved per run</div><div class="v">{mwh(b['measured_saved_wh'])}<small> mWh</small></div></div>
                  <div class="stat"><div class="k">Optimized below baseline</div><div class="v">{below}<small>/{nb * no} pairs</small></div></div>
                  <div class="stat"><div class="k">Pilot prediction off by</div><div class="v">{'—' if pe is None else f"{pe:g}"}<small>{'' if pe is None else ' %'}</small></div></div>
                </div><div class="note">{fmt_p(b.get('p_value'))} (exact Mann-Whitney U test). A saving only counts as
                proven when p &lt; 0.05. Runs are interleaved so drift and background noise hit both sides equally.</div>""")
                with st.expander("Table view"):
                    st.dataframe([{"variant": k, "run": i + 1, "mWh": round(v * 1000, 4)}
                                  for k, vs in vals.items() for i, v in enumerate(vs)], hide_index=True, width="stretch")
    if BODIES:
        with st.expander(f"All {len(BODIES)} receipts, including noisy and simulated runs"):
            st.dataframe([{"#": row["id"], "scenario": b["scenario"], "evidence": b["provenance"], "sensor": b["sensor"],
                           "runs": b["repeats"], "baseline mWh": round(b["baseline_wh"] * 1000, 3),
                           "optimized mWh": round(b["optimized_wh"] * 1000, 3), "saved %": b["saved_pct"],
                           "proven": "yes" if b["significant"] else "no", "p": b.get("p_value"),
                           "when": time.strftime("%d %b %H:%M", time.localtime(row["created"]))}
                          for row, b in BODIES], hide_index=True, width="stretch")
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


# ================================================================== ADVICE
def ai_energy_card(c):
    rows = c.execute("SELECT model, energy_j, energy_prov, cascade_json FROM reports WHERE kind='explanation' "
                     "AND energy_j IS NOT NULL").fetchall()
    with st.container(key="card-aienergy"):
        show('<div class="eyebrow">The copilot measures its own AI</div>')
        if not rows:
            show('<div class="note" style="margin-top:6px">Press <b>Explain</b> on any card: each explanation is metered '
                 'while the local model writes it, and the small model goes first.</div>')
            return
        small = [x for x in rows if "0.5b" in (x["model"] or "")]
        big = [x for x in rows if "1.5b" in (x["model"] or "")]
        esc_n = sum(1 for x in rows if len([s_ for s_ in json.loads(x["cascade_json"] or "[]") if "skipped" not in s_]) > 1)
        avg = lambda xs: statistics.fmean(x["energy_j"] for x in xs) if xs else None  # noqa: E731
        provs = sorted({x["energy_prov"] for x in rows})
        a_s, a_b = avg(small), avg(big)
        ratio = f"{a_b / a_s:.1f}×" if a_s and a_b else "—"
        show(f"""<div class="stats" style="margin-top:8px">
          <div class="stat"><div class="k">Explanations metered</div><div class="v">{len(rows)}</div></div>
          <div class="stat"><div class="k">Answered by 0.5B</div><div class="v">{len(small)}<small>/{len(rows)}</small></div></div>
          <div class="stat"><div class="k">Avg energy · 0.5B</div><div class="v">{'—' if a_s is None else f'{a_s:.1f}'}<small> J</small></div></div>
          <div class="stat"><div class="k">Avg energy · 1.5B</div><div class="v">{'—' if a_b is None else f'{a_b:.1f}'}<small> J</small></div></div>
          <div class="stat"><div class="k">1.5B costs</div><div class="v">{ratio}</div></div>
          <div class="stat"><div class="k">Escalations</div><div class="v">{esc_n}</div></div></div>
          <div class="note">{' '.join(prov(p_) for p_ in provs)} &nbsp;Whole-laptop energy while the model wrote. The CPU
          estimate cannot see the GPU, so it under-counts; run the cascade experiment with powermetrics for MEASURED numbers.</div>""")


def page_advice():
    c = C
    alert_banner(c, "adv")
    ai_energy_card(c)
    st.write("")
    top_l, top_r = st.columns([4, 1], vertical_alignment="center")
    top_l.markdown('<div class="note">Facts and predictions are <b>computed</b> from your readings. The local AI only '
                   'writes the explanation, and a grounding check rejects any number it makes up.</div>',
                   unsafe_allow_html=True)
    if top_r.button("Refresh from readings", icon=":material/refresh:", width="stretch"):
        recommend.refresh(c)
        st.rerun()
    recs = [x for x in db.list_recommendations(c) if x["status"] != "cleared"]
    small = [x for x in recs if ((x["facts"].get("prediction") or {}).get("saved_wh_per_day") or 1e9) < POL["min_wh_day"]
             and x["kind"] != "anomaly"]
    recs = [x for x in recs if x not in small]
    recs.sort(key=lambda x: (x["kind"] != "anomaly", x["status"] != "open"))
    if small:
        st.caption(f"{len(small)} recommendation(s) under {POL['min_wh_day']:g} Wh/day hidden by the "
                   f"**{POL['label']}** goal.")
    if not recs:
        st.info("No recommendations yet. Collect a few minutes of readings, then refresh.")
    for rec in recs:
        f = rec["facts"]
        pred = f.get("prediction") or {}
        with st.container(key=f"card-rec{rec['id']}"):
            review = ' <span class="status review">needs review</span>' if rec["needs_review"] else ""
            show(f"""<div style="display:flex;justify-content:space-between;align-items:center;gap:10px">
                 <p class="rec-title">{esc(rec['title'])}</p>
                 <span><span class="status {esc(rec['status'])}">{esc(rec['status'])}</span>{review}</span></div>
                 <div class="rec-head">{esc(f.get('headline', ''))}</div>""")
            if pred:
                show(f"""<div class="stats">
                  <div class="stat"><div class="k">Predicted saving</div><div class="v">{esc(pred['saved_wh_per_day'])}<small> Wh/day</small></div></div>
                  <div class="stat"><div class="k">Cost</div><div class="v">₹{esc(pred['saved_inr_per_month'])}<small> /month</small></div></div>
                  <div class="stat"><div class="k">Carbon</div><div class="v">{esc(pred['saved_co2_g_per_month'])}<small> g CO₂e/month</small></div></div>
                </div><div class="note">{prov(pred.get('provenance', 'ESTIMATED'))} &nbsp;{esc(pred.get('method', ''))}</div>""")
            last = c.execute("SELECT * FROM reports WHERE rec_id=? AND kind='explanation' "
                             "ORDER BY id DESC LIMIT 1", (rec["id"],)).fetchone()
            if last:
                body = esc(last["body"]).replace("\n", "<br>")
                chk = "✓ every number checked against the facts" if last["grounded"] else "✗ grounding check failed"
                show(f"""<div class="ai"><div class="who">{ico("explain", 14)} {esc(last['model'])} · offline<span class="chk">{chk}</span></div>
                     {body}{ai_meter(last)}</div>""")
            st.write("")
            b1, b2, b3, b4, _ = st.columns([1.5, 1, 1, 1, 2])
            if b1.button("Explain", icon=":material/psychology:", key=f"ex{rec['id']}", type="primary", width="stretch"):
                from joule.cli import explain_and_save
                with st.spinner(f"{' → '.join(POL['models'])} writing offline, metering its own energy…"):
                    explain_and_save(c, rec)
                st.rerun()
            for col, decision, label in ((b2, "accept", "Accept"), (b3, "reject", "Reject"), (b4, "defer", "Defer")):
                if col.button(label, key=f"{decision}{rec['id']}", width="stretch"):
                    db.record_decision(c, rec["id"], decision, device_id=s.device_id)
                    st.toast(f"{label} saved locally and queued for sync")
                    st.rerun()


# ================================================================== WHAT-IF
def curve(xs, ys, measured, current, x_title, ticks) -> go.Figure:
    """Model curve (line), the two measured settings (dots) and the slider's setting (ring)."""
    fig = go.Figure(go.Scatter(x=xs, y=ys, mode="lines", name="model (ESTIMATED)", line={"color": INK2, "width": 2},
                               hovertemplate=f"{x_title} %{{x:g}}<br><b>%{{y:.3f}} mWh</b><extra></extra>"))
    for (mx, my, name), color in zip(measured, (ORANGE, BLUE)):
        fig.add_scatter(x=[mx], y=[my], mode="markers", name=name,
                        marker={"color": color, "size": 12, "line": {"color": SURF, "width": 2}},
                        hovertemplate=f"{name}<br>{x_title} %{{x:g}}<br><b>%{{y:.3f}} mWh</b><extra></extra>")
    fig.add_scatter(x=[current[0]], y=[current[1]], mode="markers", name="your setting",
                    marker={"color": "rgba(0,0,0,0)", "size": 18, "line": {"color": INK, "width": 2}},
                    hovertemplate=f"your setting<br>{x_title} %{{x:g}}<br><b>%{{y:.3f}} mWh</b><extra></extra>")
    fig = style(fig, y_title="mWh", x_title=x_title, height=250)
    fig.update_layout(legend={"y": 1.14})
    fig.update_xaxes(type="log", tickvals=ticks, ticktext=[f"{t:g}" for t in ticks])
    return fig


def wi_result(res: dict, delay_text: str) -> None:
    ext = ' · <b>outside the measured range</b> (extrapolated)' if res["extrapolated"] else ""
    show(f"""<div class="stats" style="margin-top:6px">
      <div class="stat"><div class="k">Energy saved</div><div class="v">{res['saved_pct']:.0f}<small> %</small></div></div>
      <div class="stat"><div class="k">Per day</div><div class="v">{r(res['wh_per_day'] * 1000)}<small> mWh</small></div></div>
      <div class="stat"><div class="k">Per month</div><div class="v">₹{r(res['inr_per_month'])}</div></div>
      <div class="stat"><div class="k">CO₂e / month</div><div class="v">{r(res['co2_g_per_month'])}<small> g</small></div></div>
      <div class="stat"><div class="k">Trade-off</div><div class="v" style="font-size:1rem">{delay_text}</div></div></div>
      <div class="note">{prov('ESTIMATED')} &nbsp;model fitted through the two runs of receipt #{res['fitted_to']}
      {prov(res['fit_provenance'])}{ext}. Prove a setting by running it as an experiment.</div>""")


def page_whatif():
    c = C
    show('<div class="note">Try a change <b>before</b> making it. Each model passes through the two settings a receipt '
         'actually measured, so between them the slider interpolates real data. Results are ESTIMATED until an '
         'experiment proves them.</div>')
    st.write("")
    left, right = st.columns(2, gap="medium")
    with left, st.container(key="card-wi-poll"):
        show('<div class="eyebrow">Background sync · how often it checks for changes</div>')
        rc = whatif.latest_receipt(c, "idle")
        if not rc:
            st.caption("Needs an idle receipt: run the idle experiment first.")
        else:
            m = whatif.polling_model(rc)
            x = st.select_slider("Check every", [0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0], value=1.0,
                                 format_func=lambda v: f"{v:g} s", key="wi_poll")
            hrs = st.slider("Hours a day it runs", 1, 24, int(a.usage_hours_per_day), key="wi_poll_h")
            res = whatif.polling(rc, x, hrs, a)
            show(f'<div class="wi-big">{r(res["energy_per_window_wh"] * 1000)}<small> mWh per {m["window_s"]:.0f} s '
                 f'vs {r(res["baseline_per_window_wh"] * 1000)} at {m["fast_s"]:g} s</small></div>')
            xs = [0.1 * (1.15 ** i) for i in range(0, 44)]
            e = lambda v: (m["fixed_wh"] + m["per_scan_wh"] / v) * 1000      # noqa: E731
            st.plotly_chart(curve(xs, [e(v) for v in xs],
                                  [(m["fast_s"], e(m["fast_s"]), f"measured: every {m['fast_s']:g} s"),
                                   (m["slow_s"], e(m["slow_s"]), f"measured: every {m['slow_s']:g} s")],
                                  (x, e(x)), "seconds between checks", [0.1, 0.2, 0.5, 1, 2, 5, 10, 30, 60]),
                            width="stretch", config={"displayModeBar": False}, key="wi_poll_chart")
            wi_result(res, f"changes seen up to {x:g} s later")
    with right, st.container(key="card-wi-batch"):
        show('<div class="eyebrow">Small jobs · how many run per launch</div>')
        rc = whatif.latest_receipt(c, "batching")
        if not rc:
            st.caption("Needs a batching receipt: run the batching experiment first.")
        else:
            m = whatif.batching_model(rc)
            bsz = st.select_slider("Jobs per launch", [1, 2, 5, 10, 20, 50, 100, 200], value=5, key="wi_batch")
            runs = st.slider("Workloads a day", 1, 100, 10, key="wi_batch_n")
            res = whatif.batching(rc, bsz, runs, a)
            show(f'<div class="wi-big">{res["launches"]}<small> launches for {m["jobs"]} jobs · '
                 f'{r(res["energy_per_workload_wh"] * 1000)} mWh vs {r(res["baseline_per_workload_wh"] * 1000)}</small></div>')
            xs = [1, 2, 3, 4, 5, 6, 8, 10, 13, 16, 20, 25, 34, 40, 50, 67, 100, 200]
            e = lambda b: (m["work_wh"] + m["per_launch_wh"] * -(-m["jobs"] // b)) * 1000   # noqa: E731
            st.plotly_chart(curve(xs, [e(v) for v in xs],
                                  [(1, e(1), "measured: 1 job per launch"),
                                   (m["measured_batch"], e(m["measured_batch"]), f"measured: {m['measured_batch']} per launch")],
                                  (bsz, e(bsz)), "jobs per launch", [1, 2, 5, 10, 20, 50, 100, 200]),
                            width="stretch", config={"displayModeBar": False}, key="wi_batch_chart")
            wi_result(res, f"first result after {bsz} job{'s' if bsz > 1 else ''}")
    with st.container(key="card-wi-app"):
        show('<div class="eyebrow">Pause a background app</div>')
        apps = [x for x in db.list_recommendations(c) if x["kind"] in ("background", "anomaly")
                and (x["facts"].get("observed") or {}).get("avg_w", (x["facts"].get("observed") or {}).get("extra_w"))]
        if not apps:
            st.caption("No background apps found yet: collect readings, then refresh the advice.")
        else:
            w_of = lambda x: x["facts"]["observed"].get("avg_w") or x["facts"]["observed"].get("extra_w")  # noqa: E731
            c1, c2 = st.columns([2, 3])
            pick = c1.selectbox("App", apps, format_func=lambda x: f"{x['facts'].get('app', x['title'])} · {w_of(x)} W",
                                key="wi_app")
            hrs = c2.slider("Hours a day it would be paused", 1, 24, int(a.usage_hours_per_day), key="wi_app_h")
            res = whatif.app_pause(w_of(pick), hrs, a)
            show(f"""<div class="stats" style="margin-top:6px">
              <div class="stat"><div class="k">Per day</div><div class="v">{r(res['wh_per_day'])}<small> Wh</small></div></div>
              <div class="stat"><div class="k">Per month</div><div class="v">₹{r(res['inr_per_month'])}</div></div>
              <div class="stat"><div class="k">CO₂e / month</div><div class="v">{r(res['co2_g_per_month'])}<small> g</small></div></div>
              <div class="stat"><div class="k">Trade-off</div><div class="v" style="font-size:1rem">{esc(pick['facts'].get('tradeoff', ''))}</div></div></div>
              <div class="note">{prov('ESTIMATED')} &nbsp;{w_of(pick)} W {prov((pick['facts'].get('observed') or {}).get('provenance', 'ATTRIBUTED'))}
              × {hrs} h/day × 30 days · ₹{a.tariff_inr_per_kwh}/kWh · {a.grid_kg_per_kwh} kg CO₂/kWh</div>""")


# ================================================================== CERTIFY YOUR SOFTWARE
def page_certify():
    import shlex
    from joule import certify
    c = C
    show('<div class="h-hero" style="font-size:1.7rem">Certify your own software</div>'
         '<div class="lead" style="max-width:none">Give the command for the <b>old</b> version of your program and the '
         'command for the <b>new</b> one. Joule Receipts runs both 5 times, alternating, measures the energy, checks '
         'that both printed the same output (same work), and issues a hash-chained receipt, an A–G energy label and a '
         'certificate. Fast programs are repeated until each run lasts 5 s, then divided per run.</div>')
    st.write("")
    form_l, form_r = st.columns([3, 2], gap="medium")
    with form_l, st.container(key="card-certify-form"):
        name = st.text_input("Software name", "Prime counter", key="cf_name")
        old = st.text_input("Old version (reference) command", "python3 examples/primes_v1.py", key="cf_old")
        new = st.text_input("New version (to certify) command", "python3 examples/primes_v2.py", key="cf_new")
        f1, f2, f3 = st.columns([3, 1.3, 1.3])
        folder = f1.text_input("Run in folder", str(ROOT), key="cf_dir")
        reps = f2.number_input("Runs each", 3, 10, 5, key="cf_reps")
        src = f3.selectbox("Sensor", ["auto", "estimate", "battery", "simulated"], key="cf_src",
                           help="powermetrics needs sudo: use the Terminal command on the right for MEASURED")
        loose = st.checkbox("Outputs may differ (equal work then not proven, label stays provisional)", key="cf_loose")
        args = ["certify", "--name", name, "--baseline", old, "--candidate", new, "--cwd", folder,
                "--repeats", str(reps), "--source", src] + (["--allow-different-output"] if loose else [])
        if st.button("Certify in background", icon=":material/verified:", type="primary", key="cf_go",
                     disabled=not (name.strip() and old.strip() and new.strip())):
            spawn(args)
            st.toast(f"Certifying '{name}': about 1–3 minutes. The certificate appears below when it finishes.")
    with form_r, st.container(key="card-certify-how"):
        show('<p class="rec-title">For a MEASURED certificate</p><div class="note" style="margin:6px 0 8px">Only '
             'MEASURED, significant, same-output results can be CERTIFIED. Run this in Terminal (needs your '
             'password):</div>')
        st.code(" ".join(["sudo .venv/bin/python -m joule certify --name", shlex.quote(name), "--baseline",
                          shlex.quote(old), "--candidate", shlex.quote(new), "--cwd", shlex.quote(folder),
                          "--repeats", str(reps), "--source powermetrics"] +
                         (["--allow-different-output"] if loose else [])), language="bash", wrap_lines=True)

        @st.fragment(run_every="3s")
        def job_log():
            path = config.data_dir() / "jobs.log"
            lines = [ln for ln in (path.read_text().splitlines()[-200:] if path.exists() else []) if ln.strip()]
            start = max((i for i, ln in enumerate(lines) if ln.startswith("$ joule certify")), default=None)
            tail = lines[start:][-7:] if start is not None else []
            show('<div class="note" style="margin-top:8px">Latest certification run</div>'
                 f'<div class="log">{"<br>".join(esc(ln[:120]) for ln in tail) or "no certification run yet"}</div>')
        job_log()

    st.write("")
    certs = certify.certificates(c)
    if not certs:
        st.info("No software certified yet. The example above compares two prime counters that print the same "
                "answer: version 1 tests every number by trial division, version 2 uses a sieve.")
        return
    rows = {row["id"]: (row, b) for row, b in BODIES if b.get("scenario") == certify.KEY}
    pick = st.selectbox("Certificates", [x["id"] for x in certs if x["id"] in rows], key="cf_pick",
                        format_func=lambda i: f"#{i} · {rows[i][1]['title'].replace('Software certificate: ', '')} · "
                                              f"{rows[i][1]['provenance']} · "
                                              f"{time.strftime('%d %b %H:%M', time.localtime(rows[i][0]['created']))}")
    if pick is None:
        st.caption("A certification just finished: reload the page to see it.")
        return
    row, b = rows[pick]
    left, right = st.columns([5, 6], gap="large")
    with left:
        show(receipt_html(row, b, None))
    with right:
        label_card(c, row)


# ================================================================== LIVE
def page_live():
    st.segmented_control("Window", [5, 10, 30, 120], default=10, key="window_min",
                         format_func=lambda m: f"{m} min")

    @st.fragment(run_every="5s")
    def live():
        c = conn()
        window = st.session_state.get("window_min") or 10
        rows, replay = window_rows(c, window)
        if not rows:
            st.info("No readings yet. Open **Controls → Start collecting**.")
            return
        if replay:
            st.caption(f"Not collecting right now, so this replays the last recorded session (ended {replay}). "
                       "Open Controls → Start collecting for live readings.")
        pts = [(x["ts"], x["watts"]) for x in rows]
        ws = sorted(w for _, w in pts)
        idle_w = ws[int(0.1 * (len(ws) - 1))]
        last = rows[-1]
        k, chart = st.columns([1, 3], gap="medium")
        with k, st.container(key="card-now"):
            show(f"""<div class="eyebrow">{'Last reading' if replay else 'Power now'}</div>
              <div class="power-now" style="margin:10px 0 6px">{last['watts']:.2f}<small> W</small></div>
              <div class="note">{prov(last['provenance'])}<br>via {esc(last['source'])} · {len(rows)} samples</div>
              <div class="stats" style="grid-template-columns:1fr;margin-top:12px">
                <div class="stat"><div class="k">Average</div><div class="v">{energy.mean_power(pts):.2f}<small> W</small></div></div>
                <div class="stat"><div class="k">Idle floor (10th pct)</div><div class="v">{idle_w:.2f}<small> W</small></div></div>
                <div class="stat"><div class="k">Energy in window</div><div class="v">{energy.integrate_wh(pts) * 1000:.0f}<small> mWh</small></div></div>
              </div>""")
        with chart, st.container(key="card-chart"):
            show('<div class="eyebrow">Laptop power over time</div>')
            st.plotly_chart(power_line(pts, idle_w, height=380), width="stretch", config={"displayModeBar": False})

        left, right = st.columns([3, 2], gap="medium")
        with left, st.container(key="card-apps"):
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
            show('<div class="eyebrow">Who is using the power · average per app</div>')
            if top:
                bar = go.Figure(go.Bar(
                    x=[v for _, v in top], y=[k for k, _ in top], orientation="h",
                    marker={"color": BLUE, "cornerradius": 4}, width=0.6,
                    text=[f"{v:.2f} W" for _, v in top], textposition="outside", cliponaxis=False,
                    textfont={"color": INK2, "size": 11},
                    hovertemplate="%{y}<br><b>%{x:.3f} W</b> average<extra></extra>"))
                bar = style(bar, x_title="W", height=320)
                bar.update_yaxes(showgrid=False)
                bar.update_xaxes(range=[0, max(v for _, v in top) * 1.2])
                st.plotly_chart(bar, width="stretch", config={"displayModeBar": False})
                st.caption(f"Per-app power is {', '.join(sorted(provs))}: CPU power split by each app's CPU share.")
                with st.expander("Table view"):
                    st.dataframe([{"app": k, "avg W": round(v, 3)} for k, v in reversed(top)], hide_index=True)
            else:
                st.caption("No per-app data in this window.")
        with right, st.container(key="card-states"):
            summ = markov.summarize(pts, idle_w)
            share = summ.get("share", {})
            show('<div class="eyebrow">Where the time went · workload states</div>')
            if share:
                sfig = go.Figure()
                for (state, v), color in zip(share.items(), RAMP):
                    sfig.add_bar(x=[v * 100], y=[""], orientation="h", name=state,
                                 marker={"color": color, "line": {"color": SURF, "width": 2}},
                                 hovertemplate=f"{state}<br><b>%{{x:.1f}}%</b> of time<extra></extra>")
                sfig = style(sfig, height=110)
                sfig.update_layout(barmode="stack", legend={"y": -0.35, "yanchor": "top", "traceorder": "normal"},
                                   margin=dict(t=4, b=4))
                sfig.update_xaxes(range=[0, 100], showticklabels=False)
                sfig.update_yaxes(showticklabels=False, showgrid=False)
                st.plotly_chart(sfig, width="stretch", config={"displayModeBar": False})
            show(f"""<div class="stats" style="grid-template-columns:1fr 1fr 1fr">
              <div class="stat"><div class="k">Typical idle stretch</div><div class="v">{summ.get('expected_idle_run_s', 0):.0f}<small> s</small></div></div>
              <div class="stat"><div class="k">Short bursts / hour</div><div class="v">{summ.get('short_bursts_per_hour', 0):.0f}</div></div>
              <div class="stat"><div class="k">Idle within 60 s</div><div class="v">{summ.get('p_idle_within_60s', 0) * 100:.0f}<small>%</small></div></div>
            </div><div class="note">From a Markov chain over 1-second states. Short, frequent bursts are what
            batching removes.</div>""")
            with st.expander("Table view"):
                st.dataframe([{"state": k, "time %": round(v * 100, 1),
                               "mean W": round(summ.get("mean_w", {}).get(k, 0), 2)} for k, v in share.items()],
                             hide_index=True, width="stretch")
    live()


# ================================================================== SYNC
def page_sync():
    @st.fragment(run_every="3s")
    def sync_panel():
        c = conn()
        q = outbox.stats(c)
        online = SyncWorker(log=lambda *_: None).online()
        with st.container(key="cardglow-sync" if online else "card-sync-off"):
            wire = "wire" if online else "wire idle"
            show(f"""<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap">
              <div><div class="eyebrow">Transactional outbox → cloud</div>
              <div class="cloud-big" style="margin:8px 0 4px"><span class="dot {'ok' if online else 'off'}"></span>
                Cloud {'online' if online else 'offline'}</div>
              <div class="note">{'Draining automatically every 3 s.' if online else 'Items wait safely in SQLite and go out automatically on reconnect.'}</div></div>
            </div>
            <div class="flow" style="margin-top:14px">
              <div class="node"><div class="k">{ico("waiting", 14)} Waiting</div><div class="v">{q['pending']}</div></div><div class="{wire}"></div>
              <div class="node"><div class="k">{ico("sending", 14)} Sending</div><div class="v">{q['in_flight']}</div></div><div class="{wire}"></div>
              <div class="node"><div class="k">{ico("delivered", 14)} Delivered</div><div class="v">{q['done']}</div></div>
              <div class="node{' dead' if q['dead'] else ''}"><div class="k">{ico("rejected", 14)} Rejected</div><div class="v">{q['dead']}</div></div>
            </div>""")
            if online:
                try:
                    import urllib.request
                    with urllib.request.urlopen(f"{config.Settings().cloud_url}/stats", timeout=2) as resp:
                        cs = json.loads(resp.read())
                    show(f'<div class="note">Cloud server: {cs["events"]} events · {cs["processed"]} processed · '
                         f'<b>{cs["duplicates_ignored"]} duplicates ignored</b> thanks to idempotency keys</div>')
                except OSError:
                    pass
                try:
                    import urllib.request
                    with urllib.request.urlopen(f"{config.Settings().cloud_url}/chain", timeout=2) as resp:
                        ch = json.loads(resp.read()).get(s.device_id)
                    local = db.verify_chain(c)
                    if ch:
                        same = ch["ok"] and ch["n"] == local["n"] and local["head"].startswith(ch["head"])
                        show(f'<div class="note">Receipt chain checked <b>by the cloud</b>: {ch["n"]} receipts · '
                             f'{"✓ intact" if ch["ok"] else "✗ broken at #" + str(ch["broken_at"])} · head {esc(ch["head"])}'
                             f'{" · matches this laptop ✓" if same else " · laptop has " + str(local["n"]) + " (syncing)"}</div>')
                except OSError:
                    show('<div class="note">Cloud chain check: this cloud server version has no /chain endpoint yet '
                         '(rebuild it to enable).</div>')
        left, right = st.columns([3, 2], gap="medium")
        with left, st.container(key="card-queue"):
            show('<div class="eyebrow">Outbox items (newest first)</div>')
            st.dataframe([{"#": i["id"], "kind": i["kind"], "status": i["status"], "attempts": i["attempts"],
                           "next try in s": max(0, round(i["next_attempt_at"] - time.time(), 1)),
                           "key": i["idem_key"][:8], "error": i["last_error"] or ""} for i in outbox.items(c, limit=15)],
                         hide_index=True, width="stretch", height=300)
        with right, st.container(key="card-log"):
            show('<div class="eyebrow">Sync log · offline → reconnect</div>')
            path = config.data_dir() / "sync.log"
            lines = path.read_text().splitlines()[-14:] if path.exists() else []
            out = []
            for ln in reversed(lines):
                t, _, msg = ln.partition("  ")
                cls = "off" if "unreachable" in msg else ("ok" if "reachable" in msg else "")
                out.append(f'<span class="t">{esc(t)}</span> <span class="{cls}">{esc(msg[:110])}</span>')
            show(f'<div class="log">{"<br>".join(out) or "no sync activity yet"}</div>')

    l, rr = st.columns([5, 1], vertical_alignment="center")
    l.markdown('<div class="note">Every decision, explanation, report and receipt is written to the outbox <b>in the same '
               'transaction</b> as the data, so nothing is lost on a crash or restart. Retries use exponential backoff '
               'with jitter, and the server ignores duplicates.</div>', unsafe_allow_html=True)
    if rr.button("Sync now", width="stretch", type="primary"):
        res = SyncWorker(log=lambda *_: None).tick(conn())
        st.toast(f"Sync: {res}" if res is not None else "Cloud unreachable: items stay queued")
    sync_panel()


# ================================================================== REPORT
def page_report():
    c = C
    last = c.execute("SELECT body, model, grounded, created FROM reports WHERE kind='report' ORDER BY id DESC "
                     "LIMIT 1").fetchone()
    l, m, rr = st.columns([3, 1.2, 1.2], vertical_alignment="center")
    if last:
        l.markdown(f'<div class="note">Latest report: {time.strftime("%d %b %Y, %H:%M", time.localtime(last["created"]))} · '
                   f'written by <b>{esc(last["model"])}</b> · grounding {"passed" if last["grounded"] else "failed"}</div>',
                   unsafe_allow_html=True)
    if m.button("Write new report", icon=":material/edit_note:", type="primary", width="stretch"):
        from joule.slm.report import build_report
        with st.spinner("The local AI is writing the report, offline…"):
            out = build_report(c)
        st.toast(f"Saved {Path(out['path']).name} · grounded: {out['grounded']}")
        st.rerun()
    if last:
        rr.download_button("Download .md", icon=":material/download:", data=last["body"], file_name="energy-report.md", width="stretch")
        with st.container(key="card-report"):
            st.markdown(last["body"])
    else:
        st.info("No report yet. Press **Write new report**.")


{"Overview": page_overview, "Receipts": page_receipts, "Certify": page_certify, "Advice": page_advice, "What-if": page_whatif, "Live": page_live,
 "Sync": page_sync, "Report": page_report}[page]()
