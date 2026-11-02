# Validation — v0.1.0, 2026-11-02

The current public snapshot was tested with CPython 3.12.14 on Windows:

- **101 existing offline tests passed** in 53.295 seconds.
- Enumeration: 54,000 full-factorial combinations, **1,323 structural candidates**,
  **85 columns** in the generated hand-off table.
- The review CSV used by the regression tests is bundled and the test refers to
  its repository-relative path. Assertions were not weakened or skipped.
- Basic token/private-key/email/workstation-name marker scan: no matches in the
  public text sources. This is a focused release check, not a full security audit.
- Python files were syntax-checked without importing case-specific runners.
- No licensed Aspen simulation was launched for this release.
- The experimental C0295 source and workspace-dependent tests are reference
  material, excluded from the portable 101-test suite.

Source snapshots and packaging transformations are recorded in the provenance
manifest. GitHub Actions repeats the portable suite for pushes and pull requests.
The runtime status in the original metadata is not independently certified here.
