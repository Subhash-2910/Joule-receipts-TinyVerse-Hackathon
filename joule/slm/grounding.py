"""Grounding check: every number in the SLM's text must come from the facts.

A number in the text is grounded when it equals a fact number rounded to the text's precision, or is within 1%
of one. Numbers glued to letters on the left (CO2, Q4, qwen2.5) are names, not quantities, and are skipped.
List markers at the start of a line ('1.', '2)') are skipped. 0, 1 and 100 are always allowed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

NUMBER = re.compile(r"(?<![A-Za-z_\d.])\d+(?:,\d{3})*(?:\.\d+)?")
LIST_MARKER = re.compile(r"^\s*\d+[.)]\s", re.M)
ALWAYS_OK = {0.0, 1.0, 100.0}


def numbers_in(text: str) -> list[str]:
    return NUMBER.findall(LIST_MARKER.sub(" ", text))


def _to_float(token: str) -> float:
    return float(token.replace(",", ""))


def fact_numbers(facts) -> set[float]:
    """Every number anywhere in the facts: numeric values and numbers written inside strings."""
    found: set[float] = set()

    def walk(x):
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, (int, float)):
            found.add(float(x))
        elif isinstance(x, str):
            found.update(_to_float(t) for t in numbers_in(x))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
    walk(facts)
    return found


def _matches(token: str, value: float, allowed: set[float]) -> bool:
    if value in ALWAYS_OK:
        return True
    decimals = len(token.split(".")[1]) if "." in token else 0
    for a in allowed:
        if round(a, decimals) == value or (a and abs(value - a) <= 0.01 * abs(a)):
            return True
    return False


@dataclass
class GroundingResult:
    grounded: bool
    checked: list[str] = field(default_factory=list)
    ungrounded: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        return 1.0 if not self.checked else 1 - len(self.ungrounded) / len(self.checked)


def check(text: str, facts) -> GroundingResult:
    allowed = fact_numbers(facts if not isinstance(facts, str) else json.loads(facts))
    tokens = numbers_in(text)
    bad = [t for t in tokens if not _matches(t, _to_float(t), allowed)]
    return GroundingResult(grounded=not bad, checked=tokens, ungrounded=bad)
