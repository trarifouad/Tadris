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
    payments,
    refunds,
    registrations,
    school_years,
    students,
    subscriptions,
    teachers,
)
from tadris.ui.pages.payments_page import PaymentsPage
from tadris.ui.pages.refunds_tab import RefundsTab
from tadris.ui.pages.student_detail import StudentDetailView
from tadris.ui.refund_dialogs import (
    ApproveRefundDialog,
    PayOutDialog,
    RefundRequestDialog,
    RejectRefundDialog,
)
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
def director(conn):
    return auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")


@pytest.fixture
def desk(conn, director):
    auth.create_user(conn, director, "accueil", "password2", "receptionist")
    return auth.login(conn, "accueil", "password2")


@pytest.fixture
def amine(conn, director):
    """Fee 1 000; M1 3 000 from 18/10 to 18/11."""
    year = school_years.create(conn, director, "2026-2027", date(2026, 9, 1), date(2027, 6, 30))
    level = catalog.create(conn, director, "level", "4AM")
    teacher = teachers.create(conn, director, TeacherInput("Karim Haddad"), 6000,
                              date(2026, 9, 1))
    maths = groups.create(conn, director, GroupInput(
        year, level, catalog.create(conn, director, "subject", "Maths"), "M1", 3000, 10,
        date(2026, 9, 1)), teacher)
    student = students.create(conn, director, StudentInput("Amine", "Benali"))
    registrations.register(conn, director, student, level, 1000)
    enrollments.enroll(conn, director, student, maths)
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


def month_charge(conn, ctx, student_id) -> int:
    [m] = subscriptions.for_student(conn, ctx, student_id)
    return m.charge_id


def make_tab(qtbot, conn, ctx, student_id) -> RefundsTab:
    tab = RefundsTab(conn, ctx, student_id)
    qtbot.addWidget(tab)
    return tab


# ----- the tab -----

def test_empty_tab_and_buttons_by_role(qtbot, conn, director, desk, amine):
    tab = make_tab(qtbot, conn, desk, amine)
    assert shown(tab.refunds.empty)
    assert shown(tab.request) and shown(tab.refunds.pay)
    assert not shown(tab.refunds.approve) and not shown(tab.refunds.reject)
    boss = make_tab(qtbot, conn, director, amine)
    assert shown(boss.refunds.approve) and shown(boss.refunds.reject)


# ----- refunds -----

def test_refund_dialog_suggests_and_follows_the_date(qtbot, conn, director, desk, amine):
    payments.record(conn, director, amine, 4000, "cash")
    dialog = RefundRequestDialog(conn, desk, amine)
    qtbot.addWidget(dialog)
    select_data(dialog.charge, month_charge(conn, desk, amine))
    assert dialog.amount.text() == "3 000 DA"  # the month starts today: nothing used
    dialog.unused_from.setText("28/10/2026")  # 10 of 31 days used
    assert dialog.amount.text() == "2 032 DA"
    assert "2 032 DA" in dialog.info.text()
    dialog.reason.setText("Départ")
    dialog._submit()
    r = refunds.get(conn, desk, dialog.refund_id)
    assert (r.status, r.amount_final, r.amount_computed) == ("pending", 2032, 2032)


def test_refund_dialog_with_nothing_paid(qtbot, conn, desk, amine):
    dialog = RefundRequestDialog(conn, desk, amine)
    qtbot.addWidget(dialog)
    assert shown(dialog.nothing) and not dialog.submit.isEnabled()


@pytest.fixture
def asked(conn, director, desk, amine):
    payments.record(conn, director, amine, 4000, "cash")
    return refunds.request(conn, desk, month_charge(conn, desk, amine), 2000, "Départ")


def test_request_from_the_tab(qtbot, conn, director, desk, amine, monkeypatch):
    payments.record(conn, director, amine, 4000, "cash")

    def fill(dialog):
        select_data(dialog.charge, month_charge(conn, desk, amine))
        dialog.amount.setText("1 500")
        dialog.reason.setText("Départ")
        dialog._submit()
    auto_exec(monkeypatch, RefundRequestDialog, fill)
    tab = make_tab(qtbot, conn, desk, amine)
    click(qtbot, tab.request)
    assert rows(tab.refunds.table)[0][1:] == [
        "Abonnement M1 du 18/10/2026 au 18/11/2026", "1 500 DA", "En attente", "—"]
    assert tab.refunds.selected_id() is not None


def test_approve_then_pay_out_prints_the_slip(qtbot, conn, director, desk, amine, asked,
                                              documents, monkeypatch):
    def approve(dialog):
        assert dialog.amount.text() == "2 000 DA"
        dialog.amount.setText("1 800")
        dialog._submit()

    def pay(dialog):
        assert dialog.submit.text() == "Rembourser 1 800 DA"
        select_data(dialog.method, "cash")
        dialog._submit()
    auto_exec(monkeypatch, ApproveRefundDialog, approve)
    auto_exec(monkeypatch, PayOutDialog, pay)
    boss = make_tab(qtbot, conn, director, amine)
    boss.refunds.table.selectRow(0)
    assert boss.refunds.approve.isEnabled() and not boss.refunds.pay.isEnabled()
    click(qtbot, boss.refunds.approve)
    assert rows(boss.refunds.table)[0][2:4] == ["1 800 DA", "Approuvé"]

    tab = make_tab(qtbot, conn, desk, amine)
    tab.refunds.table.selectRow(0)
    assert tab.refunds.pay.isEnabled()
    click(qtbot, tab.refunds.pay)
    assert rows(tab.refunds.table)[0][2:] == ["1 800 DA", "Versé", "RB2026-00001"]
    assert [p.name for p in documents] == ["remboursement_RB2026-00001.pdf"]
    assert documents[0].exists()
    tab.refunds.table.selectRow(0)
    assert tab.refunds.print.isEnabled() and not tab.refunds.pay.isEnabled()


def test_reject_needs_a_reason(qtbot, conn, director, amine, asked, monkeypatch):
    seen = {}

    def fill(dialog):
        dialog._submit()
        seen["banner"] = dialog.banner.text()
        dialog.reason.setText("Le mois est commencé")
        dialog._submit()
    auto_exec(monkeypatch, RejectRefundDialog, fill)
    tab = make_tab(qtbot, conn, director, amine)
    tab.refunds.table.selectRow(0)
    click(qtbot, tab.refunds.reject)
    assert seen["banner"] == t["refund.reason_required"]
    assert rows(tab.refunds.table)[0][3] == "Refusé"


# ----- the Paiements page -----

def test_refund_queue_on_the_payments_page(qtbot, conn, director, desk, amine, asked):
    page = PaymentsPage(conn, director)
    qtbot.addWidget(page)
    assert page.tabs.tabText(2) == t["payments_page.tab.refunds"].format(count=1)
    assert rows(page.refunds.table)[0][1:4] == [
        "Benali Amine", "Abonnement M1 du 18/10/2026 au 18/11/2026", "2 000 DA"]
    opened = []
    page.open_student.connect(opened.append)
    page.refunds.activated.emit(asked)
    assert opened == [amine]


def test_cash_shows_the_refunds_paid_out(qtbot, conn, director, desk, amine, asked):
    refunds.approve(conn, director, asked)
    refunds.pay_out(conn, desk, asked, "cash")
    page = PaymentsPage(conn, desk)
    qtbot.addWidget(page)
    assert page.tabs.tabText(2) == t["payments_page.tab.refunds"].format(count=0)
    assert shown(page.cash.refunded)
    assert page.cash.refunded.text() == t["cash.refunded"].format(
        count=1, total="2 000 DA", drawer="2 000 DA")  # 4 000 received, 2 000 handed back


def test_pay_out_from_the_queue_prints_the_slip(qtbot, conn, director, desk, amine, asked,
                                                documents, monkeypatch):
    """A paid refund leaves the queue: the slip is printed by id, not by the selection."""
    refunds.approve(conn, director, asked)
    auto_exec(monkeypatch, PayOutDialog, lambda dialog: dialog._submit())
    page = PaymentsPage(conn, desk)
    qtbot.addWidget(page)
    page.refunds.select_id(asked)
    click(qtbot, page.refunds.pay)
    assert page.refunds.table.isHidden()  # the queue is empty now
    assert [p.name for p in documents] == ["remboursement_RB2026-00001.pdf"]


def test_student_page_tabs_follow_a_refund(qtbot, conn, director, desk, amine, monkeypatch):
    """A month refunded in full: the Abonnements tab lets the director cancel it."""
    payments.record(conn, director, amine, 4000, "cash")
    refund_id = refunds.request(conn, desk, month_charge(conn, desk, amine), 3000, "Erreur")
    refunds.approve(conn, director, refund_id)
    auto_exec(monkeypatch, PayOutDialog, lambda dialog: dialog._submit())
    view = StudentDetailView(conn, director, amine)
    qtbot.addWidget(view)
    assert view.tabs.tabText(view.tabs.indexOf(view.refunds)) == t["student_detail.tab.refunds"]
    view.subscriptions.list.table.selectRow(0)
    assert not view.subscriptions.cancel.isEnabled()  # 3 000 paid and kept
    view.refunds.refunds.select_id(refund_id)
    click(qtbot, view.refunds.refunds.pay)
    view.subscriptions.list.table.selectRow(0)
    assert view.subscriptions.cancel.isEnabled()  # refunded in full: it may go
