import unittest

from joule import energy
from joule.config import Assumptions
from joule.provenance import Provenance, combine


class EnergyTest(unittest.TestCase):
    def test_constant_power_integrates_to_wh(self):
        samples = [(t, 36.0) for t in range(0, 101)]          # 36 W for 100 s = 1 Wh
        self.assertAlmostEqual(energy.integrate_wh(samples), 1.0, places=9)
        self.assertAlmostEqual(energy.mean_power(samples), 36.0)

    def test_trapezoid_on_a_ramp_and_unsorted_input(self):
        samples = [(10, 20.0), (0, 0.0)]                      # ramp 0->20 W over 10 s: 100 J
        self.assertAlmostEqual(energy.integrate_wh(samples), 100 / 3600)

    def test_net_cost_co2(self):
        a = Assumptions(tariff_inr_per_kwh=10.0, grid_kg_per_kwh=0.5)
        self.assertAlmostEqual(energy.net_wh(2.0, 36.0, 100), 1.0)
        self.assertAlmostEqual(energy.cost_inr(1000, a), 10.0)          # 1 kWh
        self.assertAlmostEqual(energy.co2_g(1000, a), 500.0)

    def test_compare_flags_significance(self):
        clear = energy.compare([10.0, 10.1, 9.9, 10.2, 9.8], [5.0, 5.1, 4.9, 5.2, 4.8])
        self.assertTrue(clear["significant"])
        self.assertAlmostEqual(clear["p_value"], 2 / 252)       # exact: the most extreme of C(10,5) splits
        self.assertAlmostEqual(clear["saved_wh"], 5.0)
        self.assertAlmostEqual(clear["saved_pct"], 50.0)
        noisy = energy.compare([10, 2, 18], [9, 1, 17])
        self.assertFalse(noisy["significant"])

    def test_one_disturbed_run_does_not_flip_the_verdict(self):
        base = [2.7, 2.9, 2.6, 2.8, 2.6]
        calm = energy.compare(base, [0.10, 0.12, 0.11, 0.13, 0.09])
        disturbed = energy.compare(base, [0.10, 0.12, 0.11, 2.5, 0.09])   # run 4 disturbed by another app
        self.assertAlmostEqual(calm["saved_wh"], disturbed["saved_wh"])    # the median ignores the outlier
        self.assertTrue(disturbed["significant"])                          # all 5 still rank below baseline
        self.assertGreater(abs(calm["saved_wh_mean"] - disturbed["saved_wh_mean"]), 0.4)  # the mean does not
        self.assertAlmostEqual(disturbed["saved_wh"], 2.7 - 0.11)

    def test_provenance_weakest_wins(self):
        self.assertEqual(combine(Provenance.MEASURED, "ATTRIBUTED"), Provenance.ATTRIBUTED)
        self.assertEqual(combine("MEASURED", "SIMULATED", "ESTIMATED"), Provenance.SIMULATED)
        self.assertEqual(str(Provenance.MEASURED), "MEASURED")


if __name__ == "__main__":
    unittest.main()
