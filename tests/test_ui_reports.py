from datetime import date

import pytest
from openpyxl import load_workbook
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea

from tadris import config
from tadris.core import dates
from tadris.core.context import UserContext
from tadris.domain.models import Dashboard, DashboardSession, Debtor, GroupFill
from tadris.i18n.fr import t
from tadris.services import auth, reports
from tadris.ui.main_window import MainWindow
from tadris.ui.pages.dashboard import LIST_ROWS, DashboardPage
from tadris.ui.pages.reports import ReportsPage
from tadris.ui.theme import apply_theme, load_fonts
from tadris.ui.widgets import common
from test_reports import TODAY, School


@pytest.fixture(autouse=True)
def theme(qapp, monkeypatch):
    load_fonts()
    apply_theme(qapp)
    monkeypatch.setattr(reports, "_now_time", lambda: "10:00")


@pytest.fixture(autouse=True)
def documents(monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(config, "documents_dir", lambda: tmp_path)
    monkeypatch.setattr(common, "open_document", lambda path: opened.append(path))
    return opened


@pytest.fixture
def director(conn):
    return auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")


@pytest.fixture
def desk(conn, director):
    user_id = auth.create_user(conn, director, "accueil", "password2", "receptionist")
    return UserContext(user_id=user_id, username="accueil", role="receptionist")


@pytest.fixture
def school(conn, director, monkeypatch):
    built = School(conn, director, monkeypatch)
    monkeypatch.setattr(dates, "today", lambda: TODAY)
    return built


def click(qtbot, button):
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)


def texts(table) -> list[list[str]]:
    return [[table.item(r, c).text() for c in range(table.columnCount())]
            for r in range(table.rowCount())]


def double_click_row(table, row: int) -> None:
    table.activated.emit(table.model().index(row, 0))


# ----- dashboard -----

def test_dashboard_cards_and_lists(qtbot, conn, director, school):
    page = DashboardPage(conn, director)
    qtbot.addWidget(page)
    assert page.day.text() == "Aujourd'hui, 18/10/2026"
    assert page.debt_card.value.text() == "7 000 DA"
    assert page.debt_card.detail.text() == "1 élève(s) en retard"
    assert page.money_card.value.text() == "14 000 DA"
    assert page.money_card.detail.text() == (
        "Facturé 17 000 DA · réglé 13 000 DA · remboursé 1 000 DA")
    assert page.sessions_card.value.text() == "0"
    assert texts(page.debtors.list.table) == [["Cherif Badis", "7 000 DA", "47 j"]]
    assert texts(page.groups.list.table) == [["A · Maths 4AM", "2", "20", "10 %"],
                                            ["B · Physique 4AM", "1", "20", "5 %"]]
    assert not page.sessions.list.table.isVisible()


def full_board() -> Dashboard:
    """Nine of everything: more than a dashboard list shows."""
    many = range(9)
    return Dashboard(
        today="2026-10-18", now="10:00",
        sessions=tuple(DashboardSession(id=i, start_time=f"{8 + i:02d}:00",
                                        end_time=f"{9 + i:02d}:00", group_title=f"G{i}",
                                        room="Salle A", teacher="Karim", status="planned")
                       for i in many),
        ending=(), lapsed=0, debt_total=9000, debtors=12,
        top_debtors=tuple(Debtor(student_id=i, student_number=f"2026-{i:04d}",
                                 student_name=f"Élève {i}", owed_now=1000, due=1000, credit=0,
                                 oldest_overdue="2026-10-01", days_overdue=17)
                          for i in range(5)),
        groups=tuple(GroupFill(group_id=i, title=f"G{i}", enrolled=5, seats=10) for i in many),
        charged=0, settled=0, collected=0, refunded=0)


def test_long_lists_stop_at_four_rows(qtbot, conn, director):
    page = DashboardPage(conn, director)
    qtbot.addWidget(page)
    page.show_board(full_board())
    for panel, button in ((page.sessions, "Voir les 9"), (page.debtors, "Voir les 12"),
                          (page.groups, "Voir les 9")):
        assert panel.list.table.rowCount() == LIST_ROWS
        assert panel.more.text() == button
    assert page.ending.more.text() == "Voir tout"  # nothing left out
    assert page.ending.list.empty.isVisibleTo(page) and page.ending.list.table.isHidden()


def test_the_dashboard_never_scrolls(qtbot, conn, director):
    """1920 x 1080 at 125 % is 1536 x 864 in Qt's units; the window gets about 1536 x 795
    (the desktop's bar and the title bar take the rest): everything shows."""
    page = DashboardPage(conn, director)
    qtbot.addWidget(page)
    page.show_board(full_board())
    assert page.findChildren(QScrollArea) == []
    page.resize(1536 - 216, 795 - 24)  # minus the sidebar and the status bar
    page.show()
    qtbot.wait(10)
    assert page.layout().minimumSize().height() <= page.height()
    for panel in (page.sessions, page.debtors, page.groups):
        table = panel.list.table
        assert table.height() == table.maximumHeight()  # every row shown, no inner scroll
        assert table.verticalScrollBar().maximum() == 0


def test_receptionist_sees_the_fill_instead_of_the_money(qtbot, conn, desk, school):
    page = DashboardPage(conn, desk)
    qtbot.addWidget(page)
    page.show()
    assert not page.money_card.isVisible() and page.fill_card.isVisible()
    assert page.fill_card.value.text() == "7 %"  # 3 of 40, rounded down
    assert page.fill_card.detail.text() == "3 élèves pour 40 places"


def test_dashboard_opens_a_debtor(qtbot, conn, director, school):
    page = DashboardPage(conn, director)
    qtbot.addWidget(page)
    with qtbot.waitSignal(page.open_student) as opened:
        double_click_row(page.debtors.list.table, 0)
    assert opened.args == [school.badis]


def test_see_all_opens_the_page(qtbot, conn, director, school):
    window = MainWindow(conn, director)
    qtbot.addWidget(window)
    window.nav_buttons["dashboard"].click()
    dashboard = window.pages.currentWidget()
    assert isinstance(dashboard, DashboardPage)
    more = dashboard.debtors.list._end.itemAt(0).widget()
    assert more.text() == "Voir tout"
    click(qtbot, more)
    assert window.nav_buttons["payments"].isChecked()


# ----- reports page -----

def tab_labels(page) -> list[str]:
    return [page.tabs.tabText(i) for i in range(page.tabs.count())]


def test_tabs_follow_the_rights(qtbot, conn, director, desk, school):
    boss = ReportsPage(conn, director)
    front = ReportsPage(conn, desk)
    qtbot.addWidget(boss)
    qtbot.addWidget(front)
    assert tab_labels(boss) == ["Recettes", "Retards", "Présences", "Enseignants", "Élèves",
                                "Journal"]
    assert tab_labels(front) == ["Retards", "Présences", "Élèves"]


def test_revenue_tab_shows_the_service_figures(qtbot, conn, director, school):
    page = ReportsPage(conn, director)
    qtbot.addWidget(page)
    view = page.views["revenue"]
    shown = texts(view.table)
    assert shown[0] == ["Septembre 2026", "12 000 DA", "9 000 DA", "3 000 DA", "9 000 DA",
                        "0 DA", "9 000 DA"]
    assert shown[-1] == ["Total", "29 000 DA", "22 000 DA", "7 000 DA", "23 000 DA",
                         "1 000 DA", "22 000 DA"]
    assert view.table.item(len(shown) - 1, 0).font().weight() > view.table.item(
        0, 0).font().weight()
    assert view.period.text() == "Année 2026-2027"

    view.view.setCurrentIndex(view.view.findData("group"))
    assert view.month_box.isVisibleTo(view)
    view.month.setCurrentIndex(view.month.findData("2026-10-01"))
    assert view.period.text() == "Octobre 2026"
    assert [row[0] for row in texts(view.table)] == [
        "A · Maths 4AM", "B · Physique 4AM", "Frais d'inscription", "Total"]


def test_excel_button_writes_what_the_screen_shows(qtbot, conn, director, school, documents):
    page = ReportsPage(conn, director)
    qtbot.addWidget(page)
    view = page.views["revenue"]
    click(qtbot, view.excel)
    [path] = documents
    sheet = load_workbook(path).active
    total_row = 4 + len(view.report.rows) + 1
    assert [cell.value for cell in sheet[total_row]] == list(view.report.total)
    assert view.rows_shown()[-1][1] == "29 000 DA" == f"{sheet.cell(total_row, 2).value:,} DA"\
        .replace(",", " ")

    click(qtbot, view.pdf)
    assert documents[-1].suffix == ".pdf"


def test_debtors_tab_opens_the_student(qtbot, conn, desk, school):
    page = ReportsPage(conn, desk)
    qtbot.addWidget(page)
    view = page.views["debtors"]
    assert texts(view.table)[0] == ["Cherif Badis", "2026-0002", "4 000 DA", "3 000 DA",
                                    "0 DA", "0 DA", "7 000 DA"]
    with qtbot.waitSignal(page.open_student) as opened:
        double_click_row(view.table, 0)
    assert opened.args == [school.badis]
    # The total row opens nobody.
    with qtbot.assertNotEmitted(page.open_student):
        double_click_row(view.table, 1)


def test_attendance_tab_bad_dates_show_a_banner(qtbot, conn, desk, school):
    page = ReportsPage(conn, desk)
    qtbot.addWidget(page)
    page.tabs.setCurrentIndex(1)
    view = page.views["attendance"]
    view.first.set_value(date(2026, 10, 18))
    view.last.set_value(date(2026, 10, 1))
    assert view.banner.text() == t["report.dates_order"]
    view.last.set_value(date(2026, 10, 31))
    assert view.banner.isHidden()
    assert view.empty.isVisibleTo(view)  # no attendance recorded


def test_student_tab_filters(qtbot, conn, desk, school):
    page = ReportsPage(conn, desk)
    qtbot.addWidget(page)
    page.tabs.setCurrentIndex(2)
    view = page.views["students"]
    assert [row[1] for row in texts(view.table)] == ["Benali", "Cherif", "Djebbar", ""]
    assert texts(view.table)[-1][0] == "3 élève(s)"
    view.group.setCurrentIndex(view.group.findData(school.b))
    assert [row[1] for row in texts(view.table)] == ["Cherif", ""]


def test_audit_tab(qtbot, conn, director, desk, school):
    page = ReportsPage(conn, director)
    qtbot.addWidget(page)
    page.tabs.setCurrentIndex(5)
    view = page.views["audit"]
    today = date.today()  # audit rows carry SQLite's clock
    view.first.set_value(today)
    view.last.set_value(today)
    assert view.table.rowCount() == len(view.entries) > 0

    view.family.setCurrentIndex(view.family.findData("payment"))
    assert {row[2] for row in texts(view.table)} == {"payment.record", "payment.void"}
    view.table.selectRow(0)
    assert view.detail.toPlainText().startswith(view.entries[0].action)
    assert "Après :" in view.detail.toPlainText()

    view.user.setCurrentIndex(view.user.findData(desk.user_id))
    assert view.table.rowCount() == 0 and view.empty.isVisibleTo(view)

    view.user.setCurrentIndex(0)
    view.entity.setText("abc")
    view.entity.editingFinished.emit()
    assert view.banner.text() == t["report.entity_invalid"]
