"""Independent Aspen Plus COM sessions.

This module owns only the document that it creates.  It does not use
``GetActiveObject`` because Aspen Plus V14 does not reliably register a manual
document in the Running Object Table.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Any


DEFAULT_PROGID = "Apwn.Document.40.0"


class AspenConnectionError(RuntimeError):
    """A COM connection failed; inspect the visible Aspen window for details."""


def validate_backup(path: str | Path) -> Path:
    """Validate a safe local backup copy before starting Aspen."""
    backup = Path(path).expanduser().resolve()
    if backup.suffix.lower() != ".bkp":
        raise ValueError("Automation requires an Aspen backup copy (.bkp).")
    if not backup.is_file():
        raise FileNotFoundError(f"Backup does not exist: {backup}")
    if not str(backup).isascii():
        raise ValueError(f"Backup path must contain ASCII characters only: {backup}")
    return backup


def running_aspen_processes() -> list[str]:
    """Return running Aspen GUI/engine image names without changing them."""
    result = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"],
        text=True,
        capture_output=True,
        check=False,
    )
    images = ("aspenplus.exe", "apmain.exe")
    return [
        line
        for line in result.stdout.splitlines()
        if line.lower().lstrip('"').startswith(images)
    ]


@dataclass(frozen=True)
class LaunchOptions:
    """Defaults appropriate for an observable first-run connection."""

    visible: bool = True
    suppress_dialogs: bool = False
    allow_parallel_aspen: bool = False
    progid: str = DEFAULT_PROGID


class AspenSession:
    """One independent, read-only Aspen document session."""

    def __init__(self, options: LaunchOptions = LaunchOptions()) -> None:
        self.options = options
        self.document: Any | None = None
        self.backup: Path | None = None

    def open(self, backup_path: str | Path) -> None:
        """Start an independent visible Aspen document from a `.bkp` copy."""
        backup = validate_backup(backup_path)
        existing = running_aspen_processes()
        if existing and not self.options.allow_parallel_aspen:
            raise AspenConnectionError(
                "An Aspen Plus session is already running. Close it before starting "
                "automation, then run this script again. This prevents a second V14 "
                "session from conflicting with the open interactive model."
            )
        try:
            import pythoncom
            import win32com.client as win32

            pythoncom.CoInitialize()
            document = win32.DispatchEx(self.options.progid)
            # Assign immediately so an initialization failure closes only the
            # process we created, rather than leaving an orphan Aspen session.
            self.document = document
            document.InitFromArchive2(str(backup))
            # Aspen V14 rejects UI properties until InitFromArchive2/InitNew has
            # initialized the document.  Set them only after the archive opens.
            document.Visible = self.options.visible
            document.SuppressDialogs = self.options.suppress_dialogs
        except Exception as exc:
            self.close()
            raise AspenConnectionError(
                "Aspen could not open the backup. Copy any message shown in the visible Aspen window."
            ) from exc

        self.backup = backup

    def names(self, branch: str) -> list[str]:
        """Read names below an Aspen tree branch without changing the model."""
        if self.document is None:
            raise AspenConnectionError("Open a backup before reading the model.")
        node = self.document.Tree.FindNode(branch)
        if node is None:
            return []
        return [str(element.Name) for element in node.Elements]

    def run(self) -> None:
        """Run the opened automation copy. Never call Save implicitly."""
        if self.document is None:
            raise AspenConnectionError("Open a backup before running Aspen.")
        self.document.Engine.Reinit()
        self.document.Engine.Run2()

    def close(self) -> None:
        """Close only the document created by this object."""
        if self.document is None:
            return
        try:
            self.document.Close()
        finally:
            self.document = None
            self.backup = None

    def __enter__(self) -> "AspenSession":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()
