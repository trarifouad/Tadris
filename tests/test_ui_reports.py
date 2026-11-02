"""The Rapports page: who sees which report, the views, a row that opens its page, the exports."""

from datetime import date

import pytest
from PySide6.QtCore import Qt

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.i18n.fr import t
from tadris.services import attendance, auth
from tadris.ui.main_window import MainWindow
from tadris.ui.pages import reports as reports_page
from tadris.ui.pages.reports import ReportsPage
from tadris.ui.theme import apply_theme, load_fonts
from test_reports import MONDAY, TODAY, School


@pytest.fixture(autouse=True)
def theme(qapp, monkeypatch):
    load_fonts()
    apply_theme(qapp)
    monkeypatch.setattr(dates, "today", lambda: TODAY)


@pytest.fixture
def director(conn):
    return auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")


@pytest.fixture
def desk(conn, director):
    user_id = auth.create_user(conn, director, "accueil", "password2", "receptionist")
    return UserContext(user_id=user_id, username="accueil", role="receptionist")


@pytest.fixture
def school(conn, director):
    return School(conn, director)


def page_for(qtbot, conn, ctx) -> ReportsPage:
    page = ReportsPage(conn, ctx)
    qtbot.addWidget(page)
    page.resize(1100, 900)
    page.show()
    return page


def double_click(qtbot, table, row: int, column: int = 0) -> None:
    """As a mouse does it: a click, then the double-click on the same row."""
    point = table.visualRect(table.model().index(row, column)).center()
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=point)
    qtbot.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=point)


def cells(table, row: int) -> list[str]:
    return [table.item(row, c).text() for c in range(table.columnCount())]


def test_the_desk_sees_two_reports_the_director_four(qtbot, conn, director, desk, school):
    assert [b.text() for b in page_for(qtbot, conn, director).tabs.buttons] == [
        "Recettes", "Présences", "Enseignants", "Élèves"]
    desk_page = page_for(qtbot, conn, desk)
    assert [b.text() for b in desk_page.tabs.buttons] == ["Présences", "Élèves"]
    assert desk_page.current().report.key == "presences-par-groupe"


def test_revenue_tiles_chart_table_and_total(qtbot, conn, director, school):
    page = page_for(qtbot, conn, director)
    view = page.current().view
    assert [(tile.name.text(), tile.value.text()) for tile in view.tiles] == [
        ("Facturé", "35 000 DA"), ("Encaissé", "17 000 DA"), ("Reste dû", "18 000 DA"),
        ("Part école", "15 000 DA")]
    assert view.chart_card.isVisible() and view.bars.labels[:2] == ("sept.", "oct.")
    assert view.table.rowCount() == 10
    assert cells(view.table, 0) == ["Septembre 2026", "24 000", "11 000", "13 000", "0",
                                    "14 400", "9 600"]
    assert cells(view.total, 0)[:2] == ["Total", "35 000"]
    assert view.table_card.subtitle.text() == "Année 2026-2027 · montants en DA"


def test_the_switch_shows_the_groups_and_a_row_opens_its_group(qtbot, conn, director, school):
    page = page_for(qtbot, conn, director)
    view = page.current().view
    view.views.select(1)
    assert page.current().report.key == "recettes-par-groupe"
    assert view.table.item(0, 0).text() == "A · Maths 4AM"
    with qtbot.waitSignal(page.open_item) as opened:
        double_click(qtbot, view.table, 0)
    assert opened.args == ["groups", school.a]
    # The fees' line opens nothing.
    fees = next(r for r in range(view.table.rowCount())
                if view.table.item(r, 0).text() == t["reports.fees"])
    with qtbot.assertNotEmitted(page.open_item):
        double_click(qtbot, view.table, fees)


def test_the_total_follows_the_table_columns(qtbot, conn, director, school):
    page = page_for(qtbot, conn, director)
    view = page.current().view
    qtbot.waitUntil(lambda: view.table.columnWidth(0) > 0)
    assert [view.total.columnWidth(c) for c in range(view.table.columnCount())] == [
        view.table.columnWidth(c) for c in range(view.table.columnCount())]


def test_low_attendance_is_red_and_the_period_presets(qtbot, conn, director, school,
                                                      monkeypatch):
    monkeypatch.setattr(dates, "today", lambda: MONDAY)
    session = conn.execute("SELECT id FROM sessions WHERE date = ? AND group_id = ?",
                           (dates.iso(MONDAY), school.a)).fetchone()[0]
    attendance.save(conn, director, session, {school.amine_a: "present",
                                              school.badis_a: "absent"})
    page = page_for(qtbot, conn, director)
    page.show_report("attendance")
    panel = page.current()
    assert (panel.first.value(), panel.last.value()) == (date(2026, 10, 1),
                                                         date(2026, 10, 31))
    assert not panel.first.isEnabled()
    rate = panel.view.table.item(0, panel.view.table.columnCount() - 1)
    assert rate.text() == "50 %"
    assert rate.foreground().color().name() != panel.view.table.item(0, 0).foreground().color(
    ).name()  # in the danger colour
    panel.period.setCurrentIndex(panel.period.findData("custom"))
    assert panel.first.isEnabled()
    panel.first.set_value(date(2026, 10, 20))
    assert panel.view.table.isHidden() and panel.view.empty.isVisible()


def test_a_student_row_opens_the_students_page(qtbot, conn, director, school):
    window = MainWindow(conn, director)
    qtbot.addWidget(window)
    window.nav_buttons["reports"].click()
    page = window.pages.widget(window._slots["reports"])
    page.show_report("students")
    table = page.current().view.table
    window.show()
    row = next(r for r in range(table.rowCount()) if table.item(r, 1).text() == "Test Chems")
    table.setCurrentCell(row, 1)
    qtbot.keyClick(table, Qt.Key.Key_Return)  # Enter opens the row too
    students = window.pages.currentWidget()
    assert students.detail is not None
    assert window.back_button.text() == "← Retour : Rapports"


def test_pdf_and_excel_buttons_write_and_open(qtbot, conn, director, school, tmp_path,
                                              monkeypatch):
    from tadris import config

    opened = []
    monkeypatch.setattr(config, "documents_dir", lambda: tmp_path)
    monkeypatch.setattr(reports_page, "open_document", opened.append)
    page = page_for(qtbot, conn, director)
    qtbot.mouseClick(page.pdf, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(page.excel, Qt.MouseButton.LeftButton)
    assert [p.suffix for p in opened] == [".pdf", ".xlsx"]
    assert all(p.parent == tmp_path and p.exists() for p in opened)


def test_save_as_keeps_the_file_where_chosen(qtbot, conn, director, school, tmp_path,
                                             monkeypatch):
    opened = []
    monkeypatch.setattr(reports_page, "open_document", opened.append)
    monkeypatch.setattr(reports_page.QFileDialog, "getSaveFileName",
                        lambda *args: (str(tmp_path / "bilan"), "Excel (*.xlsx)"))
    page = page_for(qtbot, conn, director)
    qtbot.mouseClick(page.save_as, Qt.MouseButton.LeftButton)
    assert (tmp_path / "bilan.xlsx").exists() and opened == []


def test_a_file_that_cannot_be_written_says_so(qtbot, conn, director, school, tmp_path):
    page = page_for(qtbot, conn, director)
    assert page.export("pdf", tmp_path / "missing" / "r.pdf") is None
    assert page.banner.text().startswith("Impossible d'écrire le fichier")


def test_no_school_year_yet(qtbot, conn, director):
    page = page_for(qtbot, conn, director)
    assert page.current().banner.text() == t["reports.no_year"]


def test_the_wide_column_shrinks_before_the_table_scrolls(qtbot, conn, director, school):
    page = page_for(qtbot, conn, director)
    page.show_report("students")
    view = page.current().view
    room = view.table.viewport().width()
    # Four columns of 100 px and a wide one that would like 300: short of room, the wide
    # one gives way (not under 160 px) so that the table fits without scrolling sideways.
    view._natural = [100, 100, 100, 100, room - 400 + 50]
    view._wide = 4
    view.table.setColumnCount(5)
    view._spread()
    widths = [view.table.columnWidth(c) for c in range(5)]
    assert widths[:4] == [100] * 4 and sum(widths) == room
