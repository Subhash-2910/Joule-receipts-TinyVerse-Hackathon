"""Durable outbox queue in SQLite (transactional-outbox pattern).

pending --claim--> in_flight --ok--> done
                       |--retryable error--> pending (attempts+1, next_attempt_at = now + backoff)
                       |--permanent error--> dead
in_flight with an expired lease (worker crashed) is claimable again.
The idempotency key is UNIQUE, so the same item can never be queued twice; the server dedupes on the same key.
"""
from __future__ import annotations

import json
import random
import time
import uuid

from joule import db

BASE_DELAY_S = 2.0
MAX_DELAY_S = 300.0


def enqueue(conn, kind: str, payload: dict, key: str | None = None, in_tx: bool = False, now: float | None = None) -> str:
    key = key or str(uuid.uuid4())
    now = time.time() if now is None else now
    sql = ("INSERT OR IGNORE INTO outbox(idem_key, kind, payload_json, status, attempts, next_attempt_at, created,"
           " updated) VALUES (?,?,?,'pending',0,?,?,?)")
    args = (key, kind, db.dumps(payload), now, now, now)
    if in_tx:
        conn.execute(sql, args)
    else:
        with db.tx(conn):
            conn.execute(sql, args)
    return key


def claim(conn, limit: int = 20, lease_s: float = 30.0, now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    with db.tx(conn):
        rows = conn.execute(
            "UPDATE outbox SET status='in_flight', lease_until=?, updated=? WHERE id IN ("
            " SELECT id FROM outbox WHERE (status='pending' AND next_attempt_at<=?)"
            " OR (status='in_flight' AND lease_until<?) ORDER BY id LIMIT ?) RETURNING *",
            (now + lease_s, now, now, now, limit)).fetchall()
    items = [dict(r) for r in rows]
    for it in items:
        it["payload"] = json.loads(it.pop("payload_json"))
    return sorted(items, key=lambda d: d["id"])


def mark_done(conn, item_id: int, now: float | None = None) -> None:
    now = time.time() if now is None else now
    with db.tx(conn):
        conn.execute("UPDATE outbox SET status='done', delivered_at=?, lease_until=NULL, last_error=NULL, updated=?"
                     " WHERE id=?", (now, now, item_id))


def backoff(attempts: int, rng: random.Random | None = None) -> float:
    rng = rng or random
    return min(BASE_DELAY_S * (2 ** max(0, attempts - 1)), MAX_DELAY_S) * rng.uniform(0.5, 1.0)


def mark_failed(conn, item_id: int, error: str, permanent: bool = False, now: float | None = None,
                rng: random.Random | None = None) -> None:
    now = time.time() if now is None else now
    with db.tx(conn):
        row = conn.execute("SELECT attempts FROM outbox WHERE id=?", (item_id,)).fetchone()
        attempts = (row["attempts"] if row else 0) + 1
        conn.execute("UPDATE outbox SET status=?, attempts=?, next_attempt_at=?, lease_until=NULL, last_error=?,"
                     " updated=? WHERE id=?",
                     ("dead" if permanent else "pending", attempts, now + backoff(attempts, rng), error[:500], now,
                      item_id))


def release(conn, ids: list[int], now: float | None = None) -> None:
    """Give claimed items back without counting an attempt (e.g. we went offline mid-drain)."""
    if not ids:
        return
    now = time.time() if now is None else now
    with db.tx(conn):
        conn.executemany("UPDATE outbox SET status='pending', lease_until=NULL, updated=? WHERE id=? AND "
                         "status='in_flight'", [(now, i) for i in ids])


def stats(conn) -> dict:
    out = {"pending": 0, "in_flight": 0, "done": 0, "dead": 0}
    for row in conn.execute("SELECT status, COUNT(*) n FROM outbox GROUP BY status"):
        out[row["status"]] = row["n"]
    return out


def items(conn, status: str | None = None, limit: int = 50) -> list[dict]:
    sql, args = "SELECT id, idem_key, kind, status, attempts, next_attempt_at, last_error, created, delivered_at " \
                "FROM outbox", []
    if status:
        sql += " WHERE status=?"
        args.append(status)
    return [dict(r) for r in conn.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()]
