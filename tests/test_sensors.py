import unittest

from joule.provenance import Provenance
from joule.sensors import SensorUnavailable, SimulatedSensor
from joule.sensors.battery import parse_ioreg, power_from_fields, to_signed64
from joule.sensors.cpu_estimate import CpuEstimateSensor, parse_top
from joule.sensors.powermetrics import parse_powermetrics
from joule.sensors.procs import anonymize, attribute, parse_ps

IOREG = """
+-o AppleSmartBattery  <class AppleSmartBattery, id 0x100000abc, registered>
    {
      "ExternalConnected" = No
      "Voltage" = 12482
      "InstantAmperage" = 18446744073709551366
      "CurrentCapacity" = 90
      "BatteryData" = {"Voltage"=11111,"Amperage"=5}
    }
"""

POWERMETRICS = """
**** Processor usage ****
CPU Power: 1234 mW
GPU Power: 56 mW
ANE Power: 0 mW
Combined Power (CPU + GPU + ANE): 1290 mW
"""

TOP = """Processes: 500 total
CPU usage: 3.10% user, 2.00% sys, 94.90% idle
Processes: 500 total
CPU usage: 9.71% user, 7.77% sys, 82.51% idle
"""

PS = """  101  12.5 /Applications/Foo.app/Contents/MacOS/Foo Helper (Renderer)
  102   7.5 /Applications/Foo.app/Contents/MacOS/Foo Helper (Renderer)
  200   5.0 /usr/libexec/mds_stores
  300   0,0 /sbin/launchd
garbage line
"""


class SensorParsingTest(unittest.TestCase):
    def test_battery_power_from_ioreg(self):
        f = parse_ioreg(IOREG)
        self.assertEqual(f["Voltage"], 12482)               # top-level value, not the nested one
        self.assertEqual(to_signed64(f["InstantAmperage"]), -250)
        watts, on_batt = power_from_fields(f)
        self.assertAlmostEqual(watts, 12.482 * 0.25)
        self.assertTrue(on_batt)

    def test_battery_on_ac_is_not_system_power(self):
        f = parse_ioreg(IOREG.replace('"ExternalConnected" = No', '"ExternalConnected" = Yes'))
        with self.assertRaises(SensorUnavailable):
            power_from_fields(f)

    def test_powermetrics_parse(self):
        p = parse_powermetrics(POWERMETRICS)
        self.assertAlmostEqual(p["cpu"], 1.234)
        self.assertAlmostEqual(p["combined"], 1.290)
        with self.assertRaises(SensorUnavailable):
            parse_powermetrics("nothing here")

    def test_top_uses_last_sample(self):
        self.assertAlmostEqual(parse_top(TOP), 1 - 0.8251)

    def test_cpu_estimate_model(self):
        s = CpuEstimateSensor(idle_w=3.0, max_w=23.0)
        self.assertAlmostEqual(s.watts_for(0.5), 13.0)
        self.assertEqual(s.provenance, Provenance.ESTIMATED)

    def test_ps_groups_by_name_and_attribution_sums(self):
        procs = parse_ps(PS)
        self.assertEqual(procs[0], ("Foo Helper (Renderer)", 20.0))
        self.assertEqual(parse_ps(PS, exclude_pids={101})[0], ("Foo Helper (Renderer)", 7.5))
        shares = attribute(procs, cpu_power_w=5.0, power_provenance=Provenance.MEASURED)
        self.assertAlmostEqual(sum(s.watts for s in shares), 5.0)
        self.assertAlmostEqual(shares[0].watts, 5.0 * 20 / 25)
        self.assertEqual(shares[0].provenance, Provenance.ATTRIBUTED)
        est = attribute(procs, 5.0, Provenance.ESTIMATED)
        self.assertEqual(est[0].provenance, Provenance.ESTIMATED)
        self.assertNotIn("Foo", anonymize("Foo Helper", "salt"))

    def test_simulated_sensor_tracks_cpu_time(self):
        clock = iter([0.0, 1.0, 2.0])
        cpu = iter([0.0, 0.0, 2.0])                              # idle second, then 2 busy cores
        s = SimulatedSensor(idle_w=3.0, w_per_core=4.0, noise_w=0.0, clock=lambda: next(clock),
                            cpu_clock=lambda: next(cpu))
        self.assertAlmostEqual(s.read().watts, 3.0)
        self.assertAlmostEqual(s.read().watts, 11.0)
        self.assertEqual(s.provenance, Provenance.SIMULATED)


if __name__ == "__main__":
    unittest.main()
