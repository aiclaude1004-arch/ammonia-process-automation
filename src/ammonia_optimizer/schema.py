"""The fixed hand-off table shared with the external optimization team.

Every case writes the same columns in the same order, whether or not the case
uses them.  A column that does not apply to a topology is written empty, never
zero: a purifier that is not installed has no recovery, and a zero would be read
as a perfectly bad purifier.

Failed Aspen runs are written too, with `converged = 0` and the diagnosis in
`violated_constraints`.  Dropping them would hide the shape of the feasible
region from whoever fits the surrogate model.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .superstructure import Case, Superstructure

EMPTY = ""


@dataclass(frozen=True)
class Column:
    name: str
    unit: str
    group: str
    description: str


def _columns(group: str, entries: Sequence[tuple[str, str, str]]) -> tuple[Column, ...]:
    return tuple(Column(name, unit, group, description) for name, unit, description in entries)


IDENTITY_COLUMNS = _columns(
    "identity",
    [
        ("case_id", "-", "Stable identifier assigned by the enumerator"),
        ("case_label", "-", "Concatenated option codes, human readable"),
        ("schema_version", "-", "Version of this hand-off table"),
        ("timestamp_utc", "ISO8601", "When the row was written"),
        ("aspen_model_file", "-", "Backup file the row was produced from"),
    ],
)

PERFORMANCE_COLUMNS = _columns(
    "performance",
    [
        ("W_fuelcell_kW", "kW", "Gross DC power from the stack"),
        ("W_engine_kW", "kW", "Gross shaft power from the dual fuel engine"),
        ("W_bottoming_kW", "kW", "Gross power from the bottoming cycle"),
        ("W_auxiliary_kW", "kW", "Pumps, blowers, compressors, purifier and NORR duty"),
        ("W_net_kW", "kW", "Net electrical and shaft power delivered to the ship"),
        ("Q_reformer_kW", "kW", "Heat duty demanded by the reformer or cracker"),
        ("Q_recovered_kW", "kW", "Heat actually recovered into a useful sink"),
        ("Q_reject_kW", "kW", "Heat rejected to sea water and stack"),
        ("eta_net_LHV", "-", "W_net_kW divided by feed LHV power"),
        ("eta_exergy", "-", "Second law efficiency of the whole plant"),
        ("load_ramp_pct_per_min", "%/min", "Achievable ramp rate, the reason an engine is present"),
    ],
)

MATERIAL_COLUMNS = _columns(
    "material",
    [
        ("feed_kg_h", "kg/h", "Fresh carrier fed at the tank boundary"),
        ("feed_LHV_kW", "kW", "Lower heating value power of the fresh feed"),
        ("h2_produced_kg_h", "kg/h", "Hydrogen leaving the reformer"),
        ("h2_to_fuelcell_kg_h", "kg/h", "Hydrogen entering the stack anode"),
        ("h2_to_engine_kg_h", "kg/h", "Hydrogen burned as combustion promoter"),
        ("nh3_recovered_kg_h", "kg/h", "Ammonia returned by NORR, empty when absent"),
        ("nh3_consumed_scr_kg_h", "kg/h", "Ammonia or urea consumed by SCR, empty when absent"),
        ("water_makeup_kg_h", "kg/h", "Demineralised water make-up"),
    ],
)

EMISSION_COLUMNS = _columns(
    "emissions",
    [
        ("CO2_kg_h", "kg/h", "Carbon dioxide at the stack"),
        ("CH4_kg_h", "kg/h", "Methane slip, relevant for carbon bearing feeds"),
        ("N2O_kg_h", "kg/h", "Nitrous oxide, GWP100 of 273 and the decisive term for ammonia"),
        ("NOx_g_per_kWh", "g/kWh", "Specific NOx against the IMO Tier III limit"),
        ("NH3_slip_ppmv", "ppmv", "Ammonia slip at the funnel, toxicity limited"),
        ("GWP100_kgCO2e_h", "kgCO2e/h", "CO2 plus 28 times CH4 plus 273 times N2O"),
        ("GWP100_gCO2e_per_kWh", "gCO2e/kWh", "Climate intensity of delivered power"),
    ],
)

ECONOMIC_COLUMNS = _columns(
    "economics",
    [
        ("CAPEX_reformer_kUSD", "kUSD", "Reformer or cracker including its burner"),
        ("CAPEX_purifier_kUSD", "kUSD", "PSA or membrane skid"),
        ("CAPEX_fuelcell_kUSD", "kUSD", "Stack, balance of plant and first replacement reserve"),
        ("CAPEX_engine_kUSD", "kUSD", "Dual fuel engine and fuel supply system"),
        ("CAPEX_bottoming_kUSD", "kUSD", "Bottoming cycle turbomachinery and exchangers"),
        ("CAPEX_aftertreatment_kUSD", "kUSD", "SCR, slip catalyst or NORR cell stack"),
        ("CAPEX_storage_kUSD", "kUSD", "Fuel tank, containment and bunkering system"),
        ("CAPEX_total_kUSD", "kUSD", "Installed capital cost"),
        ("OPEX_fixed_kUSD_y", "kUSD/y", "Maintenance, crew and insurance"),
        ("OPEX_variable_kUSD_y", "kUSD/y", "Fuel, catalyst, water and consumables"),
        ("TAC_kUSD_y", "kUSD/y", "Annualised capital plus operating cost"),
        ("LCOE_USD_per_MWh", "USD/MWh", "Levelised cost of delivered power"),
    ],
)

PHYSICAL_COLUMNS = _columns(
    "physical",
    [
        ("volume_machinery_m3", "m3", "Machinery space occupied by the conversion train"),
        ("volume_storage_m3", "m3", "Fuel storage volume for the design range"),
        ("volume_total_m3", "m3", "Total volume charged against cargo capacity"),
        ("mass_total_ton", "t", "Total installed mass including fuel at departure"),
        ("power_density_kW_per_m3", "kW/m3", "Net power per total volume, the marine specific metric"),
        ("specific_power_kW_per_ton", "kW/t", "Net power per total mass"),
    ],
)

STATUS_COLUMNS = _columns(
    "status",
    [
        ("converged", "0/1", "1 when Aspen converged and all balances closed"),
        ("violated_constraints", "-", "Semicolon separated diagnosis, empty when feasible"),
        ("n_aspen_errors", "-", "Error count reported by the run"),
        ("runtime_s", "s", "Wall clock time of the Aspen run"),
    ],
)


def build_columns(superstructure: Superstructure) -> tuple[Column, ...]:
    """Assemble the full ordered column list for this superstructure.

    Structure and operating columns are derived from the configuration so the
    table can never drift out of step with the decision space.
    """
    structure = tuple(
        Column(f"{node.id}_{node.name}", "-", "structure", node.label_ko) for node in superstructure.nodes
    )
    operating = tuple(
        Column(variable.name, variable.unit, "operating", f"bounds {variable.lower} to {variable.upper}")
        for variable in superstructure.operating_variables
    )
    return (
        IDENTITY_COLUMNS
        + structure
        + operating
        + (Column("n_active_operating_vars", "-", "operating", "Dimension of the inner optimization"),)
        + PERFORMANCE_COLUMNS
        + MATERIAL_COLUMNS
        + EMISSION_COLUMNS
        + ECONOMIC_COLUMNS
        + PHYSICAL_COLUMNS
        + STATUS_COLUMNS
    )


def blank_row(case: Case, superstructure: Superstructure, model_file: str = EMPTY) -> dict[str, object]:
    """A hand-off row with structure filled in and every result still empty.

    Inapplicable operating variables stay empty for the life of the row; the
    Aspen adapter fills only the names in `case.active_variables`.
    """
    row: dict[str, object] = {column.name: EMPTY for column in build_columns(superstructure)}
    row["case_id"] = case.case_id
    row["case_label"] = case.label
    row["schema_version"] = superstructure.schema_version
    row["timestamp_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    row["aspen_model_file"] = model_file
    for node in superstructure.nodes:
        row[f"{node.id}_{node.name}"] = case.selection[node.id]
    row["n_active_operating_vars"] = len(case.active_variables)
    row["converged"] = 0
    return row


def write_case_matrix(
    path: str | Path,
    rows: Iterable[Mapping[str, object]],
    superstructure: Superstructure,
) -> int:
    """Write the hand-off table as UTF-8 with BOM so Excel opens it correctly."""
    columns = build_columns(superstructure)
    written = 0
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[column.name for column in columns], extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            written += 1
    return written


def write_data_dictionary(path: str | Path, superstructure: Superstructure) -> int:
    """Write the column meanings next to the data so the table travels alone."""
    columns = build_columns(superstructure)
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["column", "unit", "group", "description"])
        for column in columns:
            writer.writerow([column.name, column.unit, column.group, column.description])
    return len(columns)
