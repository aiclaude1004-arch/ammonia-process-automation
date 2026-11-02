from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ammonia_optimizer.physics import check_physical_consistency
from ammonia_optimizer.spec import load_case_spec


class PhysicsChecksTest(unittest.TestCase):
    def setUp(self):
        self.spec = load_case_spec(Path(__file__).resolve().parents[1] / "configs" / "baseline.json")
        self.results = {
            "net_power_kw": 120.0,
            "nh3_feed_kg_h": 45.0,
            "nox_mg_per_nm3": 50.0,
            "energy_in_kw": 1000.0,
            "energy_out_kw": 995.0,
            "min_temperature_approach_c": 12.0,
            "min_pressure_bar": 1.2,
        }

    def test_balanced_feasible_case(self):
        report = check_physical_consistency(
            self.results, {"H": 100.0, "N": 50.0, "O": 80.0}, {"H": 100.0, "N": 50.0, "O": 80.0}, self.spec.constraints
        )
        self.assertTrue(report.feasible)

    def test_unbalanced_case_is_rejected(self):
        report = check_physical_consistency(
            self.results, {"H": 100.0, "N": 50.0, "O": 80.0}, {"H": 99.0, "N": 50.0, "O": 80.0}, self.spec.constraints
        )
        self.assertFalse(report.feasible)
        self.assertIn("H balance", " ".join(report.violations))


if __name__ == "__main__":
    unittest.main()
