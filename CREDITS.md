# Credits

| What | Used for | Licence / source |
|---|---|---|
| [Ollama](https://ollama.com) | Runs the local SLM on `localhost` | MIT |
| [Qwen2.5-1.5B-Instruct, Qwen2.5-0.5B-Instruct](https://huggingface.co/Qwen) | Local SLMs (1.54B / 0.49B parameters) | Apache-2.0 |
| Apple `powermetrics`, `ioreg`, `top`, `ps` | Power and CPU readings on macOS | Ships with macOS |
| CEA CO₂ Baseline Database for the Indian Power Sector | Grid emission factor (assumption, to be verified) | Central Electricity Authority, Government of India |
| Python standard library (sqlite3, urllib, http.server, threading) | Core app, storage, sync | PSF licence |
| [Streamlit](https://streamlit.io) | Dashboard | Apache-2.0 |
| [Plotly](https://plotly.com/python/) | Dashboard charts | MIT |
| [psutil](https://github.com/giampaolo/psutil) | CPU utilisation (optional) | BSD-3-Clause |
| [Docker](https://www.docker.com) | Runs the cloud sync server | Apache-2.0 (Engine) |
| [Lucide](https://lucide.dev) icon shapes | Line icons in the dashboard | ISC |
| BESCOM Domestic (LT-1) tariff, FY 2026–27 | Electricity tariff ₹5.80/kWh (assumption) | Bangalore Electricity Supply Company |

## My own earlier work reused

* `retail-basket-prediction-analyzer` — local LLM client idea (`app/llm.py`) → `joule/slm/client.py` (rewritten for Ollama's native API)
* `retail-basket-prediction-analyzer`, `learning-path-predictor` — Apriori itemsets and Markov baselines (re-implemented)
* `customer-feedback-analyzer` — confidence threshold and "flag for review"

## AI assistance

Parts of this project were written with an AI coding assistant. I reviewed, ran and tested all of it, and I can
explain every part.
