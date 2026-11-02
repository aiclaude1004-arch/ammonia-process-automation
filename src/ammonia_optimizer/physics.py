"""Process-independent checks applied to every Aspen result before ranking it.

The simulator adapter supplies quantities in one consistent unit system.  This
module never invents balances from missing data: a missing required result is a
hard failure, not a favourable zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping


REQUIRED_RESULTS = frozenset(
    {
        "net_power_kw",
        "nh3_feed_kg_h",
        "nox_mg_per_nm3",
        "energy_in_kw",
        "energy_out_kw",
        "min_temperature_approach_c",
        "min_pressure_bar",
    }
)


@dataclass(frozen=True)
class ConstraintReport:
    feasible: bool
    violations: tuple[str, ...]
    element_relative_errors: Mapping[str, float]
    energy_relative_error: float


def _relative_error(inlet: float, outlet: float) -> float:
    denominator = max(abs(inlet), 1.0e-12)
    return abs(inlet - outlet) / denominator


def check_physical_consistency(
    results: Mapping[str, float],
    element_in: Mapping[str, float],
    element_out: Mapping[str, float],
    limits: Mapping[str, float],
) -> ConstraintReport:
    """Check elemental conservation and non-negotiable operating constraints.

    `element_in` and `element_out` must be total molar atomic flows for the
    complete model boundary (e.g., H, N and O), not selected streams.
    """
    violations: list[str] = []
    missing = REQUIRED_RESULTS.difference(results)
    if missing:
        violations.append("missing simulator results: " + ", ".join(sorted(missing)))

    all_numbers = [*results.values(), *element_in.values(), *element_out.values()]
    if not all(isfinite(float(value)) for value in all_numbers):
        violations.append("simulator returned a non-finite value")

    elements = set(element_in) | set(element_out)
    element_errors = {
        element: _relative_error(element_in.get(element, 0.0), element_out.get(element, 0.0))
        for element in elements
    }
    element_limit = limits["max_element_balance_relative_error"]
    for element, error in sorted(element_errors.items()):
        if error > element_limit:
            violations.append(f"{element} balance error {error:.3%} exceeds {element_limit:.3%}")

    energy_error = _relative_error(results.get("energy_in_kw", 0.0), results.get("energy_out_kw", 0.0))
    if energy_error > limits["max_energy_balance_relative_error"]:
        violations.append("overall energy balance does not close")
    if results.get("net_power_kw", float("-inf")) < limits["min_net_power_kw"]:
        violations.append("net power target is not met")
    if results.get("nox_mg_per_nm3", float("inf")) > limits["max_nox_mg_per_nm3"]:
        violations.append("NOx limit is exceeded")
    if results.get("min_temperature_approach_c", float("-inf")) < limits["min_temperature_approach_c"]:
        violations.append("heat-exchanger temperature approach is infeasible")
    if results.get("min_pressure_bar", float("-inf")) < limits["min_pressure_bar"]:
        violations.append("pressure fell below the design minimum")

    return ConstraintReport(
        feasible=not violations,
        violations=tuple(violations),
        element_relative_errors=element_errors,
        energy_relative_error=energy_error,
    )
