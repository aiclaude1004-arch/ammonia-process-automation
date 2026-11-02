"""The physics that joins the sweep windows is data, not memory (2026-09-18 audit)."""
from pathlib import Path
import json
import unittest

CONFIGS = Path(__file__).resolve().parents[1] / "configs"


class PhysicalConstraintTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ranges = json.loads((CONFIGS / "operating_ranges.json").read_text(encoding="utf-8"))
        cls.q = {x["id"]: x for x in cls.ranges["quantities"]}

    def test_steam_to_carbon_is_not_shown_for_dehydrogenation(self):
        self.assertNotIn("LOHC", self.q["steam_to_carbon"]["active_when"]["S1"])

    def test_the_coupling_constraints_found_by_the_audit_are_declared(self):
        ids = {c["id"] for c in self.ranges["physical_constraints"]["constraints"]}
        self.assertTrue({"PH01", "PH02", "PH03", "PH05", "PH06"} <= ids)

    def test_the_ammonia_equilibrium_bound_rises_with_pressure(self):
        pc = {c["id"]: c for c in self.ranges["physical_constraints"]["constraints"]}
        t = pc["PH01"]["values_C"]
        self.assertLess(t["1 bar"], t["3 bar"])
        self.assertLess(t["3 bar"], t["9 bar"])
        # the literature window's lower end cannot deliver FULL conversion at any listed pressure
        low = min(v["v"] for v in self.q["nh3_cracking_T"]["values"])
        self.assertLess(low, t["1 bar"])


if __name__ == "__main__":
    unittest.main()


import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ammonia_optimizer.feasibility import check_point, load_thermo, nh3_equilibrium_conversion  # noqa: E402
from ammonia_optimizer.flowsheet import load_flowsheet  # noqa: E402
from ammonia_optimizer.superstructure import load_superstructure  # noqa: E402


class FeasibilityTest(unittest.TestCase):
    """The physics joining the optimizer bounds, evaluated before Aspen is called."""

    @classmethod
    def setUpClass(cls):
        cls.raw = json.loads((CONFIGS / "superstructure.json").read_text(encoding="utf-8"))
        cls.constraints = cls.raw["physical_constraints"]["constraints"]
        cls.thermo = load_thermo(CONFIGS / "thermo_nasa7.json")
        cls.ss = load_superstructure(CONFIGS / "superstructure.json")

    def test_equilibrium_matches_the_aspen_rgibbs_crosscheck(self):
        # C0421: Aspen RGibbs gave 0.99729 at 610 C, 3 bar
        self.assertAlmostEqual(nh3_equilibrium_conversion(self.thermo, 610.0, 3.0), 0.99729, delta=1e-3)

    def test_conversion_past_equilibrium_is_rejected(self):
        sel = {"S1": "NH3", "S2": "FULL", "S4": "SOFC", "S5": "FUELBURN"}
        bad, _ = check_point(self.constraints, self.thermo, sel,
                             {"T_cracker_C": 350, "P_reformer_bar": 20, "reformer_conversion_full": 0.995})
        good, _ = check_point(self.constraints, self.thermo, sel,
                              {"T_cracker_C": 700, "P_reformer_bar": 3, "reformer_conversion_full": 0.995})
        self.assertTrue(any(v.startswith("PC01") for v in bad))
        self.assertEqual(good, [])

    def test_a_reformer_cannot_run_hotter_than_the_stack_heating_it(self):
        sel = {"S1": "NH3", "S2": "FULL", "S4": "SOFC", "S5": "SOFCEXH"}
        bad, _ = check_point(self.constraints, self.thermo, sel,
                             {"T_cracker_C": 700, "sofc_T_C": 720, "P_reformer_bar": 1.1,
                              "reformer_conversion_full": 0.99})
        self.assertTrue(any(v.startswith("PC02") for v in bad))

    def test_direct_ammonia_needs_a_hot_stack(self):
        sel = {"S1": "NH3", "S2": "NONE", "S4": "SOFC", "S5": "NONE"}
        bad, _ = check_point(self.constraints, self.thermo, sel, {"sofc_T_C": 550})
        self.assertTrue(any(v.startswith("PC03") for v in bad))

    def test_lohc_equilibrium_is_left_to_rgibbs_not_guessed(self):
        sel = {"S1": "LOHC", "S2": "FULL", "S4": "SOFC", "S5": "FUELBURN", "LOHC_CARRIER": "MCH"}
        _, deferred = check_point(self.constraints, self.thermo, sel, {"T_mch_dehydro_C": 300})
        self.assertIn("PC04", deferred)

    def test_full_conversion_is_bounded_as_full(self):
        ov = {v["name"]: v for v in self.raw["operating_variables"]}
        self.assertGreaterEqual(ov["reformer_conversion_full"]["bounds"][0], 0.99)
        self.assertNotIn("T_reformer_C", ov)

    def test_each_run_gets_exactly_one_reformer_temperature_for_its_carrier(self):
        names = {"T_cracker_C", "T_meoh_reformer_C", "T_gly_reformer_C", "T_mch_dehydro_C", "T_dbt_dehydro_C"}
        for run in self.ss.expand_cases():
            active = {v.name for v in self.ss.operating_variables if v.is_active(run.selection)} & names
            expected = 1 if run.selection["S2"] in ("PARTIAL", "FULL") else 0
            self.assertEqual(len(active), expected, (run.case_id, active))

    def test_burner_exhaust_meets_the_aftertreatment_the_case_has(self):
        fs = load_flowsheet(CONFIGS / "flowsheet.json", self.ss)
        for run in self.ss.expand_cases():
            s = run.selection
            if s["S5"] not in ("FUELBURN", "ANODEBURN") or s["S7"] == "NONE":
                continue
            burner = "FIREDHTR" if s["S5"] == "FUELBURN" else "ANODEBURN"
            out = {st.target for st in fs.active_streams(s) if st.source == burner and st.type == "exhaust"}
            self.assertNotIn("STACK", out, run.case_id)
            self.assertTrue(out & {"SCR", "NORR_PRE"}, run.case_id)
