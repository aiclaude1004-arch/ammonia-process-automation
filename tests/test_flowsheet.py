from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ammonia_optimizer.flowsheet import SINK, SOURCE, State, load_flowsheet
from ammonia_optimizer.superstructure import load_superstructure

CONFIGS = Path(__file__).resolve().parents[1] / "configs"


class FlowsheetTest(unittest.TestCase):
    def setUp(self):
        self.superstructure = load_superstructure(CONFIGS / "superstructure.json")
        self.flowsheet = load_flowsheet(CONFIGS / "flowsheet.json", self.superstructure)
        self.cases = self.superstructure.enumerate_cases()

    def test_every_case_is_a_connected_path_from_tank_to_propeller(self):
        """The diagram's correctness test: no orphaned unit, no unreachable sink."""
        faults = {
            case.case_id: self.flowsheet.check_connectivity(case.selection)
            for case in self.cases
        }
        broken = {case_id: reasons for case_id, reasons in faults.items() if reasons}
        self.assertEqual(broken, {})

    def test_source_and_sink_are_active_in_every_case(self):
        for case in self.cases:
            active = set(self.flowsheet.active_blocks(case.selection))
            self.assertIn(SOURCE, active, case.label)
            self.assertIn(SINK, active, case.label)

    def test_a_complete_selection_activates_exactly_one_prime_mover_path(self):
        for case in self.cases:
            active = set(self.flowsheet.active_blocks(case.selection))
            cells = active & {"SOFC", "HTPEM", "PEMFC"}
            self.assertLessEqual(len(cells), 1, case.label)
            if case.selection["S4"] == "HYB":
                self.assertIn("SOFC", active, case.label)
                self.assertIn("ENGINE", active, case.label)

    def test_nothing_pinned_leaves_no_block_eliminated(self):
        blocks, streams = self.flowsheet.states([case.selection for case in self.cases])
        self.assertNotIn(State.ELIMINATED, blocks.values())
        self.assertNotIn(State.ELIMINATED, streams.values())

    def test_no_block_or_stream_is_unreachable_in_principle(self):
        """A route the logic cuts make impossible is dead ink; the diagram may not carry it."""
        selections = [case.selection for case in self.cases]
        dead_blocks = [b.id for b in self.flowsheet.blocks if not any(b.is_active(s) for s in selections)]
        dead_streams = [s.id for s in self.flowsheet.streams if not any(s.is_active(x) for x in selections)]
        self.assertEqual(dead_blocks, [])
        self.assertEqual(dead_streams, [])

    def test_pinning_a_solid_oxide_stack_eliminates_the_membrane_units(self):
        remaining = [c.selection for c in self.cases if c.selection["S4"] == "SOFC"]
        blocks, _ = self.flowsheet.states(remaining)
        self.assertEqual(blocks["PEMFC"], State.ELIMINATED)
        self.assertEqual(blocks["HTPEM"], State.ELIMINATED)
        self.assertEqual(blocks["PSA"], State.ELIMINATED)
        self.assertEqual(blocks["SOFC"], State.ACTIVE)
        self.assertEqual(blocks["ENGINE"], State.ELIMINATED)

    def test_a_single_case_leaves_no_block_merely_possible(self):
        one = [self.cases[0].selection]
        blocks, streams = self.flowsheet.states(one)
        self.assertNotIn(State.POSSIBLE, blocks.values())
        self.assertNotIn(State.POSSIBLE, streams.values())

    def test_reformer_label_follows_the_feed(self):
        reformer = self.flowsheet.block("REFORMER")
        self.assertEqual(reformer.label_for({"S1": "NH3"}), "NH3 cracker")
        self.assertEqual(reformer.label_for({"S1": "GLY"}), "Glycerol SR")
        self.assertEqual(reformer.label_for({}), reformer.label)

    def test_loader_rejects_a_predicate_naming_an_unknown_option(self):
        import json
        import tempfile

        raw = json.loads((CONFIGS / "flowsheet.json").read_text(encoding="utf-8"))
        raw["blocks"][0]["active_when"] = {"S4": ["TURBOENCABULATOR"]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(raw, handle)
            path = handle.name
        with self.assertRaises(ValueError):
            load_flowsheet(path, self.superstructure)
        Path(path).unlink()


if __name__ == "__main__":
    unittest.main()


class LabMeetingReviewTest(unittest.TestCase):
    """The 2026-09-04 review asked what each questioned block was for."""

    @classmethod
    def setUpClass(cls):
        cls.superstructure = load_superstructure(CONFIGS / "superstructure.json")
        cls.flowsheet = load_flowsheet(CONFIGS / "flowsheet.json", cls.superstructure)
        cls.cases = cls.superstructure.enumerate_cases()

    def test_power_leaves_through_one_outlet(self):
        ids = {block.id for block in self.flowsheet.blocks}
        self.assertIn("POWER", ids)
        self.assertNotIn("PROP", ids)
        self.assertNotIn("AUX", ids)

    def test_an_ammonia_ship_carries_no_second_reagent_tank(self):
        """It doses SCR from its own fuel tank, so the extra tank was duplicate kit."""
        reagent = self.flowsheet.block("REAGENT")
        for case in self.cases:
            if case.selection["S1"] != "NH3":
                continue
            self.assertFalse(reagent.is_active(case.selection), case.label)
            if case.selection["S7"] in {"SCR", "SCR_ASC"}:
                streams = {(s.source, s.target) for s in self.flowsheet.active_streams(case.selection)}
                self.assertIn(("TANK", "SCR"), streams, case.label)

    def test_a_non_ammonia_feed_still_needs_its_own_reagent(self):
        reagent = self.flowsheet.block("REAGENT")
        self.assertTrue(any(reagent.is_active(c.selection) for c in self.cases))

    def test_carbon_and_water_leave_the_reformate_drum(self):
        """Carbon was vanishing from the diagram and condensate was not recovered."""
        carbon_cases = [c for c in self.cases if c.selection["S1"] in {"MEOH", "GLY"}
                        and c.selection["S2"] in {"PARTIAL", "FULL"}]
        self.assertTrue(carbon_cases)
        for case in carbon_cases:
            streams = {(s.source, s.target) for s in self.flowsheet.active_streams(case.selection)}
            self.assertIn(("COND", "STACK"), streams, case.label)
            self.assertIn(("COND", "STEAMGEN"), streams, case.label)

    def test_every_questioned_block_states_why_it_is_there(self):
        for block_id in ("ANODEBURN", "ASC", "SCR", "COND", "REAGENT", "SWCOND", "POWER"):
            self.assertTrue(self.flowsheet.block(block_id).rationale, block_id)


class LayoutTest(unittest.TestCase):
    """Coordinates are placed by hand, so nothing stops two blocks landing on
    each other. One did: the recycle unit was dropped onto the air blower."""

    @classmethod
    def setUpClass(cls):
        cls.superstructure = load_superstructure(CONFIGS / "superstructure.json")
        cls.flowsheet = load_flowsheet(CONFIGS / "flowsheet.json", cls.superstructure)

    def test_no_two_blocks_overlap(self):
        width = self.flowsheet.canvas["block_width"]
        height = self.flowsheet.canvas["block_height"]
        blocks = self.flowsheet.blocks
        for i, a in enumerate(blocks):
            for b in blocks[i + 1:]:
                touching = abs(a.x - b.x) < width + 10 and abs(a.y - b.y) < height + 8
                self.assertFalse(touching, f"{a.id} and {b.id} overlap on the canvas")

    def test_every_block_fits_inside_the_canvas(self):
        width = self.flowsheet.canvas["block_width"]
        height = self.flowsheet.canvas["block_height"]
        for block in self.flowsheet.blocks:
            self.assertGreaterEqual(block.x, 0, block.id)
            self.assertGreaterEqual(block.y, 0, block.id)
            self.assertLessEqual(block.x + width, self.flowsheet.canvas["width"], block.id)
            self.assertLessEqual(block.y + height, self.flowsheet.canvas["height"], block.id)


REVIEW = Path(__file__).resolve().parent / "fixtures" / "case_review_20260911"


class Review20260911Test(unittest.TestCase):
    """What the 2026-09-11 external review asked the diagram to guarantee.

    Each check here failed, or could not be stated, against the pre-review
    configs kept in backups/v1_pre_review_20260911.
    """

    @classmethod
    def setUpClass(cls):
        cls.superstructure = load_superstructure(CONFIGS / "superstructure.json")
        cls.flowsheet = load_flowsheet(CONFIGS / "flowsheet.json", cls.superstructure)
        cls.cases = cls.superstructure.enumerate_cases()
        cls.runs = cls.superstructure.expand_cases(cls.cases)

    def streams_of(self, selection):
        return self.flowsheet.active_streams(selection)

    def test_every_run_is_connected_with_no_dangling_stream(self):
        """315 dangling stream instances in 285 cases before the review."""
        broken = {r.case_id: f for r in self.runs if (f := self.flowsheet.check_connectivity(r.selection))}
        self.assertEqual(broken, {})

    def test_every_active_unit_has_an_inlet_and_an_outlet(self):
        """Boundaries supply or discharge; every piece of equipment must pass
        something on, or its outlet has silently vanished."""
        # The seawater condenser rejects heat overboard; the stack and the power
        # boundary are where exhaust and work leave.
        sinks = {"STACK", "POWER", "SWCOND"}
        for run in self.runs:
            streams = self.streams_of(run.selection)
            outs = {s.source for s in streams}
            ins = {s.target for s in streams}
            for block_id in self.flowsheet.active_blocks(run.selection):
                block = self.flowsheet.block(block_id)
                # The fuel tank and the reagent tank are filled in port.
                if block.kind == "boundary" or block_id in {"TANK", "REAGENT"}:
                    continue
                self.assertIn(block_id, ins, f"{run.case_id}: {block_id} has no inlet")
                if block_id not in sinks:
                    self.assertIn(block_id, outs, f"{run.case_id}: {block_id} has no outlet")

    def test_the_series_hybrid_feeds_its_engine_from_the_anode_off_gas_only(self):
        """Reformate to both stack and engine counted the same hydrogen twice."""
        reformate = {"REFORMER", "COND", "LOHC_SEP", "PSA", "MEMB"}
        hybrids = [r for r in self.runs if r.selection["S4"] == "HYB"]
        self.assertEqual(len({r.parent_id for r in hybrids}), 825)
        for run in hybrids:
            into_engine = {s.source for s in self.streams_of(run.selection) if s.target == "ENGINE"}
            self.assertIn("AOG_SPLITTER", into_engine, run.case_id)
            self.assertFalse(into_engine & reformate, f"{run.case_id}: {into_engine & reformate}")

    def test_the_anode_outlet_is_split_not_copied(self):
        for run in self.runs:
            if run.selection["S4"] not in {"SOFC", "HYB"}:
                continue
            from_stack = [s for s in self.streams_of(run.selection)
                          if s.source == "SOFC" and s.type == "h2"]
            self.assertEqual([s.target for s in from_stack], ["AOG_SPLITTER"], run.case_id)
            outlets = [s for s in self.streams_of(run.selection) if s.source == "AOG_SPLITTER"]
            self.assertIn("STACK", {s.target for s in outlets}, f"{run.case_id}: no purge")

    def test_lohc_hydrogen_leaves_through_the_carrier_separator(self):
        lohc = [r for r in self.runs if r.selection["S1"] == "LOHC"]
        self.assertEqual(len(lohc), 2 * 296)
        for run in lohc:
            streams = self.streams_of(run.selection)
            from_reactor = {s.target for s in streams if s.source == "REFORMER" and s.type == "h2"}
            self.assertEqual(from_reactor, {"LOHC_SEP"}, run.case_id)
            self.assertIn(("LOHC_SEP", "CARRIER"), {(s.source, s.target) for s in streams}, run.case_id)
            label = self.flowsheet.block("LOHC_SEP").label_for(run.selection)
            self.assertIn(run.selection["LOHC_CARRIER"][:1], label.replace("H0-DBT", "D"))

    def test_nox_electrolysis_neither_takes_raw_exhaust_nor_returns_wet_ammonia(self):
        for run in self.runs:
            if run.selection["S7"] != "NORR":
                continue
            pairs = {(s.source, s.target) for s in self.streams_of(run.selection)}
            self.assertNotIn(("ENGINE", "NORR"), pairs)
            self.assertNotIn(("NORR", "TANK"), pairs)
            self.assertLessEqual({("ENGINE", "NORR_PRE"), ("NORR_PRE", "NORR"),
                                  ("NORR", "NH3REC"), ("NH3REC", "TANK")}, pairs)

    def test_retired_streams_are_gone_and_recorded(self):
        import json
        raw = json.loads((CONFIGS / "flowsheet.json").read_text(encoding="utf-8"))
        retired = raw["review"]["2026-09-11"]["retired_streams"]
        self.assertEqual(set(retired), {"E014", "E052", "E058", "E077"})
        self.assertFalse(set(retired) & {s.sid for s in self.flowsheet.streams})
        self.assertTrue(all(s.sid for s in self.flowsheet.streams))

    def test_cut_kinds_separate_dependencies_from_scope(self):
        kinds = {cut.id: cut.kind for cut in self.superstructure.logic_cuts}
        scope = {k for k, v in kinds.items() if v == "scope"}
        self.assertEqual(scope, {"LC03", "LC04", "LC09", "LC10", "LC11", "LC12", "LC14", "LC15"})
        for cut in self.superstructure.logic_cuts:
            if cut.kind == "scope":
                self.assertNotIn("impossible", cut.rationale.replace("not impossible", "").replace(
                    "is impossible or", ""), cut.id)

    def test_the_run_list_matches_the_review_id_for_id(self):
        import csv
        with (REVIEW / "Expanded_Review_1619.csv").open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        review = {row["Case_ID"]: row["Source_Case_ID"] for row in rows}
        ours = {run.case_id: run.parent_id for run in self.runs}
        self.assertEqual(len(ours), 1619)
        self.assertEqual(ours, review)

    def test_the_34_heat_source_cases_are_held_not_deleted(self):
        import json
        status = json.loads((CONFIGS / "case_status.json").read_text(encoding="utf-8"))
        held = {r["case_id"] for r in status["original"] if r["status"] == "hold_heat_source"}
        self.assertEqual(len(held), 34)
        self.assertLessEqual(held, {case.case_id for case in self.cases})
        for record in status["original"]:
            if record["case_id"] in held:
                self.assertIn("T01", record["issues"])
                self.assertEqual(record["layers"]["aspen_converged"], "not_run")

    def test_no_status_claims_validation_it_does_not_have(self):
        import json
        status = json.loads((CONFIGS / "case_status.json").read_text(encoding="utf-8"))
        for record in status["expanded"]:
            self.assertEqual(record["layers"]["experimental"], "none", record["case_id"])
            if record["parent_id"] != "C0421":
                self.assertEqual(record["layers"]["aspen_converged"], "not_run", record["case_id"])


class Audit20260912Test(unittest.TestCase):
    """What the second pass over the revised diagram found: heat and water drawn
    as if they came from nowhere, or were used twice."""

    @classmethod
    def setUpClass(cls):
        cls.superstructure = load_superstructure(CONFIGS / "superstructure.json")
        cls.flowsheet = load_flowsheet(CONFIGS / "flowsheet.json", cls.superstructure)
        cls.runs = cls.superstructure.expand_cases()

    def test_the_steam_cycle_returns_its_condensate(self):
        """The turbine used to consume water: steam in, work and a heat arrow out."""
        for run in self.runs:
            if run.selection["S6"] not in {"SRC", "CASC"}:
                continue
            pairs = {(s.source, s.target, s.type) for s in self.flowsheet.active_streams(run.selection)}
            self.assertIn(("HRSG", "STEAMTURB", "water"), pairs, run.case_id)
            steam_out = {p for p in pairs if p[0] == "STEAMTURB" and p[2] == "water"}
            self.assertTrue(steam_out, f"{run.case_id}: the turbine exhaust goes nowhere")
            back = {p for p in pairs if p[1] == "HRSG" and p[2] == "water"}
            self.assertTrue({p for p in back if p[0] in {"SWCOND", "ORC"}},
                            f"{run.case_id}: no condensate returns to the HRSG")

    def test_no_heat_source_is_claimed_by_two_consumers(self):
        """One exhaust cannot heat the reformer and a bottoming cycle as though it
        were two streams. The reformer exchanger takes its duty first and passes
        on what is left."""
        cascade = {"REFHX"}
        for run in self.runs:
            out = {}
            for s in self.flowsheet.active_streams(run.selection):
                if s.type == "heat" and s.source not in cascade:
                    out.setdefault(s.source, set()).add(s.target)
            for source, targets in out.items():
                self.assertEqual(len(targets), 1,
                                 f"{run.case_id}: {source} heats {sorted(targets)} at once")

    def test_the_cascade_is_drawn_as_a_cascade(self):
        for run in self.runs:
            sel = run.selection
            if sel["S5"] != "SOFCEXH" or sel["S6"] == "NONE" or sel["S4"] not in {"SOFC", "HYB"}:
                continue
            pairs = {(s.source, s.target) for s in self.flowsheet.active_streams(sel) if s.type == "heat"}
            self.assertIn(("SOFC", "REFHX"), pairs, run.case_id)
            self.assertTrue({p for p in pairs if p[0] == "REFHX" and p[1] != "REFORMER"},
                            f"{run.case_id}: nothing is left to the bottoming cycle")
            self.assertFalse({p for p in pairs if p[0] == "SOFC" and p[1] != "REFHX"},
                             f"{run.case_id}: the cathode exhaust also feeds the cycle directly")
