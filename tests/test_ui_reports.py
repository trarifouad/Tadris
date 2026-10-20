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
from tadris.ui.pages.dashboard import DashboardPage, share_rows
from tadris.ui.pages.reports import ReportsPage
from tadris.ui.theme import apply_theme, load_fonts
from tadris.ui.widgets import common
from test_reports import TODAY, School, automatic_entry


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


def test_rows_are_shared_where_they_are_hidden():
    assert share_rows(10, [2, 0]) == [2, 0]  # room left over
    assert share_rows(10, [9, 9]) == [5, 5]
    assert share_rows(10, [9, 3]) == [7, 3]  # the short list shows all, the long one the rest
    assert share_rows(10, [12, 12]) == [5, 5]
    assert share_rows(0, [4, 4]) == [1, 1]  # always one row, even when nothing fits


def dashboard_at(qtbot, conn, ctx, width: int, height: int) -> DashboardPage:
    page = DashboardPage(conn, ctx)
    qtbot.addWidget(page)
    page.show_board(full_board())
    page.resize(width, height)
    page.show()
    qtbot.wait(10)
    return page


def lists_bottom(page) -> int:
    """The lowest edge of a panel, in the page's coordinates."""
    return max(panel.mapTo(page, panel.rect().bottomLeft()).y()
               for panels in page.columns for panel in panels)


def test_a_large_window_shows_every_row(qtbot, conn, director):
    """1920 x 1080 at 100 %: room for the nine sessions and the nine groups."""
    page = dashboard_at(qtbot, conn, director, 1920 - 216, 1000 - 24)
    assert (page.sessions.shown, page.debtors.shown, page.groups.shown) == (9, 5, 9)
    assert page.sessions.more.text() == "Voir tout"
    assert page.groups.more.text() == "Voir tout"
    assert page.debtors.more.text() == "Voir les 12"  # 12 late, the five largest sent


def test_rows_fill_the_window_and_never_scroll(qtbot, conn, director):
    """1920 x 1080 at 125 % is 1536 x 864 in Qt's units; the window gets about 1536 x 795.
    The lists take the height there is, and stop at the window's bottom edge."""
    page = dashboard_at(qtbot, conn, director, 1536 - 216, 795 - 24)
    assert page.findChildren(QScrollArea) == []
    assert page.sessions.shown > 4  # more than the old fixed four
    assert page.sessions.shown + page.groups.shown > 8
    assert lists_bottom(page) <= page.height()
    for panel in (page.sessions, page.debtors, page.groups):
        table = panel.list.table
        assert table.rowCount() == panel.shown
        assert table.verticalScrollBar().maximum() == 0  # no inner scroll either
    assert page.ending.list.empty.isVisibleTo(page) and page.ending.list.table.isHidden()
    assert page.ending.more.text() == "Voir tout"


def test_a_smaller_window_shows_fewer_rows(qtbot, conn, director):
    big = dashboard_at(qtbot, conn, director, 1320, 771)
    small = dashboard_at(qtbot, conn, director, 1320, 600)
    assert 1 <= small.sessions.shown < big.sessions.shown
    assert small.sessions.more.text() == "Voir les 9"
    assert lists_bottom(small) <= small.height()


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
    automatic_entry(conn)
    page = ReportsPage(conn, director)
    qtbot.addWidget(page)
    page.tabs.setCurrentIndex(5)
    view = page.views["audit"]
    today = date.today()  # audit rows carry SQLite's clock
    view.first.set_value(today)
    view.last.set_value(today)
    assert view.table.rowCount() == len(view.entries) > 0

    assert "Sauvegarde créée" not in {row[2] for row in texts(view.table)}
    assert all(e.user is not None for e in view.entries)  # the app's own work: not shown
    assert view.user.findText("Système") == -1

    view.family.setCurrentIndex(view.family.findData("payment"))
    assert {row[2] for row in texts(view.table)} == {"Paiement enregistré", "Paiement annulé"}
    view.table.selectRow(0)
    detail = view.detail.toPlainText()
    assert detail.startswith(texts(view.table)[0][2] + " par ")  # « Paiement … par accueil »
    assert " à " in detail and "Paiement n° " in detail
    assert "Montant" in detail and "{" not in detail

    view.user.setCurrentIndex(view.user.findData(desk.user_id))
    assert view.table.rowCount() == 0 and view.empty.isVisibleTo(view)

    view.user.setCurrentIndex(0)
    view.entity.setText("abc")
    view.entity.editingFinished.emit()
    assert view.banner.text() == t["report.entity_invalid"]


def test_journal_detail_card():
    from tadris.services.journal import Field
    from tadris.ui.pages.reports import detail_html

    html = detail_html("Remboursement approuvé par directeur", "le 18/10/2026 à 10:00",
                       [Field("Statut", "Approuvé", before="En attente"),
                        Field("Motif", "<départ>")])
    assert "<b>Approuvé</b>" in html and "En attente" in html
    assert "&lt;départ&gt;" in html  # what was typed is escaped
    empty = detail_html("Déconnexion par kadam", "le 18/10/2026 à 15:30", [])
    assert "Aucun autre détail enregistré." in empty


def test_redrawing_the_dashboard_many_times_is_safe(qtbot, conn, director):
    """Shrinking and growing the lists, and going to another page and back, again and again:
    a cell reused across redraws once corrupted memory (a crash a few clicks later)."""
    window = MainWindow(conn, director)
    qtbot.addWidget(window)
    window.show()
    dashboard = window.pages.currentWidget()
    for height in (500, 800, 450, 900, 600) * 4:
        dashboard.show_board(full_board())
        window.resize(1300, height)
        qtbot.wait(1)
        window.nav_buttons["students"].click()
        window.nav_buttons["dashboard"].click()
    assert dashboard.sessions.list.table.rowCount() == dashboard.sessions.shown


def test_every_tab_exports_pdf_and_excel(qtbot, conn, director, school, documents):
    """Each tab, each view: the PDF and the Excel file are written, open, and hold the rows
    on screen."""
    page = ReportsPage(conn, director)
    qtbot.addWidget(page)
    variants = [("revenue", None), ("revenue", ("view", "group")), ("debtors", None),
                ("attendance", None), ("attendance", ("view", "student")),
                ("teachers", None), ("students", None), ("audit", None)]
    keys = list(page.views)
    for key, change in variants:
        page.tabs.setCurrentIndex(keys.index(key))
        view = page.views[key]
        if key == "audit":
            view.first.set_value(date(2020, 1, 1))
        if change is not None:
            combo = getattr(view, change[0])
            combo.setCurrentIndex(combo.findData(change[1]))
        click(qtbot, view.pdf)
        assert documents[-1].suffix == ".pdf" and documents[-1].read_bytes()[:4] == b"%PDF"
        click(qtbot, view.excel)
        sheet = load_workbook(documents[-1]).active
        assert sheet["A1"].value == view.report.title
        body = [row for row in sheet.iter_rows(min_row=5, max_row=4 + len(view.report.rows),
                                               values_only=True)]
        assert len(body) == len(view.report.rows), key
    assert len(documents) == 2 * len(variants)
