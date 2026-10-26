"""The documents folder: the cleanup of the app's old working copies."""

import json
import os
import time

from tadris import app
from tadris.services import documents

DAY = 24 * 60 * 60


def aged(folder, name: str, days: float):
    path = folder / name
    path.write_bytes(b"x")
    when = time.time() - days * DAY
    os.utime(path, (when, when))
    return path


# ----- the cleanup -----

def test_old_working_copies_go_and_nothing_else(tmp_path):
    old_report = aged(tmp_path, "rapport_journal_2026-09-01_101010.pdf", 31)
    new_report = aged(tmp_path, "rapport_journal_2026-10-01_101010.xlsx", 29)
    old_receipt = aged(tmp_path, "recu_R2026-00001.pdf", 91)
    new_receipt = aged(tmp_path, "recu_R2026-00002.pdf", 89)
    old_sheet = aged(tmp_path, "presence-semaine_maths_2026-06-01.pdf", 120)
    old_slip = aged(tmp_path, "paiement-enseignant_karim_2026-06-30.pdf", 120)
    mine = aged(tmp_path, "notes du directeur.pdf", 400)  # not the app's: never removed
    other = aged(tmp_path, "rapport_journal.txt", 400)  # not a PDF nor an Excel file
    (tmp_path / "rapport_dossier").mkdir()  # a folder, whatever its name

    removed = documents.clean(tmp_path)
    assert sorted(removed) == sorted([old_report, old_receipt, old_sheet, old_slip])
    for kept in (new_report, new_receipt, mine, other, tmp_path / "rapport_dossier"):
        assert kept.exists()


def test_a_missing_folder_is_fine(tmp_path):
    assert documents.clean(tmp_path / "nowhere") == []


def test_the_cleanup_at_start_is_recorded_by_the_app(conn, tmp_path):
    aged(tmp_path, "rapport_x_2026-01-01_000000.pdf", 40)
    assert documents.clean_at_start(conn, tmp_path) == 1
    row = conn.execute("SELECT user_id, new_value FROM audit_log "
                       "WHERE action = 'documents.clean'").fetchone()
    assert row["user_id"] is None and json.loads(row["new_value"])["count"] == 1
    assert documents.clean_at_start(conn, tmp_path) == 0  # nothing left: nothing written
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'documents.clean'"
                        ).fetchone()[0] == 1


def test_a_failing_cleanup_never_stops_the_app(conn, monkeypatch, capsys):
    def broken(conn, folder):
        raise PermissionError("denied")

    monkeypatch.setattr(app.documents, "clean_at_start", broken)
    app._clean_documents(conn)
    assert "Nettoyage des documents impossible" in capsys.readouterr().err
