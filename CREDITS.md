# Credits

| What | Used for | Licence / source |
|---|---|---|
| [Ollama](https://ollama.com) | Runs the local SLM on `localhost` | MIT |
| [Qwen2.5-1.5B-Instruct, Qwen2.5-0.5B-Instruct](https://huggingface.co/Qwen) | Local SLMs (1.54B / 0.49B parameters) | Apache-2.0 |
| GPT-2 (OpenAI, via Hugging Face) — planned | Base for my own LoRA energy-report writer | MIT |
| Apple `powermetrics`, `ioreg`, `top`, `ps` | Power and CPU readings on macOS | Ships with macOS |
| CEA CO₂ Baseline Database for the Indian Power Sector | Grid emission factor (assumption, to be verified) | Central Electricity Authority, Government of India |
| Python standard library (sqlite3, urllib, http.server, threading) | Core app, storage, sync | PSF licence |

## My own earlier work reused

* `retail-basket-prediction-analyzer` — OpenAI-compatible LLM client idea (`app/llm.py`) → `joule/slm/client.py`
* `retail-basket-prediction-analyzer`, `learning-path-predictor` — Apriori itemsets and Markov baselines (re-implemented)
* `customer-feedback-analyzer` — confidence threshold and "flag for review"
* `student-feedback-summarizer` — from-scratch LoRA (planned GPT-2 report writer)
* `support-response-generator` — anonymise before storing or sending

## AI assistance

Parts of this project were written with an AI coding assistant. I reviewed, ran and tested all of it, and I can
explain every part.
