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
from tadris.domain.models import ContactInput, GroupInput, StudentInput, TeacherInput
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


# ----- debt -----

def test_debt_of_a_new_student_is_the_fee_and_the_first_month(conn, director, amine):
    d = debt.for_student(conn, director, amine)
    assert [(c.kind, c.amount, c.due) for c in d.charges] == [("registration", 1000, 1000),
                                                              ("subscription", 3000, 3000)]
    # 1 000 + 3 000, both due today, nothing paid, no credit
    assert (d.due, d.overdue, d.credit, d.balance, d.owed_now) == (4000, 4000, 0, 4000, 4000)
    assert d.oldest_overdue == "2026-10-18"


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
    assert debt.for_student(conn, director, student).balance == 0


# ----- recording: allocation order -----

def test_exact_payment_settles_everything_with_a_receipt(conn, receptionist, amine):
    payment_id = payments.record(conn, receptionist, amine, 4000, "cash")
    fee, [month] = fee_charge(conn, amine), month_charges(conn, amine)
    assert allocations_of(conn, payment_id) == [(fee["id"], 1000), (month["id"], 3000)]
    p = payments.get(conn, receptionist, payment_id)
    assert (p.amount, p.allocated, p.unallocated, p.method, p.cashier) == (4000, 4000, 0, "cash",
                                                                          "accueil")
    assert p.receipt_number == "R2026-00001"
    assert p.paid_at.startswith("2026-10-18T")
    d = debt.for_student(conn, receptionist, amine)
    assert (d.charges, d.balance, d.credit) == ((), 0, 0)


def test_partial_payment_pays_the_oldest_charge_first(conn, receptionist, amine):
    payment_id = payments.record(conn, receptionist, amine, 2500, "cash")
    fee, [month] = fee_charge(conn, amine), month_charges(conn, amine)
    # the fee (1 000) first, then 1 500 of the month
    assert allocations_of(conn, payment_id) == [(fee["id"], 1000), (month["id"], 1500)]
    d = debt.for_student(conn, receptionist, amine)
    assert [(c.id, c.paid, c.due) for c in d.charges] == [(month["id"], 1500, 1500)]
    assert d.balance == 1500


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


def test_overpayment_is_kept_as_credit(conn, receptionist, amine):
    payment_id = payments.record(conn, receptionist, amine, 5000, "cash")
    p = payments.get(conn, receptionist, payment_id)
    assert (p.allocated, p.unallocated) == (4000, 1000)
    d = debt.for_student(conn, receptionist, amine)
    assert (d.due, d.credit, d.balance, d.owed_now) == (0, 1000, -1000, 0)
    audit = json.loads(last_audit(conn, "payment.record")["new_value"])
    assert audit["to_credit"] == 1000


def test_payment_without_any_charge_is_all_credit(conn, director, school):
    student = new_student(conn, director, school, "Yacine", "Mansouri", fee=0)
    payment_id = payments.record(conn, director, student, 2000, "transfer")
    assert allocations_of(conn, payment_id) == []
    assert debt.for_student(conn, director, student).balance == -2000


def test_credit_pays_the_next_month_first_when_money_comes_in(conn, director, amine):
    first = payments.record(conn, director, amine, 5000, "cash")  # 1 000 left as credit
    [month] = subscriptions.for_student(conn, director, amine)
    subscriptions.renew(conn, director, month.id)  # 3 000, due 18/11
    d = debt.for_student(conn, director, amine)
    assert (d.due, d.credit, d.balance) == (3000, 1000, 2000)

    plan = payments.preview(conn, director, amine, 2000)
    assert (plan.credit_before, plan.credit_used, plan.allocated, plan.to_credit,
            plan.left_to_pay) == (1000, 1000, 2000, 0, 0)

    second = payments.record(conn, director, amine, 2000, "cash")
    _old, renewal = month_charges(conn, amine)
    # the 1 000 of credit from the first payment, then the 2 000
    assert allocations_of(conn, first)[-1] == (renewal["id"], 1000)
    assert allocations_of(conn, second) == [(renewal["id"], 2000)]
    d = debt.for_student(conn, director, amine)
    assert (d.due, d.credit, d.balance) == (0, 0, 0)
    applied = json.loads(last_audit(conn, "payment.apply_credit")["new_value"])
    assert applied["allocations"] == [{"payment_id": first, "charge_id": renewal["id"],
                                       "amount": 1000}]


def test_preview_matches_what_record_does(conn, director, amine):
    plan = payments.preview(conn, director, amine, 2500)
    assert [(line.charge.amount, line.from_payment, line.left) for line in plan.lines] == [
        (1000, 1000, 0), (3000, 1500, 1500)]
    payment_id = payments.record(conn, director, amine, 2500, "cash")
    assert [v for _c, v in allocations_of(conn, payment_id)] == [1000, 1500]
    assert conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 1  # preview wrote none


# ----- recording: chosen charges -----

def test_chosen_charges_replace_the_oldest_first_order(conn, director, amine):
    [month] = month_charges(conn, amine)
    payment_id = payments.record(conn, director, amine, 3000, "cash",
                                 chosen=[(month["id"], 3000)])
    assert allocations_of(conn, payment_id) == [(month["id"], 3000)]
    d = debt.for_student(conn, director, amine)
    assert [(c.kind, c.due) for c in d.charges] == [("registration", 1000)]


def test_chosen_less_than_the_payment_keeps_the_rest_as_credit(conn, director, amine):
    [month] = month_charges(conn, amine)
    payment_id = payments.record(conn, director, amine, 3000, "cash",
                                 chosen=[(month["id"], 2000)])
    assert payments.get(conn, director, payment_id).unallocated == 1000
    # 1 000 + 1 000 owed, 1 000 credit
    assert debt.for_student(conn, director, amine).balance == 1000


@pytest.mark.parametrize("chosen_kind, message_key", [
    ("too_high", "payment.allocation_too_high"),
    ("unknown", "payment.charge_unknown"),
    ("twice", "payment.charge_unknown"),
    ("exceeds", "payment.allocations_exceed"),
])
def test_chosen_charges_are_checked(conn, director, amine, chosen_kind, message_key):
    fee, [month] = fee_charge(conn, amine), month_charges(conn, amine)
    chosen, amount = {
        "too_high": ([(month["id"], 3500)], 4000),
        "unknown": ([(9999, 100)], 4000),
        "twice": ([(month["id"], 100), (month["id"], 100)], 4000),
        "exceeds": ([(fee["id"], 1000), (month["id"], 3000)], 3000),
    }[chosen_kind]
    with pytest.raises(ValidationError) as caught:
        payments.record(conn, director, amine, amount, "cash", chosen=chosen)
    assert caught.value.message.split("(")[0] == t[message_key].split("(")[0]
    assert conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0


def test_a_chosen_charge_of_another_student_is_refused(conn, director, school, amine):
    other = new_student(conn, director, school, "Sara", "Kaci")
    with pytest.raises(ValidationError):
        payments.record(conn, director, other, 1000, "cash",
                        chosen=[(fee_charge(conn, amine)["id"], 1000)])


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
    assert (p.voided, p.void_reason, p.voided_by, p.unallocated) == (True, "Billet refusé",
                                                                     "directeur", 0)
    assert p.receipt_number == "R2026-00001"  # the receipt stays, marked voided
    assert debt.for_student(conn, director, amine).balance == 4000
    entry = json.loads(last_audit(conn, "payment.void")["new_value"])
    assert entry == {"voided": True, "reason": "Billet refusé"}


def test_void_removes_the_credit(conn, director, amine):
    payment_id = payments.record(conn, director, amine, 5000, "cash")
    payments.void(conn, director, payment_id, "Erreur de montant")
    d = debt.for_student(conn, director, amine)
    assert (d.credit, d.balance) == (0, 4000)


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


def test_void_is_refused_once_counted_in_a_teacher_payout(conn, director, school, amine):
    payment_id = payments.record(conn, director, amine, 4000, "cash")
    [month] = month_charges(conn, amine)
    cur = conn.execute("INSERT INTO teacher_payouts(teacher_id, period_start, period_end, "
                       "base_amount, amount_due) VALUES (?, '2026-10-01', '2026-10-31', 3000, "
                       "1800)", (school.teacher,))
    line = conn.execute("INSERT INTO payout_lines(payout_id, group_id, revenue_basis, "
                        "percentage_bp, amount) VALUES (?, ?, 3000, 6000, 1800)",
                        (cur.lastrowid, school.maths))
    conn.execute("INSERT INTO payout_line_charges(payout_line_id, charge_id, amount) "
                 "VALUES (?, ?, 3000)", (line.lastrowid, month["id"]))
    with pytest.raises(BusinessRuleError) as caught:
        payments.void(conn, director, payment_id, "Erreur")
    assert caught.value.message == t["db.void_after_payout"]
    assert payments.get(conn, director, payment_id).voided is False


def test_paid_subscription_can_no_longer_be_cancelled(conn, director, amine):
    payments.record(conn, director, amine, 4000, "cash")
    [month] = subscriptions.for_student(conn, director, amine)
    with pytest.raises(BusinessRuleError):
        subscriptions.cancel(conn, director, month.id, "Erreur")


# ----- a hand-calculated scenario -----

def test_hand_calculated_scenario(conn, director, school, monkeypatch):
    """Fee 1 000; M1 3 000 from 18/10; P1 2 500 from 20/10; M1 renewed (due 18/11).

    18/10 pays 2 000: fee 1 000, M1 Oct 1 000.
    20/10 pays 6 000: M1 Oct 2 000, P1 Oct 2 500, M1 Nov 1 500.
    21/10 the 18/10 payment is voided: fee and M1 Oct owe 1 000 each again.
    Owed: fee 1 000 + M1 Oct 1 000 + M1 Nov 1 500 = 3 500; late on 21/10: 2 000.
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
    assert sorted(c.due for c in d.charges) == [1000, 1000, 1500]
    assert (d.due, d.overdue, d.credit, d.balance, d.owed_now) == (3500, 2000, 0, 3500, 2000)
    assert d.oldest_overdue == "2026-10-18"


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


def test_debtors_filters(conn, receptionist, school, desk):
    assert [d.student_name for d in debt.debtors(conn, receptionist, min_amount=1000)] == [
        "Benali Amine"]
    assert debt.debtors(conn, receptionist, group_id=school.physics) == []
    assert len(debt.debtors(conn, receptionist, group_id=school.maths)) == 2
    assert len(debt.debtors(conn, receptionist, min_days=15)) == 2
    assert debt.debtors(conn, receptionist, min_days=16) == []


def test_credit_takes_a_student_off_the_debtors_list(conn, director, desk):
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


def test_receipt_with_credit(conn, director, amine):
    payment_id = payments.record(conn, director, amine, 5000, "cash")
    doc = printing.receipt_content(conn, director, receipt_of(conn, director, payment_id))
    assert doc.lines[-1] == ("Avance (crédit pour les prochains mois)", "1 000 DA")
    assert doc.totals == [("Total payé", "5 000 DA"), ("Reste à payer au 18/10/2026", "0 DA"),
                          ("Crédit disponible", "1 000 DA")]


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
