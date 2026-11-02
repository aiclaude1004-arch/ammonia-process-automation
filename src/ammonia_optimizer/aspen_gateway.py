"""Narrow py2aspen adapter for one verified Aspen Plus case.

Do not add guessed `Tree.FindNode` paths here.  Each path must be obtained from
the saved baseline `.bkp`, recorded with units, and covered by a smoke test.
"""

from __future__ import annotations

from pathlib import Path

from py2aspen import UnitAspen


def verify_com_connection(progid: str) -> str:
    """Create and cleanly close Aspen, returning its application name."""
    app = UnitAspen(progid)
    try:
        app.lazybind()
        return str(app.app.Name)
    finally:
        app.exit()


def require_baseline_model(path: str | Path) -> Path:
    path = Path(path).resolve()
    if path.suffix.lower() != ".bkp":
        raise ValueError("Automation baseline must be an Aspen backup (.bkp) copy.")
    if not path.is_file():
        raise FileNotFoundError(f"Create a converged baseline model first: {path}")
    return path
