from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ammonia_optimizer.flowsheet import load_flowsheet
from ammonia_optimizer.parameters import load_parameters
from ammonia_optimizer.superstructure import load_superstructure

CONFIGS = Path(__file__).resolve().parents[1] / "configs"
PARAMS = CONFIGS / "parameters.json"


class ParameterTableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Vocabulary comes from the expanded space; the study runs the narrow one.
        cls.vocabulary = load_superstructure(CONFIGS / "superstructure_expanded.json")
        cls.superstructure = load_superstructure(CONFIGS / "superstructure.json")
        cls.flowsheet = load_flowsheet(CONFIGS / "flowsheet.json", cls.superstructure)
        cls.parameters = load_parameters(PARAMS, cls.vocabulary, cls.flowsheet)
        cls.cases = cls.superstructure.enumerate_cases()
        cls.wide_cases = cls.vocabulary.enumerate_cases()
        # The run list: LOHC cases split into one run per carrier.
        cls.runs = cls.superstructure.expand_cases(cls.cases)

    def test_every_live_parameter_shows_in_some_run_of_this_study(self):
        """The 2026-09-11 review found rows guarded by DME, S8 and thermal storage,
        which this study does not offer. Such a row is retired with its reason,
        never left in the table where it can never appear."""
        selections = [run.selection for run in self.runs]
        for parameter in self.parameters.parameters:
            if parameter.is_retired:
                continue
            reachable = any(parameter.is_active(s) for s in selections)
            self.assertTrue(reachable, f"{parameter.parameter_id} {parameter.name} on "
                                       f"{parameter.block} never shows")

    def test_a_parameter_only_shows_when_its_unit_is_on_the_diagram(self):
        """The review counted 1,142 cases showing a value for a unit that was not
        drawn - a stack-side SOFC number in a PEM case, reagent-tank numbers with
        ammonia dosing from the fuel tank."""
        for run in self.runs:
            active = set(self.flowsheet.active_blocks(run.selection))
            for parameter in self.parameters.for_selection(run.selection):
                self.assertIn(parameter.block, active,
                              f"{run.case_id}: {parameter.parameter_id} on inactive {parameter.block}")

    def test_retired_rows_keep_their_reason_and_never_show(self):
        retired = [p for p in self.parameters.parameters if p.is_retired]
        self.assertEqual({p.parameter_id for p in retired}, {"P035", "P036", "P054", "P057", "P095"})
        raw = {item["parameter_id"]: item for item in json.loads(PARAMS.read_text(encoding="utf-8"))["parameters"]}
        for parameter in retired:
            self.assertTrue(raw[parameter.parameter_id].get("retired_because"))
            self.assertFalse(parameter.is_active({}))

    def test_every_row_has_a_stable_id_and_a_role(self):
        ids = [p.parameter_id for p in self.parameters.parameters]
        self.assertEqual(ids, [f"P{i:03d}" for i in range(1, len(ids) + 1)])
        self.assertTrue(all(p.model_role for p in self.parameters.parameters))

    def test_a_literature_system_efficiency_is_never_a_model_input(self):
        """P017 is a standalone hydrogen-fired steam cycle. It is a result to
        compare against, not a turbine efficiency to type into a bottoming cycle."""
        p017 = next(p for p in self.parameters.parameters if p.parameter_id == "P017")
        self.assertEqual(p017.model_role, "system_result")

    def test_carrier_specific_values_follow_the_carrier(self):
        by_id = {p.parameter_id: p for p in self.parameters.parameters}
        mch = {"S1": "LOHC", "S2": "FULL", "LOHC_CARRIER": "MCH"}
        dbt = {"S1": "LOHC", "S2": "FULL", "LOHC_CARRIER": "DBT"}
        for pid in ("P007", "P019", "P044"):
            self.assertEqual(by_id[pid].active_when.get("LOHC_CARRIER"), ("DBT",), pid)
            self.assertFalse(by_id[pid].is_active(mch), pid)
        self.assertEqual(by_id["P043"].active_when.get("LOHC_CARRIER"), ("MCH",))
        self.assertFalse(by_id["P043"].is_active(dbt))

    def test_the_table_is_empty_until_a_structure_is_pinned(self):
        self.assertEqual(self.parameters.for_selection({}), ())

    def test_pinning_ammonia_cracking_reveals_the_cracker_window(self):
        rows = self.parameters.for_selection({"S1": "NH3", "S2": "FULL"})
        names = {row.name for row in rows}
        self.assertIn("Cracking temperature", names)
        self.assertIn("Cracking pressure", names)
        temperature = next(row for row in rows if row.name == "Cracking temperature")
        self.assertEqual(temperature.display_value(), "400 – 650")
        self.assertEqual(temperature.unit, "°C")

    def test_a_methanol_case_does_not_show_the_ammonia_cracker_window(self):
        rows = self.parameters.for_selection({"S1": "MEOH", "S2": "FULL"})
        self.assertNotIn("Cracking pressure", {row.name for row in rows})
        self.assertIn("Reforming temperature", {row.name for row in rows})

    def test_unsourced_parameters_render_blank_rather_than_guessed(self):
        blank = [p for p in self.parameters.parameters if not p.is_sourced]
        self.assertTrue(blank, "the set should still be honest about what is unresearched")
        for parameter in blank:
            self.assertEqual(parameter.display_value(), "")
            self.assertTrue(parameter.note)

    def test_every_stated_number_carries_a_resolvable_source(self):
        for parameter in self.parameters.parameters:
            if parameter.display_value():
                self.assertIsNotNone(parameter.source, parameter.name)
                self.assertIn(parameter.source, self.parameters.sources)

    def test_coverage_reports_the_sourced_fraction(self):
        sourced, total = self.parameters.coverage([c.selection for c in self.cases])
        self.assertGreater(total, 0)
        self.assertLessEqual(sourced, total)

    def _load_mutated(self, mutate):
        raw = json.loads(PARAMS.read_text(encoding="utf-8"))
        mutate(raw)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(raw, handle)
            path = handle.name
        try:
            return load_parameters(path, self.vocabulary, self.flowsheet)
        finally:
            Path(path).unlink()

    def test_a_value_without_a_source_is_refused(self):
        def strip_source(raw):
            raw["parameters"][0]["source"] = None
        with self.assertRaises(ValueError):
            self._load_mutated(strip_source)

    def test_a_parameter_on_an_unknown_block_is_refused(self):
        def rename(raw):
            raw["parameters"][0]["block"] = "FLUX_CAPACITOR"
        with self.assertRaises(ValueError):
            self._load_mutated(rename)


class ExpandedSuperstructureTest(unittest.TestCase):
    """The literature-expanded space is kept loadable so it can be compared, not lost."""

    @classmethod
    def setUpClass(cls):
        # Two million combinations: enumerate once for the whole class.
        cls.expanded = load_superstructure(CONFIGS / "superstructure_expanded.json")
        cls.cases = cls.expanded.enumerate_cases()

    def test_it_is_a_strict_superset_of_the_current_study(self):
        current = load_superstructure(CONFIGS / "superstructure.json")
        self.assertGreater(len(self.expanded.nodes), len(current.nodes))
        self.assertGreater(len(self.cases), len(current.enumerate_cases()))

    def test_capture_only_appears_on_a_carbon_bearing_feed(self):
        carbon = {"MEOH", "GLY", "LNG", "LPG", "DME"}
        for case in self.cases:
            if case.selection["S8"] != "NONE":
                self.assertIn(case.selection["S1"], carbon, case.label)
            if case.selection["S1"] in {"NH3", "LOHC", "LH2"}:
                self.assertEqual(case.selection["S8"], "NONE", case.label)

    def test_an_autothermal_reformer_is_not_given_an_external_heat_source(self):
        for case in self.cases:
            if case.selection["S2"] == "ATR":
                self.assertEqual(case.selection["S5"], "NONE", case.label)

    def test_a_membrane_reactor_needs_no_separate_purifier(self):
        """It performs the separation itself, so a downstream purifier is dead weight."""
        found = False
        for case in self.cases:
            if case.selection["S2"] == "MEMBRXN":
                found = True
                self.assertEqual(case.selection["S3"], "NONE", case.label)
                self.assertEqual(case.selection["S1"], "NH3", case.label)
                self.assertNotEqual(case.selection["S5"], "NONE", case.label)
        self.assertTrue(found)

    def test_anode_recirculation_requires_a_fuel_cell(self):
        for case in self.cases:
            if case.selection["S10"] != "NONE":
                self.assertIn(case.selection["S4"], {"SOFC", "HYB", "PCFC"}, case.label)


if __name__ == "__main__":
    unittest.main()


class LiteratureIntegrityTest(unittest.TestCase):
    """The reference list is judged on composition and honesty, not on length."""

    @classmethod
    def setUpClass(cls):
        vocabulary = load_superstructure(CONFIGS / "superstructure_expanded.json")
        superstructure = load_superstructure(CONFIGS / "superstructure.json")
        flowsheet = load_flowsheet(CONFIGS / "flowsheet.json", superstructure)
        cls.parameters = load_parameters(PARAMS, vocabulary, flowsheet)
        cls.protocol = json.loads(
            (CONFIGS / "literature_protocol.json").read_text(encoding="utf-8")
        )

    def test_every_source_declares_a_type(self):
        for source in self.parameters.sources.values():
            self.assertTrue(source.type, source.key)

    def test_peer_reviewed_work_is_at_least_half_the_list(self):
        types = [s.type for s in self.parameters.sources.values()]
        peer = sum(t == "peer-reviewed" for t in types)
        self.assertGreaterEqual(peer * 2, len(types))

    def test_conclusion_bearing_values_are_corroborated(self):
        """N2O decides whether ammonia beats the fossil baseline at all."""
        decisive = [p for p in self.parameters.parameters if p.name.startswith("N2O")]
        self.assertTrue(decisive)
        uncorroborated = [p.name for p in decisive if not p.is_corroborated]
        self.assertNotIn("N2O, measured range", uncorroborated)

    def test_corroboration_never_cites_the_primary_source_again(self):
        for parameter in self.parameters.parameters:
            self.assertNotIn(parameter.source, parameter.corroborated_by, parameter.name)

    def test_the_screening_funnel_adds_up(self):
        """The screen has now been run, so its arithmetic is the thing to guard.

        A funnel whose stages do not reconcile is a funnel someone edited by
        hand, and a reader cannot tell which number to trust.
        """
        s = self.protocol["screening"]
        self.assertEqual(
            s["records_identified"] - s["duplicates_removed"], s["title_abstract_screened"])
        self.assertEqual(
            s["included_after_title_screen"] + s["held_pending_abstract"]
            + s["excluded_at_screening"], s["title_abstract_screened"])
        self.assertLessEqual(s["abstracts_read"], s["abstracts_retrieved"])
        self.assertLessEqual(s["abstracts_retrieved"], s["included_after_title_screen"])
        # Registry entries that no row and no sample value points to are kept, flagged
        # "unreferenced", and not counted as cited (2026-09-18 review).
        self.assertEqual(s["records_cited"] + s.get("records_registered_unreferenced", 0),
                         len(self.parameters.sources))

    def test_the_protocol_says_the_unread_records_are_unread(self):
        """Six thousand records passed the title screen; eighty-four were read.

        Nothing stops someone quoting the larger number as though it were the
        reference list, so the protocol has to say plainly that it is not.
        """
        note = self.protocol["screening"]["note"].lower()
        self.assertIn("unread", note)
        self.assertIn("must not be cited", note)
        self.assertLess(
            self.protocol["screening"]["records_cited"],
            self.protocol["screening"]["included_after_title_screen"])


class ReferenceSpanTest(unittest.TestCase):
    """Foundational work counts. A list confined to the last few years is a red flag."""

    @classmethod
    def setUpClass(cls):
        vocabulary = load_superstructure(CONFIGS / "superstructure_expanded.json")
        superstructure = load_superstructure(CONFIGS / "superstructure.json")
        flowsheet = load_flowsheet(CONFIGS / "flowsheet.json", superstructure)
        cls.parameters = load_parameters(PARAMS, vocabulary, flowsheet)

    def test_the_list_reaches_back_to_the_foundational_era(self):
        oldest, newest = self.parameters.year_span()
        self.assertLessEqual(oldest, 2010, "no work older than 2010 is cited")
        self.assertGreaterEqual(newest, 2025)

    def test_a_real_share_of_the_list_predates_the_recent_wave(self):
        years = [s.year for s in self.parameters.sources.values()]
        self.assertGreaterEqual(sum(y < 2020 for y in years), 8)

    def test_every_source_carries_a_plausible_year(self):
        for source in self.parameters.sources.values():
            self.assertGreaterEqual(source.year, 2000, source.key)
            self.assertLessEqual(source.year, 2026, source.key)
