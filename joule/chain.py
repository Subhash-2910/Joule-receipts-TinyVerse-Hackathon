"""Tamper-evident receipt chain (standard library only, so the cloud server can verify it too).

hash_n = sha256(hash_{n-1} | receipt id | created time | canonical JSON of the receipt body)
Changing any number in any receipt changes its hash, which no longer matches the prev_hash stored in the next one.
"""
from __future__ import annotations

import hashlib
import json

GENESIS = "0" * 64


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


def chain_hash(prev_hash: str, receipt_id: int, created: float, body: dict) -> str:
    blob = f"{prev_hash}|{int(receipt_id)}|{float(created)!r}|{canonical(body)}"
    return hashlib.sha256(blob.encode()).hexdigest()


def verify_entries(entries: list[dict]) -> dict:
    """entries: dicts with receipt_id, created, prev_hash, hash, body - in receipt order.
    Returns ok, n, broken_at (first receipt id whose hash or link is wrong), head (last good hash)."""
    prev = GENESIS
    for e in entries:
        if e.get("prev_hash") != prev or e.get("hash") != chain_hash(prev, e["receipt_id"], e["created"], e["body"]):
            return {"ok": False, "n": len(entries), "broken_at": e["receipt_id"], "head": prev}
        prev = e["hash"]
    return {"ok": True, "n": len(entries), "broken_at": None, "head": prev}
