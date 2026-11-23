"""Apriori frequent itemsets (the market-basket idea from my basket / learning-path projects, re-implemented).

Here a 'basket' is the set of processes active in one high-power second. `contrast` finds process sets that
are much more common in high-power seconds than overall (lift), i.e. what tends to run together in spikes.
"""
from __future__ import annotations

from itertools import combinations


def apriori(transactions: list[set], min_support: float, max_len: int = 3) -> dict[frozenset, float]:
    n = len(transactions)
    if n == 0:
        return {}
    tx = [frozenset(t) for t in transactions]
    counts: dict[frozenset, int] = {}
    for t in tx:
        for item in t:
            k = frozenset([item])
            counts[k] = counts.get(k, 0) + 1
    current = {k: c / n for k, c in counts.items() if c / n >= min_support}
    result = dict(current)
    size = 1
    while current and size < max_len:
        size += 1
        prev = list(current)
        candidates = set()
        for a, b in combinations(prev, 2):
            union = a | b
            if len(union) == size and all(frozenset(sub) in current for sub in combinations(union, size - 1)):
                candidates.add(union)
        current = {}
        for c in candidates:
            support = sum(1 for t in tx if c <= t) / n
            if support >= min_support:
                current[c] = support
        result.update(current)
    return result


def support(itemset: frozenset, transactions: list[set]) -> float:
    return sum(1 for t in transactions if itemset <= set(t)) / len(transactions) if transactions else 0.0


def contrast(high: list[set], everything: list[set], min_support: float = 0.3, min_size: int = 2,
             max_len: int = 3) -> list[dict]:
    """Itemsets frequent in `high`, ranked by lift = support_in_high / support_overall."""
    out = []
    for items, s_high in apriori(high, min_support, max_len).items():
        if len(items) < min_size:
            continue
        s_all = support(items, everything)
        out.append({"items": sorted(items), "support_high": s_high, "support_all": s_all,
                    "lift": s_high / s_all if s_all else float("inf")})
    return sorted(out, key=lambda d: (-d["lift"], -d["support_high"]))
