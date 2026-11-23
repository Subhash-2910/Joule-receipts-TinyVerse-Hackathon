import unittest

from joule import db
from joule.slm import explain, grounding
from tests.helpers import TempDataTest

FACTS = {
    "headline": "While idle, 'Dropbox' used about 0.62 W (ATTRIBUTED). Active in 58% of those seconds.",
    "observed": {"avg_attributed_w": 0.62, "active_share_pct": 58, "provenance": "ATTRIBUTED"},
    "prediction": {"saved_wh_per_day": 4.96, "saved_inr_per_month": 1.19, "saved_co2_g_per_month": 107.0},
    "model": "qwen2.5:1.5b",
}


class GroundingTest(unittest.TestCase):
    def test_grounded_text_passes(self):
        text = ("Dropbox drew 0.62 W while the laptop was idle (ATTRIBUTED), active 58% of the time. "
                "Pausing it could save 4.96 Wh per day, about INR 1.19 and 107 g CO2e per month on qwen2.5.")
        res = grounding.check(text, FACTS)
        self.assertTrue(res.grounded, res.ungrounded)

    def test_rounding_to_fewer_decimals_is_allowed(self):
        self.assertTrue(grounding.check("about 0.6 W and 5 Wh per day", FACTS).grounded)

    def test_invented_numbers_are_caught(self):
        res = grounding.check("This would save 12.5 Wh per day, 40% less.", FACTS)
        self.assertFalse(res.grounded)
        self.assertEqual(res.ungrounded, ["12.5", "40"])

    def test_names_and_list_markers_are_not_quantities(self):
        text = "1. Use CO2 data and Q4 quantization with qwen2.5.\n2. Done."
        self.assertEqual(grounding.numbers_in(text), [])


class ExplainFallbackTest(TempDataTest):
    def test_offline_slm_falls_back_to_labelled_template(self):
        res = explain.explain(FACTS | {"action": "Pause Dropbox when idle.", "tradeoff": "files sync later"})
        self.assertTrue(res.fallback)
        self.assertIn("template", res.model)
        self.assertTrue(grounding.check(res.text, FACTS).grounded)
        self.assertIn("Action: Pause Dropbox", res.text)

    def test_no_fallback_raises(self):
        from joule.slm.client import SLMUnavailable
        with self.assertRaises(SLMUnavailable):
            explain.explain(FACTS, allow_fallback=False)

    def test_report_written_offline(self):
        from joule.slm.report import build_report
        out = build_report(self.conn)
        self.assertTrue(out["grounded"])
        row = self.conn.execute("SELECT kind FROM outbox").fetchone()
        self.assertEqual(row["kind"], "report")             # reports are queued for sync too
        self.assertIn("Assumptions and formulas", open(out["path"]).read())


if __name__ == "__main__":
    unittest.main()
