"""SLM explanations grounded in computed facts, with one corrective retry and a labelled template fallback."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from joule.config import Settings
from joule.slm import client, grounding

SYSTEM = (
    "You are an energy copilot on the user's laptop. Rewrite the FACTS as a short, friendly explanation for a "
    "non-expert.\n"
    "Rules:\n"
    "1. Copy every number exactly as written in FACTS, with its unit. Do not add any other numbers, percentages, "
    "comparisons or calculations.\n"
    "2. Keep the label in brackets (MEASURED, ATTRIBUTED, ESTIMATED or SIMULATED) next to the number it belongs to.\n"
    "3. Write 2-3 sentences, then one line starting 'Action:' and one line starting 'Trade-off:'. No lists, no headings."
)

EXAMPLE_FACTS = {
    "topic": "Pause cloud file sync while idle",
    "finding": "While the laptop was idle, cloud file sync used about 0.42 W (ESTIMATED).",
    "estimated_saving": "3.36 Wh per day, about INR 0.81 and 72.2 g CO2e per month (ESTIMATED)",
    "action": "Pause syncing while you are not changing files.",
    "tradeoff": "files reach the cloud later",
}
EXAMPLE_ANSWER = (
    "Even when you are not using the laptop, cloud file sync keeps checking for changes and uses about 0.42 W "
    "(ESTIMATED). Pausing it while you are idle would save roughly 3.36 Wh per day, about INR 0.81 and 72.2 g CO2e "
    "per month (ESTIMATED).\n"
    "Action: Pause syncing while you are not changing files.\n"
    "Trade-off: files reach the cloud later."
)


@dataclass
class ExplainResult:
    text: str
    model: str
    grounded: bool
    ungrounded: list[str] = field(default_factory=list)
    latency_s: float | None = None
    tokens: int | None = None
    attempts: int = 0
    fallback: bool = False
    rejected: list[str] = field(default_factory=list)   # SLM drafts that failed the grounding check


def visible_facts(facts: dict) -> dict:
    """A short, flat fact sheet for the SLM: sentences that already contain the numbers.
    Small models copy these reliably; a big nested JSON of numbers invites them to compute and invent."""
    pred = facts.get("prediction") or {}
    sheet = {"topic": facts.get("title", ""), "finding": facts.get("headline", "")}
    if pred.get("saved_wh_per_day") is not None:
        sheet["estimated_saving"] = (f"{pred['saved_wh_per_day']} Wh per day, about INR {pred['saved_inr_per_month']} "
                                     f"and {pred['saved_co2_g_per_month']} g CO2e per month "
                                     f"({pred.get('provenance', 'ESTIMATED')})")
    for k in ("action", "tradeoff"):
        if facts.get(k):
            sheet[k] = facts[k]
    return sheet


def template(facts: dict) -> str:
    """Deterministic explanation built only from fact strings: always grounded."""
    lines = [facts.get("headline", facts.get("title", "")).strip()]
    pred = facts.get("prediction")
    if pred and pred.get("saved_wh_per_day") is not None:
        lines.append(f"Estimated saving: {pred['saved_wh_per_day']} Wh per day, about INR {pred['saved_inr_per_month']} "
                     f"and {pred['saved_co2_g_per_month']} g CO2e per month ({pred.get('provenance', 'ESTIMATED')}).")
    if facts.get("action"):
        lines.append(f"Action: {facts['action']}")
    if facts.get("tradeoff"):
        lines.append(f"Trade-off: {facts['tradeoff']}")
    return "\n".join(x for x in lines if x)


def explain(facts: dict, model: str | None = None, max_tokens: int = 180, retries: int = 2,
            allow_fallback: bool = True, settings: Settings | None = None) -> ExplainResult:
    s = settings or Settings()
    model = model or s.llm_model
    shown = visible_facts(facts)
    if not client.is_available(model, s):
        if not allow_fallback:
            raise client.SLMUnavailable(f"model {model} is not available in Ollama")
        return ExplainResult(text=template(facts), model="template (SLM offline)", grounded=True, fallback=True)
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": "FACTS:\n" + json.dumps(EXAMPLE_FACTS, indent=1)},
                {"role": "assistant", "content": EXAMPLE_ANSWER},
                {"role": "user", "content": "FACTS:\n" + json.dumps(shown, indent=1, ensure_ascii=False)}]
    rejected, latency, tokens = [], 0.0, 0
    res = None
    for attempt in range(retries + 1):
        out = client.chat(messages, model=model, max_tokens=max_tokens, temperature=0.1 + 0.3 * attempt,
                          seed=attempt, settings=s)
        latency += out.latency_s
        tokens += out.tokens or 0
        res = grounding.check(out.content, {"sheet": shown, "facts": facts})
        if res.grounded:
            return ExplainResult(text=out.content, model=model, grounded=True, latency_s=latency, tokens=tokens,
                                 attempts=attempt + 1, rejected=rejected)
        rejected.append(out.content)
        messages += [{"role": "assistant", "content": out.content},
                     {"role": "user", "content": "These numbers are not in FACTS: " + ", ".join(res.ungrounded)
                      + ". Rewrite the explanation using only numbers that appear in FACTS."}]
    if allow_fallback:
        return ExplainResult(text=template(facts), model=f"template (after {model} failed grounding)", grounded=True,
                             ungrounded=res.ungrounded if res else [], latency_s=latency, tokens=tokens,
                             attempts=retries + 1, fallback=True, rejected=rejected)
    return ExplainResult(text=rejected[-1], model=model, grounded=False, ungrounded=res.ungrounded if res else [],
                         latency_s=latency, tokens=tokens, attempts=retries + 1, rejected=rejected)


def sample_facts() -> list[dict]:
    """Fixed prompts for the inference-settings scenario (same work for every model)."""
    base = [("Chrome Helper", 0.84, 72), ("mds_stores", 0.41, 35), ("Dropbox", 0.62, 58),
            ("Docker Desktop", 1.9, 91), ("Spotify", 0.33, 40), ("Slack Helper", 0.55, 66)]
    out = []
    for name, w, share in base:
        out.append({
            "title": f"Reduce background activity of {name}", "process": name,
            "headline": f"While the laptop was idle, '{name}' used about {w} W (ATTRIBUTED). "
                        f"It was active in {share}% of those seconds.",
            "observed": {"avg_attributed_w": w, "active_share_pct": share, "provenance": "ATTRIBUTED"},
            "prediction": {"saved_w": w, "hours_per_day": 8.0, "saved_wh_per_day": round(w * 8, 2),
                           "saved_inr_per_month": round(w * 8 * 30 / 1000 * 8.0, 2),
                           "saved_co2_g_per_month": round(w * 8 * 30 / 1000 * 716, 1), "provenance": "ESTIMATED"},
            "action": f"Quit or pause '{name}' while you are not using it.",
            "tradeoff": "the app may update later than before",
        })
    return out
