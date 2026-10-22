from datetime import date

import pytest
from PySide6.QtCore import Qt

from tadris.core import dates
from tadris.domain.models import GroupInput, StudentInput, TeacherInput
from tadris.i18n.fr import t
from tadris.services import (
    auth,
    catalog,
    enrollments,
    groups,
    registrations,
    school_years,
    students,
    subscriptions,
    teachers,
)
from tadris.ui.enrollment_dialogs import EnrollDialog
from tadris.ui.pages.student_detail import StudentDetailView
from tadris.ui.pages.subscriptions_tab import SubscriptionsTab
from tadris.ui.subscription_dialogs import CancelSubscriptionDialog, RenewDialog, StartDialog
from tadris.ui.theme import apply_theme, load_fonts


@pytest.fixture(autouse=True)
def theme(qapp, monkeypatch):
    load_fonts()
    apply_theme(qapp)
    monkeypatch.setattr(dates, "today", lambda: date(2026, 10, 18))


@pytest.fixture
def director(conn):
    return auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")


@pytest.fixture
def receptionist(conn, director):
    auth.create_user(conn, director, "accueil", "password2", "receptionist")
    return auth.login(conn, "accueil", "password2")


@pytest.fixture
def school(conn, director):
    year = school_years.create(conn, director, "2026-2027", date(2026, 9, 1), date(2027, 6, 30))
    level = catalog.create(conn, director, "level", "4AM")
    teacher = teachers.create(conn, director, TeacherInput("Karim Haddad"), 6000,
                              date(2026, 9, 1))

    def group(name, subject, price):
        subject_id = catalog.create(conn, director, "subject", subject)
        return groups.create(conn, director, GroupInput(year, level, subject_id, name, price,
                                                        10, date(2026, 9, 1)), teacher)

    return {"level": level, "maths": group("M1", "Maths", 3000),
            "physics": group("P1", "Physique", 2500), "club": group("Club", "Lecture", 0)}


@pytest.fixture
def amine(conn, director, school):
    student = students.create(conn, director, StudentInput("Amine", "Benali"))
    registrations.register(conn, director, student, school["level"], 0)
    return student


@pytest.fixture
def in_maths(conn, receptionist, school, amine):
    return enrollments.enroll(conn, receptionist, amine, school["maths"])


def click(qtbot, button):
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)


def auto_exec(monkeypatch, dialog_class, fill_and_submit):
    def exec_(self):
        fill_and_submit(self)
        return self.result()
    monkeypatch.setattr(dialog_class, "exec", exec_)


def make_tab(qtbot, conn, ctx, student_id) -> SubscriptionsTab:
    tab = SubscriptionsTab(conn, ctx, student_id)
    qtbot.addWidget(tab)
    return tab


def rows(tab) -> list[list[str]]:
    table = tab.list.table
    return [[table.item(r, c).text() for c in range(table.columnCount())]
            for r in range(table.rowCount())]


def shown(widget) -> bool:
    return not widget.isHidden()


def pay(conn, director, student_id, subscription_id, amount):
    charge = conn.execute("SELECT id FROM charges WHERE subscription_id = ?",
                          (subscription_id,)).fetchone()[0]
    cur = conn.execute("INSERT INTO payments(student_id, amount, method, paid_at, received_by) "
                       "VALUES (?, ?, 'cash', '2026-10-18T10:00:00', ?)",
                       (student_id, amount, director.user_id))
    conn.execute("INSERT INTO payment_allocations(payment_id, charge_id, amount) VALUES (?, ?, ?)",
                 (cur.lastrowid, charge, amount))


def test_empty_tab(qtbot, conn, receptionist, amine):
    tab = make_tab(qtbot, conn, receptionist, amine)
    assert tab.list.empty.text() == t["subscriptions.empty"]
    assert not shown(tab.start)


def test_the_automatic_first_month_is_listed(qtbot, conn, receptionist, in_maths, amine):
    tab = make_tab(qtbot, conn, receptionist, amine)
    assert rows(tab) == [["M1 · Maths 4AM", "18 oct. → 18 nov.", "3 000 DA",
                          "3 000 DA", "En cours"]]
    assert tab.summary.text() == t["subscriptions.summary"].format(due="3 000 DA")


def test_free_group_says_free(qtbot, conn, receptionist, school, amine):
    enrollments.enroll(conn, receptionist, amine, school["club"])
    tab = make_tab(qtbot, conn, receptionist, amine)
    assert rows(tab)[0][2:4] == ["0 DA", t["subscriptions.free"]]


def test_renew_from_the_tab(qtbot, conn, receptionist, in_maths, amine, monkeypatch):
    seen = {}

    def fill(dialog):
        seen["date"], seen["preview"] = dialog.date.text(), dialog.preview.text()
        dialog._submit()
    auto_exec(monkeypatch, RenewDialog, fill)
    tab = make_tab(qtbot, conn, receptionist, amine)
    tab.list.table.selectRow(0)
    assert tab.renew.isEnabled()
    click(qtbot, tab.renew)
    assert seen["date"] == "18/11/2026"
    assert seen["preview"] == t["renew_dialog.preview"].format(
        period="du 18/11/2026 au 18/12/2026", price="3 000 DA")
    assert [r[1:] for r in rows(tab)] == [
        ["18 nov. → 18 déc.", "3 000 DA", "3 000 DA", "À venir"],
        ["18 oct. → 18 nov.", "3 000 DA", "3 000 DA", "En cours"],
    ]
    assert tab.selected().start_date == "2026-11-18"  # the new month is selected
    tab.list.table.selectRow(1)
    assert not tab.renew.isEnabled()  # only the latest month


def test_renew_before_the_end_shows_in_the_dialog(qtbot, conn, receptionist, in_maths, amine):
    month = subscriptions.for_student(conn, receptionist, amine)[0]
    dialog = RenewDialog(conn, receptionist, month)
    qtbot.addWidget(dialog)
    dialog.date.setText("01/11/2026")
    dialog._submit()
    assert dialog.banner.text() == t["subscription.start_before_end"].format(end="18/11/2026")


def test_no_renewal_once_the_student_left(qtbot, conn, receptionist, in_maths, amine):
    enrollments.leave(conn, receptionist, in_maths)
    tab = make_tab(qtbot, conn, receptionist, amine)
    tab.list.table.selectRow(0)
    assert not tab.renew.isEnabled()


def test_cancel_is_for_the_director(qtbot, conn, director, receptionist, in_maths, amine,
                                    monkeypatch):
    assert not shown(make_tab(qtbot, conn, receptionist, amine).cancel)
    reasons = iter(["", "Erreur de date"])

    def fill(dialog):
        dialog.reason.setText(next(reasons))
        dialog._submit()
        assert dialog.banner.text() == t["subscription.reason_required"]
        dialog.reason.setText(next(reasons))
        dialog._submit()
    auto_exec(monkeypatch, CancelSubscriptionDialog, fill)
    tab = make_tab(qtbot, conn, director, amine)
    tab.list.table.selectRow(0)
    click(qtbot, tab.cancel)
    assert rows(tab)[0][3:] == ["—", "Annulé"]
    assert tab.summary.text() == t["subscriptions.summary"].format(due="0 DA")
    assert shown(tab.start)  # no month left in M1: a new one can be started


def test_cancel_disabled_once_paid(qtbot, conn, director, in_maths, amine):
    pay(conn, director, amine, subscriptions.for_student(conn, director, amine)[0].id, 1000)
    tab = make_tab(qtbot, conn, director, amine)
    tab.list.table.selectRow(0)
    assert rows(tab)[0][3] == "2 000 DA"
    assert not tab.cancel.isEnabled()


def test_start_again_after_a_cancellation(qtbot, conn, director, receptionist, in_maths, amine,
                                          monkeypatch):
    month = subscriptions.for_student(conn, director, amine)[0]
    subscriptions.cancel(conn, director, month.id, "Erreur")
    seen = {}

    def fill(dialog):
        seen["group"], seen["date"] = dialog.enrollment.currentText(), dialog.date.text()
        dialog.date.setText("25/10/2026")
        dialog._submit()
    auto_exec(monkeypatch, StartDialog, fill)
    tab = make_tab(qtbot, conn, receptionist, amine)
    click(qtbot, tab.start)
    assert (seen["group"], seen["date"]) == ("M1 · Maths 4AM", "18/10/2026")
    assert rows(tab)[0][1:] == ["25 oct. → 25 nov.", "3 000 DA", "3 000 DA",
                                "À venir"]
    assert not shown(tab.start)


def test_enrolling_from_the_groups_tab_shows_the_month(qtbot, conn, receptionist, school,
                                                      amine, monkeypatch):
    def fill(dialog):
        dialog.picker.select(school["physics"])
        dialog._submit()
    auto_exec(monkeypatch, EnrollDialog, fill)
    view = StudentDetailView(conn, receptionist, amine)
    qtbot.addWidget(view)
    click(qtbot, view.groups.enroll)
    assert rows(view.subscriptions)[0][0] == "P1 · Physique 4AM"


# ----- the Abonnements page, bulk renewal -----

def yanis_in(conn, ctx, school, group_key):
    student = students.create(conn, ctx, StudentInput("Yanis", "Haddad"))
    registrations.register(conn, ctx, student, school["level"], 0)
    return student, enrollments.enroll(conn, ctx, student, school[group_key])


def page(qtbot, conn, ctx):
    from tadris.ui.pages.subscriptions_page import SubscriptionsPage

    view = SubscriptionsPage(conn, ctx)
    qtbot.addWidget(view)
    return view


def section_rows(section) -> list[list[str]]:
    table = section.table
    return [[table.item(r, c).text() for c in range(table.columnCount())]
            for r in range(table.rowCount())]


def test_page_lists_months_to_renew(qtbot, conn, receptionist, school, amine, in_maths,
                                    monkeypatch):
    monkeypatch.setattr(dates, "today", lambda: date(2026, 11, 15))
    view = page(qtbot, conn, receptionist)
    assert view.tabs.tabText(0) == t["subscriptions_page.tab.soon"].format(count=1)
    assert section_rows(view.soon) == [["Benali Amine", "2026-0001", "M1 · Maths 4AM",
                                        "du 18/10/2026 au 18/11/2026", "3 000 DA"]]
    assert view.tabs.tabText(1) == t["subscriptions_page.tab.lapsed"].format(count=0)
    assert not view.renew_lapsed.isEnabled()
    monkeypatch.setattr(dates, "today", lambda: date(2026, 11, 20))
    view.refresh()
    assert view.tabs.tabText(1) == t["subscriptions_page.tab.lapsed"].format(count=1)


def test_bulk_renewal_with_an_unticked_student(qtbot, conn, receptionist, school, amine,
                                              in_maths, monkeypatch):
    from tadris.ui.subscription_dialogs import BulkRenewDialog

    yanis_in(conn, receptionist, school, "physics")
    monkeypatch.setattr(dates, "today", lambda: date(2026, 11, 15))
    seen = {}

    def fill(dialog):
        seen["rows"] = dialog.table.rowCount()
        seen["total"] = dialog.total.text()
        dialog.table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)  # Yanis stops
        seen["after"] = dialog.total.text()
        dialog._submit()
    auto_exec(monkeypatch, BulkRenewDialog, fill)
    view = page(qtbot, conn, receptionist)
    click(qtbot, view.renew_soon)
    assert seen["rows"] == 2
    assert seen["total"] == t["bulk_renew.total"].format(count=2, total="5 500 DA")
    assert seen["after"] == t["bulk_renew.total"].format(count=1, total="3 000 DA")
    starts = {s.student_name: s.start_date for s in subscriptions.ending_soon(
        conn, receptionist, days=40)}
    assert starts == {"Benali Amine": "2026-11-18", "Haddad Yanis": "2026-10-18"}
    assert view.tabs.tabText(0) == t["subscriptions_page.tab.soon"].format(count=1)


def test_nothing_ticked_cannot_be_submitted(qtbot, conn, receptionist, in_maths, amine,
                                            monkeypatch):
    from tadris.ui.subscription_dialogs import BulkRenewDialog

    monkeypatch.setattr(dates, "today", lambda: date(2026, 11, 15))
    dialog = BulkRenewDialog(conn, receptionist, subscriptions.ending_soon(conn, receptionist),
                             "x")
    qtbot.addWidget(dialog)
    dialog.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    assert not dialog.submit.isEnabled()


def test_bulk_refusal_shows_in_the_dialog_and_renews_nothing(qtbot, conn, receptionist, school,
                                                            amine, in_maths, monkeypatch):
    from tadris.ui.subscription_dialogs import BulkRenewDialog

    _, yanis_enrollment = yanis_in(conn, receptionist, school, "physics")
    monkeypatch.setattr(dates, "today", lambda: date(2026, 11, 15))
    dialog = BulkRenewDialog(conn, receptionist, subscriptions.ending_soon(conn, receptionist),
                             "x")
    qtbot.addWidget(dialog)
    enrollments.leave(conn, receptionist, yanis_enrollment)  # meanwhile, Yanis left
    dialog._submit()
    assert dialog.banner.text() == t["subscription.enrollment_not_live"]
    assert len(subscriptions.for_student(conn, receptionist, amine)) == 1


def test_missing_tab_starts_a_month(qtbot, conn, director, receptionist, amine, in_maths,
                                    monkeypatch):
    subscriptions.cancel(conn, director, subscriptions.for_student(conn, director, amine)[0].id,
                         "Erreur")

    def fill(dialog):
        dialog._submit()
    auto_exec(monkeypatch, StartDialog, fill)
    view = page(qtbot, conn, receptionist)
    assert view.tabs.tabText(2) == t["subscriptions_page.tab.missing"].format(count=1)
    view.missing.table.selectRow(0)
    click(qtbot, view.start)
    assert view.tabs.tabText(2) == t["subscriptions_page.tab.missing"].format(count=0)


def test_double_click_opens_the_student_page(qtbot, conn, receptionist, amine, in_maths,
                                             monkeypatch):
    from tadris.ui.main_window import MainWindow

    monkeypatch.setattr(dates, "today", lambda: date(2026, 11, 15))
    window = MainWindow(conn, receptionist)
    qtbot.addWidget(window)
    assert "subscriptions" in window.nav_buttons
    window.nav_buttons["subscriptions"].click()
    subs = window.pages.currentWidget()
    subs.soon.activated.emit(subs.soon.ids()[0])
    students_page = window.pages.currentWidget()
    assert window.nav_buttons["students"].isChecked()
    assert students_page.detail.student_id == amine
