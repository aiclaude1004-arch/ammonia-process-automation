"""Structural decision space for the marine hybrid-power superstructure.

A *case* is one complete flowsheet topology: exactly one option chosen at every
structural node.  The full Cartesian product contains many topologies that are
not flowsheets at all (an unheated endothermic reformer, a purifier feeding an
engine, a NOx aftertreatment train with no combustor).  Those are removed by
declarative logic cuts, so every enumerated case is worth an Aspen run.

Cuts live in `configs/superstructure.json`, never in code: each carries an id
and a written rationale so a reviewer can audit why a topology was excluded.
Rejection is reported per cut rather than as a silent filter.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Iterator, Mapping, Sequence

Selection = Mapping[str, str]


@dataclass(frozen=True)
class Option:
    code: str
    label_ko: str
    label_en: str
    note: str


@dataclass(frozen=True)
class Node:
    id: str
    name: str
    label_ko: str
    label_en: str
    options: tuple[Option, ...]

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(option.code for option in self.options)


@dataclass(frozen=True)
class Variant:
    """A sub-choice that exists only under one parent option.

    LOHC was split into MCH and DBT. Making them two S1 options would renumber
    every case after the first LOHC one and break the case IDs the 2026-09-11
    review is written against, so the carrier is a variant axis instead: the
    original cases keep their IDs and each LOHC case gains one child per carrier.
    """

    id: str
    parent_node: str
    parent_code: str
    label_ko: str
    label_en: str
    options: tuple[Option, ...]

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(option.code for option in self.options)


#: Why a cut exists. A dependency follows from the flowsheet itself (no reformer,
#: nothing to purify). A scope cut is a choice this study made on economics or
#: range, and must not be described as a physical impossibility.
CUT_KINDS = ("dependency", "scope")


@dataclass(frozen=True)
class LogicCut:
    """A guarded structural implication.

    The cut is *triggered* when every node listed in `condition` holds one of
    the listed codes.  A triggered cut then demands that each node in `require`
    holds a listed code, and that no node in `forbid` does.
    """

    id: str
    condition: Mapping[str, tuple[str, ...]]
    require: Mapping[str, tuple[str, ...]]
    forbid: Mapping[str, tuple[str, ...]]
    rationale: str
    kind: str = "dependency"

    def triggers_on(self, selection: Selection) -> bool:
        return all(selection[node] in codes for node, codes in self.condition.items())

    def is_violated_by(self, selection: Selection) -> bool:
        """The same test as `violation`, without building the explanation.

        Enumeration rejects the overwhelming majority of combinations, so
        formatting a message for each one dominated the run time.
        """
        if not self.triggers_on(selection):
            return False
        for node, codes in self.require.items():
            if selection[node] not in codes:
                return True
        for node, codes in self.forbid.items():
            if selection[node] in codes:
                return True
        return False

    def violation(self, selection: Selection) -> str | None:
        """Return a human-readable reason, or None when the selection passes."""
        if not self.triggers_on(selection):
            return None
        for node, codes in self.require.items():
            if selection[node] not in codes:
                return f"{self.id}: {node}={selection[node]} but requires one of {'/'.join(codes)} - {self.rationale}"
        for node, codes in self.forbid.items():
            if selection[node] in codes:
                return f"{self.id}: {node}={selection[node]} is forbidden here - {self.rationale}"
        return None


@dataclass(frozen=True)
class OperatingVariable:
    name: str
    unit: str
    lower: float
    upper: float
    active_when: Mapping[str, tuple[str, ...]]

    def is_active(self, selection: Selection) -> bool:
        # An original LOHC case has not chosen its carrier yet; a variable keyed on the
        # carrier axis is therefore open for it and settled in each expanded run.
        return all(selection[node] in codes if node in selection else True
                   for node, codes in self.active_when.items())


@dataclass(frozen=True)
class Case:
    case_id: str
    selection: Selection
    active_variables: tuple[str, ...]

    @property
    def label(self) -> str:
        """Codes in declared node order - sorting the ids would put S10 before S2."""
        return "-".join(self.selection.values())


@dataclass(frozen=True)
class ExpandedCase:
    """One run of the study: an original case, or one carrier of an LOHC case."""

    case_id: str
    parent_id: str
    selection: Selection


@dataclass(frozen=True)
class Superstructure:
    name: str
    schema_version: str
    nodes: tuple[Node, ...]
    logic_cuts: tuple[LogicCut, ...]
    operating_variables: tuple[OperatingVariable, ...]
    gwp100_factors: Mapping[str, float]
    design_basis: Mapping[str, object]
    variants: tuple[Variant, ...] = ()

    @property
    def node_ids(self) -> tuple[str, ...]:
        return tuple(node.id for node in self.nodes)

    def axes(self) -> Mapping[str, frozenset[str]]:
        """Every key a predicate may name: the nodes and the variant axes."""
        known = {node.id: frozenset(node.codes) for node in self.nodes}
        known.update({variant.id: frozenset(variant.codes) for variant in self.variants})
        return known

    def expand_cases(self, cases: Sequence[Case] | None = None) -> tuple[ExpandedCase, ...]:
        """The run list: each case once, or once per variant option under it.

        A child's id is its parent's with the variant code appended, so the
        mapping back to the original case is in the id as well as the record.
        """
        out: list[ExpandedCase] = []
        for case in cases if cases is not None else self.enumerate_cases():
            splits = [v for v in self.variants
                      if case.selection.get(v.parent_node) == v.parent_code]
            if not splits:
                out.append(ExpandedCase(case.case_id, case.case_id, dict(case.selection)))
                continue
            variant = splits[0]
            for code in variant.codes:
                selection = dict(case.selection)
                selection[variant.id] = code
                out.append(ExpandedCase(f"{case.case_id}_{code}", case.case_id, selection))
        return tuple(out)

    def full_factorial_size(self) -> int:
        size = 1
        for node in self.nodes:
            size *= len(node.options)
        return size

    def rejections(self, selection: Selection) -> tuple[str, ...]:
        """Every cut violated by this selection, not just the first."""
        reasons = (cut.violation(selection) for cut in self.logic_cuts)
        return tuple(reason for reason in reasons if reason is not None)

    def is_feasible(self, selection: Selection) -> bool:
        return not any(cut.is_violated_by(selection) for cut in self.logic_cuts)

    def active_variables(self, selection: Selection) -> tuple[str, ...]:
        return tuple(
            variable.name for variable in self.operating_variables if variable.is_active(selection)
        )

    def enumerate_cases(self) -> tuple[Case, ...]:
        """All structurally valid topologies, in a stable deterministic order."""
        cases: list[Case] = []
        for index, selection in enumerate(self._iter_feasible_selections(), start=1):
            cases.append(
                Case(
                    case_id=f"C{index:04d}",
                    selection=selection,
                    active_variables=self.active_variables(selection),
                )
            )
        return tuple(cases)

    def cut_statistics(self) -> Mapping[str, int]:
        """How many full-factorial combinations each cut removes on its own.

        The counts overlap, so they do not sum to the number of rejected cases.
        They show which structural rules are doing the work.
        """
        counts = {cut.id: 0 for cut in self.logic_cuts}
        for selection in self._iter_all_selections():
            for cut in self.logic_cuts:
                if cut.is_violated_by(selection):
                    counts[cut.id] += 1
        return counts

    def _iter_all_selections(self) -> Iterator[Selection]:
        node_ids = self.node_ids
        for combination in product(*(node.codes for node in self.nodes)):
            yield dict(zip(node_ids, combination))

    def _iter_feasible_selections(self) -> Iterator[Selection]:
        for selection in self._iter_all_selections():
            if self.is_feasible(selection):
                yield selection


def _as_code_map(raw: Mapping[str, Sequence[str]] | None) -> Mapping[str, tuple[str, ...]]:
    if raw is None:
        return {}
    return {node: tuple(codes) for node, codes in raw.items()}


def load_superstructure(path: str | Path) -> Superstructure:
    """Load the structural decision space, failing loudly on an unknown code.

    A cut or an operating variable that names a node or option which does not
    exist is a specification error, not something to skip quietly: it would
    silently stop constraining the search.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))

    nodes = tuple(
        Node(
            id=node["id"],
            name=node["name"],
            label_ko=node["label_ko"],
            label_en=node["label_en"],
            options=tuple(
                Option(
                    code=item["code"],
                    label_ko=item["label_ko"],
                    label_en=item["label_en"],
                    note=item["note"],
                )
                for item in node["options"]
            ),
        )
        for node in raw["nodes"]
    )
    known: dict[str, frozenset[str]] = {node.id: frozenset(node.codes) for node in nodes}

    def validate(where: str, code_map: Mapping[str, tuple[str, ...]]) -> None:
        for node_id, codes in code_map.items():
            if node_id not in known:
                raise ValueError(f"{where} references unknown node '{node_id}'")
            unknown = set(codes) - known[node_id]
            if unknown:
                raise ValueError(f"{where} references unknown {node_id} options: {sorted(unknown)}")

    variants: list[Variant] = []
    for axis_id, item in (raw.get("variants") or {}).items():
        parent_node, parent_code = item["parent_node"], item["parent_code"]
        if parent_node not in known or parent_code not in known[parent_node]:
            raise ValueError(f"variant {axis_id} hangs off {parent_node}={parent_code}, which does not exist")
        if axis_id in known:
            raise ValueError(f"variant {axis_id} reuses a node id")
        variants.append(Variant(
            id=axis_id, parent_node=parent_node, parent_code=parent_code,
            label_ko=item["label_ko"], label_en=item["label_en"],
            options=tuple(Option(code=o["code"], label_ko=o["label_ko"],
                                 label_en=o["label_en"], note=o["note"])
                          for o in item["options"]),
        ))

    logic_cuts: list[LogicCut] = []
    for item in raw["logic_cuts"]:
        cut = LogicCut(
            id=item["id"],
            condition=_as_code_map(item["if"]),
            require=_as_code_map(item.get("then_require")),
            forbid=_as_code_map(item.get("then_forbid")),
            rationale=item["rationale"],
            kind=item.get("kind", "dependency"),
        )
        if cut.kind not in CUT_KINDS:
            raise ValueError(f"{cut.id} has kind '{cut.kind}'; expected one of {CUT_KINDS}")
        if not cut.require and not cut.forbid:
            raise ValueError(f"{cut.id} states a condition but no consequence")
        validate(f"cut {cut.id}", cut.condition)
        validate(f"cut {cut.id}", cut.require)
        validate(f"cut {cut.id}", cut.forbid)
        logic_cuts.append(cut)

    operating_variables: list[OperatingVariable] = []
    for item in raw["operating_variables"]:
        lower, upper = (float(value) for value in item["bounds"])
        if lower >= upper:
            raise ValueError(f"Invalid bounds for {item['name']}: {lower} >= {upper}")
        variable = OperatingVariable(
            name=item["name"],
            unit=item["unit"],
            lower=lower,
            upper=upper,
            active_when=_as_code_map(item["active_when"]),
        )
        # A variable may be keyed on a variant axis (the LOHC carrier) as well as on nodes.
        for axis, codes in variable.active_when.items():
            if axis in known:
                validate(f"variable {variable.name}", {axis: codes})
                continue
            variant = next((v for v in variants if v.id == axis), None)
            if variant is None:
                raise ValueError(f"variable {variable.name} references unknown node '{axis}'")
            unknown = set(codes) - set(variant.codes)
            if unknown:
                raise ValueError(f"variable {variable.name} references unknown {axis} options: {sorted(unknown)}")
        operating_variables.append(variable)

    return Superstructure(
        name=raw["superstructure_name"],
        schema_version=raw["schema_version"],
        nodes=nodes,
        logic_cuts=tuple(logic_cuts),
        operating_variables=tuple(operating_variables),
        gwp100_factors={key: value for key, value in raw["gwp100_factors"].items() if key != "source"},
        design_basis=raw["design_basis"],
        variants=tuple(variants),
    )
