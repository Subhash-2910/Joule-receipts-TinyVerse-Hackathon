"""Local SLM client for Ollama on localhost (no API keys, no internet after the model is pulled).

Adapted from app/llm.py in my retail-basket-prediction-analyzer (one chat call, settings from the environment),
rewritten with urllib so the core has no dependencies, and using Ollama's native /api/chat so we also get
token counts and timings for the inference-energy scenario.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from joule.config import Settings


class SLMUnavailable(RuntimeError):
    pass


@dataclass
class ChatResult:
    content: str
    model: str
    tokens: int | None
    prompt_tokens: int | None
    latency_s: float
    eval_s: float | None


def _request(url: str, payload: dict | None = None, timeout: float = 5.0) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"},
                                 method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        raise SLMUnavailable(f"Ollama not reachable at {url}: {e}") from e


def installed_models(settings: Settings | None = None) -> list[str]:
    s = settings or Settings()
    return [m["name"] for m in _request(f"{s.llm_base_url}/api/tags", timeout=2.0).get("models", [])]


def is_available(model: str | None = None, settings: Settings | None = None) -> bool:
    s = settings or Settings()
    try:
        names = installed_models(s)
    except SLMUnavailable:
        return False
    want = model or s.llm_model
    return any(n == want or n.split(":")[0] == want or n == f"{want}:latest" for n in names)


def chat(messages: list[dict], model: str | None = None, max_tokens: int = 256, temperature: float = 0.2,
         seed: int = 0, settings: Settings | None = None) -> ChatResult:
    s = settings or Settings()
    model = model or s.llm_model
    t0 = time.time()
    out = _request(f"{s.llm_base_url}/api/chat", {
        "model": model, "messages": messages, "stream": False,
        "options": {"num_predict": max_tokens, "temperature": temperature, "seed": seed},
    }, timeout=s.llm_timeout_s)
    if "error" in out:
        raise SLMUnavailable(out["error"])
    return ChatResult(content=out.get("message", {}).get("content", "").strip(), model=model,
                      tokens=out.get("eval_count"), prompt_tokens=out.get("prompt_eval_count"),
                      latency_s=time.time() - t0,
                      eval_s=(out["eval_duration"] / 1e9) if out.get("eval_duration") else None)
