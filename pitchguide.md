# Joule Receipts: pitch and viva guide

Your cheat sheet for the presentation and the technical questions (30 of 60 marks).
Read Part 1 for the pitch, Part 2 for the demo, Part 3 for why you win, and **Part 4 + Part 5 for the technical
viva**. Part 6 is the numbers to memorise.

---

## Part 1 · The pitch

### The one-liner (memorise this)

> "Joule Receipts is an offline energy copilot that doesn't just guess what saves energy. It **proves** it, with a
> receipt: for your laptop, for any developer's code, and even for its own AI."

### 30-second version (elevator)

> "Computers waste energy in background apps and oversized AI, and today's tools only show vague scores. Joule
> Receipts measures real power with the Mac's own sensor, a small local AI explains what to change, and then the app
> **proves** the saving: it runs the old way and the new way five times each, alternating, and gives a receipt with a
> statistical test. We have four proven results: −71%, −94%, −56% for its own AI, and −99% for a developer's program.
> Everything works offline and syncs later with no duplicates."

### 2-minute version (opening of the presentation)

1. **Problem (20 s):** "Activity Monitor shows 'energy impact', not watts or rupees. Nobody tells you what to change,
   and nobody checks if the change worked. Cloud AI assistants need internet and can invent numbers."
2. **What we built (30 s):** "An offline copilot. It **measures** every app, **finds** waste, a **local AI explains**
   it, and every saving is **proven** by an A/B experiment, a receipt, and an A–G energy label."
3. **Proof (30 s):** "Four savings, all measured and statistically significant: idle polling −71%, batching −94%, our
   own AI −56%, and a developer's code −99%. Every receipt is locked in a hash chain the cloud verifies."
4. **Why it's different (30 s):** "Startups solve one piece each. We're the only one that measures, explains, proves,
   certifies code, and meters its own AI, offline."
5. **Close (10 s):** "Measure, explain, prove, certify, sync. All offline."

### How to sound confident

* Say the **trust label** out loud every time: "this number is MEASURED", "this one is ESTIMATED".
* Tell the **honesty story**: "Our first idle test wasn't significant, p = 0.33, because other apps were busy. The
  app refused to claim it until a clean rerun proved it." Judges love this.
* When you don't know something: "We didn't measure that, so we don't claim it. Here's what we did measure…"

---

## Part 2 · The demo (about 5 minutes)

**Before:** start Ollama, `docker compose start cloud`, the dashboard; set the **Goal to Balanced**; close heavy
apps; keep one Terminal window visible. Have the backup video ready.

| Step | Click | Say |
|---|---|---|
| 1 | **Overview** | "Three proofs, all MEASURED: −71, −94, −56. The pipeline on the right shows each stage live." |
| 2 | **Receipts → Self-measuring AI** | "Always 1.5B: 20.4 mWh. Small model first: 8.91 mWh. Every blue dot is below every orange dot: 25 out of 25 pairs, p = 0.008. Grade C, certified." |
| 3 | **Try to fake a number** | "If anyone edits a result, the hash chain breaks. The cloud keeps its own copy, so a local edit can't hide." |
| 4 | **Certify** → receipt #9 → **Certificate (HTML)** | "Any developer gives the old and new command. We check the output is identical, measure both, and certify: v2 uses 1% of v1's energy, grade A." |
| 5 | **Advice** → **Explain** | "The local AI wrote this offline. Every number is checked against the facts. And this chip shows the answer itself cost about 7 joules." |
| 6 | **What-if** → drag the slider | "The curve passes through the two settings we actually measured. Between them it's interpolation; outside, it warns us." |
| 7 | Terminal: `docker compose stop cloud` → **Accept** a tip → **Sync** | "Offline. The decision is safe in the local database: Waiting 1." |
| 8 | Terminal: `docker compose start cloud` | "Back online: delivered automatically, zero duplicates, and the cloud re-verified all receipts." |

If something fails live, say "this is exactly why we record receipts", play the video, and continue.

---

## Part 3 · Why it stands out

| Everyone else | Joule Receipts |
|---|---|
| Shows numbers | **Proves** savings with A/B experiments and a statistical test |
| Mixes guesses and measurements | **Trust label on every number**: MEASURED / ATTRIBUTED / ESTIMATED / SIMULATED |
| AI can invent numbers | **AI can't**: a fact-checker rejects any number not in the computed facts |
| AI tools ignore their own energy | **AI meters itself**; small model first cut its energy by **56%** (measured) |
| Results can be edited | **SHA-256 hash chain**, re-verified by the cloud |
| Tools measure energy | **Certifies developers' code** with an A–G label (like an appliance sticker) |
| Needs internet | **100% offline**; outbox syncs later with zero duplicates |

**Competitors in one breath:** "Cactus and RunAnywhere run small AI on-device but don't measure its energy. DeepAware
saves data-centre energy, but its 15% is simulated. CodeCarbon and CarbonLint estimate. Unravel and SINAI count
carbon from spending data. Nobody proves a saving on the device."

---

## Part 4 · Technical knowledge (the 30 marks)

Each topic: **the simple answer** (say this first), then **if they dig deeper**.

### 4.1 Energy basics

* **Power vs energy:** power (watts, W) is *how fast* energy is used; energy (watt-hours, Wh) is power × time.
  1 Wh = 3600 J; 1 mWh = 3.6 J.
* **How we get energy from readings:** we take power readings over time and add up the area under the curve
  (**trapezoidal integration**): each pair of readings forms a trapezoid, area = average power × time gap.
* **Net energy:** energy of the run minus what the laptop would use anyway at idle:
  `Net = E_run − P_idle × t`. This isolates the workload's own energy.
* **Idle power = median** of idle readings, after a 5 s settle, so one spike doesn't distort it.
* **₹ and CO₂:** `₹ = kWh × ₹5.80` (BESCOM Domestic LT-1, FY 2026–27, energy charge only) and
  `CO₂e (g) = kWh × 0.716 kg/kWh × 1000` (CEA grid factor, approximate).

### 4.2 Measurement

* **powermetrics:** Apple's built-in tool; reports power of the chip (CPU + GPU + Neural Engine) in 1-second
  windows. Needs `sudo`. → **MEASURED**.
  * *Limits:* chip only, not the screen, SSD or Wi-Fi. Readings arrive ~1.4 s apart because per-app tracking adds
    time. Short workloads are repeated until a run lasts ≥ 15 s.
* **Battery gauge:** voltage × current = whole-laptop power, no sudo, but updates only every ~12–33 s, so only for
  long windows (≥ 90 s).
* **CPU estimate:** `P = P_idle + (P_max − P_idle) × CPU%`, defaults 3 W and 22 W. → **ESTIMATED**. It can't see the
  GPU, so it under-counts AI work. Can be calibrated against powermetrics with least squares (`joule calibrate`).
* **Per-app power:** CPU power × the app's share of CPU time → **ATTRIBUTED**. Helpers are grouped into their app
  (Chrome Helper → Chrome).
* **Provenance rule:** a combined number gets the **weakest** label (MEASURED > ATTRIBUTED > ESTIMATED > SIMULATED).
  Anything projected into the future (Wh/day, ₹/month) is ESTIMATED.

### 4.3 Experiment design and statistics (most likely to be asked)

* **A/B experiment:** run the baseline (old way) and the optimized way, same work, measured.
* **Interleaving:** runs alternate (B, O, then O, B, …) so slow drift (temperature, battery level, other apps)
  affects both sides equally. Your AI test showed drift: power fell from 13 W to 4–5 W over the test, and the small
  model still won every round.
* **Why the median, not the mean:** one disturbed run (another app waking up) can drag the mean a lot; the median
  ignores it.
* **Mann–Whitney U test:** ranks all runs together and asks "are the optimized runs consistently lower?". No
  assumption of a bell curve. We compute it **exactly** by checking every possible split of the runs.
* **p-value:** the probability of seeing a difference this big **if there were no real difference**. Below 0.05 =
  significant.
* **Why p = 0.0079 keeps appearing:** with 5 vs 5 runs there are C(10,5) = 252 ways to split the ranks; the most
  extreme split in either direction is 2 of 252 = **0.0079**. That's the strongest result possible with 5 vs 5; it
  means **every** optimized run beat **every** baseline run. With 10 vs 10, the best possible is 2/184,756 ≈ 1.1 × 10⁻⁵
  (your idle result).
* **Pilot prediction:** a small run (20–34% size) first, scaled up, to **predict** the saving; the receipt shows
  predicted vs measured (batching: within 0.3%; AI: 84% off because the models load into memory on the first run).
* **Same work check:** output checksums must match (identical stdout for certify), otherwise "more efficient" might
  just mean "did less".

### 4.4 The local AI

* **Why a small local model:** PS 04 needs < 4B parameters and offline. Local = private (data never leaves) and works
  with no internet. Smaller = less energy.
* **The models:** Qwen2.5-0.5B (494M parameters, 398 MB) and Qwen2.5-1.5B (1.5B, 986 MB), Apache-2.0 open licence.
* **Ollama:** a local server (`localhost:11434`) that runs the models on the Mac's GPU through Metal; we call its
  HTTP API, which also returns token counts and timings.
* **Quantization:** weights stored in **4 bits (Q4_K_M, GGUF format)** instead of 16, so the model is ~4× smaller
  and faster with little quality loss. *K_M* = a mixed 4-bit scheme that keeps some important layers at higher
  precision.
* **Tokens:** pieces of words the model reads and writes; max 180 output tokens per explanation.
* **Temperature:** randomness of the model's choices; we use low values (0.1, rising on retries) for consistent,
  factual text.
* **Hallucination:** small models sometimes invent numbers ("a 100-watt light bulb"). That's why…
* **…the AI never computes numbers.** The analytics compute every number deterministically; the AI only rewrites a
  short fact sheet into plain English.
* **Grounding check:** extract every number from the AI's text; each must match a fact (same value at the text's
  rounding, or within 1%). Numbers glued to letters (CO2, qwen2.5) and list markers don't count; 0, 1, 100 are always
  allowed. One invented number = rejected.
* **Cascade:** 0.5B writes first → if the check passes, done → else 1.5B → else a fixed template. In our test the
  0.5B passed 6/6, so 1.5B was never needed, saving 56% energy.
* **AI energy meter:** a background thread samples power while the model writes; energy = mean power × time
  (e.g. "⚡ 6.8 J").

### 4.5 Analytics

* **Markov chain:** each second is a state (idle < 0.5 W above idle, light < 2, busy < 6, heavy ≥ 6). We count
  transitions between states to get: how long idle stretches last, the chance of being idle within 60 s, and **short
  bursts per hour** (wake-ups ≤ 10 s). ≥ 30 bursts/hour → "batch your small jobs" advice. Your session: ~437/hour.
* **Apriori:** finds sets of apps active together in high-power seconds. *Support* = how often they appear together;
  *lift* = how much more often than by chance. Rule: support ≥ 30% and lift ≥ 1.3.
* **Background hogs:** apps averaging ≥ 0.15 W while the laptop is idle/light; top 3; confidence < 0.6 → "needs
  review".
* **Anomaly alerts:** an app using ≥ 3× its usual power (Balanced goal) and ≥ 0.3 W extra in the last 60 s, compared
  only with readings from the same sensor.
* **What-if:** polling energy `E(x) = F + k/x`, batching `E(b) = W + L × ⌈jobs/b⌉`, fitted **exactly through the two
  measured points** of a receipt. Between them = interpolation; outside = flagged extrapolation.

### 4.6 Storage

* **SQLite:** a database in one file, no server; perfect for offline.
* **WAL (write-ahead log):** changes are written to a log first, so the dashboard can read while the collector
  writes, and a crash can't corrupt the database.
* **`synchronous=FULL`:** every committed transaction is flushed to disk; survives power loss.
* **Transaction (ACID):** a group of writes that happen all-or-nothing. We save the data **and** its outbox item in
  one transaction.

### 4.7 Offline-first sync (a PS 04 must-have)

* **Transactional outbox pattern:** we never call the cloud directly. Each event goes into an `outbox` table in the
  same transaction as the data; a worker sends it later.
* **Idempotency key:** every item has a unique ID; the server stores it as a primary key, so if the same item arrives
  twice (lost reply + retry), the second is ignored → processed **exactly once** in effect (at-least-once delivery +
  dedupe).
* **Retries with exponential backoff and jitter:** wait 2 s, 4 s, 8 s … up to 5 min, × random 0.5–1. Prevents
  hammering a recovering server, and many clients don't retry at the same instant.
* **Leases:** a claimed item is "in flight" for 30 s; if the worker crashes, the lease expires and the item is sent
  again.
* **Survives restarts:** everything is in SQLite on disk, so a restart just picks up the queue.
* **Auto-sync:** the worker checks `/health` every 3 s and drains the queue when the cloud answers.
* **Docker** plays "the cloud": stop it = offline, start it = reconnect. Fault injection can make it fail or drop
  replies on purpose to prove the dedupe.

### 4.8 Integrity and certification

* **SHA-256:** a hash function: any input → a fixed 64-character fingerprint; change one character and the
  fingerprint changes completely; you can't reverse it or find a different input with the same hash.
* **Hash chain:** each receipt's hash includes the previous receipt's hash, its id, time and contents. Edit any old
  receipt → its hash changes → every later link breaks.
* **Canonical JSON:** keys sorted so the same receipt always produces the same bytes (and the same hash).
* **"Is this a blockchain?"** No. It's the same tamper-evidence idea without mining or consensus; a second party (the
  cloud) independently recomputes the chain, which is enough for our trust model.
* **Energy label A–G:** optimized ÷ baseline energy: A ≤ 25%, B ≤ 40%, C ≤ 55%, D ≤ 70%, E ≤ 85%, F ≤ 100%,
  G > 100%.
* **CERTIFIED only if all five hold:** MEASURED · exact test available · p < 0.05 · same work · chain intact (and
  energies above the noise floor). Otherwise PROVISIONAL, with the reason printed.
* **Certify your code:** both versions must print identical output; fast programs repeat until each run lasts ≥ 5 s
  (≥ 15 s with powermetrics), energy divided per run. Prime counter v2 ran ~700 times per window.

### 4.9 Tech stack: one line each

| Tech | Why |
|---|---|
| Python 3.12 (stdlib core) | one language; core needs no installs |
| Ollama + Qwen2.5 0.5B/1.5B | local, < 4B, open licence |
| powermetrics · battery · psutil | real watts without extra hardware |
| SQLite WAL | crash-safe offline storage |
| Outbox + idempotency keys | no lost or duplicate syncs |
| SHA-256 chain | tamper-evident receipts |
| Streamlit + Plotly | dashboard in Python, interactive charts |
| Docker Compose | the cloud server; stop/start = offline demo |
| unittest + GitHub Actions | 57 tests on Ubuntu and macOS on every push |

Full details: `joule-receipts/docs/TECHNOLOGY.md` and `docs/CERTIFICATION_AND_RULES.md`.

---

## Part 5 · Likely questions with model answers

**Q: Is your energy data real?**
A: "Yes, MEASURED with Apple's powermetrics on my M3, in 1-second windows. Anything not measured is labelled
ESTIMATED or SIMULATED, and the app never mixes them."

**Q: Why should I trust a 56% saving from only 5 runs?**
A: "Because every one of the 5 small-model runs used less energy than every one of the 5 big-model runs, 25 out of 25
pairs. The exact Mann–Whitney p-value is 0.008, the strongest possible with 5 vs 5. And the runs alternated, so drift
hit both sides equally."

**Q: The ₹ savings are tiny. Why does it matter?**
A: "Per laptop, yes: the Chrome tip is about ₹0.34 a month at BESCOM rates. The value is the method: every claim is
proven. Percentages carry over: a 56% cheaper AI answer matters at data-centre scale, and the same savings multiply
across a lab of machines."

**Q: What stops the AI from making up numbers?**
A: "The AI never computes numbers. It only rewrites computed facts, and a checker rejects the text if any number
isn't in the facts. Then it tries the bigger model, then a fixed template."

**Q: Why not always use the 0.5B model?**
A: "On these prompts it passed every check, so it was used every time. The 1.5B is the safety net for harder facts,
and the fact-checker decides automatically. The Goal switch can force 0.5B-only or 1.5B-only."

**Q: What happens if the app crashes mid-sync?**
A: "The item stays in the SQLite outbox. Its 30 s lease expires, it's sent again, and the server ignores the duplicate
using the idempotency key. Nothing lost, nothing doubled."

**Q: How is "same work" proven when certifying code?**
A: "Both versions must print byte-identical output: we compare SHA-256 hashes of stdout. If they differ, we refuse,
unless the developer overrides, and then the label can never be certified."

**Q: What are the limitations?**
A: "powermetrics measures the chip only, not the screen; it needs sudo; it's Mac-only today, though tests run on
Ubuntu and macOS. The battery gauge is slow. Per-app power is CPU-share-based, so GPU-heavy apps are under-attributed.
The AI test used 6 easy prompts, so the step-up to 1.5B wasn't triggered."

**Q: How does it scale?**
A: "Each laptop is independent and offline; the cloud only collects receipts and dedupes by key, so adding devices
just adds rows. Next is a lab fleet view and Linux/Windows sensors (Intel RAPL)."

**Q: What's new compared with CodeCarbon or Green Metrics Tool?**
A: "They measure or estimate. We close the loop: recommend, prove with statistics, certify with a tamper-evident
label, and do it offline with a local AI that measures itself."

**Q: Why SQLite and not a server database?**
A: "Offline-first: no server to run, one file, crash-safe with WAL and full sync, and transactions let us save data
and its outbox item together."

**Q: What is the 0.716 and the ₹5.80?**
A: "0.716 kg CO₂ per kWh is the approximate Indian grid average from the CEA baseline database; ₹5.80/kWh is the
BESCOM Domestic LT-1 energy charge for FY 2026–27. Both are stored on every receipt so the calculation is
reproducible."

**Q: Did you use AI to build it?**
A: "Yes, an AI coding assistant helped, and that's stated in CREDITS.md. I reviewed, ran and tested everything: 57
tests pass on Ubuntu and macOS, and all four results are real measurements from my laptop."

---

## Part 6 · Numbers to memorise

| What | Number |
|---|---|
| Idle polling (0.1 s → 2 s) | **2.09 → 0.62 mWh/min, −71%**, 10 + 10 runs, p ≈ 1.1 × 10⁻⁵, label **B** |
| Batching (200 → 10 launches) | **3.49 → 0.21 mWh, −94%**, p = 0.008, pilot within **0.3%**, label **A** |
| Own AI (1.5B → 0.5B first) | **20.4 → 8.91 mWh, −56%**, p = 0.008, 25/25 pairs, 6/6 fact-checked, label **C** |
| Your code (prime counter v1 → v2) | **3.12 → 0.02 mWh/run, −99.4%**, p = 0.008, label **A** |
| 15-min session | 642 readings, avg **1.32 W**, resting 0.65 W, peak 8.5 W, Chrome ≈ **25%** of chip power |
| Sync | 55 delivered, **0 lost, 0 duplicates**; cloud verified **9/9** receipts |
| Models | 0.5B = 494M params, 398 MB · 1.5B = 1.5B params, 986 MB · Q4_K_M 4-bit |
| Assumptions | ₹5.80/kWh (BESCOM) · 0.716 kg CO₂/kWh (CEA) · 8 h/day · 30 days |
| Code | 57 tests · 8 dashboard pages · CI on Ubuntu + macOS |
| Thresholds | p < 0.05 · anomaly 3× + 0.3 W · hog ≥ 0.15 W · bursts ≥ 30/h · label A ≤ 25% |

**Last-minute checklist:** Goal = Balanced · Ollama, Docker and dashboard running · heavy apps closed · backup video
ready · speak the labels · tell the honesty story.
