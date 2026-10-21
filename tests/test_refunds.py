import json
from datetime import date

import pytest

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, NotFound, PermissionDenied, ValidationError
from tadris.domain.models import GroupInput, StudentInput, TeacherInput
from tadris.i18n.fr import t
from tadris.services import (
    auth,
    catalog,
    debt,
    enrollments,
    groups,
    payments,
    printing,
    refunds,
    registrations,
    school_years,
    settings,
    students,
    subscriptions,
    teachers,
)

TODAY = date(2026, 10, 18)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(dates, "today", lambda: TODAY)


def move_to(monkeypatch, day: date) -> None:
    monkeypatch.setattr(dates, "today", lambda: day)


@pytest.fixture
def director(conn):
    return auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")


@pytest.fixture
def desk(conn, director):
    user_id = auth.create_user(conn, director, "accueil", "password2", "receptionist")
    return UserContext(user_id=user_id, username="accueil", role="receptionist")


@pytest.fixture
def school(conn, director):
    year = school_years.create(conn, director, "2026-2027", date(2026, 9, 1), date(2027, 6, 30))
    level = catalog.create(conn, director, "level", "4AM")
    teacher = teachers.create(conn, director, TeacherInput("Karim Haddad"), 6000,
                              date(2026, 9, 1))
    subject = catalog.create(conn, director, "subject", "Maths")
    maths = groups.create(conn, director, GroupInput(year, level, subject, "M1", 3000, 10,
                                                     date(2026, 9, 1)), teacher)
    return {"level": level, "maths": maths}


@pytest.fixture
def amine(conn, director, school):
    """Fee 1 000 (due 18/10); M1 3 000 from 18/10 to 18/11 (31 days)."""
    student = students.create(conn, director, StudentInput("Amine", "Benali"))
    registrations.register(conn, director, student, school["level"], 1000)
    enrollments.enroll(conn, director, student, school["maths"])
    return student


def fee_charge(conn, student_id) -> int:
    return conn.execute("SELECT c.id FROM charges c JOIN registrations r "
                        "ON r.id = c.registration_id WHERE r.student_id = ? "
                        "AND c.status = 'open'", (student_id,)).fetchone()[0]


def month(conn, ctx, student_id):
    [m] = [s for s in subscriptions.for_student(conn, ctx, student_id)
           if s.status != "cancelled"]
    return m


def last_audit(conn, action):
    row = conn.execute("SELECT * FROM audit_log WHERE action = ? ORDER BY id DESC",
                       (action,)).fetchone()
    return json.loads(row["new_value"]), row


# ----- refunds: asking -----

def leave(conn, director, student_id, on: date) -> None:
    [e] = enrollments.for_student(conn, director, student_id)
    enrollments.leave(conn, director, e.id, on)


def test_the_suggestion_follows_the_days_used(conn, director, desk, amine, monkeypatch):
    payments.record(conn, director, amine, 4000, "cash")
    move_to(monkeypatch, date(2026, 11, 2))
    leave(conn, director, amine, date(2026, 10, 27))
    [fee, m] = refunds.options(conn, desk, amine)
    # 18/10 to 27/10 used: 10 of 31 days, 3 000 x 10 / 31 = 967.7 -> 968 kept
    assert (m.paid, m.refundable, m.suggestion) == (3000, 3000, 2032)
    assert (fee.paid, fee.suggestion) == (1000, 1000)  # the fee: everything, the director decides
    refund_id = refunds.request(conn, desk, m.charge_id, 2032, "Départ de l'élève")
    r = refunds.get(conn, desk, refund_id)
    assert (r.status, r.amount_computed, r.amount_final, r.requested_by) == (
        "pending", 2032, 2032, "accueil")
    [_fee, m] = refunds.options(conn, desk, amine)
    assert (m.reserved, m.refundable) == (2032, 968)


def test_still_in_the_group_today_means_nothing_used_yet(conn, director, desk, amine):
    payments.record(conn, director, amine, 4000, "cash")
    [_fee, m] = refunds.options(conn, desk, amine)
    assert m.suggestion == 3000  # the month starts today


def test_a_month_over_suggests_nothing(conn, director, desk, amine, monkeypatch):
    payments.record(conn, director, amine, 4000, "cash")
    move_to(monkeypatch, date(2026, 12, 1))
    [_fee, m] = refunds.options(conn, desk, amine)
    assert (m.suggestion, m.refundable) == (0, 3000)


def test_a_refund_cannot_exceed_what_was_paid(conn, director, desk, amine):
    payments.record(conn, director, amine, 2500, "cash")  # fee 1 000, month 1 500
    charge = month(conn, desk, amine).charge_id
    with pytest.raises(BusinessRuleError) as caught:
        refunds.request(conn, desk, charge, 1501, "Départ")
    assert caught.value.message == t["refund.exceeds"].format(amount="1 500 DA")
    refunds.request(conn, desk, charge, 1000, "Départ")
    with pytest.raises(BusinessRuleError) as caught:  # 1 000 already asked
        refunds.request(conn, desk, charge, 501, "Encore")
    assert caught.value.message == t["refund.exceeds"].format(amount="500 DA")


def test_nothing_paid_nothing_to_refund(conn, desk, amine):
    assert refunds.options(conn, desk, amine) == []
    with pytest.raises(BusinessRuleError):
        refunds.request(conn, desk, month(conn, desk, amine).charge_id, 100, "Départ")


@pytest.mark.parametrize("amount, reason", [(0, "x"), (-5, "x"), (12.5, "x"), (100, " ")])
def test_request_input_is_checked(conn, director, desk, amine, amount, reason):
    payments.record(conn, director, amine, 4000, "cash")
    with pytest.raises(ValidationError):
        refunds.request(conn, desk, month(conn, desk, amine).charge_id, amount, reason)


# ----- refunds: deciding and paying out -----

@pytest.fixture
def paid_twice(conn, director, amine):
    """2 500 (fee 1 000 + month 1 500), then 1 500 (month): the month is paid in full."""
    first = payments.record(conn, director, amine, 2500, "cash")
    second = payments.record(conn, director, amine, 1500, "cash")
    return first, second


def test_approve_pay_out_takes_the_latest_money_first(conn, director, desk, amine, paid_twice):
    first, second = paid_twice
    charge = month(conn, desk, amine).charge_id
    refund_id = refunds.request(conn, desk, charge, 2500, "Départ")
    with pytest.raises(PermissionDenied):
        refunds.approve(conn, desk, refund_id)
    refunds.approve(conn, director, refund_id, 2000)  # the director lowers it
    assert [r.id for r in refunds.queue(conn, desk)] == [refund_id]
    number = refunds.pay_out(conn, desk, refund_id, "cash")
    assert number == "RB2026-00001"
    r = refunds.get(conn, desk, refund_id)
    assert (r.status, r.refunded_amount, r.method, r.paid_out_by, r.decided_by) == (
        "paid", 2000, "cash", "accueil", "directeur")
    taken = conn.execute(
        "SELECT pa.payment_id, ra.amount FROM refund_allocations ra "
        "JOIN payment_allocations pa ON pa.id = ra.payment_allocation_id ORDER BY ra.id"
    ).fetchall()
    assert [tuple(row) for row in taken] == [(second, 1500), (first, 500)]
    assert refunds.queue(conn, desk) == []
    entry, _row = last_audit(conn, "refund.pay")
    assert (entry["number"], entry["amount"]) == ("RB2026-00001", 2000)


def test_a_refund_does_not_change_the_debt(conn, director, desk, amine, paid_twice):
    m = month(conn, desk, amine)
    refund_id = refunds.request(conn, desk, m.charge_id, 2000, "Départ")
    refunds.approve(conn, director, refund_id)
    refunds.pay_out(conn, desk, refund_id, "cash")
    assert debt.for_student(conn, desk, amine).balance == 0
    m = month(conn, desk, amine)
    assert (m.paid, m.refunded, m.kept, m.due) == (3000, 2000, 1000, 0)
    with pytest.raises(BusinessRuleError) as caught:  # 1 000 still kept
        subscriptions.cancel(conn, director, m.id, "Départ")
    assert caught.value.message == t["subscription.paid"].format(amount="1 000 DA")


def test_a_month_refunded_in_full_can_be_cancelled(conn, director, desk, amine, paid_twice):
    m = month(conn, desk, amine)
    refund_id = refunds.request(conn, desk, m.charge_id, 3000, "Inscrit par erreur")
    refunds.approve(conn, director, refund_id)
    refunds.pay_out(conn, desk, refund_id, "transfer")
    subscriptions.cancel(conn, director, m.id, "Inscrit par erreur")
    d = debt.for_student(conn, desk, amine)
    assert (d.due, d.credit, d.balance) == (0, 0, 0)  # the fee paid, the month gone


def test_the_fee_refunded_lets_the_registration_go(conn, director, desk, school):
    student = students.create(conn, director, StudentInput("Lina", "Saidi"))
    registration = registrations.register(conn, director, student, school["level"], 1000)
    payments.record(conn, director, student, 1000, "cash")
    with pytest.raises(BusinessRuleError):
        registrations.cancel(conn, director, registration, "Désistement")
    refund_id = refunds.request(conn, desk, fee_charge(conn, student), 1000, "Désistement")
    assert refunds.get(conn, desk, refund_id).subscription_id is None
    refunds.approve(conn, director, refund_id)
    refunds.pay_out(conn, desk, refund_id, "cash")
    registrations.cancel(conn, director, registration, "Désistement")
    assert registrations.current(conn, director, student) is None


def test_reject(conn, director, desk, amine, paid_twice):
    refund_id = refunds.request(conn, desk, month(conn, desk, amine).charge_id, 1000, "Départ")
    with pytest.raises(PermissionDenied):
        refunds.reject(conn, desk, refund_id, "Non")
    with pytest.raises(ValidationError):
        refunds.reject(conn, director, refund_id, "  ")
    refunds.reject(conn, director, refund_id, "Le mois est commencé")
    assert refunds.get(conn, desk, refund_id).status == "rejected"
    entry, _row = last_audit(conn, "refund.reject")
    assert entry["reason"] == "Le mois est commencé"
    with pytest.raises(BusinessRuleError) as caught:
        refunds.pay_out(conn, desk, refund_id, "cash")
    assert caught.value.message == t["refund.not_approved"]
    with pytest.raises(BusinessRuleError):
        refunds.approve(conn, director, refund_id)
    with pytest.raises(BusinessRuleError) as caught:
        refunds.reject(conn, director, refund_id, "Encore")
    assert caught.value.message == t["refund.closed"]
    [_fee, m] = refunds.options(conn, desk, amine)
    assert m.refundable == 3000  # a rejected request reserves nothing


def test_an_approved_refund_can_still_be_rejected(conn, director, desk, amine, paid_twice):
    refund_id = refunds.request(conn, desk, month(conn, desk, amine).charge_id, 1000, "Départ")
    refunds.approve(conn, director, refund_id)
    refunds.reject(conn, director, refund_id, "Finalement l'élève reste")
    assert refunds.get(conn, desk, refund_id).status == "rejected"


def test_pay_out_needs_an_approval_and_a_method(conn, director, desk, amine, paid_twice):
    refund_id = refunds.request(conn, desk, month(conn, desk, amine).charge_id, 1000, "Départ")
    with pytest.raises(BusinessRuleError):
        refunds.pay_out(conn, desk, refund_id, "cash")
    refunds.approve(conn, director, refund_id)
    with pytest.raises(ValidationError):
        refunds.pay_out(conn, desk, refund_id, "bitcoin")
    refunds.pay_out(conn, desk, refund_id, "cash")
    with pytest.raises(BusinessRuleError):  # once only
        refunds.pay_out(conn, desk, refund_id, "cash")


def test_approve_cannot_raise_beyond_what_was_paid(conn, director, desk, amine, paid_twice):
    charge = month(conn, desk, amine).charge_id
    first = refunds.request(conn, desk, charge, 1000, "Départ")
    refunds.request(conn, desk, charge, 1500, "Autre demande")
    with pytest.raises(BusinessRuleError) as caught:  # 3 000 - 1 500 asked elsewhere
        refunds.approve(conn, director, first, 1501)
    assert caught.value.message == t["refund.exceeds"].format(amount="1 500 DA")
    refunds.approve(conn, director, first, 1500)


def test_a_payment_voided_after_the_approval(conn, director, desk, amine):
    payment_id = payments.record(conn, director, amine, 4000, "cash")
    refund_id = refunds.request(conn, desk, month(conn, desk, amine).charge_id, 1000, "Départ")
    refunds.approve(conn, director, refund_id)
    payments.void(conn, director, payment_id, "Billet refusé")
    with pytest.raises(BusinessRuleError) as caught:
        refunds.pay_out(conn, desk, refund_id, "cash")
    assert caught.value.message == t["refund.money_gone"].format(amount="0 DA")
    assert refunds.get(conn, desk, refund_id).status == "approved"  # nothing changed


def test_a_refunded_payment_can_no_longer_be_voided(conn, director, desk, amine):
    payment_id = payments.record(conn, director, amine, 4000, "cash")
    refund_id = refunds.request(conn, desk, month(conn, desk, amine).charge_id, 1000, "Départ")
    refunds.approve(conn, director, refund_id)
    refunds.pay_out(conn, desk, refund_id, "cash")
    with pytest.raises(BusinessRuleError) as caught:
        payments.void(conn, director, payment_id, "Erreur")
    assert caught.value.message == t["db.void_has_refunds"]


def test_refund_numbers_are_sequential(conn, director, desk, amine, paid_twice):
    charge = month(conn, desk, amine).charge_id
    numbers = []
    for _ in range(2):
        refund_id = refunds.request(conn, desk, charge, 500, "Départ")
        refunds.approve(conn, director, refund_id)
        numbers.append(refunds.pay_out(conn, desk, refund_id, "cash"))
    assert numbers == ["RB2026-00001", "RB2026-00002"]


def test_unknown_refund(conn, director):
    with pytest.raises(NotFound):
        refunds.approve(conn, director, 999)


# ----- the day's cash -----

def test_cash_report_counts_refunds_paid_out(conn, director, desk, amine):
    payments.record(conn, desk, amine, 4000, "cash")
    refund_id = refunds.request(conn, desk, month(conn, desk, amine).charge_id, 1200, "Départ")
    refunds.approve(conn, director, refund_id)
    refunds.pay_out(conn, desk, refund_id, "cash")
    report = payments.cash_report(conn, desk, TODAY)
    assert (report.total, report.refunded, report.cash_in_drawer) == (4000, 1200, 2800)
    assert report.refunded_by_method()["cash"] == 1200
    assert [r.number for r in report.refunds] == ["RB2026-00001"]
    assert payments.cash_report(conn, desk, date(2026, 10, 19)).refunds == ()


# ----- the audit trail -----

def test_every_step_is_in_the_audit_log(conn, director, desk, amine, paid_twice):
    charge = month(conn, desk, amine).charge_id
    refund_id = refunds.request(conn, desk, charge, 500, "Départ")
    refunds.approve(conn, director, refund_id)
    refunds.pay_out(conn, desk, refund_id, "cash")
    actions = [row[0] for row in conn.execute(
        "SELECT action FROM audit_log WHERE entity_name = 'refunds' AND entity_id = ? "
        "ORDER BY id", (refund_id,))]
    assert actions == ["refund.request", "refund.approve", "refund.pay"]


# ----- the refund slip -----

def test_refund_slip(conn, director, desk, amine, paid_twice, tmp_path):
    refund_id = refunds.request(conn, desk, month(conn, desk, amine).charge_id, 2000, "Départ")
    with pytest.raises(BusinessRuleError) as caught:  # not paid out yet
        printing.refund_slip_content(conn, desk, refund_id)
    assert caught.value.message == t["refund.not_paid_yet"]
    refunds.approve(conn, director, refund_id)
    refunds.pay_out(conn, desk, refund_id, "cash")
    doc = printing.refund_slip_content(conn, desk, refund_id)
    assert (doc.title, doc.number, doc.stamp, doc.copy_mark) == (
        "Bon de remboursement", "RB2026-00001", "REMBOURSÉ", "")
    assert doc.note == ""
    settings.save_school(conn, director, "École Ennour", "", "", "08:00", "20:00",
                         receipt_header="NIF 0001", receipt_footer="Bon à conserver.")
    doc = printing.refund_slip_content(conn, desk, refund_id)
    assert (doc.school.header, doc.note) == ("NIF 0001", "Bon à conserver.")
    assert dict(doc.details)["Élève"] == "Benali Amine (N° 2026-0001)"
    assert (dict(doc.details)["Approuvé par"], dict(doc.details)["Remis par"]) == (
        "directeur", "accueil")
    assert doc.lines == [("Abonnement M1 du 18/10/2026 au 18/11/2026", "2 000 DA")]
    assert doc.totals == [("Total remboursé", "2 000 DA")]
    path = printing.refund_slip(conn, desk, refund_id, tmp_path)
    assert path.name == "remboursement_RB2026-00001.pdf"
    assert path.read_bytes().startswith(b"%PDF")
    assert printing.refund_slip_content(conn, desk, refund_id).copy_mark == "DUPLICATA"
