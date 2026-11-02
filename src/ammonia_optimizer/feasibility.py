"""Physical feasibility of a sampled operating point, before Aspen is called.

The operating variable bounds are boxes, one variable at a time. Physics joins
them: a cracker cannot pass its equilibrium, a reformer heated by stack exhaust
cannot run hotter than the stack, and ammonia fed straight into a solid oxide
stack needs the stack hot enough to crack it. Those rules are declared in
superstructure.json under "physical_constraints" and evaluated here, so a point
that breaks one is rejected by the sampler instead of being sent to Aspen and
counted as a model failure.

Equilibrium uses the NASA-7 polynomials copied from gri30.yaml into
configs/thermo_nasa7.json - the same thermodynamics as C0421's ideal-gas screen,
which agreed with Aspen RGibbs (0.99733 against 0.99729 at 610 C, 3 bar). Only
ammonia is computed here; carriers without validated data in this repository
(MCH, DBT) are flagged for the RGibbs check at run time rather than guessed.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

R = 8.31446261815324
P_STD_BAR = 1.01325


@dataclass(frozen=True)
class Nasa7:
    t_mid: float
    t_min: float
    t_max: float
    low: tuple[float, ...]
    high: tuple[float, ...]

    def g(self, t: float) -> float:
        """Gibbs energy [J/mol] at the standard pressure of the polynomials."""
        if not self.t_min <= t <= self.t_max:
            raise ValueError(f"{t} K outside the NASA-7 range")
        a = self.high if t > self.t_mid else self.low
        h = R * t * (a[0] + a[1] * t / 2 + a[2] * t * t / 3 + a[3] * t ** 3 / 4 + a[4] * t ** 4 / 5 + a[5] / t)
        s = R * (a[0] * math.log(t) + a[1] * t + a[2] * t * t / 2 + a[3] * t ** 3 / 3 + a[4] * t ** 4 / 4 + a[6])
        return h - t * s


def load_thermo(path: str | Path) -> dict[str, Nasa7]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))["species"]
    return {sp: Nasa7(t_min=d["T_ranges_K"][0], t_mid=d["T_ranges_K"][1], t_max=d["T_ranges_K"][2],
                      low=tuple(d["low"]), high=tuple(d["high"])) for sp, d in raw.items()}


def nh3_equilibrium_conversion(thermo: Mapping[str, Nasa7], t_c: float, p_bar: float) -> float:
    """Pure ammonia feed, NH3 -> 1/2 N2 + 3/2 H2, ideal gas; the C0421 screen."""
    t = t_c + 273.15
    dg = 1.5 * thermo["H2"].g(t) + 0.5 * thermo["N2"].g(t) - thermo["NH3"].g(t)
    k = math.exp(-dg / R / t)
    return math.sqrt(k / (k + 1.5 ** 1.5 * 0.5 ** 0.5 * p_bar / P_STD_BAR))


def _applies(rule: Mapping[str, Sequence[str]], selection: Mapping[str, str]) -> bool:
    return all(selection.get(axis) in codes for axis, codes in rule.items())


def _first(values: Mapping[str, float], names: Sequence[str]) -> tuple[str, float] | None:
    for name in names:
        if values.get(name) is not None:
            return name, float(values[name])
    return None


def check_point(
    constraints: Sequence[Mapping[str, object]],
    thermo: Mapping[str, Nasa7],
    selection: Mapping[str, str],
    values: Mapping[str, float],
) -> tuple[list[str], list[str]]:
    """Return (violations, deferred): broken rules, and rules left to Aspen RGibbs."""
    violations: list[str] = []
    deferred: list[str] = []
    for c in constraints:
        if not _applies(c["applies_to"], selection):
            continue
        kind = c["kind"]
        if kind == "nh3_equilibrium":
            x = _first(values, c["conversion"])
            t = _first(values, [c["temperature"]])
            p = _first(values, [c["pressure"]])
            if x and t and p:
                limit = nh3_equilibrium_conversion(thermo, t[1], p[1]) - float(c["margin"])
                if x[1] > limit:
                    violations.append(f"{c['id']}: {x[0]}={x[1]:.4f} exceeds equilibrium "
                                      f"{limit + float(c['margin']):.4f} - margin at {t[1]:.0f} C, {p[1]:.2f} bar")
        elif kind == "hotter_source":
            cold = _first(values, c["colder"])
            hot = _first(values, [c["hotter"]])
            if cold and hot and cold[1] > hot[1] - float(c["gap_K"]):
                violations.append(f"{c['id']}: {cold[0]}={cold[1]:.0f} C is within {c['gap_K']} K of "
                                  f"{hot[0]}={hot[1]:.0f} C, its heat source")
        elif kind == "minimum":
            v = _first(values, [c["variable"]])
            if v and v[1] < float(c["min"]):
                violations.append(f"{c['id']}: {v[0]}={v[1]:g} below {c['min']}")
        elif kind == "rgibbs_at_run_time":
            deferred.append(str(c["id"]))
        else:
            raise ValueError(f"unknown constraint kind {kind}")
    return violations, deferred
