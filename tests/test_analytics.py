import random
import time
import unittest
from itertools import combinations

from joule import db
from joule.analytics import apriori, markov, recommend
from joule.analytics.power_model import fit_linear
from joule.provenance import Provenance
from joule.sensors.base import PowerReading
from joule.sensors.procs import ProcShare
from tests.helpers import TempDataTest


class AprioriTest(unittest.TestCase):
    def test_matches_brute_force(self):
        rng = random.Random(1)
        items = list("abcdef")
        tx = [set(rng.sample(items, rng.randint(1, 4))) for _ in range(200)]
        got = apriori.apriori(tx, 0.1, max_len=3)
        for size in (1, 2, 3):
            for combo in combinations(items, size):
                s = apriori.support(frozenset(combo), tx)
                if s >= 0.1:
                    self.assertAlmostEqual(got[frozenset(combo)], s)
                else:
                    self.assertNotIn(frozenset(combo), got)

    def test_contrast_finds_spike_set(self):
        high = [{"sync", "indexer", "x"} for _ in range(20)]
        everything = high + [{"x"} for _ in range(80)] + [{"sync"} for _ in range(10)]
        found = {tuple(c["items"]): c for c in apriori.contrast(high, everything, min_support=0.5)}
        self.assertIn(("indexer", "sync"), found)
        self.assertGreater(found[("indexer", "sync")]["lift"], 4)          # 100% of spikes vs 18% overall
        self.assertNotIn(("x",), found)                                    # singletons are not reported


class MarkovTest(unittest.TestCase):
    def test_states_and_matrix(self):
        self.assertEqual(markov.classify(3.2, 3.0), "idle")
        self.assertEqual(markov.classify(12.0, 3.0), "heavy")
        m = markov.transition_matrix(["idle"] * 50 + ["busy"] + ["idle"] * 50)
        for row in m.values():
            self.assertAlmostEqual(sum(row.values()), 1.0)
        self.assertGreater(m["idle"]["idle"], 0.9)
        self.assertGreater(markov.p_reach_within(m, "busy", "idle", 5), 0.5)
        self.assertEqual(markov.bursts(["idle", "busy", "busy", "idle", "light", "idle"]), [2, 1])


class KnowledgeTest(unittest.TestCase):
    def test_helpers_group_and_system_advice_is_feasible(self):
        from joule.analytics import knowledge
        self.assertEqual(knowledge.app_of("Google Chrome Helper (Renderer)"), "Google Chrome")
        self.assertEqual(knowledge.app_of("Code Helper (Plugin)"), "Visual Studio Code")
        self.assertIsNone(knowledge.app_of("kernel_task"))
        self.assertNotIn("Quit", knowledge.advice_for("WindowServer")["action"])
        self.assertIn("Spotlight", knowledge.advice_for(knowledge.app_of("mds_stores"))["action"])


class PowerModelTest(unittest.TestCase):
    def test_fit_linear(self):
        fit = fit_linear([0, 0.5, 1.0], [3.0, 13.0, 23.0])
        self.assertAlmostEqual(fit["slope"], 20.0)
        self.assertAlmostEqual(fit["intercept"], 3.0)
        self.assertAlmostEqual(fit["r2"], 1.0)


class RecommendTest(TempDataTest):
    def _fill(self, n=300):
        rng = random.Random(3)
        t0 = time.time() - n
        for i in range(n):
            spike = i % 30 < 3                       # short burst every 30 s
            watts = (9.0 if spike else 3.0) + rng.gauss(0, 0.05)
            procs = [ProcShare("Dropbox", 6.0, 0.6, Provenance.ATTRIBUTED)]
            if spike:
                procs += [ProcShare("mds_stores", 40.0, 3.0, Provenance.ATTRIBUTED),
                          ProcShare("backupd", 30.0, 2.0, Provenance.ATTRIBUTED)]
            db.insert_sample(self.conn, PowerReading(t0 + i, watts, "test", Provenance.MEASURED), "s1", procs)

    def test_recommendations_have_facts_predictions_and_review_flags(self):
        self._fill()
        ids, summary = recommend.refresh(self.conn)
        recs = db.list_recommendations(self.conn)
        kinds = {r["kind"] for r in recs}
        self.assertIn("background", kinds)
        self.assertIn("batching", kinds)
        self.assertIn("coactive", kinds)
        bg = next(r for r in recs if r["key"] == "background:cloud file sync")
        self.assertAlmostEqual(bg["facts"]["observed"]["avg_w"], 0.6, places=2)
        self.assertIn("Pause syncing", bg["action"])
        self.assertEqual(bg["facts"]["prediction"]["provenance"], "ESTIMATED")
        self.assertAlmostEqual(bg["facts"]["prediction"]["saved_wh_per_day"], 4.8, places=1)
        n_pred = self.conn.execute("SELECT COUNT(*) FROM predictions WHERE rec_id=?", (bg["id"],)).fetchone()[0]
        self.assertEqual(n_pred, 2)
        batching = next(r for r in recs if r["kind"] == "batching")
        self.assertTrue(batching["needs_review"])          # no measured batching saving yet
        self.assertGreater(summary["short_bursts_per_hour"], 100)
        # refreshing again does not duplicate recommendations
        recommend.refresh(self.conn)
        self.assertEqual(len(db.list_recommendations(self.conn)), len(recs))


if __name__ == "__main__":
    unittest.main()
