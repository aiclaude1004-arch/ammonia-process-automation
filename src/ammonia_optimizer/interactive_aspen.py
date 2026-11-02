"""A safe, observable Aspen Plus COM session for the first automation stage.

Aspen Plus V14 does not reliably publish a manually opened document in the
Running Object Table.  Trying to attach to the user's GUI therefore fails even
though manual simulation is healthy.  This module deliberately launches an
independent instance for an ASCII-path backup copy instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_PROGID = "Apwn.Document.40.0"


class AspenConnectionError(RuntimeError):
    """Raised with a useful remedy when a COM session cannot be established."""


def validate_automation_backup(path: str | Path) -> Path:
    """Require a local, ASCII-only `.bkp` copy before any COM call.

    The original user model is not modified.  Keeping the automation copy in
    an ASCII-only location, e.g. ``C:\\Temp\\AspenMCP``, removes a known source
    of failures in legacy Windows components.
    """
    backup = Path(path).expanduser().resolve()
    if backup.suffix.lower() != ".bkp":
        raise ValueError("Use an Aspen backup copy (.bkp), not the working .apw/.apwz document.")
    if not backup.is_file():
        raise FileNotFoundError(f"Automation backup does not exist: {backup}")
    if not str(backup).isascii():
        raise ValueError(f"Automation backup path must be ASCII-only: {backup}")
    return backup


@dataclass(frozen=True)
class LaunchOptions:
    """Keep first-run automation visible and dialog-capable for diagnosis."""

    visible: bool = True
    suppress_dialogs: bool = False
    progid: str = DEFAULT_PROGID


class InteractiveAspenSession:
    """Own one independent Aspen document without changing the user's GUI case."""

    def __init__(self, options: LaunchOptions = LaunchOptions()) -> None:
        self.options = options
        self.document: Any | None = None
        self.model_path: Path | None = None

    def open_backup(self, path: str | Path) -> None:
        """Open an archived case in an isolated COM instance.

        ``DispatchEx`` is intentional: it prevents COM from reusing or
        modifying a document the user already has open in Aspen Plus.
        """
        backup = validate_automation_backup(path)
        try:
            import pythoncom
            import win32com.client as win32

            pythoncom.CoInitialize()
            document = win32.DispatchEx(self.options.progid)
            document.InitFromArchive2(str(backup))
            # V14 accepts these UI properties only after a document has been
            # initialized with InitFromArchive2/InitNew.
            document.Visible = self.options.visible
            document.SuppressDialogs = self.options.suppress_dialogs
        except Exception as exc:  # COM exceptions have vendor-specific types.
            self.close()
            raise AspenConnectionError(
                "Aspen could not open the automation backup. Keep the Aspen window visible "
                "and dialogs enabled; copy the displayed Aspen error before retrying."
            ) from exc

        self.document = document
        self.model_path = backup

    def run(self) -> None:
        """Run the opened case.  Call only after inspecting the visible first run."""
        if self.document is None:
            raise AspenConnectionError("Open a backup before running Aspen.")
        self.document.Engine.Reinit()
        self.document.Engine.Run2()

    def close(self) -> None:
        """Close only this module's independent document; never the user's GUI case."""
        if self.document is None:
            return
        try:
            self.document.Close()
        finally:
            self.document = None
            self.model_path = None

    def __enter__(self) -> "InteractiveAspenSession":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()
