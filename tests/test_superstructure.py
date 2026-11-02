from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ammonia_optimizer.schema import blank_row, build_columns
from ammonia_optimizer.superstructure import load_superstructure

CONFIG = Path(__file__).resolve().parents[1] / "configs" / "superstructure.json"


class SuperstructureTest(unittest.TestCase):
    def setUp(self):
        self.superstructure = load_superstructure(CONFIG)
        self.cases = self.superstructure.enumerate_cases()

    def test_enumeration_is_a_strict_subset_and_non_empty(self):
        self.assertGreater(len(self.cases), 0)
        self.assertLess(len(self.cases), self.superstructure.full_factorial_size())

    def test_case_ids_and_selections_are_unique(self):
        self.assertEqual(len({case.case_id for case in self.cases}), len(self.cases))
        self.assertEqual(len({case.label for case in self.cases}), len(self.cases))

    def test_every_case_satisfies_every_cut(self):
        for case in self.cases:
            self.assertEqual(self.superstructure.rejections(case.selection), ())

    def test_reformer_is_never_left_unheated(self):
        for case in self.cases:
            if case.selection["S2"] in {"PARTIAL", "FULL"}:
                self.assertNotEqual(case.selection["S5"], "NONE", case.label)
            else:
                self.assertEqual(case.selection["S5"], "NONE", case.label)

    def test_aftertreatment_only_where_there_is_a_flame(self):
        for case in self.cases:
            has_engine = case.selection["S4"] in {"ICE", "HYB"}
            has_aftertreatment = case.selection["S7"] != "NONE"
            self.assertEqual(has_engine, has_aftertreatment, case.label)

    def test_norr_only_closes_a_loop_on_ammonia_feed(self):
        for case in self.cases:
            if case.selection["S7"] == "NORR":
                self.assertEqual(case.selection["S1"], "NH3", case.label)

    def test_low_temperature_cells_get_purified_hydrogen(self):
        """A carrier must be fully reformed and cleaned up; liquid hydrogen must not."""
        for case in self.cases:
            if case.selection["S4"] not in {"PEMFC", "HTPEM"}:
                continue
            self.assertIn(case.selection["S6"], {"NONE", "ORC"}, case.label)
            if case.selection["S1"] == "LH2":
                self.assertEqual(case.selection["S2"], "NONE", case.label)
                self.assertEqual(case.selection["S3"], "NONE", case.label)
            else:
                self.assertEqual(case.selection["S2"], "FULL", case.label)
                self.assertIn(case.selection["S3"], {"PSA", "MEMB"}, case.label)

    def test_liquid_hydrogen_can_feed_a_pem_cell(self):
        """The most natural pairing in the whole space; an early cut wrongly removed it."""
        pairings = {
            (case.selection["S1"], case.selection["S4"])
            for case in self.cases
            if case.selection["S1"] == "LH2"
        }
        self.assertIn(("LH2", "PEMFC"), pairings)
        self.assertIn(("LH2", "HTPEM"), pairings)

    def test_anode_recirculation_requires_a_fuel_cell(self):
        """A blower or a compressor needs an anode to recycle from."""
        found = False
        for case in self.cases:
            if case.selection["S10"] != "NONE":
                found = True
                self.assertIn(case.selection["S4"], {"SOFC", "HYB"}, case.label)
        self.assertTrue(found)

    def test_baseline_topology_survives_enumeration(self):
        baseline = {
            "S1": "NH3", "S2": "FULL", "S3": "NONE", "S4": "HYB",
            "S5": "SOFCEXH", "S6": "CASC", "S7": "NORR", "S10": "BLOWER",
        }
        self.assertTrue(self.superstructure.is_feasible(baseline))
        self.assertIn(baseline, [dict(case.selection) for case in self.cases])

    def test_rejection_names_the_cut_and_explains_itself(self):
        unheated = {
            "S1": "NH3", "S2": "FULL", "S3": "NONE", "S4": "SOFC",
            "S5": "NONE", "S6": "ORC", "S7": "NONE", "S10": "NONE",
        }
        reasons = self.superstructure.rejections(unheated)
        self.assertTrue(any(reason.startswith("LC06") for reason in reasons), reasons)

    def test_active_variables_track_the_selected_options(self):
        for case in self.cases:
            active = set(case.active_variables)
            self.assertEqual("norr_faradaic_efficiency" in active, case.selection["S7"] == "NORR")
            self.assertEqual("fc_power_fraction" in active, case.selection["S4"] == "HYB")
            if case.selection["S6"] == "NONE":
                self.assertNotIn("bottoming_pinch_C", active)


class HandOffSchemaTest(unittest.TestCase):
    def setUp(self):
        self.superstructure = load_superstructure(CONFIG)
        self.columns = build_columns(self.superstructure)

    def test_column_names_are_unique(self):
        names = [column.name for column in self.columns]
        self.assertEqual(len(set(names)), len(names))

    def test_every_operating_variable_has_a_column(self):
        names = {column.name for column in self.columns}
        for variable in self.superstructure.operating_variables:
            self.assertIn(variable.name, names)

    def test_blank_row_leaves_results_empty_not_zero(self):
        case = self.superstructure.enumerate_cases()[0]
        row = blank_row(case, self.superstructure)
        self.assertEqual(set(row), {column.name for column in self.columns})
        self.assertEqual(row["case_id"], case.case_id)
        self.assertEqual(row["W_net_kW"], "")
        self.assertEqual(row["eta_net_LHV"], "")
        self.assertEqual(row["converged"], 0)

    def test_inactive_operating_variables_stay_empty(self):
        engine_only = next(case for case in self.superstructure.enumerate_cases() if case.selection["S4"] == "ICE")
        row = blank_row(engine_only, self.superstructure)
        self.assertEqual(row["fc_power_fraction"], "")
        self.assertEqual(row["S4_prime_mover"], "ICE")


if __name__ == "__main__":
    unittest.main()
