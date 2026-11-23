"""Stand-in 'cloud' sync server (standard library only; runs in Docker for the demo).

POST /events   stores an event once per idempotency key; repeats return {"status": "duplicate"}
GET  /health   liveness
GET  /stats    totals: events processed, duplicates ignored, by kind
GET  /events   last events

Fault injection for the demo and tests:
  fail_rate            share of requests answered 503 before doing anything
  drop_response_rate   share of NEW events stored but answered by closing the connection (a lost response);
                       the client retries with the same key and the server must not process it twice
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class CloudStore:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(
            "CREATE TABLE IF NOT EXISTS events (idem_key TEXT PRIMARY KEY, kind TEXT, device_id TEXT,"
            " payload_json TEXT, received_at REAL);"
            "CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);")

    def _bump(self, name: str) -> None:
        self.conn.execute("INSERT INTO counters(name, value) VALUES (?, 1) ON CONFLICT(name) DO UPDATE SET "
                          "value = value + 1", (name,))

    def put(self, key: str, kind: str, device_id: str, payload) -> bool:
        """True if new (processed now), False if a duplicate (ignored)."""
        with self.lock:
            cur = self.conn.execute("INSERT OR IGNORE INTO events VALUES (?,?,?,?,?)",
                                    (key, kind, device_id, json.dumps(payload), time.time()))
            new = cur.rowcount == 1
            self._bump("processed" if new else "duplicates_ignored")
            return new

    def stats(self) -> dict:
        with self.lock:
            c = dict(self.conn.execute("SELECT name, value FROM counters").fetchall())
            by_kind = dict(self.conn.execute("SELECT kind, COUNT(*) FROM events GROUP BY kind").fetchall())
            n = self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        return {"events": n, "processed": c.get("processed", 0),
                "duplicates_ignored": c.get("duplicates_ignored", 0), "by_kind": by_kind}

    def recent(self, limit: int = 20) -> list[dict]:
        with self.lock:
            rows = self.conn.execute("SELECT idem_key, kind, device_id, received_at FROM events ORDER BY received_at "
                                     "DESC LIMIT ?", (limit,)).fetchall()
        return [dict(zip(("idempotency_key", "kind", "device_id", "received_at"), r)) for r in rows]


def make_handler(store: CloudStore, fail_rate: float, drop_rate: float, rng: random.Random):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quiet
            pass

        def _send(self, code: int, obj) -> None:
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/health":
                return self._send(200, {"ok": True})
            if self.path == "/stats":
                return self._send(200, store.stats())
            if self.path.startswith("/events"):
                return self._send(200, store.recent())
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/events":
                return self._send(404, {"error": "not found"})
            if rng.random() < fail_rate:
                return self._send(503, {"error": "injected failure"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "invalid JSON"})
            key = self.headers.get("Idempotency-Key") or body.get("idempotency_key")
            if not key or "kind" not in body:
                return self._send(400, {"error": "idempotency key and kind are required"})
            new = store.put(key, body["kind"], body.get("device_id", "?"), body.get("payload"))
            if new and rng.random() < drop_rate:
                self.close_connection = True       # stored, but the client never hears back
                return
            self._send(201 if new else 200, {"status": "accepted" if new else "duplicate", "key": key})

    return Handler


def make_server(port: int = 8787, db_file: str | Path = "cloud-data/cloud.db", fail_rate: float = 0.0,
                drop_rate: float = 0.0, seed: int | None = None, host: str = "0.0.0.0"):
    store = CloudStore(db_file)
    server = ThreadingHTTPServer((host, port), make_handler(store, fail_rate, drop_rate, random.Random(seed)))
    server.daemon_threads = True
    return server, store


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Joule Receipts cloud sync server")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8787)))
    ap.add_argument("--db", default=os.environ.get("JOULE_CLOUD_DB", "cloud-data/cloud.db"))
    ap.add_argument("--fail-rate", type=float, default=float(os.environ.get("JOULE_CLOUD_FAIL_RATE", 0)))
    ap.add_argument("--drop-response-rate", type=float,
                    default=float(os.environ.get("JOULE_CLOUD_DROP_RESPONSE_RATE", 0)))
    args = ap.parse_args(argv)
    server, _ = make_server(args.port, args.db, args.fail_rate, args.drop_response_rate)
    print(f"cloud sync server on :{args.port} (fail_rate={args.fail_rate}, drop_response_rate="
          f"{args.drop_response_rate})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
