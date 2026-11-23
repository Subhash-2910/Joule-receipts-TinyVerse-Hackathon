"""Sync worker: notices when the server is reachable and drains the outbox with the idempotency key."""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

from joule import db
from joule.config import Settings
from joule.sync import outbox

RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}


class SyncWorker:
    def __init__(self, db_path=None, cloud_url: str | None = None, device_id: str | None = None,
                 batch: int = 20, lease_s: float = 30.0, timeout_s: float = 5.0, log=print):
        s = Settings()
        self.db_path = db_path
        self.cloud_url = (cloud_url or s.cloud_url).rstrip("/")
        self.device_id = device_id or s.device_id
        self.batch, self.lease_s, self.timeout_s, self.log = batch, lease_s, timeout_s, log
        self.was_online: bool | None = None

    def online(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.cloud_url}/health", timeout=2.0) as r:
                return r.status == 200
        except (urllib.error.URLError, OSError, TimeoutError):
            return False

    def deliver(self, item: dict) -> tuple[str, str]:
        """Returns ('done'|'retry'|'dead'|'offline', detail)."""
        body = json.dumps({"idempotency_key": item["idem_key"], "kind": item["kind"], "device_id": self.device_id,
                           "created": item["created"], "payload": item["payload"]}).encode()
        req = urllib.request.Request(f"{self.cloud_url}/events", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "Idempotency-Key": item["idem_key"]})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                return "done", json.loads(r.read().decode() or "{}").get("status", str(r.status))
        except urllib.error.HTTPError as e:
            return ("retry" if e.code in RETRYABLE_HTTP else "dead"), f"HTTP {e.code}"
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
            return "offline", f"{type(e).__name__}: {e}"

    def drain(self, conn=None) -> dict:
        conn = conn or db.connect(self.db_path)
        counts = {"done": 0, "duplicate": 0, "retry": 0, "dead": 0, "offline": 0}
        while True:
            claimed = outbox.claim(conn, self.batch, self.lease_s)
            if not claimed:
                return counts
            for i, item in enumerate(claimed):
                result, detail = self.deliver(item)
                if result == "done":
                    outbox.mark_done(conn, item["id"])
                    counts["duplicate" if detail == "duplicate" else "done"] += 1
                elif result == "dead":
                    outbox.mark_failed(conn, item["id"], detail, permanent=True)
                    counts["dead"] += 1
                else:
                    # A lost response may still have reached the server: the retry carries the same key, so it
                    # is deduplicated there. Count an attempt and back off.
                    outbox.mark_failed(conn, item["id"], detail)
                    counts[result] += 1
                    if result == "offline":
                        outbox.release(conn, [x["id"] for x in claimed[i + 1:]])
                        return counts

    def tick(self, conn) -> dict | None:
        up = self.online()
        if up != self.was_online:
            self.log("cloud reachable: syncing queued items" if up else "cloud unreachable: working offline, "
                     "items stay queued")
            self.was_online = up
        if not up:
            return None
        counts = self.drain(conn)
        if any(counts.values()):
            self.log(f"sync: {counts} | queue {outbox.stats(conn)}")
        return counts

    def run(self, poll_s: float = 3.0, stop: threading.Event | None = None) -> None:
        stop = stop or threading.Event()
        conn = db.connect(self.db_path)
        while not stop.is_set():
            self.tick(conn)
            stop.wait(poll_s)
