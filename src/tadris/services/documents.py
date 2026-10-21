"""The app's own documents folder (config.documents_dir()): what the app writes there to
open it (a report to print, a receipt, a sheet) is a working copy, cleaned up after a while
so the folder does not grow for ever. Only files the app named itself are ever removed;
a report the user saved elsewhere (« Enregistrer sous ») is never touched.
"""

import time
from pathlib import Path

from tadris.db.connection import transaction
from tadris.services import audit

REPORT_DAYS = 30  # an export is a snapshot: made again from the app at any time
PRINT_DAYS = 90  # receipts, slips and sheets: printed again from the app (« DUPLICATA »)
REPORTS = ("rapport_",)
PRINTS = ("recu_", "remboursement_",  # refund slips printed before 0015 (none since)
          "paiement-enseignant_", "presence_", "presence-semaine_")
SUFFIXES = (".pdf", ".xlsx")
DAY = 24 * 60 * 60


def _kept_days(name: str) -> int | None:
    """How long a file the app wrote is kept; None for any other file (never removed)."""
    if name.startswith(REPORTS):
        return REPORT_DAYS
    if name.startswith(PRINTS):
        return PRINT_DAYS
    return None


def clean(folder: Path, now: float | None = None) -> list[Path]:
    """Remove the app's documents older than their keeping time; returns what was removed.
    A file that cannot be removed (open in a viewer on Windows) is left for next time."""
    now = time.time() if now is None else now
    removed = []
    if not folder.is_dir():
        return removed
    for path in folder.iterdir():
        days = _kept_days(path.name)
        if days is None or path.suffix.lower() not in SUFFIXES or not path.is_file():
            continue
        try:
            if now - path.stat().st_mtime > days * DAY:
                path.unlink()
                removed.append(path)
        except OSError:
            continue
    return removed


def clean_at_start(conn, folder: Path) -> int:
    """At the app's start: the cleanup, written to the audit log (by the app itself)."""
    removed = clean(folder)
    if removed:
        with transaction(conn):
            audit.log_system(conn, "documents.clean", "documents",
                             new={"count": len(removed), "folder": str(folder)})
    return len(removed)
