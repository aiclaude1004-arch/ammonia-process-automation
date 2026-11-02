# Repository benchmarks

Reviewed 2026-11-02. Structural inspiration only; no source code was imported
from the following repositories in this packaging task.

| Reference | Observed practice | Applied here |
|---|---|---|
| [Aspen-Plus-Automation](https://github.com/zwang1995/Aspen-Plus-Automation) | Domain-specific process simulation automation repository | Explain Aspen prerequisites and provide an explicit model connection entry point |
| [PyPSA](https://github.com/PyPSA/PyPSA) | Separate source, examples, tests, documentation; CITATION.cff and contribution instructions | Separate code/docs/tests; citation template; contribution guide; offline CI |
| [cookiecutter-reproducible-research](https://github.com/timtroendle/cookiecutter-reproducible-research) | Config/data/scripts/tests/report/environment separation and explicit workflow | Keep configuration versioned, document execution order, record hashes and input dependencies |

The last template states native Windows is not actively supported. Its structure
is adopted, not its platform assumptions: Aspen COM requires Windows here.
Snakemake is not introduced merely for appearance; the present entry points remain
small Python commands and the existing Windows campaign controller.

Our additional needs: distinguish topology candidates from actual simulations;
preserve failures, model assumptions, units and convergence/audit evidence;
keep commercial Aspen installation separate from the distributable code.
