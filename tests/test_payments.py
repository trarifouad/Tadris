import json
import re
from datetime import date

import pytest

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import (
    BusinessRuleError,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from tadris.domain.models import (
    ChargeDue,
    ContactInput,
    Debt,
    GroupInput,
    StudentInput,
    TeacherInput,
)
from tadris.i18n.fr import t
from tadris.repositories import payments as payments_repo
from tadris.services import (
    auth,
    catalog,
    contacts,
    debt,
    enrollments,
    groups,
    payments,
    payouts,
    printing,
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
def receptionist(conn, director):
    user_id = auth.create_user(conn, director, "accueil", "password2", "receptionist")
    return UserContext(user_id=user_id, username="accueil", role="receptionist")


class School:
    def __init__(self, conn, ctx):
        self.year = school_years.create(conn, ctx, "2026-2027", date(2026, 9, 1),
                                        date(2027, 6, 30))
        self.level = catalog.create(conn, ctx, "level", "4AM")
        self.teacher = teachers.create(conn, ctx, TeacherInput("Karim Haddad"), 6000,
                                       date(2026, 9, 1))
        self.maths = self.group(conn, ctx, "M1", "Maths", 3000)
        self.physics = self.group(conn, ctx, "P1", "Physique", 2500)

    def group(self, conn, ctx, name, subject, price):
        subject_id = catalog.create(conn, ctx, "subject", subject)
        return groups.create(conn, ctx, GroupInput(self.year, self.level, subject_id, name,
                                                   price, 10, date(2026, 9, 1)), self.teacher)


@pytest.fixture
def school(conn, director):
    return School(conn, director)


def new_student(conn, ctx, school, first, last, fee=1000) -> int:
    student = students.create(conn, ctx, StudentInput(first, last))
    registrations.register(conn, ctx, student, school.level, fee)
    return student


@pytest.fixture
def amine(conn, director, school):
    """Registered with a 1 000 DA fee (due 18/10), in M1 from 18/10 (3 000 DA, due 18/10)."""
    student = new_student(conn, director, school, "Amine", "Benali")
    enrollments.enroll(conn, director, student, school.maths)
    return student


def fee_charge(conn, student_id):
    return conn.execute(
        "SELECT c.* FROM charges c JOIN registrations r ON r.id = c.registration_id "
        "WHERE r.student_id = ? AND c.status = 'open'", (student_id,)).fetchone()


def month_charges(conn, student_id):
    return conn.execute(
        "SELECT c.* FROM charges c JOIN subscriptions s ON s.id = c.subscription_id "
        "JOIN enrollments e ON e.id = s.enrollment_id WHERE e.student_id = ? "
        "ORDER BY c.due_date, c.id", (student_id,)).fetchall()


def allocations_of(conn, payment_id):
    return [(row["charge_id"], row["amount"]) for row in conn.execute(
        "SELECT charge_id, amount FROM payment_allocations WHERE payment_id = ? ORDER BY id",
        (payment_id,))]


def last_audit(conn, action):
    return conn.execute("SELECT * FROM audit_log WHERE action = ? ORDER BY id DESC",
                        (action,)).fetchone()


def enrollment_of(conn, ctx, student_id) -> int:
    [month] = subscriptions.for_student(conn, ctx, student_id)
    return month.enrollment_id


def payment_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0]


def subscription_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0]


# ----- debt -----

def test_debt_of_a_new_student_is_the_fee_and_the_first_month(conn, director, amine):
    d = debt.for_student(conn, director, amine)
    assert [(c.kind, c.amount, c.due) for c in d.charges] == [("registration", 1000, 1000),
                                                              ("subscription", 3000, 3000)]
    # 1 000 + 3 000, both due today, nothing paid
    assert (d.due, d.overdue, d.owed_now) == (4000, 4000, 4000)
    assert d.oldest_overdue == "2026-10-18"
    assert not hasattr(d, "credit") and not hasattr(d, "after_credit")


def test_a_month_renewed_ahead_is_owed_but_not_late(conn, director, amine):
    [month] = subscriptions.for_student(conn, director, amine)
    subscriptions.renew(conn, director, month.id)  # 18/11 -> 18/12, due 18/11
    d = debt.for_student(conn, director, amine)
    # owed: 1 000 + 3 000 + 3 000; late today: 1 000 + 3 000
    assert (d.due, d.overdue, d.owed_now) == (7000, 4000, 4000)


def test_debt_of_an_unknown_student(conn, director):
    with pytest.raises(NotFound):
        debt.for_student(conn, director, 999)


def test_cancelled_charges_are_not_owed(conn, director, school):
    student = new_student(conn, director, school, "Sara", "Kaci", fee=0)
    enrollments.enroll(conn, director, student, school.maths)
    [month] = subscriptions.for_student(conn, director, student)
    subscriptions.cancel(conn, director, month.id, "Erreur de saisie")
    assert debt.for_student(conn, director, student).due == 0


def test_debt_figures_are_what_is_left_on_each_line():
    charges = (ChargeDue(1, "registration", "Frais", 1000, "2026-10-01", 0, None),
               ChargeDue(2, "subscription", "M1", 3000, "2026-10-18", 500, 1),
               ChargeDue(3, "subscription", "M1", 3000, "2026-11-18", 0, 1))
    d = Debt(student_id=1, as_of="2026-10-20", charges=charges)
    assert (d.due, d.overdue, d.owed_now, d.oldest_overdue) == (6500, 3500, 3500, "2026-10-01")
    assert Debt(1, "2026-10-20", charges[2:]).oldest_overdue is None  # only a month to come


# ----- recording: allocation order -----

def test_exact_payment_settles_everything_with_a_receipt(conn, receptionist, amine):
    payment_id = payments.record(conn, receptionist, amine, 4000, "cash")
    fee, [month] = fee_charge(conn, amine), month_charges(conn, amine)
    assert allocations_of(conn, payment_id) == [(fee["id"], 1000), (month["id"], 3000)]
    p = payments.get(conn, receptionist, payment_id)
    assert (p.amount, p.allocated, p.method, p.cashier) == (4000, 4000, "cash", "accueil")
    assert p.receipt_number == "R2026-00001"
    assert p.paid_at.startswith("2026-10-18T")
    d = debt.for_student(conn, receptionist, amine)
    assert (d.charges, d.due) == ((), 0)


def test_partial_payment_pays_the_oldest_charge_first(conn, receptionist, amine):
    payment_id = payments.record(conn, receptionist, amine, 2500, "cash")
    fee, [month] = fee_charge(conn, amine), month_charges(conn, amine)
    # the fee (1 000) first, then 1 500 of the month: the rest of the month stays owed
    assert allocations_of(conn, payment_id) == [(fee["id"], 1000), (month["id"], 1500)]
    d = debt.for_student(conn, receptionist, amine)
    assert [(c.id, c.paid, c.due) for c in d.charges] == [(month["id"], 1500, 1500)]
    assert d.due == 1500
    payments.record(conn, receptionist, amine, 1500, "cash")  # the rest, later
    assert debt.for_student(conn, receptionist, amine).due == 0


def test_order_is_by_due_date_not_by_creation(conn, director, school):
    """A month created after the fee but due earlier (entry back-dated to 01/10) is paid
    before it."""
    student = new_student(conn, director, school, "Lina", "Saidi")  # fee due 18/10
    enrollments.enroll(conn, director, student, school.maths, enrolled_on=date(2026, 10, 1))
    fee, [month] = fee_charge(conn, student), month_charges(conn, student)
    assert (month["due_date"], fee["due_date"]) == ("2026-10-01", "2026-10-18")
    assert month["id"] > fee["id"]
    payment_id = payments.record(conn, director, student, 3500, "cash")
    assert allocations_of(conn, payment_id) == [(month["id"], 3000), (fee["id"], 500)]


def test_a_payment_above_what_is_left_is_refused(conn, receptionist, amine):
    """No credit: 4 001 DA for 4 000 DA left is refused, nothing written, no receipt number
    used."""
    with pytest.raises(ValidationError) as caught:
        payments.record(conn, receptionist, amine, 4001, "cash")
    assert caught.value.message == t["payment.above_due"].format(amount="4 000 DA")
    assert payment_count(conn) == 0
    first = payments.record(conn, receptionist, amine, 4000, "cash")
    assert payments.get(conn, receptionist, first).receipt_number == "R2026-00001"
    with pytest.raises(ValidationError) as caught:
        payments.record(conn, receptionist, amine, 100, "cash")  # all paid now
    assert caught.value.message == t["payment.nothing_due"]


def test_a_payment_with_nothing_to_pay_is_refused(conn, director, school):
    student = new_student(conn, director, school, "Yacine", "Mansouri", fee=0)
    with pytest.raises(ValidationError) as caught:
        payments.record(conn, director, student, 2000, "transfer")
    assert caught.value.message == t["payment.nothing_due"]
    assert payment_count(conn) == 0


def test_a_month_renewed_ahead_is_paid_like_any_line(conn, director, amine):
    [month] = subscriptions.for_student(conn, director, amine)
    subscriptions.renew(conn, director, month.id)  # 3 000, due 18/11
    with pytest.raises(ValidationError):
        payments.record(conn, director, amine, 7001, "cash")
    payment_id = payments.record(conn, director, amine, 7000, "cash")
    _october, november = month_charges(conn, amine)
    assert allocations_of(conn, payment_id)[-1] == (november["id"], 3000)
    assert debt.for_student(conn, director, amine).due == 0


def test_preview_matches_what_record_does(conn, director, amine):
    plan = payments.preview(conn, director, amine, 2500)
    assert [(line.charge.amount, line.from_payment, line.left) for line in plan.lines] == [
        (1000, 1000, 0), (3000, 1500, 1500)]
    assert (plan.allocated, plan.left_to_pay) == (2500, 1500)
    payment_id = payments.record(conn, director, amine, 2500, "cash")
    assert [v for _c, v in allocations_of(conn, payment_id)] == [1000, 1500]
    assert payment_count(conn) == 1  # the preview wrote none


def test_the_preview_refuses_what_record_refuses(conn, director, amine):
    with pytest.raises(ValidationError):
        payments.preview(conn, director, amine, 4001)
    assert payments.preview(conn, director, amine, 0).allocated == 0  # the lines, unpaid


def test_record_is_audited_without_credit(conn, receptionist, amine):
    payments.record(conn, receptionist, amine, 2500, "cash")
    entry = json.loads(last_audit(conn, "payment.record")["new_value"])
    assert "to_credit" not in entry and entry["months_ahead"] == 0
    assert last_audit(conn, "payment.apply_credit") is None


# ----- recording: chosen charges -----

def test_chosen_charges_replace_the_oldest_first_order(conn, director, amine):
    [month] = month_charges(conn, amine)
    payment_id = payments.record(conn, director, amine, 3000, "cash", chosen=[month["id"]])
    assert allocations_of(conn, payment_id) == [(month["id"], 3000)]
    d = debt.for_student(conn, director, amine)
    assert [(c.kind, c.due) for c in d.charges] == [("registration", 1000)]


def test_chosen_lines_are_paid_oldest_first_and_cap_the_amount(conn, director, amine):
    fee, [month] = fee_charge(conn, amine), month_charges(conn, amine)
    with pytest.raises(ValidationError) as caught:
        payments.record(conn, director, amine, 3500, "cash", chosen=[month["id"]])
    assert caught.value.message == t["payment.above_due"].format(amount="3 000 DA")
    payment_id = payments.record(conn, director, amine, 1500, "cash",
                                 chosen=[month["id"], fee["id"]])  # any order given
    assert allocations_of(conn, payment_id) == [(fee["id"], 1000), (month["id"], 500)]
    payment_id = payments.record(conn, director, amine, 2000, "cash", chosen=[month["id"]])
    assert allocations_of(conn, payment_id) == [(month["id"], 2000)]  # part of a month
    assert debt.for_student(conn, director, amine).due == 500


@pytest.mark.parametrize("chosen_kind, message_key", [
    ("unknown", "payment.charge_unknown"),
    ("twice", "payment.charge_unknown"),
    ("none", "payment.nothing_chosen"),
])
def test_chosen_charges_are_checked(conn, director, amine, chosen_kind, message_key):
    [month] = month_charges(conn, amine)
    chosen = {"unknown": [9999], "twice": [month["id"], month["id"]], "none": []}[chosen_kind]
    with pytest.raises(ValidationError) as caught:
        payments.record(conn, director, amine, 1000, "cash", chosen=chosen)
    assert caught.value.message == t[message_key]
    assert payment_count(conn) == 0


def test_a_chosen_charge_of_another_student_is_refused(conn, director, school, amine):
    other = new_student(conn, director, school, "Sara", "Kaci")
    with pytest.raises(ValidationError):
        payments.record(conn, director, other, 1000, "cash",
                        chosen=[fee_charge(conn, amine)["id"]])


def test_a_line_paid_in_full_can_no_longer_be_chosen(conn, director, amine):
    fee = fee_charge(conn, amine)
    payments.record(conn, director, amine, 1000, "cash", chosen=[fee["id"]])
    with pytest.raises(ValidationError) as caught:
        payments.record(conn, director, amine, 1000, "cash", chosen=[fee["id"]])
    assert caught.value.message == t["payment.charge_unknown"]


# ----- recording: months paid ahead -----

def test_next_months_follow_the_latest_month_to_the_end_of_the_year(conn, director, amine):
    [group] = subscriptions.next_months(conn, director, amine)
    assert (group.enrollment_id, group.group_title, group.group_name, group.price) == (
        enrollment_of(conn, director, amine), "M1 · Maths 4AM", "M1", 3000)
    # October is the month running; the year ends on 30/06/2027.
    assert [start for start, _end in group.months] == [
        "2026-11-18", "2026-12-18", "2027-01-18", "2027-02-18", "2027-03-18", "2027-04-18",
        "2027-05-18", "2027-06-18"]
    assert group.months[0] == ("2026-11-18", "2026-12-18")


def test_next_months_are_the_months_renewing_makes(conn, director, school):
    """The cycle of the 31st: 31/10 -> 30/11 -> 31/12 -> 31/01 -> 28/02 -> 31/03. What the
    payment dialog shows is what the payment renews."""
    student = new_student(conn, director, school, "Lina", "Saidi", fee=0)
    enrollment_id = enrollments.enroll(conn, director, student, school.maths,
                                       enrolled_on=date(2026, 10, 31))
    [group] = subscriptions.next_months(conn, director, student)
    planned = list(group.months[:4])
    assert planned == [("2026-11-30", "2026-12-31"), ("2026-12-31", "2027-01-31"),
                       ("2027-01-31", "2027-02-28"), ("2027-02-28", "2027-03-31")]
    payments.record(conn, director, student, 15000, "cash", ahead={enrollment_id: 4})
    made = [(m.start_date, m.end_date)
            for m in subscriptions.for_enrollment(conn, director, enrollment_id)][1:]
    assert made == planned


def test_pay_two_months_ahead(conn, receptionist, amine):
    """What is owed (fee and October: 4 000) and two months ahead (6 000) in one payment:
    November and December are renewed with it and paid."""
    enrollment_id = enrollment_of(conn, receptionist, amine)
    plan = payments.preview(conn, receptionist, amine, 10000, ahead={enrollment_id: 2})
    assert [(line.charge.description, line.from_payment, line.ahead) for line in plan.lines] == [
        ("Frais d'inscription 2026-2027", 1000, False),
        ("Abonnement M1 du 18/10/2026 au 18/11/2026", 3000, False),
        ("Abonnement M1 du 18/11/2026 au 18/12/2026", 3000, True),
        ("Abonnement M1 du 18/12/2026 au 18/01/2027", 3000, True)]
    assert subscription_count(conn) == 1  # the preview renewed nothing

    payment_id = payments.record(conn, receptionist, amine, 10000, "cash",
                                 ahead={enrollment_id: 2})
    months = subscriptions.for_enrollment(conn, receptionist, enrollment_id)
    assert [(m.start_date, m.end_date, m.paid) for m in months] == [
        ("2026-10-18", "2026-11-18", 3000), ("2026-11-18", "2026-12-18", 3000),
        ("2026-12-18", "2027-01-18", 3000)]
    assert months[2].renewal_of_id == months[1].id  # renewed one from the other
    assert [line.description for line in payments.lines(conn, receptionist, payment_id)] == [
        line.charge.description for line in plan.lines]
    assert debt.for_student(conn, receptionist, amine).due == 0
    entry = json.loads(last_audit(conn, "payment.record")["new_value"])
    assert (entry["months_ahead"], len(entry["allocations"])) == (2, 4)
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'subscription.create'"
                        ).fetchone()[0] == 3  # October at entry, then the two ahead


def test_a_month_ahead_paid_in_part(conn, director, amine):
    enrollment_id = enrollment_of(conn, director, amine)
    payments.record(conn, director, amine, 8500, "cash", ahead={enrollment_id: 2})
    d = debt.for_student(conn, director, amine)
    assert [(c.due_date, c.paid, c.due) for c in d.charges] == [("2026-12-18", 1500, 1500)]
    assert (d.owed_now, d.due) == (0, 1500)  # to come, not late


def test_a_month_ahead_the_amount_does_not_reach_is_refused(conn, director, amine):
    """6 000 DA with two months ahead: the fee, October and 2 000 of November; December would
    be renewed for nothing. Refused, and nothing is renewed."""
    enrollment_id = enrollment_of(conn, director, amine)
    with pytest.raises(ValidationError) as caught:
        payments.record(conn, director, amine, 6000, "cash", ahead={enrollment_id: 2})
    assert caught.value.message == t["payment.ahead_unpaid"]
    with pytest.raises(ValidationError):
        payments.preview(conn, director, amine, 6000, ahead={enrollment_id: 2})
    assert (payment_count(conn), subscription_count(conn)) == (0, 1)
    with pytest.raises(ValidationError) as caught:
        payments.record(conn, director, amine, 13001, "cash", ahead={enrollment_id: 3})
    assert caught.value.message == t["payment.above_due"].format(amount="13 000 DA")


def test_months_ahead_alone_with_lines_still_owed(conn, director, amine):
    """The desk ticks no line and adds a month ahead: only that month is paid; the fee and
    October stay owed."""
    enrollment_id = enrollment_of(conn, director, amine)
    fee = fee_charge(conn, amine)
    payment_id = payments.record(conn, director, amine, 3000, "cash", chosen=[],
                                 ahead={enrollment_id: 1})
    _october, november = month_charges(conn, amine)
    assert allocations_of(conn, payment_id) == [(november["id"], 3000)]
    assert debt.for_student(conn, director, amine).owed_now == 4000
    payment_id = payments.record(conn, director, amine, 4000, "cash", chosen=[fee["id"]],
                                 ahead={enrollment_id: 1})
    december = month_charges(conn, amine)[-1]
    assert allocations_of(conn, payment_id) == [(fee["id"], 1000), (december["id"], 3000)]


def test_months_ahead_in_two_groups(conn, director, school, amine):
    physics = enrollments.enroll(conn, director, amine, school.physics)
    maths = next(g.enrollment_id for g in subscriptions.next_months(conn, director, amine)
                 if g.group_name == "M1")
    # owed: fee 1 000, M1 3 000, P1 2 500; ahead: M1 3 000, P1 2 500
    payments.record(conn, director, amine, 12000, "cash", ahead={maths: 1, physics: 1})
    assert debt.for_student(conn, director, amine).due == 0
    assert len(subscriptions.for_student(conn, director, amine)) == 4


def test_months_ahead_are_checked(conn, director, school, amine):
    enrollment_id = enrollment_of(conn, director, amine)
    with pytest.raises(ValidationError) as caught:
        payments.record(conn, director, amine, 28000, "cash", ahead={enrollment_id: 9})
    assert caught.value.message == t["payment.ahead_too_many"].format(count=8)
    for bad in (-1, True, 1.5):
        with pytest.raises(ValidationError) as caught:
            payments.record(conn, director, amine, 7000, "cash", ahead={enrollment_id: bad})
        assert caught.value.message == t["payment.ahead_invalid"]
    with pytest.raises(ValidationError) as caught:
        payments.record(conn, director, amine, 7000, "cash", ahead={999: 1})
    assert caught.value.message == t["payment.ahead_unknown"]
    other = new_student(conn, director, school, "Sara", "Kaci")
    with pytest.raises(ValidationError):  # another student's group
        payments.record(conn, director, other, 4000, "cash", ahead={enrollment_id: 1})
    assert (payment_count(conn), subscription_count(conn)) == (0, 1)
    payments.record(conn, director, amine, 4000, "cash", ahead={enrollment_id: 0})  # none


def test_no_months_ahead_on_trial_in_a_free_or_closed_group(conn, director, school):
    student = new_student(conn, director, school, "Lina", "Saidi", fee=0)
    trial = enrollments.enroll(conn, director, student, school.maths, trial=True)
    free = school.group(conn, director, "F1", "Soutien", 0)
    enrollments.enroll(conn, director, student, free)
    assert subscriptions.next_months(conn, director, student) == []
    with pytest.raises(ValidationError):
        payments.record(conn, director, student, 3000, "cash", ahead={trial: 1})
    enrollments.confirm_trial(conn, director, trial)
    assert [g.enrollment_id for g in subscriptions.next_months(conn, director, student)] == [
        trial]
    groups.close(conn, director, school.maths)
    assert subscriptions.next_months(conn, director, student) == []


def test_a_rolled_back_payment_renews_nothing(conn, director, amine, monkeypatch):
    enrollment_id = enrollment_of(conn, director, amine)

    def broken(*_args):
        raise RuntimeError("disk full")

    monkeypatch.setattr(payments_repo, "insert_receipt", broken)
    with pytest.raises(RuntimeError):
        payments.record(conn, director, amine, 7000, "cash", ahead={enrollment_id: 1})
    assert (payment_count(conn), subscription_count(conn)) == (0, 1)


def test_a_month_paid_ahead_cannot_be_cancelled_until_its_payment_is_voided(conn, director,
                                                                            amine):
    enrollment_id = enrollment_of(conn, director, amine)
    payment_id = payments.record(conn, director, amine, 7000, "cash", ahead={enrollment_id: 1})
    november = subscriptions.for_enrollment(conn, director, enrollment_id)[-1]
    with pytest.raises(BusinessRuleError):
        subscriptions.cancel(conn, director, november.id, "Erreur")
    payments.void(conn, director, payment_id, "Chèque sans provision")
    # The months it renewed stay, owed again like the others.
    d = debt.for_student(conn, director, amine)
    assert (d.due, d.owed_now) == (7000, 4000)
    subscriptions.cancel(conn, director, november.id, "Erreur")
    assert debt.for_student(conn, director, amine).due == 4000


def test_leaving_the_group_keeps_the_months_paid_ahead(conn, director, amine):
    """Paid ahead to December, the student leaves today: the months after today stay
    (money is on them, V1 has no refunds) and stay paid."""
    enrollment_id = enrollment_of(conn, director, amine)
    payments.record(conn, director, amine, 10000, "cash", ahead={enrollment_id: 2})
    enrollments.leave(conn, director, enrollment_id, reason="Déménagement")
    months = subscriptions.for_enrollment(conn, director, enrollment_id)
    assert [(m.status, m.paid) for m in months] == [("active", 3000)] * 3
    assert debt.for_student(conn, director, amine).due == 0
    assert subscriptions.next_months(conn, director, amine) == []  # no longer in the group


# ----- recording: checks -----

@pytest.mark.parametrize("amount", [0, -100, 10.5, True, "1000"])
def test_amount_must_be_a_positive_whole_number(conn, director, amine, amount):
    with pytest.raises(ValidationError):
        payments.record(conn, director, amine, amount, "cash")


def test_method_must_be_known(conn, director, amine):
    with pytest.raises(ValidationError):
        payments.record(conn, director, amine, 1000, "bitcoin")


def test_unknown_student(conn, director, school):
    with pytest.raises(NotFound):
        payments.record(conn, director, 999, 1000, "cash")


def test_payer_must_be_a_contact_of_the_student(conn, director, school, amine):
    other = new_student(conn, director, school, "Sara", "Kaci")
    mother = contacts.add(conn, director, other, ContactInput("Nadia Kaci", "0661902547"))
    with pytest.raises(ValidationError):
        payments.record(conn, director, amine, 1000, "cash", payer_contact_id=mother)
    father = contacts.add(conn, director, amine, ContactInput("Omar Benali", "0770112233"))
    payment_id = payments.record(conn, director, amine, 1000, "cash", payer_contact_id=father)
    assert payments.get(conn, director, payment_id).payer_name == "Omar Benali"


def test_record_is_audited(conn, receptionist, amine):
    payment_id = payments.record(conn, receptionist, amine, 2500, "cheque")
    row = last_audit(conn, "payment.record")
    entry = json.loads(row["new_value"])
    assert (row["entity_id"], row["user_id"]) == (payment_id, receptionist.user_id)
    assert (entry["amount"], entry["method"], entry["receipt_number"]) == (2500, "cheque",
                                                                           "R2026-00001")
    assert [a["amount"] for a in entry["allocations"]] == [1000, 1500]


# ----- receipt numbers -----

def test_receipt_numbers_are_sequential_and_unique(conn, director, amine):
    numbers = [payments.get(conn, director, payments.record(conn, director, amine, 100,
                                                           "cash")).receipt_number
               for _ in range(3)]
    assert numbers == ["R2026-00001", "R2026-00002", "R2026-00003"]


def test_a_rolled_back_payment_leaves_no_gap(conn, director, amine, monkeypatch):
    payments.record(conn, director, amine, 100, "cash")

    def broken(*_args):
        raise RuntimeError("disk full")

    with monkeypatch.context() as patch:
        patch.setattr(payments_repo, "insert_receipt", broken)
        with pytest.raises(RuntimeError):
            payments.record(conn, director, amine, 100, "cash")
    assert conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 1
    third = payments.record(conn, director, amine, 100, "cash")
    assert payments.get(conn, director, third).receipt_number == "R2026-00002"


def test_receipt_numbers_restart_each_year(conn, director, amine, monkeypatch):
    payments.record(conn, director, amine, 100, "cash")
    move_to(monkeypatch, date(2027, 1, 4))
    payment_id = payments.record(conn, director, amine, 100, "cash")
    assert payments.get(conn, director, payment_id).receipt_number == "R2027-00001"


# ----- voiding -----

def test_void_makes_the_charges_owed_again(conn, director, amine):
    payment_id = payments.record(conn, director, amine, 4000, "cash")
    payments.void(conn, director, payment_id, "Billet refusé")
    p = payments.get(conn, director, payment_id)
    assert (p.voided, p.void_reason, p.voided_by) == (True, "Billet refusé", "directeur")
    assert p.receipt_number == "R2026-00001"  # the receipt stays, marked voided
    assert debt.for_student(conn, director, amine).due == 4000
    entry = json.loads(last_audit(conn, "payment.void")["new_value"])
    assert entry == {"voided": True, "reason": "Billet refusé"}


def test_after_a_void_the_next_payment_pays_the_lines_again(conn, director, amine):
    fee = fee_charge(conn, amine)
    [month] = month_charges(conn, amine)
    mistake = payments.record(conn, director, amine, 2500, "cash")  # 1 000 + 1 500
    kept = payments.record(conn, director, amine, 1500, "cash")  # the other 1 500
    payments.void(conn, director, mistake, "Saisie en double")
    assert {c.id: c.due for c in debt.for_student(conn, director, amine).charges} == {
        fee["id"]: 1000, month["id"]: 1500}
    with pytest.raises(ValidationError):
        payments.record(conn, director, amine, 2501, "cash")
    later = payments.record(conn, director, amine, 2500, "cash")
    assert allocations_of(conn, later) == [(fee["id"], 1000), (month["id"], 1500)]
    assert allocations_of(conn, kept) == [(month["id"], 1500)]  # as recorded
    assert debt.for_student(conn, director, amine).due == 0


def test_a_void_shows_what_each_payment_paid(conn, director, amine):
    """Decided 2026-11-05. P1 paid the fee and October, P2 November (renewed ahead); P1
    voided. The screens show what each payment paid: the fee and October are owed (and
    late), November stays paid. No money moves from November to October."""
    fee = fee_charge(conn, amine)
    first = payments.record(conn, director, amine, 4000, "cash")
    [october] = subscriptions.for_student(conn, director, amine)
    subscriptions.renew(conn, director, october.id)  # 18/11 -> 18/12
    ahead = payments.record(conn, director, amine, 3000, "cash")
    payments.void(conn, director, first, "Chèque sans provision")
    oct_charge, nov_charge = (m["id"] for m in month_charges(conn, amine))
    d = debt.for_student(conn, director, amine)
    assert {c.id: c.due for c in d.charges} == {fee["id"]: 1000, oct_charge: 3000}
    assert debt.left_for_student(conn, director, amine) == {fee["id"]: 1000, oct_charge: 3000}
    assert (d.owed_now, d.oldest_overdue, d.due) == (4000, "2026-10-18", 4000)
    [debtor] = debt.debtors(conn, director)
    assert (debtor.owed_now, debtor.due) == (4000, 4000)
    assert [(line.charge_id, line.amount)
            for line in payments.lines(conn, director, ahead)] == [(nov_charge, 3000)]
    payments.record(conn, director, amine, 4000, "cash")
    assert debt.for_student(conn, director, amine).due == 0


def test_void_is_for_the_director_only(conn, director, receptionist, amine):
    payment_id = payments.record(conn, receptionist, amine, 1000, "cash")
    with pytest.raises(PermissionDenied):
        payments.void(conn, receptionist, payment_id, "Erreur")


def test_void_needs_a_reason_and_happens_once(conn, director, amine):
    payment_id = payments.record(conn, director, amine, 1000, "cash")
    with pytest.raises(ValidationError):
        payments.void(conn, director, payment_id, "   ")
    payments.void(conn, director, payment_id, "Erreur")
    with pytest.raises(BusinessRuleError) as caught:
        payments.void(conn, director, payment_id, "Encore")
    assert caught.value.message == t["payment.already_voided"]


def test_void_of_an_unknown_payment(conn, director):
    with pytest.raises(NotFound):
        payments.void(conn, director, 999, "Erreur")


@pytest.mark.parametrize("payout_status", ["draft", "approved", "paid"])
def test_void_after_a_teacher_payout_counted_the_month(conn, director, school, amine,
                                                       payout_status):
    """A payment voided after a payout counted its month: the payout pays the month's full
    price whether it was paid or not, so it does not change; the month is owed again."""
    payment_id = payments.record(conn, director, amine, 4000, "cash")
    payout_id = payouts.build_draft(conn, director, school.teacher, TODAY)
    if payout_status != "draft":
        payouts.approve(conn, director, payout_id)
    if payout_status == "paid":
        payouts.mark_paid(conn, director, payout_id, "cash")
    payments.void(conn, director, payment_id, "Erreur de montant")
    assert payments.get(conn, director, payment_id).voided is True
    assert debt.for_student(conn, director, amine).due == 4000  # the fee and the month
    p = payouts.get(conn, director, payout_id)
    assert (p.status, p.amount_due, p.months) == (payout_status, 1800, 1)


def test_paid_subscription_can_no_longer_be_cancelled(conn, director, amine):
    payments.record(conn, director, amine, 4000, "cash")
    [month] = subscriptions.for_student(conn, director, amine)
    with pytest.raises(BusinessRuleError):
        subscriptions.cancel(conn, director, month.id, "Erreur")


def test_money_left_on_a_payment_from_before_has_no_effect(conn, director, amine):
    """A payment recorded before 2026-11-05 with money on no line (the credit then): nothing
    spends it now, and what is owed is what is left on the lines."""
    old = payments_repo.insert(conn, amine, None, 5000, "cash", "2026-10-01T10:00:00",
                               director.user_id)
    conn.execute("INSERT INTO payment_allocations(payment_id, charge_id, amount) "
                 "VALUES (?, ?, 1000)", (old, fee_charge(conn, amine)["id"]))
    assert debt.for_student(conn, director, amine).due == 3000
    payment_id = payments.record(conn, director, amine, 3000, "cash")
    assert [amount for _c, amount in allocations_of(conn, payment_id)] == [3000]
    assert allocations_of(conn, old) == [(fee_charge(conn, amine)["id"], 1000)]


# ----- a hand-calculated scenario -----

def test_hand_calculated_scenario(conn, director, school, monkeypatch):
    """Fee 1 000; M1 3 000 from 18/10; P1 2 500 from 20/10; M1 renewed (due 18/11).

    18/10 pays 2 000: fee 1 000, M1 Oct 1 000.
    20/10 pays 6 000: M1 Oct 2 000, P1 Oct 2 500, M1 Nov 1 500.
    21/10 the 18/10 payment is voided: fee and M1 Oct owe 1 000 each again.
    Owed: fee 1 000 + M1 Oct 1 000 + M1 Nov 1 500 = 3 500; late on 21/10: the fee and M1 Oct,
    2 000, since 18/10; November 1 500, not due yet. 3 501 is refused, 3 500 pays it all.
    """
    student = new_student(conn, director, school, "Rania", "Bouzid")
    enrollments.enroll(conn, director, student, school.maths)
    first = payments.record(conn, director, student, 2000, "cash")

    move_to(monkeypatch, date(2026, 10, 20))
    enrollments.enroll(conn, director, student, school.physics)
    m1 = next(s for s in subscriptions.for_student(conn, director, student)
              if s.group_title.startswith("M1"))
    subscriptions.renew(conn, director, m1.id)
    payments.record(conn, director, student, 6000, "transfer")

    move_to(monkeypatch, date(2026, 10, 21))
    payments.void(conn, director, first, "Chèque sans provision")
    d = debt.for_student(conn, director, student)
    assert [(c.amount, c.due, c.due_date) for c in d.charges] == [
        (1000, 1000, "2026-10-18"), (3000, 1000, "2026-10-18"), (3000, 1500, "2026-11-18")]
    assert (d.due, d.overdue, d.owed_now, d.oldest_overdue) == (3500, 2000, 2000, "2026-10-18")
    assert debt.days_late(d) == 3
    with pytest.raises(ValidationError):
        payments.record(conn, director, student, 3501, "cash")
    payments.record(conn, director, student, 3500, "cash")
    assert debt.for_student(conn, director, student).due == 0


def test_late_since_the_oldest_month_left(conn, director, amine, monkeypatch):
    """Paid through November (a month ahead): late from December's first day, not before."""
    enrollment_id = enrollment_of(conn, director, amine)
    payments.record(conn, director, amine, 7000, "cash", ahead={enrollment_id: 1})
    move_to(monkeypatch, date(2026, 12, 18))
    november = subscriptions.for_enrollment(conn, director, enrollment_id)[-1]
    subscriptions.renew(conn, director, november.id)
    move_to(monkeypatch, date(2026, 12, 20))
    d = debt.for_student(conn, director, amine)
    assert (d.owed_now, d.oldest_overdue, debt.days_late(d)) == (3000, "2026-12-18", 2)
    [debtor] = debt.debtors(conn, director)
    assert (debtor.owed_now, debtor.due, debtor.days_overdue) == (3000, 3000, 2)
    assert debt.debtors(conn, director, min_days=3) == []


# ----- debtors -----

@pytest.fixture
def desk(conn, director, school, monkeypatch):
    """On 18/10: Amine owes 4 000 (M1), Sara paid everything (P1), Yacine owes 500 (M1, fee
    paid). Then the clock moves to 02/11 (15 days later)."""
    amine = new_student(conn, director, school, "Amine", "Benali")
    enrollments.enroll(conn, director, amine, school.maths)
    sara = new_student(conn, director, school, "Sara", "Kaci")
    enrollments.enroll(conn, director, sara, school.physics)
    payments.record(conn, director, sara, 3500, "cash")
    yacine = new_student(conn, director, school, "Yacine", "Mansouri")
    enrollments.enroll(conn, director, yacine, school.maths)
    payments.record(conn, director, yacine, 3500, "cash")
    move_to(monkeypatch, date(2026, 11, 2))
    return {"amine": amine, "sara": sara, "yacine": yacine}


def test_debtors_largest_first(conn, receptionist, desk):
    listed = debt.debtors(conn, receptionist)
    assert [(d.student_name, d.owed_now, d.days_overdue) for d in listed] == [
        ("Benali Amine", 4000, 15), ("Mansouri Yacine", 500, 15)]


def test_debtors_with_something_left_to_pay(conn, director, receptionist, school, desk):
    """late_only off: the students owing something, late or not (a month not due yet)."""
    lina = new_student(conn, director, school, "Lina", "Saidi", fee=0)
    enrollments.enroll(conn, director, lina, school.physics, enrolled_on=date(2026, 11, 10))
    assert "Saidi Lina" not in [d.student_name for d in debt.debtors(conn, receptionist)]
    listed = debt.debtors(conn, receptionist, late_only=False)
    assert [(d.student_name, d.owed_now, d.due, d.oldest_overdue) for d in listed] == [
        ("Benali Amine", 4000, 4000, "2026-10-18"), ("Mansouri Yacine", 500, 500, "2026-10-18"),
        ("Saidi Lina", 0, 2500, None)]
    assert len(debt.debtors(conn, receptionist, late_only=False, min_days=1)) == 2


def test_debtors_filters(conn, receptionist, school, desk):
    assert [d.student_name for d in debt.debtors(conn, receptionist, min_amount=1000)] == [
        "Benali Amine"]
    assert debt.debtors(conn, receptionist, group_id=school.physics) == []
    assert len(debt.debtors(conn, receptionist, group_id=school.maths)) == 2
    assert len(debt.debtors(conn, receptionist, min_days=15)) == 2
    assert debt.debtors(conn, receptionist, min_days=16) == []


def test_paying_what_is_late_takes_a_student_off_the_debtors_list(conn, director, desk):
    payments.record(conn, director, desk["yacine"], 500, "cash")
    assert [d.student_name for d in debt.debtors(conn, director)] == ["Benali Amine"]


def test_months_ahead_do_not_make_a_debtor(conn, director, school):
    student = new_student(conn, director, school, "Lina", "Saidi", fee=0)
    enrollments.enroll(conn, director, student, school.maths, enrolled_on=date(2026, 10, 25))
    assert debt.debtors(conn, director) == []


# ----- cash report -----

def test_cash_report_totals_per_method_and_cashier(conn, director, receptionist, desk,
                                                   monkeypatch):
    # desk recorded 3 500 + 3 500 cash on 18/10, by the director
    move_to(monkeypatch, TODAY)
    voided = payments.record(conn, receptionist, desk["amine"], 1000, "cash")
    payments.record(conn, receptionist, desk["amine"], 2000, "cheque")
    payments.void(conn, director, voided, "Erreur")
    report = payments.cash_report(conn, receptionist, TODAY)
    assert len(report.payments) == 4
    assert report.total == 9000
    assert report.by_method() == {"cash": 7000, "transfer": 0, "cheque": 2000, "other": 0}
    assert report.by_cashier() == {"accueil": 2000, "directeur": 7000}
    assert [p.amount for p in report.voided] == [1000]
    assert payments.cash_report(conn, receptionist, date(2026, 10, 17)).payments == ()


def test_a_day_counted_never_changes_when_a_payment_is_voided_later(conn, director, amine,
                                                                    monkeypatch):
    """4 000 received on 18/10 for the wrong student, voided on 20/10 and recorded again:
    18/10 keeps its 4 000 (the drawer had them), 20/10 takes them off and adds the new
    4 000, so it matches its drawer too."""
    wrong = payments.record(conn, director, amine, 4000, "cash")
    move_to(monkeypatch, date(2026, 10, 20))
    payments.void(conn, director, wrong, "Mauvais élève")
    payments.record(conn, director, amine, 4000, "cash")
    first = payments.cash_report(conn, director, TODAY)
    assert (first.total, first.by_method()["cash"], first.voided) == (4000, 4000, ())
    later = payments.cash_report(conn, director, date(2026, 10, 20))
    assert [p.id for p in later.voided_earlier] == [wrong]
    assert (later.total, later.by_method()["cash"], later.cash_in_drawer) == (0, 0, 0)
    assert later.by_cashier() == {"directeur": 4000}  # who took the day's money


# ----- debt warning -----

def test_debt_warning_needs_a_threshold(conn, director, amine):
    assert debt.warning(conn, director, amine) is None  # 0: off
    settings.set_value(conn, director, "defaults.max_debt_warning", 4000)
    assert debt.warning(conn, director, amine) == t["debt.warning"].format(
        amount="4 000 DA", threshold="4 000 DA")
    payments.record(conn, director, amine, 100, "cash")
    assert debt.warning(conn, director, amine) is None  # 3 900 < 4 000


# ----- reading -----

def test_history_and_lines(conn, director, amine):
    first = payments.record(conn, director, amine, 1500, "cash")
    second = payments.record(conn, director, amine, 500, "cash")
    assert [p.id for p in payments.for_student(conn, director, amine)] == [second, first]
    assert [(line.description, line.amount) for line in payments.lines(conn, director, first)] \
        == [("Frais d'inscription 2026-2027", 1000),
            ("Abonnement M1 du 18/10/2026 au 18/11/2026", 500)]


# ----- receipts -----

def receipt_of(conn, ctx, payment_id) -> int:
    return payments.get(conn, ctx, payment_id).receipt_id


def test_receipt_content(conn, director, receptionist, amine):
    settings.save_school(conn, director, "École Ennour", "0550 12 34 56", "Oran", "08:00",
                         "20:00")
    father = contacts.add(conn, director, amine, ContactInput("Omar Benali", "0770112233"))
    payment_id = payments.record(conn, receptionist, amine, 2500, "cash",
                                 payer_contact_id=father)
    doc = printing.receipt_content(conn, receptionist, receipt_of(conn, receptionist,
                                                                  payment_id))
    assert (doc.school.name, doc.number, doc.copy_mark, doc.stamp) == (
        "École Ennour", "R2026-00001", "", "PAYÉ")
    assert [label for label, _value in doc.details] == [
        "Date", "Élève", "Payé par", "Mode de paiement", "Reçu par"]
    assert doc.details[1][1] == "Benali Amine (N° 2026-0001)"
    assert doc.details[3][1] == "Espèces"
    assert doc.lines == [("Frais d'inscription 2026-2027", "1 000 DA"),
                         ("Abonnement M1 du 18/10/2026 au 18/11/2026", "1 500 DA")]
    assert doc.totals == [("Total payé", "2 500 DA"),
                          ("Reste à payer au 18/10/2026", "1 500 DA")]
    assert doc.voided_note == ""
    assert (doc.school.header, doc.note) == ("", "")  # nothing set: nothing printed


def test_receipt_prints_the_lines_set_in_settings(conn, director, amine, tmp_path):
    settings.save_school(conn, director, "École Ennour", "", "Oran", "08:00", "20:00",
                         receipt_header="Agrément n° 12", receipt_footer="Merci de votre "
                         "confiance.")
    payment_id = payments.record(conn, director, amine, 2500, "cash")
    receipt_id = receipt_of(conn, director, payment_id)
    doc = printing.receipt_content(conn, director, receipt_id)
    assert (doc.school.header, doc.note) == ("Agrément n° 12", "Merci de votre confiance.")
    path = printing.receipt(conn, director, receipt_id, out_dir=tmp_path)
    assert path.stat().st_size > 1000


def test_receipt_of_months_paid_ahead(conn, director, amine):
    enrollment_id = enrollment_of(conn, director, amine)
    payment_id = payments.record(conn, director, amine, 10000, "cash", ahead={enrollment_id: 2})
    doc = printing.receipt_content(conn, director, receipt_of(conn, director, payment_id))
    assert doc.lines == [("Frais d'inscription 2026-2027", "1 000 DA"),
                         ("Abonnement M1 du 18/10/2026 au 18/11/2026", "3 000 DA"),
                         ("Abonnement M1 du 18/11/2026 au 18/12/2026", "3 000 DA"),
                         ("Abonnement M1 du 18/12/2026 au 18/01/2027", "3 000 DA")]
    assert doc.totals == [("Total payé", "10 000 DA"), ("Reste à payer au 18/10/2026", "0 DA")]


def test_receipt_printed_again_lists_the_same_lines(conn, director, amine, monkeypatch):
    first = payments.record(conn, director, amine, 2500, "cash")
    move_to(monkeypatch, date(2026, 10, 25))
    payments.record(conn, director, amine, 1500, "cash")
    doc = printing.receipt_content(conn, director, receipt_of(conn, director, first))
    assert doc.lines == [("Frais d'inscription 2026-2027", "1 000 DA"),
                         ("Abonnement M1 du 18/10/2026 au 18/11/2026", "1 500 DA")]
    assert doc.totals == [("Total payé", "2 500 DA"), ("Reste à payer au 25/10/2026", "0 DA")]


def test_receipt_lines_of_a_payment_from_before_0016(conn, director, amine):
    """Allocations made before 0016 have no recorded_with: they are the payment's all the
    same."""
    payment_id = payments_repo.insert(conn, amine, None, 1000, "cash", "2026-10-18T10:00:00",
                                      director.user_id)
    conn.execute("INSERT INTO payment_allocations(payment_id, charge_id, amount) "
                 "VALUES (?, ?, 1000)", (payment_id, fee_charge(conn, amine)["id"]))
    assert [(line.description, line.amount)
            for line in payments.lines(conn, director, payment_id)] == [
        ("Frais d'inscription 2026-2027", 1000)]


def test_receipt_puts_the_months_to_come_apart(conn, director, amine):
    [october] = subscriptions.for_student(conn, director, amine)
    subscriptions.renew(conn, director, october.id)  # 18/11 -> 18/12, not due yet
    payment_id = payments.record(conn, director, amine, 4000, "cash")
    doc = printing.receipt_content(conn, director, receipt_of(conn, director, payment_id))
    assert doc.totals == [("Total payé", "4 000 DA"), ("Reste à payer au 18/10/2026", "0 DA"),
                          ("À venir (pas encore dû)", "3 000 DA")]


def test_voided_receipt(conn, director, amine):
    payment_id = payments.record(conn, director, amine, 1000, "cash")
    payments.void(conn, director, payment_id, "Erreur de saisie")
    doc = printing.receipt_content(conn, director, receipt_of(conn, director, payment_id))
    assert doc.stamp == "ANNULÉ"
    assert doc.voided_note == "Reçu annulé le 18/10/2026 : Erreur de saisie"


def test_receipt_pdf_log_and_duplicate(conn, director, receptionist, amine, tmp_path):
    payment_id = payments.record(conn, receptionist, amine, 2500, "cash")
    receipt_id = receipt_of(conn, receptionist, payment_id)
    path = printing.receipt(conn, receptionist, receipt_id, tmp_path)
    assert path.name == "recu_R2026-00001.pdf"
    pdf = path.read_bytes()
    assert pdf.startswith(b"%PDF")
    # An 80 mm ticket, one page as long as its content.
    assert len(re.findall(rb"/Type /Page(?!s)", pdf)) == 1
    width = float(re.search(rb"/MediaBox \[\s*0 0 ([\d.]+)", pdf).group(1))
    assert round(width / 72 * 25.4) == 80
    logged = conn.execute("SELECT document_type, document_id, printed_by FROM print_log"
                          ).fetchall()
    assert [tuple(row) for row in logged] == [("receipt", receipt_id, receptionist.user_id)]
    assert printing.receipt_content(conn, receptionist, receipt_id).copy_mark == "DUPLICATA"


def test_unknown_receipt(conn, director):
    with pytest.raises(NotFound):
        printing.receipt_content(conn, director, 999)
