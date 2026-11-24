"""Self-measuring AI cascade, anomaly alerts, what-if, Goal switch, energy labels and the tamper-evident chain."""
import json
import time
import unittest
from unittest import mock

from joule import chain, db, policy
from joule.analytics import anomaly, label, whatif
from joule.slm import client, explain
from tests.helpers import TempDataTest

BODY = {"scenario": "batching", "title": "Batching", "provenance": "MEASURED", "sensor": "powermetrics",
        "baseline": "200 launches", "optimized": "10 launches", "repeats": 5, "idle_w": 3.0, "basis": "above idle",
        "baseline_wh": 0.0035, "optimized_wh": 0.0002, "measured_saved_wh": 0.0033, "saved_pct": 94.0,
        "p_value": 0.0079, "significant": True, "equivalent_work": True, "tradeoff": "later first result",
        "saved_inr": 0.0, "saved_co2_g": 0.0, "noise_wh": 0.0001, "assumptions": {}}


class ChainAndLabelTest(TempDataTest):
    def add(self, **over):
        return db.save_receipt(self.conn, {**BODY, **over}, None, None, None, BODY["measured_saved_wh"], "MEASURED")

    def test_chain_links_and_verifies(self):
        ids = [self.add(), self.add(saved_pct=80.0), self.add(scenario="idle")]
        rows = self.conn.execute("SELECT * FROM receipts ORDER BY id").fetchall()
        self.assertEqual(rows[0]["prev_hash"], chain.GENESIS)
        self.assertEqual(rows[1]["prev_hash"], rows[0]["hash"])
        self.assertTrue(db.verify_chain(self.conn)["ok"])
        # every receipt also queues one 'chain' event keyed by its hash (no duplicates possible)
        keys = [r["idem_key"] for r in self.conn.execute("SELECT idem_key FROM outbox WHERE kind='chain'")]
        self.assertEqual(len(keys), len(ids))
        self.assertTrue(all(k.startswith("chain:") for k in keys))

    def test_editing_a_number_breaks_the_chain(self):
        self.add(), self.add(), self.add()
        demo = label.tamper_demo(self.conn, 2)
        self.assertFalse(demo["ok"])
        self.assertEqual(demo["broken_at"], 2)
        self.assertTrue(db.verify_chain(self.conn)["ok"])          # the demo never touches the database
        b = json.loads(self.conn.execute("SELECT body_json FROM receipts WHERE id=2").fetchone()[0])
        b["saved_pct"] = 99.9
        self.conn.execute("UPDATE receipts SET body_json=? WHERE id=2", (db.dumps(b),))   # a real edit
        self.assertEqual(db.verify_chain(self.conn)["broken_at"], 2)

    def test_cloud_verifies_independently(self):
        from joule.sync.server import CloudStore
        self.add(), self.add()
        store = CloudStore(self.tmp / "cloud.db")
        for item in self.conn.execute("SELECT idem_key, payload_json FROM outbox WHERE kind='chain'"):
            p = json.loads(item["payload_json"])
            store.put(item["idem_key"], "chain", p["device_id"], p)
        res = store.verify_chains()["laptop-1"]
        self.assertTrue(res["ok"])
        self.assertEqual(res["n"], 2)

    def test_label_grades_and_certifies(self):
        rid = self.add()
        lab = label.label_for(self.conn, rid)
        self.assertEqual(lab["grade"], "A")                        # 0.2 / 3.5 = 6 %
        self.assertTrue(lab["certified"])
        self.assertIn("Energy certificate", label.certificate_html(lab))
        weak = label.label_for(self.conn, self.add(provenance="ESTIMATED", significant=False, optimized_wh=0.0026))
        self.assertEqual(weak["grade"], "E")                       # 74 %
        self.assertFalse(weak["certified"])
        self.assertEqual(len(weak["reasons"]), 2)
        self.assertEqual([label.grade(p) for p in (10, 30, 50, 60, 80, 95, 120)], list("ABCDEFG"))

    def test_existing_receipts_are_chained_on_upgrade(self):
        for i in range(3):
            self.conn.execute("INSERT INTO receipts(created, body_json) VALUES (?, ?)", (time.time(), db.dumps(BODY)))
        self.conn.execute("UPDATE receipts SET hash=NULL, prev_hash=NULL")
        db.migrate(self.conn)
        self.assertTrue(db.verify_chain(self.conn)["ok"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM outbox WHERE kind='chain'").fetchone()[0], 3)


def rows(n, t0, watts=4.0, source="estimate"):
    return [{"id": i, "ts": t0 + i, "watts": watts, "source": source, "provenance": "ESTIMATED"} for i in range(n)]


class AnomalyTest(unittest.TestCase):
    def test_app_far_above_its_usual_power_alerts(self):
        samples = rows(100, 0) + [{**s, "id": s["id"] + 100} for s in rows(20, 100)]
        procs = {s["id"]: [{"name": "Google Chrome Helper", "watts": 0.3 if s["id"] < 100 else 1.5,
                            "provenance": "ATTRIBUTED"}] for s in samples}
        alerts = anomaly.detect(samples, procs, ratio=3.0, recent_s=20)
        self.assertEqual(alerts[0]["subject"], "Google Chrome")
        self.assertGreater(alerts[0]["times"], 4.5)                 # ~5x (window edge holds one old reading)
        self.assertEqual(anomaly.detect(samples, procs, ratio=6.0, recent_s=20), [])   # stricter goal: no alert

    def test_steady_use_and_other_sensors_do_not_alert(self):
        samples = rows(100, 0) + [{**s, "id": s["id"] + 100} for s in rows(20, 100)]
        procs = {s["id"]: [{"name": "Slack", "watts": 0.5, "provenance": "ATTRIBUTED"}] for s in samples}
        self.assertEqual(anomaly.detect(samples, procs, recent_s=20), [])
        mixed = rows(100, 0, watts=2.0, source="battery") + [{**s, "id": s["id"] + 100} for s in rows(20, 100, 9.0)]
        self.assertEqual(anomaly.detect(mixed, {}, recent_s=20), [])     # too little same-sensor history

    def test_resting_power_rise_alerts_for_the_machine(self):
        samples = rows(100, 0, watts=3.0) + [{**s, "id": s["id"] + 100} for s in rows(20, 100, watts=6.0)]
        alerts = anomaly.detect(samples, {}, ratio=3.0, recent_s=20)
        self.assertEqual(alerts[0]["kind"], "machine")


class WhatIfTest(unittest.TestCase):
    POLL = {"receipt_id": 7, "provenance": "MEASURED",
            "params": {"fast_s": 0.1, "slow_s": 2.0, "duration_s": 60.0},
            "body": {"baseline_wh": 0.002, "optimized_wh": 0.0006}}
    BATCH = {"receipt_id": 5, "provenance": "MEASURED", "params": {"jobs": 200, "batch_size": 20},
             "body": {"baseline_wh": 0.0035, "optimized_wh": 0.0002}}

    def test_polling_model_passes_through_both_measured_points(self):
        self.assertAlmostEqual(whatif.polling(self.POLL, 0.1, 8)["energy_per_window_wh"], 0.002)
        self.assertAlmostEqual(whatif.polling(self.POLL, 2.0, 8)["energy_per_window_wh"], 0.0006)
        mid = whatif.polling(self.POLL, 1.0, 8)
        self.assertFalse(mid["extrapolated"])
        self.assertTrue(whatif.polling(self.POLL, 10.0, 8)["extrapolated"])
        self.assertEqual(mid["provenance"], "ESTIMATED")
        self.assertAlmostEqual(mid["wh_per_day"], (0.002 - mid["energy_per_window_wh"]) * 8 * 60)

    def test_batching_model_passes_through_both_measured_points(self):
        self.assertAlmostEqual(whatif.batching(self.BATCH, 1, 1)["energy_per_workload_wh"], 0.0035)
        self.assertAlmostEqual(whatif.batching(self.BATCH, 20, 1)["energy_per_workload_wh"], 0.0002)
        self.assertEqual(whatif.batching(self.BATCH, 50, 1)["launches"], 4)


class GoalTest(TempDataTest):
    def test_goal_persists_and_is_queued(self):
        self.assertEqual(policy.get_goal(self.conn), "balanced")
        self.assertTrue(policy.set_goal(self.conn, "lowest"))
        self.assertFalse(policy.set_goal(self.conn, "lowest"))
        self.assertEqual(policy.get_goal(db.connect(self.db_path)), "lowest")       # survives a restart
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM outbox WHERE kind='policy'").fetchone()[0], 1)
        with self.assertRaises(ValueError):
            policy.set_goal(self.conn, "turbo")


class CascadeTest(TempDataTest):
    FACTS = {"headline": "Dropbox used about 0.62 W (ATTRIBUTED).", "action": "Pause Dropbox.", "tradeoff": "later"}

    def run_cascade(self, answers):
        calls = []

        def fake_chat(messages, model=None, **kw):
            calls.append(model)
            return client.ChatResult(answers[model], model, 20, 50, 0.01, 0.01)
        with mock.patch.object(client, "is_available", return_value=True), \
                mock.patch.object(client, "chat", side_effect=fake_chat):
            return explain.explain_cascade(self.FACTS, retries_per_model=0), calls

    def test_small_model_answers_when_it_passes_the_check(self):
        res, calls = self.run_cascade({"qwen2.5:0.5b": "Dropbox used 0.62 W.", "qwen2.5:1.5b": "unused"})
        self.assertEqual(calls, ["qwen2.5:0.5b"])
        self.assertEqual(res.model, "qwen2.5:0.5b")
        self.assertFalse(res.escalated)

    def test_escalates_only_when_the_small_model_invents_a_number(self):
        res, calls = self.run_cascade({"qwen2.5:0.5b": "Dropbox used 7.5 W.", "qwen2.5:1.5b": "Dropbox used 0.62 W."})
        self.assertEqual(calls, ["qwen2.5:0.5b", "qwen2.5:1.5b"])
        self.assertTrue(res.escalated and res.grounded)
        self.assertEqual(res.model, "qwen2.5:1.5b")
        self.assertEqual([s["grounded"] for s in res.steps], [False, True])

    def test_both_fail_falls_back_to_the_template(self):
        res, _ = self.run_cascade({"qwen2.5:0.5b": "9 W", "qwen2.5:1.5b": "8 W"})
        self.assertTrue(res.fallback and res.grounded)
        self.assertIn("template", res.model)

    def test_energy_is_metered_per_step(self):
        from joule.sensors import SimulatedSensor
        with mock.patch.object(client, "is_available", return_value=True), \
                mock.patch.object(client, "chat", return_value=client.ChatResult("Dropbox used 0.62 W.", "m", 20,
                                                                                  50, 0.01, 0.01)):
            res = explain.explain_cascade(self.FACTS, sensor=SimulatedSensor(seed=1))
        self.assertIsNotNone(res.energy_j)
        self.assertEqual(res.energy_provenance, "SIMULATED")
        rid = db.save_report(self.conn, "explanation", res.text, res.model, True, energy_j=res.energy_j,
                             energy_prov=res.energy_provenance, cascade=res.steps)
        row = self.conn.execute("SELECT energy_j, cascade_json FROM reports WHERE id=?", (rid,)).fetchone()
        self.assertAlmostEqual(row["energy_j"], res.energy_j)
        self.assertEqual(json.loads(row["cascade_json"])[0]["model"], "qwen2.5:0.5b")


if __name__ == "__main__":
    unittest.main()


class CertifyTest(TempDataTest):
    def run_certify(self, old, new, **kw):
        import sys
        from joule import certify
        from joule.sensors import SimulatedSensor
        py = f'"{sys.executable}" -c'
        return certify.certify(self.conn, "Demo app", f"{py} \"{old}\"", f"{py} \"{new}\"", SimulatedSensor(seed=3),
                               repeats=2, idle_s=0.2, interval_s=0.1, quick=True, min_seconds=0.2,
                               log=lambda *_: None, **kw)

    def test_two_versions_get_a_chained_receipt_and_label(self):
        from joule import certify
        eid, rid, body = self.run_certify("print(sum(range(300000)))", "print(44999850000)")
        self.assertEqual(body["scenario"], "certify")
        self.assertTrue(body["equivalent_work"])
        self.assertEqual(body["repeats"], 2)
        self.assertTrue(db.verify_chain(self.conn)["ok"])
        lab = label.label_for(self.conn, rid)
        self.assertIn(lab["grade"], list("ABCDEFG"))
        self.assertFalse(lab["certified"])                 # SIMULATED can never be certified
        if lab["efficiency"]:
            self.assertEqual(lab["efficiency"]["unit"], "program runs per Wh")
        self.assertTrue(certify.write_certificate(self.conn, rid).endswith(f"software-{rid}.html"))
        self.assertEqual([c["id"] for c in certify.certificates(self.conn)], [rid])
        from joule.workloads import SCENARIOS
        self.assertNotIn("certify", SCENARIOS)               # the temporary scenario is removed again

    def test_different_output_is_refused_unless_allowed(self):
        with self.assertRaises(ValueError):
            self.run_certify("print(1)", "print(2)")
        _, rid, body = self.run_certify("print(1)", "print(2)", allow_different_output=True)
        self.assertIn("NOT proven", body["tradeoff"])
        self.assertIn("outputs were allowed to differ, so equal work is not proven",
                      label.label_for(self.conn, rid)["reasons"])

    def test_a_crashing_program_is_reported(self):
        with self.assertRaises(RuntimeError):
            self.run_certify("print(1)", "raise SystemExit(3)")
