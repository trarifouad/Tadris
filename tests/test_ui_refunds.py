"""Refunds, step 6: the screens. A student's refunds in a window from their page (where the
desk asks), what waits on Paiements (where the director decides and records the money going
back, which prints the receipt), and a paid refund's receipt printed again.

Amine pays the fee and September (7 000) on 02/09; asked on 16/09, September has 2 sessions
of 4 left: 3 000 DA at most."""

from datetime import date

import pytest
from PySide6.QtCore import Qt

from tadris import config
from tadris.core.dates import short_period
from tadris.i18n.fr import t
from tadris.services import refunds, subscriptions
from tadris.ui.pages.payments_page import PaymentsPage
from tadris.ui.pages.student_detail import StudentDetailView
from tadris.ui.refund_dialogs import (
    ApproveRefundDialog,
    CloseRefundDialog,
    PayOutRefundDialog,
    RefundRequestDialog,
)
from tadris.ui.theme import apply_theme, load_fonts
from tadris.ui.widgets import common
from test_refunds import ASKED, build_school, fixed_clock, gone, paid_september, pay

PAID_DAY = date(2026, 9, 20)


@pytest.fixture(autouse=True)
def theme(qapp):
    load_fonts()
    apply_theme(qapp)


@pytest.fixture
def today(monkeypatch):
    return fixed_clock(monkeypatch)


@pytest.fixture
def school(conn, today):
    return build_school(conn, today)


@pytest.fixture(autouse=True)
def documents(monkeypatch, tmp_path):
    """Receipts are written to tmp_path; "opening" one records it instead."""
    opened = []
    monkeypatch.setattr(config, "documents_dir", lambda: tmp_path)
    monkeypatch.setattr(common, "open_document", lambda path: opened.append(path))
    return opened


def auto_exec(monkeypatch, dialog_class, fill_and_submit):
    def exec_(self):
        fill_and_submit(self)
        return self.result()
    monkeypatch.setattr(dialog_class, "exec", exec_)


def click(qtbot, button):
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)


def shown(widget) -> bool:
    return not widget.isHidden()


def rows(table) -> list[list[str]]:
    return [[table.item(r, c).text() for c in range(table.columnCount())]
            for r in range(table.rowCount())]


def student_page(qtbot, conn, ctx, school) -> StudentDetailView:
    view = StudentDetailView(conn, ctx, school.amine)
    qtbot.addWidget(view)
    return view


def asked(s, amount=2000, ctx=None) -> int:
    gone(s)  # Amine's last day the 15th
    return refunds.request(s.conn, ctx or s.desk, s.september, amount, "Départ")


# ----- the student's page: the desk asks -----

def test_the_money_card_opens_the_refunds(qtbot, conn, school):
    paid_september(school)
    view = student_page(qtbot, conn, school.desk, school)
    assert shown(view.open_refunds) and view.open_refunds.text() == "Remboursements"
    asked(school)
    view.refresh_overview()
    assert view.open_refunds.text() == "Remboursements (1)"


def test_the_page_counts_the_refunds_and_reads_them_once_opened(qtbot, monkeypatch, conn,
                                                                school):
    """The overview counts them on each change; the list is read when its window opens,
    once (REVIEW_FIXES, finding 12 and round 2, finding 13)."""
    paid_september(school)
    asked(school)
    reads = []
    real = refunds.for_student

    def counted(*args, **kwargs):
        reads.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(refunds, "for_student", counted)
    view = student_page(qtbot, conn, school.desk, school)
    assert reads == [] and view.open_refunds.text() == "Remboursements (1)"
    monkeypatch.setattr(view.windows["refunds"], "exec", lambda: 0)
    view.open_window("refunds")
    assert reads == [1]


def test_the_desk_asks_for_a_refund(qtbot, monkeypatch, conn, school):
    paid_september(school)
    gone(school)
    view = student_page(qtbot, conn, school.desk, school)
    section = view.refunds
    seen = {}

    def fill(dialog):
        seen["months"] = [dialog.month.itemText(i) for i in range(dialog.month.count())]
        seen["count"], seen["amount"] = dialog.count.text(), dialog.amount.text()
        dialog.amount.setText("2 000")
        dialog.reason.setText("Départ de l'élève")
        click(qtbot, dialog.submit)

    auto_exec(monkeypatch, RefundRequestDialog, fill)
    assert shown(section.request)
    click(qtbot, section.request)
    assert seen["months"] == [t["refund_dialog.month"].format(
        group="A · Maths 4AM", period=short_period("2026-09-01", "2026-10-01"),
        most="3 000 DA")]
    assert seen["count"].startswith("2 séance(s) sur 4 restent à partir du 16/09/2026")
    assert seen["amount"] == "3 000 DA"  # the maximum, to lower if needed
    [row] = rows(section.list.table)
    assert row[2:5] == ["2 000 DA", "—", "En attente"]
    # The desk asks and withdraws its own request; deciding and paying are the director's.
    assert not shown(section.approve) and not shown(section.reject) and not shown(section.pay)
    section.list.table.selectRow(0)
    assert shown(section.withdraw) and section.withdraw.isEnabled()


def test_a_refusal_stays_in_the_dialog(qtbot, monkeypatch, conn, school):
    paid_september(school)
    gone(school)
    seen = {}

    def fill(dialog):
        dialog.amount.setText("3 500")
        dialog.reason.setText("Départ")
        click(qtbot, dialog.submit)
        seen["banner"] = dialog.banner.text()

    auto_exec(monkeypatch, RefundRequestDialog, fill)
    view = student_page(qtbot, conn, school.desk, school)
    click(qtbot, view.refunds.request)
    assert seen["banner"] == t["refund.above_max"].format(amount="3 000 DA")
    assert rows(view.refunds.list.table) == []


def test_nothing_to_refund(qtbot, conn, school):
    """Nothing paid yet: the dialog says why and cannot be sent."""
    school.today.day = ASKED
    dialog = RefundRequestDialog(conn, school.desk, school.amine)
    qtbot.addWidget(dialog)
    assert shown(dialog.none) and not dialog.submit.isEnabled()
    assert dialog.none.text() == t["refund_dialog.none"]  # decision 2's rule, in a sentence


def test_a_month_with_no_session_is_counted_in_words():
    from tadris.ui.refund_dialogs import count_text

    assert count_text(0, 0, "2026-10-01", 6000) == t["refund_dialog.count_none"].format(
        value="6\u00a0000\u00a0DA")


def test_still_in_the_group_the_dialog_says_to_record_the_leave(qtbot, conn, school):
    """September paid, Amine still in group A: no month offered, the leave first."""
    paid_september(school)
    school.today.day = ASKED
    dialog = RefundRequestDialog(conn, school.desk, school.amine)
    qtbot.addWidget(dialog)
    assert shown(dialog.still) and not shown(dialog.none)
    assert dialog.still.text() == t["refund_dialog.still_enrolled"].format(
        groups="A · Maths 4AM")
    assert not dialog.submit.isEnabled()


# ----- Paiements: the director's queue -----

def test_the_director_approves_and_pays_out(qtbot, monkeypatch, conn, school, documents):
    paid_september(school)
    asked(school)
    school.today.day = PAID_DAY
    page = PaymentsPage(conn, school.boss)
    qtbot.addWidget(page)
    queue = page.refunds
    assert page.tabs.tabText(2) == "Remboursements à traiter (1)"
    [row] = rows(queue.list.table)
    assert row[1] == "Benali Amine" and row[5] == "En attente"
    queue.list.table.selectRow(0)
    assert queue.approve.isEnabled() and not queue.pay.isEnabled()

    def approve(dialog):
        assert dialog.amount.text() == "2 000 DA"
        assert dialog.most.text() == t["approve_refund_dialog.most"].format(
            asked="2\u00a0000\u00a0DA")  # never more than asked
        dialog.amount.setText("1 500")
        click(qtbot, dialog.submit)

    auto_exec(monkeypatch, ApproveRefundDialog, approve)
    click(qtbot, queue.approve)
    queue.list.table.selectRow(0)
    assert rows(queue.list.table)[0][4:6] == ["1 500 DA", "Approuvé"]
    assert queue.pay.isEnabled() and not queue.approve.isEnabled()

    def pay(dialog):
        dialog.method.setCurrentIndex(dialog.method.findData("cash"))
        click(qtbot, dialog.submit)

    auto_exec(monkeypatch, PayOutRefundDialog, pay)
    click(qtbot, queue.pay)
    assert rows(queue.list.table) == []  # nothing waits any more
    assert page.tabs.tabText(2) == "Remboursements à traiter"
    assert [p.name for p in documents] == ["remboursement_RB2026-00001.pdf"]
    # The day's cash takes the refund out at once.
    assert shown(page.cash.refunds) and "RB2026-00001" in page.cash.refunds.text()
    assert page.cash.net.text() == t["cash.net"].format(received="0 DA",
                                                        refunded="1 500 DA",
                                                        net="-1 500 DA")


def test_an_action_reloads_the_queue_once(qtbot, monkeypatch, conn, school):
    """Paiements used to reload the queue in the section and again from the page
    (REVIEW_FIXES round 2, finding 13)."""
    paid_september(school)
    asked(school)
    page = PaymentsPage(conn, school.boss)
    qtbot.addWidget(page)
    reads = []
    real = page.refunds.refresh

    def once():
        reads.append(1)
        real()

    monkeypatch.setattr(page.refunds, "refresh", once)

    def approve(dialog):
        click(qtbot, dialog.submit)

    auto_exec(monkeypatch, ApproveRefundDialog, approve)
    page.refunds.list.table.selectRow(0)
    click(qtbot, page.refunds.approve)
    assert reads == [1]


def test_the_director_rejects(qtbot, monkeypatch, conn, school):
    paid_september(school)
    asked(school)
    page = PaymentsPage(conn, school.boss)
    qtbot.addWidget(page)
    page.refunds.list.table.selectRow(0)

    def reject(dialog):
        dialog.reason.setText("Pas de motif valable")
        click(qtbot, dialog.submit)

    auto_exec(monkeypatch, CloseRefundDialog, reject)
    click(qtbot, page.refunds.reject)
    assert rows(page.refunds.list.table) == []
    [refund] = refunds.for_student(conn, school.boss, school.amine)
    assert (refund.status, refund.close_reason) == ("rejected", "Pas de motif valable")


def test_the_desk_sees_the_queue_but_only_withdraws_its_own(qtbot, conn, school):
    paid_september(school)
    asked(school, 1000, ctx=school.desk)
    asked(school, 1000, ctx=school.desk2)
    page = PaymentsPage(conn, school.desk)
    qtbot.addWidget(page)
    queue = page.refunds
    assert not shown(queue.approve) and not shown(queue.pay) and not shown(queue.reject)
    queue.list.table.selectRow(0)
    assert queue.withdraw.isEnabled()  # its own
    queue.list.table.selectRow(1)
    assert not queue.withdraw.isEnabled()  # the other desk's


# ----- the receipt, again -----

def test_a_paid_refunds_receipt_prints_again(qtbot, conn, school, documents):
    paid_september(school)
    refund_id = asked(school)
    refunds.approve(conn, school.boss, refund_id)
    school.today.day = PAID_DAY
    refunds.pay_out(conn, school.boss, refund_id, "cash")
    view = student_page(qtbot, conn, school.desk, school)
    section = view.refunds
    section.refresh()  # the list is read when the window opens
    section.list.table.selectRow(0)
    assert rows(section.list.table)[0][3:] == ["2 000 DA", "Versé", "RB2026-00001"]
    assert section.print.isEnabled() and not section.withdraw.isEnabled()
    click(qtbot, section.print)
    click(qtbot, section.print)
    assert [p.name for p in documents] == ["remboursement_RB2026-00001.pdf"] * 2
    assert conn.execute("SELECT COUNT(*) FROM print_log WHERE document_type = 'refund'"
                        ).fetchone()[0] == 2


def test_a_month_refunded_in_full_can_be_cancelled_from_its_window(qtbot, conn, school):
    """October paid ahead, refunded in full: the director's « Annuler » is offered."""
    school.today.day = date(2026, 9, 2)
    october = subscriptions.renew(conn, school.boss, school.september)
    pay(school, 13000)
    gone(school)
    refund_id = refunds.request(conn, school.desk, october, 6000, "Départ")
    refunds.approve(conn, school.boss, refund_id)
    refunds.pay_out(conn, school.boss, refund_id, "cash")
    view = student_page(qtbot, conn, school.boss, school)
    tab = view.subscriptions
    tab.refresh()
    tab.list.select_id(october)
    assert tab.cancel.isEnabled()


# ----- the Journal -----

def test_the_journal_reads_a_refund_in_french(conn, school):
    from tadris.services import journal

    paid_september(school)
    refund_id = asked(school)
    refunds.approve(conn, school.boss, refund_id, 1500)
    school.today.day = PAID_DAY
    refunds.pay_out(conn, school.boss, refund_id, "cash")
    # The audit log is stamped by SQLite's clock (the real day), not the test's.
    entries = journal.entries(conn, school.boss, date(2000, 1, 1), date(2100, 1, 1))
    mine = [(e.action, e.item, e.detail) for e in entries
            if e.item == f"Remboursement n° {refund_id}"]
    assert [action for action, _item, _detail in mine] == [
        "Remboursement versé", "Remboursement approuvé", "Remboursement demandé"]
    paid, approved, requested = (detail for _a, _i, detail in mine)
    assert "Accordé : 1 500 DA" in approved and "Statut : En attente → Approuvé" in approved
    assert "Montant : 2 000 DA" in requested and "Au plus : 3 000 DA" in requested
    assert "Compté à partir du : 16/09/2026" in requested
    assert "Mode : Espèces" in paid and "Numéro : RB2026-00001" in paid
