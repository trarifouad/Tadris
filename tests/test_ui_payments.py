from datetime import date

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from tadris import config
from tadris.core import dates
from tadris.domain.models import ContactInput, ContactLink, GroupInput, StudentInput, TeacherInput
from tadris.i18n.fr import t
from tadris.services import (
    auth,
    catalog,
    contacts,
    debt,
    enrollments,
    groups,
    payments,
    registrations,
    school_years,
    settings,
    students,
    subscriptions,
    teachers,
)
from tadris.ui.enrollment_dialogs import EnrollDialog
from tadris.ui.pages.payments_page import PaymentsPage
from tadris.ui.pages.payments_tab import PaymentsTab
from tadris.ui.pages.setup_tabs import SchoolTab
from tadris.ui.pages.student_detail import StudentDetailView
from tadris.ui.payment_dialogs import PaymentDialog, VoidPaymentDialog
from tadris.ui.subscription_dialogs import RenewDialog
from tadris.ui.theme import apply_theme, load_fonts, tokens
from tadris.ui.widgets import common

TODAY = date(2026, 10, 18)


@pytest.fixture(autouse=True)
def theme(qapp, monkeypatch):
    load_fonts()
    apply_theme(qapp)
    monkeypatch.setattr(dates, "today", lambda: TODAY)


@pytest.fixture(autouse=True)
def documents(monkeypatch, tmp_path):
    """Receipts are written to tmp_path; "opening" one records it instead."""
    opened = []
    monkeypatch.setattr(config, "documents_dir", lambda: tmp_path)
    monkeypatch.setattr(common, "open_document", lambda path: opened.append(path))
    return opened


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
            "physics": group("P1", "Physique", 2500)}


@pytest.fixture
def amine(conn, director, school):
    """Fee 1 000 DA and M1 3 000 DA, both due 18/10."""
    student = students.create(conn, director, StudentInput("Amine", "Benali"))
    registrations.register(conn, director, student, school["level"], 1000)
    enrollments.enroll(conn, director, student, school["maths"])
    return student


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


def make_tab(qtbot, conn, ctx, student_id) -> PaymentsTab:
    tab = PaymentsTab(conn, ctx, student_id)
    qtbot.addWidget(tab)
    return tab


def make_dialog(qtbot, conn, ctx, student_id) -> PaymentDialog:
    dialog = PaymentDialog(conn, ctx, students.get(conn, ctx, student_id))
    qtbot.addWidget(dialog)
    return dialog


# ----- the tab -----

def test_tab_lists_what_is_left_to_pay(qtbot, conn, receptionist, amine):
    tab = make_tab(qtbot, conn, receptionist, amine)
    assert tab.stats.isHidden()  # no credit: no block at all
    late = tab.dues.groups["late"]
    assert late.header.text() == "En retard · 2 échéances · 4 000 DA ▾"
    # tick · item (the group's name, not the sentence) · period · due date · left · action
    assert rows(late.table) == [
        ["", "Frais d'inscription 2026-2027", "—", "18/10/2026", "1 000 DA", ""],
        ["", "M1", "18 oct. → 18 nov.", "18/10/2026", "3 000 DA", ""]]
    assert late.table.item(1, 1).toolTip() == "Abonnement M1 du 18/10/2026 au 18/11/2026"
    color = late.table.item(0, 4).foreground().color()
    assert color == QColor(tokens()["danger"])  # late amounts in the red pen
    assert tab.dues.groups["soon"].isHidden() and tab.dues.groups["later"].isHidden()
    assert tab.history.empty.text() == t["payments_tab.empty"]
    assert shown(tab.receive) and not shown(tab.void)  # void: director only


def test_tab_with_credit(qtbot, conn, director, amine):
    payments.record(conn, director, amine, 5000, "cash")
    tab = make_tab(qtbot, conn, director, amine)
    assert shown(tab.stats.credit) and tab.stats.credit.value.text() == "1 000 DA"
    assert shown(tab.dues.empty)
    assert all(group.isHidden() for group in tab.dues.groups.values())


def test_lines_are_grouped_and_ticked_to_pay(qtbot, conn, director, receptionist, amine,
                                             monkeypatch):
    """Late and due soon open, to come folded; ticking sums the selection; « Encaisser la
    sélection », a row's « Encaisser » and « Encaisser un paiement » open the payment
    dialog with those lines ticked."""
    [month] = subscriptions.for_student(conn, director, amine)
    subscriptions.renew(conn, director, month.id)  # 18/11: to come
    payments.record(conn, director, amine, 1500, "cash")  # fee 1 000, month 500 of 3 000
    tab = make_tab(qtbot, conn, receptionist, amine)
    late, later = tab.dues.groups["late"], tab.dues.groups["later"]
    assert rows(late.table) == [["", "M1", "18 oct. → 18 nov.", "18/10/2026",
                                 "2 500 / 3 000 DA", ""]]  # paid in part
    assert later.header.text() == "À venir · 1 échéance · 3 000 DA ▸"  # folded
    assert later.table.isHidden()
    later.header.click()
    assert not later.table.isHidden()
    assert tab.dues.bar.isHidden()
    later.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    late.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    assert not tab.dues.bar.isHidden()
    assert tab.dues.bar_text.text() == "2 échéances sélectionnées · total 5 500 DA"

    seen = []

    def fill(dialog):
        seen.append((sorted(dialog._checked), dialog.choose.isChecked(), dialog.amount.text()))
        return 0
    monkeypatch.setattr(PaymentDialog, "exec", fill)
    click(qtbot, tab.dues.pay_selection)
    click(qtbot, tab.receive)  # what is late or due soon, ticked
    late.table.cellWidget(0, 5).click()  # one line
    month_now, month_next = late.charges[0].id, later.charges[0].id
    assert seen == [
        (sorted([month_now, month_next]), True, "5 500 DA"),
        ([month_now], True, "2 500 DA"),
        ([month_now], True, "2 500 DA"),
    ]


# ----- the payment dialog -----

def test_dialog_suggests_what_is_late(qtbot, conn, receptionist, amine):
    dialog = make_dialog(qtbot, conn, receptionist, amine)
    assert dialog.amount.text() == "4 000 DA"
    assert dialog.submit.text() == "Encaisser 4 000 DA"
    assert dialog.method.currentData() == "cash"
    assert dialog.payer.currentData() is None  # no contact yet


def test_dialog_preview_follows_the_amount(qtbot, conn, receptionist, amine):
    dialog = make_dialog(qtbot, conn, receptionist, amine)
    dialog.amount.setText("2 500")
    assert dialog.submit.text() == "Encaisser 2 500 DA"
    assert [r[4:] for r in rows(dialog.table)] == [["1 000 DA", "0 DA"],
                                                   ["1 500 DA", "1 500 DA"]]
    assert dialog.outcome.text() == t["payment_dialog.left_after"].format(amount="1 500 DA")
    dialog.amount.setText("5 000")
    assert t["payment_dialog.to_credit"].format(amount="1 000 DA") in dialog.outcome.text()


@pytest.mark.parametrize("typed", ["", "abc", "0", "-5"])
def test_dialog_refuses_a_bad_amount(qtbot, conn, receptionist, amine, typed):
    dialog = make_dialog(qtbot, conn, receptionist, amine)
    dialog.amount.setText(typed)
    assert not dialog.submit.isEnabled()
    assert dialog.submit.text() == t["payment_dialog.submit"]


def test_dialog_main_contact_is_the_payer(qtbot, conn, director, receptionist, amine):
    father = contacts.add(conn, director, amine, ContactInput("Omar Benali", "0770112233"),
                          ContactLink("Père", is_main=True))
    dialog = make_dialog(qtbot, conn, receptionist, amine)
    assert dialog.payer.currentData() == father
    assert dialog.payer.currentText() == "Omar Benali (Père)"


def test_dialog_chosen_lines(qtbot, conn, receptionist, amine):
    dialog = make_dialog(qtbot, conn, receptionist, amine)
    dialog.amount.setText("3 000")
    dialog.choose.setChecked(True)
    month = dialog.table.item(1, 0)
    month_id = month.data(Qt.ItemDataRole.UserRole + 1)
    assert month.checkState() == Qt.CheckState.Unchecked
    month.setCheckState(Qt.CheckState.Checked)  # the month only, not the fee
    assert dialog.table.item(1, 0) is month  # updated in place, not rebuilt
    assert dialog.chosen(3000) == [(month_id, 3000)]
    assert [r[4] for r in rows(dialog.table)] == ["—", "3 000 DA"]
    dialog.choose.setChecked(False)  # back to the oldest first: no boxes
    assert dialog.table.item(1, 0).data(Qt.ItemDataRole.CheckStateRole) is None
    assert [r[4] for r in rows(dialog.table)] == ["1 000 DA", "2 000 DA"]
    dialog.choose.setChecked(True)  # the ticks are remembered
    dialog._submit()
    d = debt.for_student(conn, receptionist, amine)
    assert [(c.kind, c.due) for c in d.charges] == [("registration", 1000)]


def test_dialog_with_nothing_due(qtbot, conn, director, school):
    student = students.create(conn, director, StudentInput("Lina", "Saidi"))
    dialog = make_dialog(qtbot, conn, director, student)
    assert dialog.amount.text() == ""
    assert shown(dialog.nothing) and not shown(dialog.table) and not shown(dialog.choose)


# ----- receiving from the tab: the receipt is printed right away -----

def test_receive_records_and_prints_the_receipt(qtbot, conn, receptionist, amine, documents,
                                                monkeypatch):
    def fill(dialog):
        dialog.amount.setText("2 500")
        dialog._submit()
    auto_exec(monkeypatch, PaymentDialog, fill)
    tab = make_tab(qtbot, conn, receptionist, amine)
    changed = []
    tab.changed.connect(lambda: changed.append(True))
    click(qtbot, tab.receive)
    [line] = rows(tab.history.table)
    assert line[0].startswith("18/10/2026 ")
    assert line[1:] == ["R2026-00001", "2 500 DA", "Espèces", "accueil", "Encaissé"]
    assert [p.name for p in documents] == ["recu_R2026-00001.pdf"]
    assert documents[0].exists()
    assert tab.dues.groups["late"].header.text() == "En retard · 1 échéance · 1 500 DA ▾"
    assert changed == [True]


def test_a_failed_payment_keeps_the_dialog_open(qtbot, conn, receptionist, amine,
                                                monkeypatch):
    seen = {}

    def fill(dialog):
        dialog.choose.setChecked(True)
        dialog.amount.setText("100")
        monkeypatch.setattr(dialog, "chosen", lambda _amount: [(9999, 100)])
        dialog._submit()
        seen["banner"] = dialog.banner.text()
    auto_exec(monkeypatch, PaymentDialog, fill)
    tab = make_tab(qtbot, conn, receptionist, amine)
    click(qtbot, tab.receive)
    assert seen["banner"] == t["payment.charge_unknown"]
    assert tab.history.table.rowCount() == 0


def test_print_again_is_a_duplicate(qtbot, conn, receptionist, amine, documents):
    payments.record(conn, receptionist, amine, 1000, "cash")
    tab = make_tab(qtbot, conn, receptionist, amine)
    tab.history.table.selectRow(0)
    assert tab.print.isEnabled()
    click(qtbot, tab.print)
    click(qtbot, tab.print)
    assert len(documents) == 2
    count = conn.execute("SELECT COUNT(*) FROM print_log WHERE document_type = 'receipt'"
                         ).fetchone()[0]
    assert count == 2


# ----- voiding -----

def test_director_voids_a_payment(qtbot, conn, director, amine, monkeypatch):
    payment_id = payments.record(conn, director, amine, 4000, "cash")

    def fill(dialog):
        dialog.reason.setText("Billet refusé")
        dialog._submit()
    auto_exec(monkeypatch, VoidPaymentDialog, fill)
    tab = make_tab(qtbot, conn, director, amine)
    tab.history.table.selectRow(0)
    assert shown(tab.void) and tab.void.isEnabled()
    click(qtbot, tab.void)
    assert rows(tab.history.table)[0][5] == "Annulé"
    assert payments.get(conn, director, payment_id).voided
    assert tab.dues.groups["late"].header.text() == "En retard · 2 échéances · 4 000 DA ▾"
    tab.history.table.selectRow(0)
    assert not tab.void.isEnabled()  # once only


def test_void_needs_a_reason(qtbot, conn, director, amine):
    payment_id = payments.record(conn, director, amine, 1000, "cash")
    dialog = VoidPaymentDialog(conn, director, payments.get(conn, director, payment_id))
    qtbot.addWidget(dialog)
    dialog._submit()
    assert dialog.banner.text() == t["payment.reason_required"]
    assert not payments.get(conn, director, payment_id).voided


# ----- the student page -----

def test_student_page_tabs_follow_each_other(qtbot, conn, receptionist, amine, monkeypatch):
    def fill(dialog):
        dialog.amount.setText("4 000")
        dialog._submit()
    auto_exec(monkeypatch, PaymentDialog, fill)
    view = StudentDetailView(conn, receptionist, amine)
    qtbot.addWidget(view)
    assert view.money_views.currentWidget() is view.payments.dues  # what is left to pay
    click(qtbot, view.payments.receive)
    # the month and the fee show as paid on their own tabs
    assert view.subscriptions.list.table.item(0, 3).text() == "0 DA"
    assert view.registration.due.text() == "0 DA"


# ----- the sidebar page -----

@pytest.fixture
def desk(conn, director, school, amine, monkeypatch):
    """Amine owes 4 000; Sara owes 500 (P1). Then the clock moves to 02/11."""
    sara = students.create(conn, director, StudentInput("Sara", "Kaci"))
    registrations.register(conn, director, sara, school["level"], 1000)
    enrollments.enroll(conn, director, sara, school["physics"])
    payments.record(conn, director, sara, 3000, "transfer")
    monkeypatch.setattr(dates, "today", lambda: date(2026, 11, 2))
    return {"amine": amine, "sara": sara}


def make_page(qtbot, conn, ctx) -> PaymentsPage:
    page = PaymentsPage(conn, ctx)
    qtbot.addWidget(page)
    return page


def test_debtors_list(qtbot, conn, receptionist, desk):
    page = make_page(qtbot, conn, receptionist)
    table = page.debtors.list.table
    assert rows(table) == [["Benali Amine", "2026-0001", "4 000 DA", "4 000 DA", "18/10/2026",
                            "15"],
                           ["Kaci Sara", "2026-0002", "500 DA", "500 DA", "18/10/2026", "15"]]
    assert page.debtors.total.text() == t["debtors.total"].format(count=2, total="4 500 DA")


def test_debtors_filters(qtbot, conn, receptionist, school, desk):
    page = make_page(qtbot, conn, receptionist)
    page.debtors.min_amount.setText("1 000")
    assert [r[0] for r in rows(page.debtors.list.table)] == ["Benali Amine"]
    page.debtors.min_amount.setText("")
    page.debtors.group.setCurrentIndex(page.debtors.group.findData(school["physics"]))
    assert [r[0] for r in rows(page.debtors.list.table)] == ["Kaci Sara"]
    page.debtors.min_days.setValue(16)
    assert page.debtors.list.table.isHidden()
    assert shown(page.debtors.list.empty)


def test_debtors_bad_minimum_shows_an_error(qtbot, conn, receptionist, desk):
    page = make_page(qtbot, conn, receptionist)
    page.debtors.min_amount.setText("abc")
    assert shown(page.debtors.list.error)


def test_debtors_open_the_student(qtbot, conn, receptionist, desk):
    page = make_page(qtbot, conn, receptionist)
    opened = []
    page.open_student.connect(opened.append)
    page.debtors.list.activated.emit(desk["sara"])
    assert opened == [desk["sara"]]


def test_cash_report(qtbot, conn, director, receptionist, desk):
    page = make_page(qtbot, conn, receptionist)
    assert page.cash.day.text() == "02/11/2026"
    assert page.cash.list.table.isHidden()  # nothing received today
    page.cash.day.set_value(TODAY)
    assert page.cash.total.text() == t["cash.total"].format(date="18/10/2026", total="3 000 DA",
                                                            count=1)
    assert "Virement 3 000 DA" in page.cash.by_method.text()
    assert page.cash.by_cashier.text() == t["cash.by_cashier"].format(parts="directeur 3 000 DA")
    assert not shown(page.cash.voided)
    assert rows(page.cash.list.table)[0][1:] == ["R2026-00001", "Kaci Sara", "3 000 DA",
                                                 "Virement", "directeur", "Encaissé"]


def test_the_page_in_the_sidebar(qtbot, conn, receptionist, desk):
    from tadris.ui.main_window import MainWindow

    window = MainWindow(conn, receptionist)
    qtbot.addWidget(window)
    window.nav_buttons["payments"].click()
    page = window.pages.currentWidget()
    assert isinstance(page, PaymentsPage)
    page.debtors.list.activated.emit(desk["amine"])
    assert window.nav_buttons["students"].isChecked()


# ----- the debt warning -----

def test_enroll_dialog_warns_about_debt(qtbot, conn, director, receptionist, amine):
    dialog = EnrollDialog(conn, receptionist, students.get(conn, receptionist, amine))
    qtbot.addWidget(dialog)
    assert dialog.findChild(common.WarningBanner) is None  # no threshold set
    settings.set_value(conn, director, "defaults.max_debt_warning", 3000)
    dialog = EnrollDialog(conn, receptionist, students.get(conn, receptionist, amine))
    qtbot.addWidget(dialog)
    banner = dialog.findChild(common.WarningBanner)
    assert banner.text() == t["debt.warning"].format(amount="4 000 DA", threshold="3 000 DA")


def test_renew_dialog_warns_about_debt(qtbot, conn, director, amine):
    settings.set_value(conn, director, "defaults.max_debt_warning", 1000)
    [month] = subscriptions.for_student(conn, director, amine)
    dialog = RenewDialog(conn, director, month)
    qtbot.addWidget(dialog)
    assert dialog.findChild(common.WarningBanner) is not None


def test_school_tab_saves_the_threshold(qtbot, conn, director):
    tab = SchoolTab(conn, director)
    qtbot.addWidget(tab)
    assert tab.debt_warning.text() == ""
    tab.debt_warning.setText("5 000")
    click(qtbot, tab.save)
    assert debt.warning_threshold(conn) == 5000
    assert tab.debt_warning.text() == "5 000 DA"
    tab.debt_warning.setText("")
    click(qtbot, tab.save)
    assert debt.warning_threshold(conn) == 0
