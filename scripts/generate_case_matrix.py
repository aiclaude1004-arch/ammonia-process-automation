"""Enumerate every structurally valid case and write the Aspen run list.

    python scripts/generate_case_matrix.py --out ../outputs/case_matrix

Produces three files:

  case_matrix.csv        one empty result row per case, ready for the Aspen sweep
  data_dictionary.csv    column meanings and units for the optimization team
  enumeration_report.md  what was cut and why, for the paper's methods section
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ammonia_optimizer.schema import blank_row, build_columns, write_case_matrix, write_data_dictionary
from ammonia_optimizer.superstructure import Superstructure, load_superstructure


def _distribution(superstructure: Superstructure, cases) -> str:
    lines = []
    for node in superstructure.nodes:
        counts = Counter(case.selection[node.id] for case in cases)
        lines.append(f"\n### {node.id} {node.name} ({node.label_ko})\n")
        lines.append("| option | cases | share |")
        lines.append("| --- | ---: | ---: |")
        for option in node.options:
            count = counts.get(option.code, 0)
            share = count / len(cases) if cases else 0.0
            lines.append(f"| `{option.code}` {option.label_ko} | {count} | {share:.1%} |")
    return "\n".join(lines)


def _report(superstructure: Superstructure, cases, n_columns: int) -> str:
    full = superstructure.full_factorial_size()
    kept = len(cases)
    stats = superstructure.cut_statistics()
    dimensions = Counter(len(case.active_variables) for case in cases)

    lines = [
        f"# Case enumeration report: {superstructure.name}",
        "",
        f"- Structural nodes: **{len(superstructure.nodes)}**",
        f"- Full factorial combinations: **{full:,}**",
        f"- Structurally valid cases: **{kept:,}** ({kept / full:.1%})",
        f"- Removed by logic cuts: **{full - kept:,}**",
        f"- Hand-off table columns: **{n_columns}**",
        "",
        "## Logic cuts",
        "",
        "Counts are how many full-factorial combinations each cut rejects on its own.",
        "They overlap, so they do not sum to the number removed.",
        "",
        "| id | rejects | rationale |",
        "| --- | ---: | --- |",
    ]
    for cut in superstructure.logic_cuts:
        lines.append(f"| `{cut.id}` | {stats[cut.id]:,} | {cut.rationale} |")

    lines += [
        "",
        "## Inner optimization dimension",
        "",
        "Continuous operating variables active in each case.",
        "",
        "| active variables | cases |",
        "| ---: | ---: |",
    ]
    for dimension in sorted(dimensions):
        lines.append(f"| {dimension} | {dimensions[dimension]} |")

    lines += ["", "## Option coverage", _distribution(superstructure, cases), ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "configs" / "superstructure.json",
    )
    parser.add_argument("--out", type=Path, required=True, help="Output directory, created if missing")
    parser.add_argument("--model-file", default="", help="Aspen backup the sweep will start from")
    arguments = parser.parse_args()

    superstructure = load_superstructure(arguments.config)
    cases = superstructure.enumerate_cases()
    if not cases:
        raise SystemExit("No feasible cases. The logic cuts contradict each other; check the report rationale.")

    arguments.out.mkdir(parents=True, exist_ok=True)
    rows = [blank_row(case, superstructure, arguments.model_file) for case in cases]
    n_rows = write_case_matrix(arguments.out / "case_matrix.csv", rows, superstructure)
    n_columns = write_data_dictionary(arguments.out / "data_dictionary.csv", superstructure)
    (arguments.out / "enumeration_report.md").write_text(
        _report(superstructure, cases, len(build_columns(superstructure))), encoding="utf-8"
    )

    full = superstructure.full_factorial_size()
    print(f"full factorial      : {full:,}")
    print(f"structurally valid  : {n_rows:,}  ({n_rows / full:.1%})")
    print(f"hand-off columns    : {n_columns}")
    print(f"written to          : {arguments.out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
