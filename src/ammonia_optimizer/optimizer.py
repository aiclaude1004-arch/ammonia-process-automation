"""A dependency-free baseline constrained optimizer.

It is intentionally simple so that every evaluated Aspen case can be traced.
Replace `random_search` with a surrogate or mixed-integer optimizer only after
the model has a stable convergence rate and verified mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Callable, Mapping

from .physics import ConstraintReport, check_physical_consistency
from .spec import CaseSpec


@dataclass(frozen=True)
class Evaluation:
    decision: Mapping[str, float]
    score: float
    report: ConstraintReport
    results: Mapping[str, float]


Simulator = Callable[[Mapping[str, float]], tuple[Mapping[str, float], Mapping[str, float], Mapping[str, float]]]


def score(results: Mapping[str, float], spec: CaseSpec) -> float:
    """Higher is better: electrical output per ammonia throughput with NOx cost."""
    feed = max(results["nh3_feed_kg_h"], 1.0e-9)
    power_per_feed = results["net_power_kw"] / feed
    return power_per_feed - float(spec.objective["nox_penalty_per_mg_nm3"]) * results["nox_mg_per_nm3"]


def random_search(spec: CaseSpec, simulator: Simulator, samples: int, seed: int = 7) -> Evaluation:
    """Return the best feasible point; fail explicitly when none is feasible."""
    rng = Random(seed)
    best: Evaluation | None = None
    for _ in range(samples):
        decision = {
            name: rng.uniform(bounds.lower, bounds.upper)
            for name, bounds in spec.decision_variables.items()
        }
        results, element_in, element_out = simulator(decision)
        report = check_physical_consistency(results, element_in, element_out, spec.constraints)
        candidate = Evaluation(decision, score(results, spec) if report.feasible else float("-inf"), report, results)
        if candidate.report.feasible and (best is None or candidate.score > best.score):
            best = candidate
    if best is None:
        raise RuntimeError("No feasible candidates. Inspect convergence, bounds, and balance reports.")
    return best
