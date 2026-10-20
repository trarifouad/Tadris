"""The documents folder: « Ouvrir le dossier », « Enregistrer sous » for Excel, and the
cleanup of the app's old working copies."""

import json
import os
import time
from datetime import date

import pytest
from openpyxl import load_workbook
from PySide6.QtCore import Qt

from tadris import app, config
from tadris.core import dates
from tadris.services import auth, documents
from tadris.ui.pages.reports import ReportsPage
from tadris.ui.theme import apply_theme, load_fonts
from tadris.ui.widgets import common

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


# ----- the reports' buttons -----

@pytest.fixture
def page(qtbot, qapp, conn, monkeypatch, tmp_path):
    load_fonts()
    apply_theme(qapp)
    monkeypatch.setattr(dates, "today", lambda: date(2026, 10, 18))
    monkeypatch.setattr(config, "documents_dir", lambda: tmp_path / "documents")
    (tmp_path / "documents").mkdir()
    director = auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")
    reports_page = ReportsPage(conn, director)
    qtbot.addWidget(reports_page)
    reports_page.tabs.setCurrentIndex([*reports_page.views].index("students"))
    return reports_page.views["students"]


def test_open_folder_shows_the_apps_documents(qtbot, page, monkeypatch, tmp_path):
    shown = []
    monkeypatch.setattr(common, "open_folder", shown.append)
    qtbot.mouseClick(page.folder, Qt.MouseButton.LeftButton)
    assert shown == [tmp_path / "documents"]
    assert page.folder.text() == "Ouvrir le dossier"


def test_excel_asks_where_to_save(qtbot, page, monkeypatch, tmp_path):
    asked = []
    target = tmp_path / "pour le comptable"
    target.mkdir()
    monkeypatch.setattr(common, "open_document", lambda path: None)
    monkeypatch.setattr(config, "save_dir", lambda: tmp_path / "Documents")

    def answer(parent, title, suggested, file_filter):
        asked.append((title, suggested, file_filter))
        return target / "élèves octobre"  # typed without « .xlsx »

    monkeypatch.setattr(common, "ask_save_path", answer)
    with qtbot.waitSignal(page.exported, timeout=15000) as done:
        qtbot.mouseClick(page.excel, Qt.MouseButton.LeftButton)
    assert asked == [("Enregistrer le fichier Excel",
                      tmp_path / "Documents" / "rapport_liste-eleves_2026-10-18.xlsx",
                      "Fichier Excel (*.xlsx)")]
    path = done.args[0]
    assert path == target / "élèves octobre.xlsx" and load_workbook(path).active["A1"].value
    assert not list((tmp_path / "documents").iterdir())  # not in the app's folder


def test_cancelling_save_as_writes_nothing(qtbot, page, conn, monkeypatch):
    monkeypatch.setattr(common, "ask_save_path", lambda *args: None)
    qtbot.mouseClick(page.excel, Qt.MouseButton.LeftButton)
    qtbot.wait(50)
    assert page.excel.isEnabled() and page.busy.isHidden()
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'report.export'"
                        ).fetchone()[0] == 0


def test_the_pdf_still_goes_to_the_apps_folder(qtbot, page, monkeypatch, tmp_path):
    asked = []
    monkeypatch.setattr(common, "ask_save_path", lambda *args: asked.append(args))
    monkeypatch.setattr(common, "open_document", lambda path: None)
    with qtbot.waitSignal(page.exported, timeout=15000) as done:
        qtbot.mouseClick(page.pdf, Qt.MouseButton.LeftButton)
    assert asked == []  # to print: no question
    assert done.args[0].parent == tmp_path / "documents"
