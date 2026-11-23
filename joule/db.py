"""Local SQLite store: readings, experiments, predictions, recommendations, reports, decisions, receipts, outbox.

WAL journal + synchronous=FULL: a committed row survives an app crash or power loss. Writes that belong together
(a decision and its outbox item) go through `tx()` so they commit or roll back as one.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from joule import config
from joule.chain import GENESIS, chain_hash, verify_entries

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS samples (
    id INTEGER PRIMARY KEY, ts REAL NOT NULL, session TEXT, source TEXT NOT NULL, provenance TEXT NOT NULL,
    watts REAL NOT NULL, cpu_w REAL, gpu_w REAL, ane_w REAL, cpu_util REAL, on_battery INTEGER);
CREATE INDEX IF NOT EXISTS samples_ts ON samples(ts);

CREATE TABLE IF NOT EXISTS proc_samples (
    id INTEGER PRIMARY KEY, sample_id INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
    ts REAL NOT NULL, name TEXT NOT NULL, cpu_pct REAL NOT NULL, watts REAL, provenance TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS proc_samples_sample ON proc_samples(sample_id);

CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY, scenario TEXT NOT NULL, created REAL NOT NULL, source TEXT NOT NULL,
    provenance TEXT NOT NULL, repeats INTEGER NOT NULL, idle_w REAL, params_json TEXT, result_json TEXT);

CREATE TABLE IF NOT EXISTS experiment_runs (
    id INTEGER PRIMARY KEY, experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    variant TEXT NOT NULL, run_idx INTEGER NOT NULL, started REAL, duration_s REAL, n_samples INTEGER,
    energy_wh REAL, net_wh REAL, mean_w REAL, std_w REAL, provenance TEXT, checksum TEXT, work_units INTEGER);

CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, created REAL NOT NULL, kind TEXT NOT NULL,
    title TEXT NOT NULL, action TEXT NOT NULL, scenario TEXT, confidence REAL, needs_review INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open', facts_json TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY, rec_id INTEGER REFERENCES recommendations(id) ON DELETE CASCADE, created REAL NOT NULL,
    metric TEXT NOT NULL, value REAL NOT NULL, unit TEXT NOT NULL, method TEXT, provenance TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY, created REAL NOT NULL, kind TEXT NOT NULL, rec_id INTEGER, model TEXT,
    grounded INTEGER, ungrounded_json TEXT, latency_s REAL, tokens INTEGER, body TEXT NOT NULL, facts_json TEXT);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY, rec_id INTEGER NOT NULL REFERENCES recommendations(id), decision TEXT NOT NULL,
    note TEXT, created REAL NOT NULL);

CREATE TABLE IF NOT EXISTS receipts (
    id INTEGER PRIMARY KEY, created REAL NOT NULL, rec_id INTEGER, experiment_id INTEGER REFERENCES experiments(id),
    predicted_saved_wh REAL, measured_saved_wh REAL, provenance TEXT, body_json TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY, idem_key TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at REAL NOT NULL,
    lease_until REAL, last_error TEXT, created REAL NOT NULL, updated REAL NOT NULL, delivered_at REAL);
CREATE INDEX IF NOT EXISTS outbox_ready ON outbox(status, next_attempt_at);
"""


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(path or config.db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)  # autocommit; tx() opens explicit transactions
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.executescript(SCHEMA)
    conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
    migrate(conn)
    config.give_back(path.parent)          # -wal / -shm files created under sudo
    return conn


ADDED_COLUMNS = {
    "reports": [("energy_j", "REAL"), ("energy_prov", "TEXT"), ("cascade_json", "TEXT")],
    "receipts": [("prev_hash", "TEXT"), ("hash", "TEXT")],
}


def migrate(conn) -> None:
    """v1 -> v2: SLM energy columns on reports, hash chain on receipts (existing receipts are chained in id order)."""
    for table, cols in ADDED_COLUMNS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, typ in cols:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
    if conn.execute("SELECT COUNT(*) FROM receipts WHERE hash IS NULL").fetchone()[0]:
        with tx(conn):
            prev = GENESIS
            for row in conn.execute("SELECT id, created, body_json, hash FROM receipts ORDER BY id").fetchall():
                if row["hash"] is None:
                    h = chain_hash(prev, row["id"], row["created"], json.loads(row["body_json"]))
                    conn.execute("UPDATE receipts SET prev_hash=?, hash=? WHERE id=?", (prev, h, row["id"]))
                    prev = h
                else:
                    prev = row["hash"]
        enqueue_missing_chain(conn)
    conn.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))


# ---------- tamper-evident receipt chain ----------

def verify_chain(conn, rows=None) -> dict:
    """Recompute the local chain. Returns {'ok', 'n', 'broken_at' (first bad receipt id or None), 'head'}."""
    rows = rows if rows is not None else conn.execute(
        "SELECT id, created, body_json, prev_hash, hash FROM receipts ORDER BY id").fetchall()
    return verify_entries([chain_entry(r) for r in rows])


def chain_entry(row) -> dict:
    return {"receipt_id": row["id"], "created": row["created"], "prev_hash": row["prev_hash"], "hash": row["hash"],
            "body": json.loads(row["body_json"])}


# ---------- settings stored in the database (survive restarts) ----------

def get_meta(conn, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn, key: str, value: str, in_tx: bool = False) -> None:
    sql = "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    if in_tx:
        conn.execute(sql, (key, value))
    else:
        with tx(conn):
            conn.execute(sql, (key, value))


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE ... COMMIT, rolled back on any exception."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


# ---------- samples ----------

def insert_sample(conn, reading, session: str | None = None, procs: list | None = None) -> int:
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO samples(ts, session, source, provenance, watts, cpu_w, gpu_w, ane_w, cpu_util, on_battery)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (reading.ts, session, reading.source, str(reading.provenance), reading.watts, reading.cpu_w,
             reading.gpu_w, reading.ane_w, reading.cpu_util,
             None if reading.on_battery is None else int(reading.on_battery)))
        sid = cur.lastrowid
        for p in procs or []:
            conn.execute("INSERT INTO proc_samples(sample_id, ts, name, cpu_pct, watts, provenance) VALUES (?,?,?,?,?,?)",
                         (sid, reading.ts, p.name, p.cpu_pct, p.watts, str(p.provenance)))
    return sid


def recent_samples(conn, since_ts: float = 0.0, limit: int | None = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM samples WHERE ts >= ? ORDER BY ts"
    if limit:
        sql = f"SELECT * FROM (SELECT * FROM samples WHERE ts >= ? ORDER BY ts DESC LIMIT {int(limit)}) ORDER BY ts"
    return conn.execute(sql, (since_ts,)).fetchall()


def proc_rows(conn, since_ts: float = 0.0) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM proc_samples WHERE ts >= ? ORDER BY ts", (since_ts,)).fetchall()


# ---------- experiments / receipts ----------

def save_experiment(conn, scenario: str, source: str, provenance: str, repeats: int, idle_w: float,
                    params: dict, runs: list, result: dict) -> int:
    with tx(conn):
        eid = conn.execute(
            "INSERT INTO experiments(scenario, created, source, provenance, repeats, idle_w, params_json, result_json)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (scenario, time.time(), source, provenance, repeats, idle_w, dumps(params), dumps(result))).lastrowid
        for r in runs:
            conn.execute(
                "INSERT INTO experiment_runs(experiment_id, variant, run_idx, started, duration_s, n_samples, energy_wh,"
                " net_wh, mean_w, std_w, provenance, checksum, work_units) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (eid, r.variant, r.run_idx, r.started, r.duration_s, r.n_samples, r.energy_wh, r.net_wh, r.mean_w,
                 r.std_w, str(r.provenance), r.checksum, r.work_units))
    return eid


def save_receipt(conn, body: dict, experiment_id: int | None, rec_id: int | None,
                 predicted_wh: float | None, measured_wh: float, provenance: str, enqueue: bool = True) -> int:
    from joule.sync import outbox  # local import: outbox depends on db
    body = json.loads(dumps(body))          # canonical form: exactly what is hashed is what is stored
    with tx(conn):
        last = conn.execute("SELECT hash FROM receipts ORDER BY id DESC LIMIT 1").fetchone()
        prev = (last["hash"] if last else None) or GENESIS
        created = time.time()
        rid = conn.execute(
            "INSERT INTO receipts(created, rec_id, experiment_id, predicted_saved_wh, measured_saved_wh, provenance,"
            " body_json, prev_hash) VALUES (?,?,?,?,?,?,?,?)",
            (created, rec_id, experiment_id, predicted_wh, measured_wh, provenance, dumps(body), prev)).lastrowid
        h = chain_hash(prev, rid, created, body)
        conn.execute("UPDATE receipts SET hash=? WHERE id=?", (h, rid))
        if enqueue:
            outbox.enqueue(conn, "receipt", {"receipt_id": rid, **body}, in_tx=True)
            enqueue_chain(conn, {"receipt_id": rid, "created": created, "prev_hash": prev, "hash": h, "body": body})
    return rid


def enqueue_chain(conn, entry: dict) -> None:
    """One 'chain' event per receipt; the key is the hash, so re-sending can never create a duplicate."""
    from joule.sync import outbox
    outbox.enqueue(conn, "chain", {"device_id": config.Settings().device_id, **entry},
                   key=f"chain:{entry['hash']}", in_tx=True)


def enqueue_missing_chain(conn) -> int:
    """Queue chain events for receipts that predate the chain (no-op for ones already queued)."""
    n = 0
    with tx(conn):
        for row in conn.execute("SELECT id, created, body_json, prev_hash, hash FROM receipts ORDER BY id").fetchall():
            if not conn.execute("SELECT 1 FROM outbox WHERE idem_key=?", (f"chain:{row['hash']}",)).fetchone():
                enqueue_chain(conn, chain_entry(row))
                n += 1
    return n


# ---------- recommendations / predictions / decisions / reports ----------

def upsert_recommendation(conn, rec: dict) -> int:
    """Insert, or refresh the facts of an open recommendation with the same key. Returns its id."""
    with tx(conn):
        row = conn.execute("SELECT id, status FROM recommendations WHERE key = ?", (rec["key"],)).fetchone()
        if row:
            if row["status"] in ("open", "cleared"):       # a cleared alert that fires again re-opens
                conn.execute("UPDATE recommendations SET facts_json=?, confidence=?, needs_review=?, title=?, action=?,"
                             " status='open' WHERE id=?", (dumps(rec["facts"]), rec.get("confidence"), int(rec.get("needs_review", 0)),
                                             rec["title"], rec["action"], row["id"]))
            rid = row["id"]
        else:
            rid = conn.execute(
                "INSERT INTO recommendations(key, created, kind, title, action, scenario, confidence, needs_review,"
                " facts_json) VALUES (?,?,?,?,?,?,?,?,?)",
                (rec["key"], time.time(), rec["kind"], rec["title"], rec["action"], rec.get("scenario"),
                 rec.get("confidence"), int(rec.get("needs_review", 0)), dumps(rec["facts"]))).lastrowid
        for p in rec.get("predictions", []):
            conn.execute("INSERT INTO predictions(rec_id, created, metric, value, unit, method, provenance)"
                         " VALUES (?,?,?,?,?,?,?)",
                         (rid, time.time(), p["metric"], p["value"], p["unit"], p.get("method"), p["provenance"]))
    return rid


def get_recommendation(conn, rec_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM recommendations WHERE id = ?", (rec_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["facts"] = json.loads(d.pop("facts_json"))
    return d


def list_recommendations(conn, status: str | None = None) -> list[dict]:
    sql, args = "SELECT id FROM recommendations", ()
    if status:
        sql, args = sql + " WHERE status = ?", (status,)
    return [get_recommendation(conn, r["id"]) for r in conn.execute(sql + " ORDER BY id", args).fetchall()]


def record_decision(conn, rec_id: int, decision: str, note: str = "", device_id: str = "laptop-1") -> int:
    """The decision row, the recommendation status and the outbox item commit together or not at all."""
    from joule.sync import outbox
    if decision not in {"accept", "reject", "defer"}:
        raise ValueError("decision must be accept, reject or defer")
    rec = get_recommendation(conn, rec_id)
    if rec is None:
        raise KeyError(f"no recommendation {rec_id}")
    with tx(conn):
        did = conn.execute("INSERT INTO decisions(rec_id, decision, note, created) VALUES (?,?,?,?)",
                           (rec_id, decision, note, time.time())).lastrowid
        status = {"accept": "accepted", "reject": "rejected", "defer": "open"}[decision]
        conn.execute("UPDATE recommendations SET status=? WHERE id=?", (status, rec_id))
        outbox.enqueue(conn, "decision", {
            "decision_id": did, "device_id": device_id, "rec_key": rec["key"], "kind": rec["kind"],
            "title": rec["title"], "decision": decision, "note": note}, in_tx=True)
    return did


def save_report(conn, kind: str, body: str, model: str, grounded: bool | None, ungrounded: list | None = None,
                rec_id: int | None = None, facts: dict | None = None, latency_s: float | None = None,
                tokens: int | None = None, enqueue: bool = True, energy_j: float | None = None,
                energy_prov: str | None = None, cascade: list | None = None) -> int:
    from joule.sync import outbox
    with tx(conn):
        rid = conn.execute(
            "INSERT INTO reports(created, kind, rec_id, model, grounded, ungrounded_json, latency_s, tokens, body,"
            " facts_json, energy_j, energy_prov, cascade_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (time.time(), kind, rec_id, model, None if grounded is None else int(grounded), dumps(ungrounded or []),
             latency_s, tokens, body, dumps(facts or {}), energy_j, energy_prov,
             None if cascade is None else dumps(cascade))).lastrowid
        if enqueue:
            outbox.enqueue(conn, kind, {"report_id": rid, "rec_id": rec_id, "model": model,
                                        "grounded": grounded, "body": body, "energy_j": energy_j,
                                        "energy_prov": energy_prov}, in_tx=True)
    return rid
