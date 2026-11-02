"""Immutable, validated design-basis objects."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class Bounds:
    lower: float
    upper: float

    def __post_init__(self) -> None:
        if self.lower >= self.upper:
            raise ValueError(f"Invalid bounds: {self.lower} >= {self.upper}")

    def contains(self, value: float) -> bool:
        return self.lower <= value <= self.upper


@dataclass(frozen=True)
class CaseSpec:
    case_name: str
    progid: str
    model_path: Path
    decision_variables: Mapping[str, Bounds]
    constraints: Mapping[str, float]
    objective: Mapping[str, float | str]


def load_case_spec(path: str | Path) -> CaseSpec:
    """Load the project design basis without silently applying defaults."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    variables = {
        name: Bounds(float(limits[0]), float(limits[1]))
        for name, limits in raw["decision_variables"].items()
    }
    return CaseSpec(
        case_name=raw["case_name"],
        progid=raw["aspen"]["progid"],
        model_path=Path(raw["aspen"]["model_path"]),
        decision_variables=variables,
        constraints={key: float(value) for key, value in raw["constraints"].items()},
        objective=raw["objective"],
    )
