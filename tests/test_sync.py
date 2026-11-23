import random
import socket
import threading
import time
import unittest

from joule import db
from joule.sync import outbox
from joule.sync.server import make_server
from joule.sync.worker import SyncWorker
from tests.helpers import TempDataTest


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class OutboxTest(TempDataTest):
    def test_same_key_is_queued_once(self):
        outbox.enqueue(self.conn, "decision", {"a": 1}, key="k1")
        outbox.enqueue(self.conn, "decision", {"a": 1}, key="k1")
        self.assertEqual(outbox.stats(self.conn)["pending"], 1)

    def test_claim_lease_and_crash_recovery(self):
        outbox.enqueue(self.conn, "x", {}, key="k1", now=100.0)
        first = outbox.claim(self.conn, lease_s=30, now=100.0)
        self.assertEqual(len(first), 1)
        self.assertEqual(outbox.claim(self.conn, lease_s=30, now=110.0), [])   # leased: nobody else gets it
        # the 'worker' crashes; the app restarts with a new connection
        self.conn.close()
        self.conn = db.connect(self.db_path)
        again = outbox.claim(self.conn, lease_s=30, now=131.0)                 # lease expired -> reclaimable
        self.assertEqual([i["idem_key"] for i in again], ["k1"])

    def test_backoff_grows_and_is_capped(self):
        rng = random.Random(0)
        delays = [outbox.backoff(n, rng) for n in range(1, 12)]
        self.assertLess(delays[0], delays[4])
        self.assertTrue(all(d <= outbox.MAX_DELAY_S for d in delays))
        outbox.enqueue(self.conn, "x", {}, key="k1", now=0.0)
        item = outbox.claim(self.conn, now=0.0)[0]
        outbox.mark_failed(self.conn, item["id"], "boom", now=0.0, rng=random.Random(0))
        row = self.conn.execute("SELECT status, attempts, next_attempt_at FROM outbox").fetchone()
        self.assertEqual((row["status"], row["attempts"]), ("pending", 1))
        self.assertGreater(row["next_attempt_at"], 0.0)
        self.assertEqual(outbox.claim(self.conn, now=0.5), [])                 # not before the backoff ends

    def test_queue_survives_restart(self):
        rec = {"key": "background:Foo", "kind": "background", "title": "t", "action": "a", "facts": {"x": 1}}
        rid = db.upsert_recommendation(self.conn, rec)
        db.record_decision(self.conn, rid, "accept")
        self.conn.close()
        self.conn = db.connect(self.db_path)
        self.assertEqual(outbox.stats(self.conn)["pending"], 1)
        self.assertEqual(db.get_recommendation(self.conn, rid)["status"], "accepted")

    def test_decision_and_outbox_are_atomic(self):
        rec = {"key": "k", "kind": "background", "title": "t", "action": "a", "facts": {}}
        rid = db.upsert_recommendation(self.conn, rec)
        original = outbox.enqueue

        def broken(*a, **kw):
            raise RuntimeError("crash between the two writes")
        outbox.enqueue = broken
        try:
            with self.assertRaises(RuntimeError):
                db.record_decision(self.conn, rid, "accept")
        finally:
            outbox.enqueue = original
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0], 0)
        self.assertEqual(db.get_recommendation(self.conn, rid)["status"], "open")


class SyncEndToEndTest(TempDataTest):
    def _server(self, port, **kw):
        server, store = make_server(port, self.tmp / "cloud.db", host="127.0.0.1", seed=1, **kw)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server, store

    def _queue(self, n):
        for i in range(n):
            outbox.enqueue(self.conn, "decision", {"i": i})

    def test_offline_then_reconnect_delivers_everything_once(self):
        port = free_port()
        worker = SyncWorker(self.db_path, f"http://127.0.0.1:{port}", log=lambda *_: None)
        self._queue(5)
        self.assertIsNone(worker.tick(self.conn))                 # offline: nothing sent, nothing lost
        self.assertEqual(outbox.stats(self.conn)["pending"], 5)
        _, store = self._server(port)                             # connectivity returns
        counts = worker.tick(self.conn)
        self.assertEqual(counts["done"], 5)
        self.assertEqual(store.stats()["processed"], 5)
        self.assertEqual(outbox.stats(self.conn)["done"], 5)

    def test_lost_responses_and_failures_never_double_process(self):
        port = free_port()
        _, store = self._server(port, fail_rate=0.3, drop_rate=0.5)
        worker = SyncWorker(self.db_path, f"http://127.0.0.1:{port}", log=lambda *_: None, timeout_s=2)
        self._queue(20)
        deadline = time.time() + 60
        while outbox.stats(self.conn)["done"] < 20 and time.time() < deadline:
            worker.tick(self.conn)
            # skip the backoff wait so the test runs fast
            self.conn.execute("UPDATE outbox SET next_attempt_at = 0 WHERE status='pending'")
        s = store.stats()
        self.assertEqual(outbox.stats(self.conn)["done"], 20)
        self.assertEqual(s["events"], 20)
        self.assertEqual(s["processed"], 20)                      # exactly once each
        self.assertGreater(s["duplicates_ignored"], 0)            # retries after lost responses were deduped

    def test_permanent_rejection_goes_dead(self):
        port = free_port()
        self._server(port)
        worker = SyncWorker(self.db_path, f"http://127.0.0.1:{port}", log=lambda *_: None)
        self.conn.execute("INSERT INTO outbox(idem_key, kind, payload_json, status, attempts, next_attempt_at,"
                          " created, updated) VALUES ('', 'x', '{}', 'pending', 0, 0, 0, 0)")
        worker.tick(self.conn)
        self.assertEqual(outbox.stats(self.conn)["dead"], 1)


if __name__ == "__main__":
    unittest.main()
