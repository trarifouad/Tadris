"""Refunds, step 4: the cash of the day and Recettes. A refund is money going out on the day it
went back, a movement of its own: the payment it came from never changes. « Encaissé » stays
what came in, « Remboursé » what went back, « Net encaissé » the difference.

Amine (group A, 6 000 DA a month, Mondays) pays the fee (1 000) and September (6 000) in
cash on 02/09; on 16/09 the desk asks 2 000 back on September (3 000 at most)."""

from datetime import date

import pytest

from tadris.core.money import format_dzd
from tadris.i18n.fr import t
from tadris.services import debt, payments, refunds, reports, subscriptions
from tadris.ui.pages.payments_page import PaymentsPage
from tadris.ui.theme import apply_theme, load_fonts
from test_refunds import (
    ASKED,
    ask,
    build_school,
    done,
    fixed_clock,
    gone,
    paid_october,
    paid_september,
    pay,
)

PAID_DAY = date(2026, 9, 20)


@pytest.fixture
def today(monkeypatch):
    return fixed_clock(monkeypatch)


@pytest.fixture
def school(conn, today):
    return build_school(conn, today)


def in_sentence(amount: int) -> str:
    """An amount as Recettes writes it in a sentence (non-breaking spaces)."""
    return format_dzd(amount).replace(" ", "\u00a0")


def refund(s, amount=2000, method="cash", on=PAID_DAY) -> int:
    """Asked on 16/09 (Amine's last day the 15th), approved, and the money gone back on
    `on`."""
    gone(s)
    refund_id = refunds.request(s.conn, s.desk, s.september, amount, "Départ")
    refunds.approve(s.conn, s.boss, refund_id)
    s.today.day = on
    refunds.pay_out(s.conn, s.boss, refund_id, method)
    return refund_id


def payment_rows(conn) -> list[tuple]:
    return [tuple(r) for r in conn.execute(
        "SELECT p.id, p.amount, p.method, p.paid_at, pa.charge_id, pa.amount "
        "FROM payments p JOIN payment_allocations pa ON pa.payment_id = p.id ORDER BY pa.id")]


# ----- the cash of the day -----

def test_the_refund_goes_out_on_its_own_day(conn, school):
    payment = paid_september(school)
    before = payment_rows(conn)
    refund_id = refund(school)
    first = payments.cash_report(conn, school.boss, date(2026, 9, 2))
    assert (first.total, first.refunded, first.net, first.cash_in_drawer) == (7000, 0, 7000,
                                                                              7000)
    out = payments.cash_report(conn, school.boss, PAID_DAY)
    assert out.payments == () and [r.id for r in out.refunds] == [refund_id]
    assert (out.total, out.refunded, out.net) == (0, 2000, -2000)
    assert out.refunded_by_method() == {"cash": 2000, "transfer": 0, "cheque": 0, "other": 0}
    assert out.by_method()["cash"] == 0  # what came in, untouched by what went out
    assert out.cash_in_drawer == -2000
    # The payment is as it was; the refund points at it on its own.
    assert payment_rows(conn) == before
    original = payments.get(conn, school.boss, payment)
    assert (original.amount, original.allocated, original.voided) == (7000, 7000, False)
    [(taken_from, amount)] = [tuple(r) for r in conn.execute(
        "SELECT pa.payment_id, ra.amount FROM refund_allocations ra "
        "JOIN payment_allocations pa ON pa.id = ra.payment_allocation_id")]
    assert (taken_from, amount) == (payment, 2000)


def test_received_and_refunded_the_same_day(conn, school):
    """October paid on the 20th (6 000 cash), 2 000 handed back in cash the same day: 6 000
    encaissés, 2 000 remboursés, 4 000 net, 4 000 in the drawer."""
    paid_september(school)
    school.today.day = PAID_DAY
    subscriptions.renew(conn, school.boss, school.september)
    pay(school, 6000, PAID_DAY)
    refund(school)
    day = payments.cash_report(conn, school.boss, PAID_DAY)
    assert (day.total, day.refunded, day.net, day.cash_in_drawer) == (6000, 2000, 4000, 4000)


def test_a_refund_by_transfer_leaves_the_drawer_alone(conn, school):
    paid_september(school)
    refund(school, method="transfer")
    day = payments.cash_report(conn, school.boss, PAID_DAY)
    assert (day.refunded, day.net, day.cash_in_drawer) == (2000, -2000, 0)
    assert day.refunded_by_method()["transfer"] == 2000


def test_a_refund_not_paid_out_counts_nowhere(conn, school):
    paid_september(school)
    gone(school)
    pending = refunds.request(conn, school.desk, school.september, 1000, "Départ")
    approved = refunds.request(conn, school.desk, school.september, 1000, "Départ")
    refunds.approve(conn, school.boss, approved)
    assert payments.cash_report(conn, school.boss, ASKED).refunds == ()
    assert refunds.get(conn, school.boss, pending).status == "pending"
    september = _recettes(conn, school)["Septembre 2026"]
    assert september[4:6] == (0, 7000)  # remboursé, net encaissé


def test_the_desk_sees_the_refunds_of_the_day(conn, school):
    paid_september(school)
    refund(school)
    assert payments.cash_report(conn, school.desk, PAID_DAY).refunded == 2000


# ----- Recettes -----

def _recettes(conn, s) -> dict[str, tuple]:
    report = reports.revenue(conn, s.boss, s.year, "month")
    return {row[0]: row[1:] for row in report.rows}


def test_recettes_by_month(conn, school):
    """September: attendu 7 000 (fee and month), payé 7 000, encaissé 7 000, remboursé
    2 000, net 5 000; the teacher's 60 % of 6 000 and the school's part do not move."""
    paid_september(school)
    refund(school)
    report = reports.revenue(conn, school.boss, school.year, "month")
    [*_, collected, refunded, net, _teachers, _school] = report.columns
    assert (collected.title, refunded.title, net.title) == ("Encaissé", "Remboursé",
                                                            "Net encaissé")
    assert {collected.kind, refunded.kind, net.kind} == {"money"}
    rows = {row[0]: row[1:] for row in report.rows}
    assert rows["Septembre 2026"] == (7000, 7000, 0, 7000, 2000, 5000, 3600, 3400)
    assert report.total == ("Total", 7000, 7000, 0, 7000, 2000, 5000, 3600, 3400)
    [_, received, _, _] = report.tiles
    assert (received.label, received.value) == ("Encaissé", 7000)
    assert received.note == t["reports.tile.collected_refunds"].format(
        refunded=in_sentence(2000), net=in_sentence(5000))


def test_a_month_refunded_then_cancelled_counts_nowhere(conn, school):
    """October paid ahead (13 000 with the fee and September), refunded in full on 16/09,
    then cancelled: its payment's allocation stays on the cancelled charge (REVIEW_FIXES,
    finding 9), yet nothing is owed, and Attendu, Payé and the teacher's share leave it out.
    Encaissé stays the money received; Remboursé takes the 6 000 out."""
    october = paid_october(school)
    done(school, ask(school, october, 6000))
    subscriptions.cancel(conn, school.boss, october, "Départ, remboursé")
    charge = subscriptions.get(conn, school.boss, october).charge_id
    assert conn.execute("SELECT SUM(amount) FROM payment_allocations WHERE charge_id = ?",
                        (charge,)).fetchone()[0] == 6000
    assert debt.for_student(conn, school.boss, school.amine).due == 0
    rows = _recettes(conn, school)
    assert rows["Septembre 2026"] == (7000, 7000, 0, 13000, 6000, 7000, 3600, 3400)
    assert rows["Octobre 2026"] == (0,) * 8
    report = reports.revenue(conn, school.boss, school.year, "month")
    assert report.total == ("Total", 7000, 7000, 0, 13000, 6000, 7000, 3600, 3400)


def test_a_refund_counts_in_the_month_the_money_went_back(conn, school):
    paid_september(school)
    refund(school, on=date(2026, 10, 2))
    rows = _recettes(conn, school)
    assert rows["Septembre 2026"][3:6] == (7000, 0, 7000)
    assert rows["Octobre 2026"][3:6] == (0, 2000, -2000)


def test_refunds_never_change_what_teachers_earn(conn, school):
    paid_september(school)
    gone(school)  # the leave changes who is in the group, not what the teacher earns
    before = reports.teacher_summary(conn, school.boss, school.year)
    refund(school)
    after = reports.teacher_summary(conn, school.boss, school.year)
    assert (after.rows, after.total, after.tiles) == (before.rows, before.total, before.tiles)


def test_without_refunds_the_tile_says_what_it_said(conn, school):
    paid_september(school)
    [_, received, _, _] = reports.revenue(conn, school.boss, school.year).tiles
    assert received.note == t["reports.tile.collected_note"]


# ----- the screen -----

@pytest.fixture
def themed(qapp):
    load_fonts()
    apply_theme(qapp)


def test_the_cash_screen_shows_refunds_net_and_drawer(qtbot, conn, school, themed):
    paid_september(school)
    refund_id = refund(school)
    number = refunds.get(conn, school.boss, refund_id).number
    page = PaymentsPage(conn, school.boss)
    qtbot.addWidget(page)
    page.cash.day.set_value(PAID_DAY)
    cash = page.cash
    assert not cash.refunds.isHidden() and not cash.net.isHidden()
    assert cash.refunds.text() == t["cash.refunds"].format(
        count=1, total="2 000 DA", refunds=t["cash.refund_of"].format(
            number=number, student="Benali Amine", amount="2 000 DA", method="Espèces"))
    assert cash.net.text() == t["cash.net"].format(received="0 DA", refunded="2 000 DA",
                                                   net="-2 000 DA")
    assert cash.drawer.text() == t["cash.drawer"].format(drawer="-2 000 DA")
    assert not cash.drawer.isHidden()
    page.cash.day.set_value(date(2026, 9, 2))
    assert cash.refunds.isHidden() and cash.net.isHidden() and cash.drawer.isHidden()


def test_the_desk_sees_refunds_and_net_not_the_drawer(qtbot, conn, school, themed):
    paid_september(school)
    refund(school)
    page = PaymentsPage(conn, school.desk)
    qtbot.addWidget(page)
    page.cash.day.set_value(PAID_DAY)
    assert not page.cash.refunds.isHidden() and not page.cash.net.isHidden()
    assert page.cash.drawer.isHidden()


def test_recettes_exports_keep_the_three_columns(conn, school, tmp_path):
    from openpyxl import load_workbook

    paid_september(school)
    refund(school)
    report = reports.revenue(conn, school.boss, school.year, "month")
    pdf = reports.export(conn, school.boss, report, "pdf", tmp_path / "recettes.pdf")
    assert pdf.read_bytes().startswith(b"%PDF")
    sheet = load_workbook(reports.export(conn, school.boss, report, "xlsx",
                                         tmp_path / "recettes.xlsx")).worksheets[0]
    header = [c.value for c in sheet[6]]
    assert header[4:7] == ["Encaissé (DA)", "Remboursé (DA)", "Net encaissé (DA)"]
    september = [c.value for c in sheet[7]]
    assert september[0] == "Septembre 2026" and september[4:7] == [7000, 2000, 5000]
