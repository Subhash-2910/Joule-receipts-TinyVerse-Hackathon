import json
import unittest

from joule import db
from joule.cli import main
from joule.experiment import experiment_and_receipt
from joule.sensors import SimulatedSensor
from joule.workloads import SCENARIOS
from tests.helpers import TempDataTest


class WorkloadTest(unittest.TestCase):
    def test_batching_variants_do_identical_work(self):
        p = SCENARIOS["batching"].params(quick=True)
        a, b = SCENARIOS["batching"].baseline(p), SCENARIOS["batching"].optimized(p)
        self.assertEqual(a.checksum, b.checksum)
        self.assertEqual(a.units, p["jobs"])
        self.assertGreater(a.detail["process_launches"], b.detail["process_launches"])

    def test_pilot_is_smaller(self):
        p = SCENARIOS["batching"].params()
        pilot, factor = SCENARIOS["batching"].pilot_params(p)
        self.assertEqual(pilot["jobs"] * factor, p["jobs"])


class ExperimentTest(TempDataTest):
    def test_batching_experiment_stores_runs_and_queues_receipt(self):
        sensor = SimulatedSensor(seed=1)
        eid, rid, receipt = experiment_and_receipt(self.conn, "batching", sensor, repeats=3, quick=True,
                                                   idle_s=1.0, interval_s=0.2, log=lambda *_: None)
        self.assertEqual(receipt["provenance"], "SIMULATED")
        self.assertTrue(receipt["equivalent_work"])
        self.assertGreater(receipt["measured_saved_wh"], 0)        # fewer process launches -> less CPU time
        self.assertIsNotNone(receipt["predicted_saved_wh"])
        runs = self.conn.execute("SELECT COUNT(*) FROM experiment_runs WHERE experiment_id=?", (eid,)).fetchone()[0]
        self.assertEqual(runs, 6)
        kinds = [r["kind"] for r in self.conn.execute("SELECT kind FROM outbox")]
        self.assertEqual(kinds, ["receipt", "chain"])           # + its hash-chain entry
        # a significant receipt becomes a verified recommendation
        from joule.analytics import recommend
        recs, _ = recommend.build(self.conn)
        if receipt["significant"]:
            self.assertIn("verified:batching", [r["key"] for r in recs])


class SlowSensorTest(TempDataTest):
    def test_slow_sensor_repeats_work_and_reports_per_repetition(self):
        from joule.experiment import run_once
        sensor = SimulatedSensor(seed=2)
        p = SCENARIOS["batching"].params(quick=True)
        r = run_once(sensor, SCENARIOS["batching"].optimized, p, "optimized", 0, idle_w=3.0, interval_s=0.1,
                     min_window_s=0.5)
        self.assertGreater(r.reps, 1)
        self.assertEqual(r.detail["reps"], r.reps)
        self.assertLess(r.duration_s, 0.5)                 # per repetition, not the whole window


class CliTest(TempDataTest):
    def test_cli_commands_run_offline(self):
        self.assertEqual(main(["init"]), 0)
        self.assertEqual(main(["status"]), 0)
        self.assertEqual(main(["sense", "--source", "simulated", "--n", "1", "--interval", "0"]), 0)
        self.assertEqual(main(["queue"]), 0)
        self.assertEqual(main(["sync", "--url", "http://127.0.0.1:9"]), 0)       # offline: keeps the queue
        self.assertEqual(main(["report", "--no-slm"]), 0)


if __name__ == "__main__":
    unittest.main()
