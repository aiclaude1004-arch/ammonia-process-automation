"""Literature operating windows attached to the units in the flowsheet.

The table is empty until the reader pins a structure, and each row appears only
when its unit is active in the selection - the same predicate the diagram and
the logic cuts use.

Two rules keep the table honest:

* A numeric value must name a source.  An unsourced number in a table that
  looks sourced is worse than a blank, so `load_parameters` refuses it.
* A parameter we have not researched yet is declared with nulls and renders as
  a visible gap with its note, exactly like an inapplicable column in the
  hand-off CSV.  Filling it with a plausible guess would put a fabricated
  operating window into the paper.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .flowsheet import Flowsheet
from .superstructure import Selection, Superstructure


#: What a literature number may be used for in a model.
MODEL_ROLES = ("model_input", "performance_reference", "system_result", "explanation")
#: How far a parameter has been taken. None of these means "Aspen validated";
#: that is a property of a converged run, not of a table row.
VALIDATION_STATUSES = ("reported", "bounded", "implemented", "retired")


@dataclass(frozen=True)
class Source:
    key: str
    short: str
    title: str
    url: str
    type: str
    year: int


@dataclass(frozen=True)
class Parameter:
    block: str
    name: str
    symbol: str
    unit: str
    low: float | None
    high: float | None
    text: str | None
    source: str | None
    note: str
    note_ko: str
    corroborated_by: tuple[str, ...]
    active_when: Mapping[str, tuple[str, ...]]
    #: Stable id (P001...) that survives reordering; the review cites by it.
    parameter_id: str = ""
    #: What the number is for. A literature system efficiency is a result to
    #: compare against, never an input to type into a unit.
    model_role: str = ""
    #: How far it has been checked: reported, bounded, implemented, validated.
    validation_status: str = ""
    #: What kind of quantity: temperature, efficiency, ratio, emission, ...
    quantity_kind: str = ""
    #: The value actually typed into a model, when one has been chosen.
    implementation_value: str = ""
    #: The external review's verdict and note, kept beside the value.
    review_verdict: str = ""
    review_note: str = ""

    @property
    def is_sourced(self) -> bool:
        return self.source is not None

    @property
    def is_corroborated(self) -> bool:
        """Backed by an independent source as well as the primary one.

        The values that decide the conclusion should not rest on one paper.
        """
        return bool(self.corroborated_by)

    @property
    def is_retired(self) -> bool:
        return self.validation_status == "retired"

    def is_active(self, selection: Selection) -> bool:
        """A retired row is kept in the file with its reason and never shown."""
        if self.is_retired:
            return False
        return all(selection.get(node) in codes for node, codes in self.active_when.items())

    def display_value(self) -> str:
        """A single range, a single number, a phrase, or an explicit blank."""
        if self.text is not None:
            return self.text
        if self.low is None or self.high is None:
            return ""
        if self.low == self.high:
            return f"{self.low:g}"
        return f"{self.low:g} – {self.high:g}"


@dataclass(frozen=True)
class ParameterSet:
    name: str
    schema_version: str
    sources: Mapping[str, Source]
    parameters: tuple[Parameter, ...]

    def for_selection(self, selection: Selection) -> tuple[Parameter, ...]:
        return tuple(p for p in self.parameters if p.is_active(selection))

    def year_span(self) -> tuple[int, int]:
        """Oldest and newest source. A list that starts in the last two years
        reads as though the field began then."""
        years = [s.year for s in self.sources.values()]
        return min(years), max(years)

    def coverage(self, selections: Sequence[Selection]) -> tuple[int, int]:
        """How many of the parameters reachable across these cases carry a source."""
        reachable = [p for p in self.parameters if any(p.is_active(s) for s in selections)]
        return sum(p.is_sourced for p in reachable), len(reachable)


def load_parameters(
    path: str | Path, superstructure: Superstructure, flowsheet: Flowsheet
) -> ParameterSet:
    """Load the windows, refusing anything the diagram or the sources cannot back.

    Pass the widest superstructure in play: the set describes units rather than
    one study's case list, so a row guarded by an option the narrower study does
    not offer is dormant, not wrong.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))

    sources = {
        key: Source(key=key, short=item["short"], title=item["title"],
                    url=item["url"], type=item["type"], year=int(item["year"]))
        for key, item in raw["sources"].items()
    }
    known_blocks = {block.id for block in flowsheet.blocks}
    known_options = superstructure.axes()

    parameters: list[Parameter] = []
    for item in raw["parameters"]:
        where = f"parameter '{item['name']}' on {item['block']}"
        if item["block"] not in known_blocks:
            raise ValueError(f"{where} references a block that is not in the flowsheet")

        active_when = {node: tuple(codes) for node, codes in item["active_when"].items()}
        for node_id, codes in active_when.items():
            if node_id not in known_options:
                raise ValueError(f"{where} references unknown node '{node_id}'")
            unknown = set(codes) - known_options[node_id]
            if unknown:
                raise ValueError(f"{where} references unknown {node_id} options: {sorted(unknown)}")

        low, high = item.get("low"), item.get("high")
        text, source = item.get("text"), item.get("source")
        has_value = text is not None or low is not None or high is not None

        if has_value and source is None:
            raise ValueError(f"{where} states a value with no source")
        if source is not None and source not in sources:
            raise ValueError(f"{where} cites unknown source '{source}'")
        for key in item.get("corroborated_by", ()):
            if key not in sources:
                raise ValueError(f"{where} corroborates against unknown source '{key}'")
            if key == source:
                raise ValueError(f"{where} lists its own source as corroboration")
        if (low is None) != (high is None):
            raise ValueError(f"{where} gives only one end of its range")
        if low is not None and high is not None and low > high:
            raise ValueError(f"{where} has low above high")
        if not item.get("note") or not item.get("note_ko"):
            raise ValueError(f"{where} is missing a note; a bare number explains nothing")
        role = item.get("model_role", "")
        if role and role not in MODEL_ROLES:
            raise ValueError(f"{where} has model_role '{role}'; expected one of {MODEL_ROLES}")
        status = item.get("validation_status", "")
        if status and status not in VALIDATION_STATUSES:
            raise ValueError(f"{where} has validation_status '{status}'; "
                             f"expected one of {VALIDATION_STATUSES}")

        parameters.append(
            Parameter(
                block=item["block"],
                name=item["name"],
                symbol=item["symbol"],
                unit=item["unit"],
                low=low,
                high=high,
                text=text,
                source=source,
                note=item["note"],
                note_ko=item["note_ko"],
                corroborated_by=tuple(item.get("corroborated_by", ())),
                active_when=active_when,
                parameter_id=item.get("parameter_id", ""),
                model_role=role,
                validation_status=status,
                quantity_kind=item.get("quantity_kind", ""),
                implementation_value=item.get("implementation_value", ""),
                review_verdict=item.get("review_verdict", ""),
                review_note=item.get("review_note", ""),
            )
        )

    return ParameterSet(
        name=raw["parameter_set_name"],
        schema_version=raw["schema_version"],
        sources=sources,
        parameters=tuple(parameters),
    )
