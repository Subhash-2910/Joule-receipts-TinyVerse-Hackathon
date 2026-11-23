# Joule Receipts

**An offline-first energy copilot that measures your computer's workloads, explains them with a local small
language model, and proves every saving it recommends with a before/after "receipt".**

Problem statement: **PS 04 — Energy-Aware AI: Offline-First Copilot** (Sustainable Computing · Edge AI · Applied
Analytics; core constraint: an open local SLM with fewer than 4B parameters).

| | |
|---|---|
| Member | [Your Name] · [USN] · [Branch] |
| Main SLM | **Qwen2.5-1.5B-Instruct** (1.54B parameters, Apache-2.0) via Ollama, 4-bit, fully offline after download |
| Comparison SLMs | Qwen2.5-0.5B-Instruct (0.49B) · GPT-2 124M + LoRA energy-report writer (my own, from `student-feedback-summarizer`) |
| Hardware used | Apple M3, 16 GB RAM, macOS (MacBook, battery-powered) |
| Core code | Python standard library only (sqlite3, urllib, http.server, threading) — runs with no installs |

---

## 1. The idea in one paragraph

Dashboards show CPU % and vague "energy impact" scores, but never say **what to change** or **whether the change
really saved energy**. Joule Receipts closes that loop: it **measures** power (Apple's own power sensors), **predicts**
what a change would save, lets a **local SLM explain** the numbers in plain language (a checker rejects any number the
SLM invents), then **runs a reproducible A/B experiment** and prints a **receipt**: predicted saving vs measured
saving, in Wh, ₹ and gCO₂e. Every reading, recommendation, decision and report is stored in a local SQLite database,
and a durable **outbox queue** syncs them to a server when the network returns — surviving restarts, retrying safely
and never processing the same item twice.

```
Measure ──► Predict ──► Explain (local SLM) ──► Decide ──► Prove (A/B ×5) ──► Receipt ──► Outbox ──► Sync
   ▲                                                                              │
   └──────────────────── measured receipts recalibrate the predictor ─────────────┘
```

## 2. How each PS 04 requirement is met

| PS 04 requirement | Where it is met |
|---|---|
| Local SLM < 4B, offline after setup | `joule/slm/` — Ollama on `localhost`, Qwen2.5-1.5B (1.54B). No cloud API anywhere. |
| Energy visibility: method, sampling interval, hardware, limitations | `joule/sensors/` + [§4 Measurement](#4-measurement-method) — every value carries a **provenance tag** |
| Predict, recommend & explain | `joule/analytics/` (power model, Markov idle forecast, Apriori co-activity) → `joule/slm/explain.py` |
| Readable report via the SLM | `joule/slm/report.py` → Markdown report in `data/reports/` |
| Offline persistence | `joule/db.py` — SQLite (WAL, `synchronous=FULL`): readings, predictions, reports, decisions |
| Persistent queue, restarts, retries, no duplicates, auto sync | `joule/sync/outbox.py`, `worker.py`, `server.py` — see [§6](#6-offline-first-sync-design) |
| Prove the savings: baseline vs optimized, Wh / ₹ / CO₂e | `joule/experiment.py`, `joule/workloads.py`, `joule/energy.py` — see [§5](#5-proving-the-savings) |
| Measured vs estimated clearly distinguished | `joule/provenance.py` — `MEASURED`, `ATTRIBUTED`, `ESTIMATED`, `SIMULATED` on every number |

## 3. Architecture

```
┌─────────────────────────── on the laptop (works with no network) ───────────────────────────┐
│                                                                                              │
│  Sensors ─► Collector ─► SQLite (WAL) ◄─► Analytics ─► Facts JSON ─► Local SLM ─► Grounding  │
│  powermetrics   1 s       samples,         power model   Wh · ₹ ·      Qwen2.5     check:     │
│  battery        samples   experiments,     Markov        gCO₂e,        1.5B        numbers    │
│  CPU estimate             recs, reports,   Apriori       provenance    (Ollama)    must match │
│  simulated                decisions,                                               facts     │
│                           OUTBOX ──────────────────────────────────────────┐                  │
│                              ▲                                              │                  │
│  Dashboard / CLI ─► decision │   Experiment runner (A/B ×5) ─► receipt ─────┘                  │
└──────────────────────────────┼──────────────────────────────────────────────┼────────────────┘
                               │                                Sync worker: lease, retry,
                               │                                backoff + jitter, Idempotency-Key
                               ▼                                              ▼
                        (survives restarts)                   ┌───────── Docker ─────────┐
                                                              │ Cloud sync server        │
                                                              │ dedupes on the key,      │
                                                              │ processes exactly once   │
                                                              └──────────────────────────┘
```

**Why the SLM never computes numbers.** Small models make arithmetic mistakes. The deterministic engine computes every
number; the SLM only turns the facts into sentences. `joule/slm/grounding.py` extracts every number from the SLM's
text and rejects the explanation if a number is not in the facts (then retries once with feedback, and finally falls
back to a deterministic template, clearly labelled).

### Code map

| Path | What it does |
|---|---|
| `joule/config.py` | Paths, settings, and the **assumptions** (tariff, grid emission factor) with their sources |
| `joule/provenance.py` | `MEASURED` / `ATTRIBUTED` / `ESTIMATED` / `SIMULATED`, and how they combine (weakest wins) |
| `joule/energy.py` | Integration (W → Wh), net energy, cost, CO₂e, run statistics, saving and significance |
| `joule/db.py` | SQLite schema and data access; decisions and their outbox items are written in **one transaction** |
| `joule/sensors/` | `powermetrics.py` (sudo), `battery.py` (no sudo), `cpu_estimate.py`, `simulated.py`, `procs.py`, `auto.py` |
| `joule/collector.py` | Samples power + per-process CPU every interval and stores them |
| `joule/workloads.py` | Reproducible baseline/optimized workloads that complete **identical work** (checked by checksum) |
| `joule/experiment.py` | Idle baseline, interleaved A/B runs ×N, statistics, receipts |
| `joule/analytics/` | `power_model.py` (least squares + calibration), `markov.py` (idle forecast), `apriori.py` (co-active processes), `knowledge.py` (process → app, feasible advice), `recommend.py` |
| `joule/slm/` | `client.py` (Ollama / OpenAI-compatible), `grounding.py`, `explain.py`, `report.py` |
| `joule/sync/` | `outbox.py` (durable queue), `worker.py` (auto sync on reconnect), `server.py` (cloud stand-in, dedupe) |
| `joule/cli.py` | `python -m joule ...` — every feature from the command line |
| `tests/` | Standard-library `unittest` tests; run offline in seconds |

## 4. Measurement method

| Source | Provenance | What it measures | Interval | Needs | Limitations |
|---|---|---|---|---|---|
| `powermetrics` (Apple) | **MEASURED** | CPU, GPU and ANE power of the M3 chip (mW) | 1 s | `sudo` | SoC only: excludes display, SSD, Wi-Fi. Apple does not publish its accuracy. |
| Battery gauge (`ioreg AppleSmartBattery`) | **MEASURED** | Whole-laptop DC power = voltage × current | 1 s read; **gauge refreshes every ~12–33 s** (observed on this M3) | Running on battery | Only valid when unplugged; includes the display; lags load changes. Experiments with it use ≥ 90 s windows (workload repeated, energy reported per repetition) |
| CPU-utilisation model | **ESTIMATED** | `P = P_idle + (P_max − P_idle) × CPU utilisation` | 1 s | Nothing | Model constants are assumptions until calibrated against a measured source (`joule calibrate`) |
| Per-process share | **ATTRIBUTED** (from powermetrics CPU power) or **ESTIMATED** (from the CPU model) | Process W = CPU power × (process CPU % ÷ total CPU %); helper processes grouped into their app | 1 s | Nothing | CPU share ≠ energy share (GPU, I/O ignored); `ps` %CPU is a decaying average; the collector excludes itself |
| Simulated sensor | **SIMULATED** | `P = P_idle + W_per_core × CPU-seconds used by the workload ÷ Δt` + seeded noise | 1 s | Nothing | For CI, Docker and judges without a Mac; never mixed with measured results |

`auto` picks the best available source in this order: powermetrics → battery → CPU estimate. Every stored sample
records its source and provenance, and any number computed from several samples takes the **weakest** provenance.

## 5. Proving the savings

**Formulas** (shown in the dashboard and every report):

```
E (Wh)      = Σ ½ (Pᵢ + Pᵢ₊₁) · (tᵢ₊₁ − tᵢ) ÷ 3600          trapezoidal integration of power samples
Net E (Wh)  = E_run − P_idle × t_run ÷ 3600                  only the workload's own energy
Cost (₹)    = E (kWh) × tariff (₹/kWh)
CO₂e (g)    = E (kWh) × grid emission factor (kg/kWh) × 1000
Saving      = median(baseline) − median(optimized);  significant if exact Mann–Whitney p < 0.05
```

**Protocol.** Measure idle power first → run baseline and optimized **interleaved** (B, O, B, O, …) to cancel
thermal and battery drift → N = 5 repeats each → report medians (and mean ± standard deviation) → the receipt compares the
predicted saving with the measured one.

| Scenario | Baseline | Optimized | Same work? |
|---|---|---|---|
| `idle` — background activity | Folder-sync poller re-scans and hashes files every 100 ms | Same poller every 5 s (change-driven) | Same detection result over the window |
| `batching` — execution timing | 200 jobs, one process launch per job | Same 200 jobs in 10 processes of 20 | Identical output checksum |
| `inference` — model settings (needs Ollama) | Larger model / longer output | Smaller model / capped tokens | Quality scored by the grounding check |

**Assumptions** (editable in `joule/config.py` or via environment variables):

| Assumption | Default | Source / status |
|---|---|---|
| Electricity tariff | ₹8.00 / kWh (`JOULE_TARIFF`) | **Placeholder** — replace with the rate on your electricity bill |
| Grid emission factor | 0.716 kg CO₂ / kWh (`JOULE_GRID_FACTOR`) | Approximate weighted average from the CEA CO₂ Baseline Database for the Indian power sector — **verify against the latest version before submission** |

### Findings so far (real runs on this Mac, 23 Nov 2026)

* Battery gauge readings work without sudo (e.g. 3.17 W at idle, MEASURED), but the gauge refreshes only every
  ~12–33 s and lags load changes by up to ~60 s (a CPU-heavy test run showed as 24.4 W for a minute *after* it ended).
  → 1 s experiments need `powermetrics`; the battery is used for long windows only.
* "Quit WindowServer" is not feasible advice: system processes now get specific actions (`knowledge.py`), and helper
  processes are grouped into their app (Chrome, VS Code).
* The first SLM prompt (full nested facts JSON) made Qwen2.5-1.5B invent numbers ("73.3 % of idle power", "a 100-watt
  light bulb"); the grounding check rejected both drafts and the labelled template was used. A short flat fact sheet
  with one worked example fixed it: 3 of 3 explanations grounded on the first attempt.
* Batching (SIMULATED, 5 runs each): 3.43 ± 0.06 → 0.254 ± 0.009 mWh per 200 jobs, **92.6 % saved**, significant;
  the pilot predicted 3.37 mWh vs 3.18 mWh measured (6.1 % error).
* **Headline result — batching, MEASURED (powermetrics, 1 s, Apple M3, 5 interleaved runs each):**
  200 separate process launches 3.49 mWh (mean 3.51 ± 0.105) → same 200 jobs in 10 launches 0.207 mWh
  (0.221 ± 0.028): **94.1 % less energy, exact Mann–Whitney p = 0.0079** (the strongest possible with 5 vs 5).
  The pilot predicted 3.29 mWh vs 3.28 mWh measured: **0.3 % prediction error**. Same output checksum in every run.
* **Idle polling, MEASURED (powermetrics, 10 interleaved runs each, quiet laptop):** checking 200 files every
  0.1 s cost a median **2.09 mWh per minute**; every 2 s cost **0.616 mWh** (means 2.44 ± 1.02 → 0.691 ± 0.355):
  **70.6 % less energy, exact Mann–Whitney p = 1.1 × 10⁻⁵** — all 10 optimized runs used less than all 10 baseline
  runs. Trade-off: a file change is noticed after ~0.4 s instead of ~0.07 s (up to 2 s). Pilot predicted 1.94 mWh vs
  1.48 mWh measured (32 % error).
  * An earlier 8-run attempt with other apps open was **not significant** (p = 0.33): two runs were hit by ~1 W
    background bursts. The app refused to claim a saving until the quiet rerun proved it.
* **First MEASURED runs (powermetrics, 1 s) exposed three method flaws, now fixed:**
  1. Batching showed "100.22 % saved": each optimized run (0.22 s) was shorter than one 1 s powermetrics window, so
     the reading was mostly idle time after the run. → with powermetrics, short workloads now repeat until each run
     lasts ≥ 15 s, and energy is reported per repetition.
  2. The idle baseline (1.94 W ± 1.3) was taken while the machine was still busy, giving negative net energies. →
     5 s settle period, 20 s idle window, **median** idle power; fixed-time scenarios compare total energy (equal
     durations need no idle subtraction).
  3. One disturbed run (1.53 W vs ~0.3 W) dominated the mean. → the headline saving is now the difference of
     **medians**, tested with an **exact Mann–Whitney** rank test (p < 0.05); means and the Welch band are still shown.
* **Real finding:** on the M3 the 100 ms folder poller costs only ~0.1 W more than polling every 2 s (Apple's
  efficiency cores make light polling cheap). Measured: median 5.0 → 4.5 mWh per minute, p = 0.74, not significant.
  The SIMULATED model had claimed 94 % — its W-per-core constant is far too high for this chip. Measured beats
  simulated, and the receipt says so.
* Sync with 50 % of server responses deliberately dropped: 2 decisions delivered, 2 retries deduplicated, each
  processed exactly once.

## 6. Offline-first sync design

* **Outbox table** in the same SQLite file. A user decision and its outbox item are inserted in **one transaction**,
  so a crash can never leave one without the other.
* Each item has a UUID **idempotency key** (unique in the table, so the same item cannot be queued twice locally).
* States: `pending → in_flight → done`, or back to `pending` with `attempts + 1` and
  `next_attempt_at = now + min(2^attempts × 2 s, 5 min) × jitter(0.5–1.0)`; `dead` after a permanent rejection (4xx).
* **Leases**: an item claimed by a worker that crashes is reclaimed automatically when its lease expires.
* **Auto sync**: the worker checks `GET /health` every few seconds; when the server becomes reachable it drains the queue.
* **Server dedupe**: the server stores the key as a primary key. A repeat returns `duplicate` and is not processed again,
  so a lost response + retry is harmless. Fault injection (`JOULE_CLOUD_FAIL_RATE`, `JOULE_CLOUD_DROP_RESPONSE_RATE`) lets
  the demo prove it.
* The server runs in **Docker** so the demo can do `docker stop` (offline) and `docker start` (reconnect).

## 7. Run it

**One-time setup** (≈3 GB):

```bash
brew install ollama && ollama serve &          # local SLM server (localhost:11434)
ollama pull qwen2.5:1.5b && ollama pull qwen2.5:0.5b
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python streamlit plotly psutil
docker compose up -d --build cloud             # cloud sync server on :8787
make dashboard                                 # http://localhost:8501
```

Core features need only Python 3.11+ (no packages):

```bash
cd joule-receipts
python3 -m joule init                      # create data/joule.db
python3 -m joule sense --n 3               # show readings from the best available sensor
python3 -m joule collect --seconds 60      # store 1 s samples (+ per-process attribution)
python3 -m joule experiment batching --repeats 5
python3 -m joule recommend                 # predictions + recommendations from stored data
python3 -m joule explain 1                 # SLM explanation (template fallback if Ollama is off)
python3 -m joule decide 1 accept           # decision → outbox (atomic)
python3 -m joule cloud --port 8787         # cloud stand-in (or the Docker image)
python3 -m joule sync --watch              # auto-sync when the server is reachable
python3 -m unittest discover -s tests      # all tests, offline
```

Measured power on Apple silicon (asks for your password — run it yourself):

```bash
sudo python3 -m joule collect --source powermetrics --seconds 300
```

## 8. Build status

| # | Milestone | Status |
|---|---|---|
| 1 | Project document, scaffold, SQLite schema, provenance | ✅ done |
| 2 | Energy maths (Wh, net, ₹, CO₂e, statistics, significance) | ✅ done |
| 3 | Sensors: battery, powermetrics parser, CPU estimate, per-process attribution, simulated | ✅ done (powermetrics **live run needs sudo**) |
| 4 | Collector + workload harness + A/B experiment runner + receipts | ✅ done |
| 5 | Analytics: power model, Markov idle forecast, Apriori co-activity, recommendations | ✅ done |
| 6 | SLM client, grounding checker, explanations, Markdown report | ✅ done — Ollama + qwen2.5:1.5b / 0.5b installed, explanations grounded |
| 7 | Outbox, sync worker, cloud server with dedupe and fault injection | ✅ done |
| 8 | Tests (standard-library unittest) — 38 tests, ~10 s, offline | ✅ done |
| 9 | Dockerfile + compose for the cloud server | ✅ built (203 MB) and tested: stop → queue → start → auto-drain |
| 10 | Streamlit dashboard (Live · Recommendations · Receipts · Sync · Report) | ✅ done |
| 11 | GPT-2 + LoRA energy-report writer (reuse of my LoRA code) | ⏳ needs PyTorch + transformers + GPT-2 download |
| 12 | Measured evidence: real A/B runs, results/ tables, slides updated | ⏳ after the above |

### Still to do

1. **Measured 1 s evidence** — run in your own terminal (you type the password):
   `sudo python3 -m joule experiment batching --source powermetrics --repeats 5` (and `idle`)
2. Inference-settings scenario on the real SLMs: `python3 -m joule experiment inference --repeats 3`
3. Your electricity tariff (₹/kWh) and name / USN / branch; verify the CEA grid factor
4. Optional: GPT-2 + LoRA report writer (PyTorch, ~2 GB)

## 9. Reuse from my learning projects

| From | Reused here |
|---|---|
| `retail-basket-prediction-analyzer` (`app/llm.py`) | OpenAI-compatible chat client pointing at Ollama on localhost → `joule/slm/client.py` |
| `retail-basket-prediction-analyzer`, `learning-path-predictor` | Apriori frequent itemsets → which processes are co-active in high-power minutes |
| `learning-path-predictor` | Markov-chain baseline → next workload state / idle-window forecast |
| `customer-feedback-analyzer` | Confidence + "flag for review" → low-confidence recommendations need explicit approval |
| `student-feedback-summarizer` | From-scratch LoRA + format/grounding metrics → GPT-2 energy-report writer (milestone 11) |
| `adventure-story-weaver` | Sampling controls (temperature, length) → inference-settings scenario |
| `support-response-generator` | Anonymise before storing/sending → process names hashed before sync |
| All six | Baselines vs model, `make all`, `results/`, tests + CI, Docker |

Third-party credits: see [CREDITS.md](CREDITS.md).
