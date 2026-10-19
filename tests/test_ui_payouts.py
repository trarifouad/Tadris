from datetime import date

import pytest
from PySide6.QtCore import Qt

from tadris import config
from tadris.core import dates
from tadris.domain.models import GroupInput, StudentInput, TeacherInput
from tadris.i18n.fr import t
from tadris.services import (
    auth,
    catalog,
    enrollments,
    groups,
    payouts,
    registrations,
    school_years,
    students,
    teachers,
)
from tadris.ui import payout_dialogs
from tadris.ui.pages.payments_page import PaymentsPage
from tadris.ui.pages.payouts_page import PayoutDetailView, PayoutListView, PayoutsPage
from tadris.ui.pages.teachers import TeacherDetailView
from tadris.ui.payout_dialogs import PayPayoutDialog
from tadris.ui.theme import apply_theme, load_fonts
from tadris.ui.widgets import common
from tadris.ui.widgets.inputs import select_data

TODAY = date(2026, 10, 18)


@pytest.fixture(autouse=True)
def theme(qapp, monkeypatch):
    load_fonts()
    apply_theme(qapp)
    monkeypatch.setattr(dates, "today", lambda: TODAY)


@pytest.fixture(autouse=True)
def documents(monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(config, "documents_dir", lambda: tmp_path)
    monkeypatch.setattr(common, "open_document", lambda path: opened.append(path))
    return opened


@pytest.fixture
def answers(monkeypatch):
    """Confirmations: True (accept) unless a test sets the next answer."""
    asked = []

    def confirm(_parent, title, text, _action):
        asked.append((title, text))
        return answers_given.pop(0) if answers_given else True
    answers_given: list[bool] = []
    monkeypatch.setattr(payout_dialogs, "confirm", confirm)
    return asked, answers_given


@pytest.fixture
def director(conn):
    return auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")


@pytest.fixture
def desk(conn, director):
    auth.create_user(conn, director, "accueil", "password2", "receptionist")
    return auth.login(conn, "accueil", "password2")


@pytest.fixture
def school(conn, director):
    """Karim (60 %) teaches M1 (3 000 DA) with two students from 01/09."""
    year = school_years.create(conn, director, "2026-2027", date(2026, 9, 1), date(2027, 6, 30))
    level = catalog.create(conn, director, "level", "4AM")
    karim = teachers.create(conn, director, TeacherInput("Karim Haddad"), 6000, date(2026, 9, 1))
    m1 = groups.create(conn, director, GroupInput(
        year, level, catalog.create(conn, director, "subject", "Maths"), "M1", 3000, 30,
        date(2026, 9, 1)), karim)

    def pupil(name, on=date(2026, 9, 1)):
        student = students.create(conn, director, StudentInput(name, "Test"))
        registrations.register(conn, director, student, level, 0)
        enrollments.enroll(conn, director, student, m1, enrolled_on=on)
    pupil("Amine")
    pupil("Lina")
    return {"karim": karim, "m1": m1, "level": level, "year": year, "pupil": pupil}


def click(qtbot, button):
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)


def auto_exec(monkeypatch, dialog_class, fill_and_submit):
    def exec_(self):
        fill_and_submit(self)
        return self.result()
    monkeypatch.setattr(dialog_class, "exec", exec_)


def shown(widget) -> bool:
    return not widget.isHidden()


def rows(table) -> list[list[str]]:
    return [[table.item(r, c).text() for c in range(table.columnCount())]
            for r in range(table.rowCount())]


def make_list(qtbot, conn, ctx) -> PayoutListView:
    view = PayoutListView(conn, ctx)
    qtbot.addWidget(view)
    return view


# ----- the list -----

def test_what_is_owed_up_to_the_date(qtbot, conn, director, school):
    view = make_list(qtbot, conn, director)
    assert view.until.text() == "30/09/2026"  # the end of last month
    assert rows(view.due.table) == [["Karim Haddad", "2", "6 000 DA", "—"]]
    view.until.setText("31/08/2026")
    assert view.due.table.isHidden() and shown(view.due.empty)


def test_the_monthly_run(qtbot, conn, director, school):
    nadia = teachers.create(conn, director, TeacherInput("Nadia Kaci"), 5000, date(2026, 10, 1))
    groups.create(conn, director, GroupInput(
        school["year"], school["level"], catalog.create(conn, director, "subject", "Anglais"),
        "A1", 2000, 30, date(2026, 9, 1)), nadia)
    student = students.create(conn, director, StudentInput("Rania", "Test"))
    registrations.register(conn, director, student, school["level"], 0)
    a1 = next(g.id for g in groups.search(conn, director) if g.name == "A1")
    enrollments.enroll(conn, director, student, a1, enrolled_on=date(2026, 9, 1))
    view = make_list(qtbot, conn, director)
    click(qtbot, view.run)
    assert rows(view.list.table) == [["Karim Haddad", "du 01/09/2026 au 30/09/2026", "2",
                                      "6 000 DA", "3 600 DA", "Brouillon", "—"]]
    assert view.error.text() == t["payout.no_rate"].format(teacher="Nadia Kaci",
                                                           date="01/09/2026")
    # Karim's months are in his draft now; Nadia's are still owed (no rate yet).
    assert rows(view.due.table) == [["Nadia Kaci", "1", "2 000 DA", "—"]]
    school["pupil"]("Yanis", date(2026, 9, 20))  # entered after Karim's draft
    view.refresh()
    assert rows(view.due.table)[0] == ["Karim Haddad", "1", "3 000 DA", t["payouts.has_draft"]]


def test_approve_asks_then_locks(qtbot, conn, director, school, answers):
    asked, given = answers
    payout_id = payouts.build_draft(conn, director, school["karim"], date(2026, 9, 30))
    view = make_list(qtbot, conn, director)
    view.list.select_id(payout_id)
    assert view.approve.isEnabled() and not view.pay.isEnabled()
    given.append(False)  # first: cancelled
    click(qtbot, view.approve)
    assert payouts.get(conn, director, payout_id).status == "draft"
    click(qtbot, view.approve)
    assert payouts.get(conn, director, payout_id).status == "approved"
    assert asked[0][1] == t["payouts.confirm_approve"].format(
        amount="3 600 DA", teacher="Karim Haddad", period="du 01/09/2026 au 30/09/2026")
    view.list.select_id(payout_id)
    assert not view.rebuild.isEnabled() and not view.delete.isEnabled() and view.pay.isEnabled()


def test_approve_warns_about_months_entered_since(qtbot, conn, director, school, answers):
    asked, _given = answers
    payout_id = payouts.build_draft(conn, director, school["karim"], date(2026, 9, 30))
    school["pupil"]("Yanis", date(2026, 9, 20))
    view = make_list(qtbot, conn, director)
    view.list.select_id(payout_id)
    click(qtbot, view.approve)
    assert t["payouts.stale"].format(count=1) in asked[0][1]


def test_pay_prints_the_slip(qtbot, conn, director, school, documents, monkeypatch):
    payout_id = payouts.build_draft(conn, director, school["karim"], date(2026, 9, 30))
    payouts.approve(conn, director, payout_id)

    def fill(dialog):
        assert dialog.submit.text() == "Verser 3 600 DA"
        select_data(dialog.method, "transfer")
        dialog._submit()
    auto_exec(monkeypatch, PayPayoutDialog, fill)
    view = make_list(qtbot, conn, director)
    view.list.select_id(payout_id)
    click(qtbot, view.pay)
    assert [p.name for p in documents] == ["paiement-enseignant_karim-haddad_2026-09-30.pdf"]
    view.filter.setCurrentIndex(view.filter.findData("paid"))
    assert rows(view.list.table)[0][5:] == ["Payé", "PE2026-00001"]


def test_delete_a_draft_from_the_list(qtbot, conn, director, school, answers):
    payout_id = payouts.build_draft(conn, director, school["karim"], date(2026, 9, 30))
    view = make_list(qtbot, conn, director)
    view.list.select_id(payout_id)
    click(qtbot, view.delete)
    assert view.list.table.isHidden()
    assert rows(view.due.table)[0][3] == "—"  # owed again, no draft


# ----- the detail -----

def test_detail_groups_and_students(qtbot, conn, director, school):
    payout_id = payouts.build_draft(conn, director, school["karim"], date(2026, 9, 30))
    view = PayoutDetailView(conn, director, payout_id)
    qtbot.addWidget(view)
    assert view.header.title.text() == "Karim Haddad · 3 600 DA"
    assert rows(view.lines.table) == [["M1 · Maths 4AM", "2", "2", "6 000 DA", "60 %",
                                       "3 600 DA"]]
    assert [r[0] for r in rows(view.months.table)] == ["Test Amine", "Test Lina"]
    assert rows(view.months.table)[0][3:] == ["01/09/2026", "3 000 DA", "60 %", "1 800 DA"]
    assert not shown(view.stale) and shown(view.approve) and not shown(view.pay)


def test_detail_rebuild_after_new_months(qtbot, conn, director, school):
    payout_id = payouts.build_draft(conn, director, school["karim"], date(2026, 9, 30))
    school["pupil"]("Yanis", date(2026, 9, 20))
    view = PayoutDetailView(conn, director, payout_id)
    qtbot.addWidget(view)
    assert shown(view.stale) and view.stale.text() == t["payouts.stale"].format(count=1)
    click(qtbot, view.rebuild)
    assert view.payout_id != payout_id
    assert view.header.title.text() == "Karim Haddad · 5 400 DA"
    assert not shown(view.stale)


def test_detail_delete_goes_back(qtbot, conn, director, school, answers):
    payout_id = payouts.build_draft(conn, director, school["karim"], date(2026, 9, 30))
    view = PayoutDetailView(conn, director, payout_id)
    qtbot.addWidget(view)
    went_back = []
    view.back.connect(lambda: went_back.append(True))
    click(qtbot, view.delete)
    assert went_back == [True]


def test_the_page_opens_a_payout(qtbot, conn, director, school):
    payout_id = payouts.build_draft(conn, director, school["karim"], date(2026, 9, 30))
    page = PayoutsPage(conn, director)
    qtbot.addWidget(page)
    page.list.list.activated.emit(payout_id)
    assert page.detail.payout_id == payout_id


# ----- elsewhere -----

def test_the_teachers_payout_history(qtbot, conn, director, desk, school):
    payout_id = payouts.build_draft(conn, director, school["karim"], date(2026, 9, 30))
    view = TeacherDetailView(conn, director, school["karim"])
    qtbot.addWidget(view)
    titles = [view.tabs.tabText(i) for i in range(view.tabs.count())]
    assert titles[-1] == t["teacher_detail.tab.payouts"]
    assert rows(view.payouts.table) == [["du 01/09/2026 au 30/09/2026", "2", "3 600 DA",
                                         "Brouillon", "—"]]
    assert view.payouts.table.item(0, 0).data(Qt.ItemDataRole.UserRole + 1) == payout_id
    desk_view = TeacherDetailView(conn, desk, school["karim"])
    qtbot.addWidget(desk_view)
    assert t["teacher_detail.tab.payouts"] not in [
        desk_view.tabs.tabText(i) for i in range(desk_view.tabs.count())]


def test_cash_shows_teachers_paid_to_the_director(qtbot, conn, director, desk, school):
    payout_id = payouts.build_draft(conn, director, school["karim"], date(2026, 9, 30))
    payouts.approve(conn, director, payout_id)
    payouts.mark_paid(conn, director, payout_id, "cash")
    page = PaymentsPage(conn, director)
    qtbot.addWidget(page)
    assert shown(page.cash.teachers_paid)
    assert page.cash.teachers_paid.text() == t["cash.teachers_paid"].format(
        count=1, total="3 600 DA", drawer="-3 600 DA")
    desk_page = PaymentsPage(conn, desk)
    qtbot.addWidget(desk_page)
    assert not shown(desk_page.cash.teachers_paid)


def test_in_the_sidebar_for_the_director_only(qtbot, conn, director, desk, school):
    from tadris.ui.main_window import MainWindow

    window = MainWindow(conn, director)
    qtbot.addWidget(window)
    window.nav_buttons["payouts"].click()
    assert isinstance(window.pages.currentWidget(), PayoutsPage)
    desk_window = MainWindow(conn, desk)
    qtbot.addWidget(desk_window)
    assert "payouts" not in desk_window.nav_buttons
