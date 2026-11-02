# Reproducibility

## Offline

Run the three README commands. No external Python packages or Aspen are needed.
The GitHub workflow runs the same checks. Keep the snapshot manifest synchronized
with intentional reviewed source changes using `python scripts/update_manifest.py`.

## Licensed baseline

The baseline implementation was taken from current SOFC/18_Thermodynamic_Revision
and SOFC/03_Model. Only local dependency injection, absolute working-directory
paths and the Aspen ProgID override were adjusted for portability.

1. Use Windows, CPython 3.12 x64, Aspen Plus V14 and requirements-aspen.txt.
2. Copy `reproduction/baseline/SOFC` to a new ASCII-only local run directory.
3. Supply the matching private `Input.bkp` and `Equilibrium.bkp` under
   `18_Thermodynamic_Revision`; those models are not distributed in this code release.
4. Supply `01_Literature/gri30.yaml` from the corresponding Cantera data distribution,
   retaining its attribution. Record its exact hash/version with the run. The
   model parses this file directly; a different data revision needs validation.
5. Create `Logs`, `Results`, `Snapshots` under `18_Thermodynamic_Revision`.
   Create Screen.json as a list of two Baseline_Config.json copies, with run_id
   and candidate_id set to BASELINE and COLD_REOPEN respectively.
6. From that directory run `python campaign_controller.py screen 1`.

This last command starts real Aspen calculations. Inspect acceptance.checks,
simulation.checks, model hashes, material/energy residuals, utility accounting,
history warnings and agreement between independent baseline runs. A result file
or supervisor exit code alone is not acceptance. Do not run simulation jobs in
a cloud synchronization folder.

The campaign branch needs a reviewed Pilot_Review.json and Candidates.json.
This release supplies neither invented approval nor a substitute for those inputs.

## Limits

No newly executed Aspen baseline is claimed by this release. All-case November
adapters are not merged into one universal runner. The C0295 reference prototype
requires its original trusted pins and fixtures; it is not a portable demo.
Final figures/results require their own versioned inputs and acceptance evidence.
