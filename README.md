# Ammonia Process Automation

**Version 0.1.0 · source snapshot 2026-11-02**

Research automation for ammonia-based hybrid power processes: enumerate
superstructure candidates, keep physical constraints explicit, open independent
Aspen Plus sessions, and inspect the baseline SOFC–ICE–ORC calculation pipeline.

[한국어](README_KO.md) · [Quick start](#quick-start) ·
[Reproduction](docs/REPRODUCIBILITY.md) · [Code map](docs/CODE_MAP.md) ·
[Validation](docs/VALIDATION.md) · [Provenance](provenance/source_manifest.json)

## What is included

| Component | Location | Status |
|---|---|---|
| Superstructure, schema, physics and feasibility | `src/ammonia_optimizer/` | Current workspace snapshot |
| Versioned design basis and constraints | `configs/` | Current workspace snapshot |
| Independent pywin32 COM sessions | `src/aspen_automation/` | Offline preflight tests; licensed run separate |
| Baseline batch calculation and audits | `reproduction/baseline/SOFC/` | Current source with portable paths |
| November C0295 source capture v6 | `research/c0295_source_capture_v6/` | Experimental, workspace-bound reference |

The runnable core is updated from the current workspace, not the earlier
September portable package. This is a curated software release, not a claim that
every active research-case adapter is integrated or that all paper results have
been reproduced. Detailed source hashes and packaging changes are recorded.

## Quick start

Use Python 3.12 (tested authoring environment). Clone and run from the repository:

```powershell
git clone https://github.com/aiclaude1004-arch/ammonia-process-automation.git
cd ammonia-process-automation
python scripts/verify_snapshot.py
python -m unittest discover -s tests -v
python scripts/generate_case_matrix.py --out outputs/case_matrix
```

These offline commands use the standard library and do not start Aspen.
Enumeration writes `case_matrix.csv`, `data_dictionary.csv` and
`enumeration_report.md`. Structural candidates are not converged simulations.
Optional editable installation: `python -m pip install -e .`.

## Aspen Plus connection

Requires Windows, a separately licensed Aspen Plus V14 installation and a local
ASCII-only path to a BKP copy:

```powershell
python -m pip install -r requirements-aspen.txt
python scripts/open_model.py --backup C:/AspenRuns/model.bkp
```

The command opens its own visible document, lists blocks and streams, and closes
that document when prompted. It does not launch the campaign. See the reproduction
guide for baseline inputs, dependency setup, acceptance checks and known limits.

## Scientific interpretation

- Keep convergence, physical acceptance and experimental validation distinct.
- Preserve failed records; use missing values for inapplicable outputs.
- `configs/case_status.json` is source metadata, not independently verified
  campaign evidence. No performance completion count is asserted from it.
- The reduced SOFC model has documented assumptions and a finite validation range.
- No new Aspen simulation or final-paper figure reproduction was performed as
  part of this release. TEA/LCA completion is not established by code packaging.

## License and citation

Author-owned code is released under [MIT](LICENSE). Aspen software and private
model inputs are not included. See [third-party notices](THIRD_PARTY_NOTICES.md).
Use [CITATION.cff](CITATION.cff) for this software; manuscript title, author order
and DOI will be added when finalized. See [release notes](CHANGELOG.md).
