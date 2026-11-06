"""Refunds, step 3: the service. Ask, approve, reject, withdraw, pay out; who may do what; what
a refund changes (the money) and what it never changes (what is owed, teacher pay).

Group A (6 000 DA a month) meets on Mondays from 01/09: September has Mondays 7, 14, 21, 28,
October 5, 12, 19, 26. Amine is in it from 01/09. A refund waits for the student to leave
(REVIEW_FIXES, decision 1): asked on 16/09, Amine's last day the 15th, September has 2 sessions
of 4 left: 3 000 DA at most."""

import json
import re
from datetime import date, timedelta

import pytest

from tadris.core import dates
from tadris.core.errors import BusinessRuleError, NotFound, PermissionDenied, ValidationError
from tadris.domain.models import GroupInput, SlotInput, StudentInput, TeacherInput
from tadris.i18n.fr import t
from tadris.repositories import payouts as payouts_repo
from tadris.services import (
    auth,
    catalog,
    enrollments,
    groups,
    holidays,
    payments,
    payouts,
    refunds,
    registrations,
    rooms,
    school_years,
    students,
    subscriptions,
    teachers,
    timetable,
)

ASKED = date(2026, 9, 16)


class Today:
    def __init__(self, day: date):
        self.day = day

    def __call__(self) -> date:
        return self.day


def fixed_clock(monkeypatch) -> Today:
    clock = Today(date(2026, 9, 1))
    monkeypatch.setattr(dates, "today", clock)
    return clock


@pytest.fixture
def today(monkeypatch):
    return fixed_clock(monkeypatch)


class School:
    pass


@pytest.fixture
def school(conn, today):
    return build_school(conn, today)


def build_school(conn, today) -> School:
    """Also used by the step 4 tests (test_refunds_money.py)."""
    s = School()
    s.conn, s.today = conn, today
    s.boss = auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")
    auth.create_user(conn, s.boss, "accueil", "password2", "receptionist")
    s.desk = auth.login(conn, "accueil", "password2")
    auth.create_user(conn, s.boss, "accueil2", "password3", "receptionist")
    s.desk2 = auth.login(conn, "accueil2", "password3")
    s.year = school_years.create(conn, s.boss, "2026-2027", date(2026, 9, 1), date(2027, 6, 30))
    s.level = level = catalog.create(conn, s.boss, "level", "4AM")
    s.subject = subject = catalog.create(conn, s.boss, "subject", "Maths")
    s.teacher = teachers.create(conn, s.boss, TeacherInput("Karim Haddad"), 6000,
                                date(2026, 9, 1))
    s.group = groups.create(conn, s.boss, GroupInput(s.year, level, subject, "A", 6000, 30,
                                                     date(2026, 9, 1)), s.teacher)
    s.room = rooms.create(conn, s.boss, "Salle 1", 20)
    timetable.add_slot(conn, s.boss, SlotInput(s.group, s.room, 1, "17:00", "18:30",
                                               valid_from=date(2026, 9, 1)))
    s.amine = students.create(conn, s.boss, StudentInput("Amine", "Benali"))
    registrations.register(conn, s.boss, s.amine, level, 1000)
    s.enrollment = enrollments.enroll(conn, s.boss, s.amine, s.group,
                                      enrolled_on=date(2026, 9, 1))
    [september] = subscriptions.for_enrollment(conn, s.boss, s.enrollment)
    s.september = september.id
    return s


def pay(s, amount, day=date(2026, 9, 2)) -> int:
    s.today.day = day
    return payments.record(s.conn, s.boss, s.amine, amount, "cash")


def paid_september(s) -> int:
    """The fee (1 000) and September (6 000), in one payment."""
    return pay(s, 7000)


def paid_october(s) -> int:
    """October renewed and paid with September and the fee: 13 000."""
    s.today.day = date(2026, 9, 2)
    october = subscriptions.renew(s.conn, s.boss, s.september)
    pay(s, 13000)
    return october


def gone(s, day=ASKED) -> None:
    """A refund waits for the leave: Amine's last day in the group is the day before `day`
    (once), so his sessions are counted from `day` on."""
    s.today.day = day
    if enrollments.get(s.conn, s.boss, s.enrollment).status in enrollments.LIVE:
        enrollments.leave(s.conn, s.boss, s.enrollment, day - timedelta(days=1))


def ask(s, month, amount, ctx=None, reason="Départ", on=ASKED) -> int:
    gone(s, on)
    return refunds.request(s.conn, ctx or s.desk, month, amount, reason)


def done(s, refund_id, amount=None, method="cash") -> str:
    refunds.approve(s.conn, s.boss, refund_id, amount)
    return refunds.pay_out(s.conn, s.boss, refund_id, method)


def month(s, subscription_id):
    return subscriptions.get(s.conn, s.boss, subscription_id)


def refused(key: str, **values):
    return pytest.raises(BusinessRuleError, match=re.escape(t[key].format(**values)))


def refund_audit(conn) -> list[tuple[str, dict]]:
    return [(row[0], json.loads(row[1])) for row in conn.execute(
        "SELECT action, new_value FROM audit_log WHERE entity_name = 'refunds' ORDER BY id")]


# ----- what can be asked -----

def test_the_maximum_is_the_value_of_the_sessions_left(conn, school):
    paid_september(school)
    gone(school)
    [september] = refunds.options(conn, school.desk, school.amine)
    assert (september.subscription_id, september.paid, september.held) == (
        school.september, 6000, 0)
    assert (september.sessions.total, september.sessions.left) == (4, 2)
    assert september.max_amount == 3000


def test_only_a_month_paid_in_full(conn, school):
    pay(school, 4000)  # the fee, then 3 000 of September
    with refused("refund.not_paid_in_full", paid="3 000 DA", price="6 000 DA"):
        ask(school, school.september, 1000)
    school.today.day = ASKED
    assert refunds.options(conn, school.desk, school.amine) == []  # nor the fee


def test_amount_and_reason_are_checked(conn, school):
    paid_september(school)
    for amount in (0, -5, True, 1.5, "100"):
        with pytest.raises(ValidationError):
            ask(school, school.september, amount)
    with pytest.raises(ValidationError):
        ask(school, school.september, 1000, reason="   ")
    with pytest.raises(NotFound):
        ask(school, 999, 1000)


def test_nothing_while_the_student_is_still_in_the_group(conn, school):
    """The leave comes first: a refund would let the student go on coming for free."""
    paid_september(school)
    school.today.day = ASKED
    [september] = refunds.options(conn, school.desk, school.amine)
    assert (september.max_amount, september.sessions, september.still_in) == (
        0, None, "A · Maths 4AM")
    with refused("refund.still_enrolled", group="A · Maths 4AM"):
        refunds.request(conn, school.desk, school.september, 1000, "Départ")
    gone(school)
    [september] = refunds.options(conn, school.desk, school.amine)
    assert (september.max_amount, september.still_in) == (3000, None)


def test_a_switch_is_not_a_leave(conn, school):
    """Amine moves to group B (Wednesdays) on 10/09 with September and October paid in A.
    B's first month starts when October ends: both months cover B, nothing can be asked on
    them. Once he leaves B on the 20th, they count on A's timetable from the 21st: September
    21 and 28 (3 000), October all of it (6 000)."""
    october = paid_october(school)
    group_b = groups.create(conn, school.boss, GroupInput(
        school.year, school.level, school.subject, "B", 6000, 30, date(2026, 9, 1)),
        school.teacher)
    timetable.add_slot(conn, school.boss, SlotInput(group_b, school.room, 3, "17:00", "18:30",
                                                    valid_from=date(2026, 9, 1)))
    school.today.day = date(2026, 9, 10)
    in_b = enrollments.switch(conn, school.boss, school.enrollment, group_b,
                              date(2026, 9, 10))
    assert [m.start_date for m in subscriptions.for_enrollment(conn, school.boss, in_b)] == [
        "2026-11-01"]
    school.today.day = ASKED
    assert {(m.subscription_id, m.max_amount, m.still_in)
            for m in refunds.options(conn, school.desk, school.amine)} == {
        (school.september, 0, "B · Maths 4AM"), (october, 0, "B · Maths 4AM")}
    for month_id in (school.september, october):
        with refused("refund.still_enrolled", group="B · Maths 4AM"):
            refunds.request(conn, school.desk, month_id, 1000, "Changement de groupe")
    school.today.day = date(2026, 9, 20)
    enrollments.leave(conn, school.boss, in_b, date(2026, 9, 20))
    counted = {m.subscription_id: (m.sessions.counted_from, m.max_amount)
               for m in refunds.options(conn, school.desk, school.amine)}
    assert counted == {school.september: ("2026-09-21", 3000), october: ("2026-09-21", 6000)}


def test_never_more_than_the_maximum(conn, school):
    paid_september(school)
    with refused("refund.above_max", amount="3 000 DA"):
        ask(school, school.september, 3001)


def test_a_month_without_a_session(conn, school):
    paid_september(school)
    school.today.day = date(2026, 9, 2)
    holidays.create(conn, school.boss, "Fermeture", date(2026, 9, 1), date(2026, 9, 30))
    with refused("refund.no_session"):
        ask(school, school.september, 1000)


# ----- a partial refund -----

def test_a_partial_refund(conn, school):
    """2 000 of the 3 000 left go back. The month stays paid and owes nothing; it counts for
    the teacher on what the school keeps; it cannot be cancelled (4 000 kept)."""
    payment = paid_september(school)
    refund = ask(school, school.september, 2000)
    assert refunds.get(conn, school.desk, refund).status == "pending"
    number = done(school, refund)
    assert number == "RB2026-00001"
    paid = refunds.get(conn, school.boss, refund)
    assert (paid.status, paid.amount, paid.method, paid.paid_by) == (
        "paid", 2000, "cash", "directeur")
    assert [tuple(r) for r in conn.execute(
        "SELECT pa.payment_id, ra.amount FROM refund_allocations ra "
        "JOIN payment_allocations pa ON pa.id = ra.payment_allocation_id")] == [(payment, 2000)]
    september = month(school, school.september)
    assert (september.paid, september.refunded, september.kept, september.due) == (
        6000, 2000, 4000, 0)
    assert september.status != "cancelled" and not september.can_cancel
    with refused("subscription.paid", amount="4 000 DA"):
        subscriptions.cancel(conn, school.boss, school.september, "Départ")
    owed = payouts_repo.owed(conn, school.teacher, "2026-10-01")
    assert [(row["charge_id"], row["amount"]) for row in owed] == [
        (september.charge_id, 4000)]  # the teacher's month, less what went back


def test_a_month_with_a_request_open_waits_for_the_teacher(conn, school):
    """Asked, the month leaves the teacher's draft and is owed nothing until decided; once
    paid out, it is owed again on what the school keeps."""
    paid_september(school)
    school.today.day = date(2026, 10, 1)
    payouts.build_draft(conn, school.boss, school.teacher, date(2026, 10, 1))
    refund = ask(school, school.september, 2000, on=date(2026, 9, 16))
    school.today.day = date(2026, 10, 1)
    assert payouts_repo.draft_of(conn, school.teacher) is None  # its only month went
    assert payouts_repo.owed(conn, school.teacher, "2026-10-01") == []
    done(school, refund)
    [row] = payouts_repo.owed(conn, school.teacher, "2026-10-01")
    assert row["amount"] == 4000
    payout = payouts.build_draft(conn, school.boss, school.teacher, date(2026, 10, 1))
    assert payouts.get(conn, school.boss, payout).amount_due == 2400  # 60 % of 4 000


def test_an_approved_request_still_holds_the_month_back(conn, school):
    paid_september(school)
    refund = ask(school, school.september, 2000)
    refunds.approve(conn, school.boss, refund)
    school.today.day = date(2026, 10, 1)
    assert payouts_repo.owed(conn, school.teacher, "2026-10-01") == []
    refunds.pay_out(conn, school.boss, refund, "cash")
    payout = payouts.build_draft(conn, school.boss, school.teacher, date(2026, 10, 1))
    [line] = payouts.lines(conn, school.boss, payout)
    assert (line.revenue_basis, line.amount) == (4000, 2400)


def test_a_refund_paid_on_a_month_a_draft_holds_lowers_its_line(conn, school, monkeypatch):
    """A draft built before 0025 may still hold a month with a request open (the request
    did not let it go then): paid out, the line counts what the school now keeps."""
    paid_september(school)
    school.today.day = date(2026, 10, 1)
    payout = payouts.build_draft(conn, school.boss, school.teacher, date(2026, 10, 1))
    with monkeypatch.context() as patch:
        patch.setattr(payouts, "drop_month", lambda *args: None)
        refund = ask(school, school.september, 2000)
    refunds.approve(conn, school.boss, refund)
    refunds.pay_out(conn, school.boss, refund, "cash")
    [line] = payouts.lines(conn, school.boss, payout)
    assert (line.revenue_basis, line.amount) == (4000, 2400)
    assert payouts.get(conn, school.boss, payout).amount_due == 2400


def test_a_month_refunded_in_full_pays_the_teacher_nothing(conn, school):
    october = paid_october(school)
    done(school, ask(school, october, 6000))
    owed = payouts_repo.owed(conn, school.teacher, "2026-11-01")
    assert month(school, october).charge_id not in {row["charge_id"] for row in owed}


def test_a_second_request_after_a_partial_refund(conn, school):
    paid_september(school)
    done(school, ask(school, school.september, 2000))
    with refused("refund.above_max", amount="1 000 DA"):
        ask(school, school.september, 1500)
    done(school, ask(school, school.september, 1000))
    with refused("refund.nothing_left"):
        ask(school, school.september, 1)


# ----- a full refund, then the month cancelled by hand -----

def test_a_full_refund_then_the_director_cancels_the_month(conn, school):
    """October paid ahead, Amine leaves on the 16th: October is kept (money was paid on it),
    refunded in full, then cancelled by the director; it no longer pays the teacher."""
    october = paid_october(school)
    school.today.day = ASKED
    enrollments.leave(conn, school.boss, school.enrollment, ASKED)
    assert month(school, october).status != "cancelled"
    assert [(m.subscription_id, m.max_amount)
            for m in refunds.options(conn, school.desk, school.amine)] == [
        (october, 6000), (school.september, 3000)]  # latest first; counted from the 17th
    refund = ask(school, october, 6000)
    with refused("subscription.refund_open"):
        subscriptions.cancel(conn, school.boss, october, "Départ")
    done(school, refund)
    october_month = month(school, october)
    assert (october_month.kept, october_month.can_cancel) == (0, True)
    with pytest.raises(PermissionDenied):
        subscriptions.cancel(conn, school.desk, october, "Départ")
    subscriptions.cancel(conn, school.boss, october, "Départ, remboursé")
    assert month(school, october).status == "cancelled"
    owed = payouts_repo.owed(conn, school.teacher, "2026-11-01")
    assert october_month.charge_id not in {row["charge_id"] for row in owed}
    [line] = [json.loads(r[0]) for r in conn.execute(
        "SELECT new_value FROM audit_log WHERE action = 'subscription.cancel'")]
    assert line["refunded"] == 6000


def test_a_refund_in_full_never_cancels_the_month_by_itself(conn, school):
    """October, kept when Amine left (paid), refunded in full: it waits for the director."""
    october = paid_october(school)
    done(school, ask(school, october, 6000))
    assert month(school, october).status != "cancelled"
    assert month(school, october).can_cancel


def test_money_comes_back_from_the_latest_payments_first(conn, school):
    """September paid by two payments (2 000 then 4 000, after the fee): 5 000 back takes the
    4 000 of the latest, then 1 000 of the first."""
    first = pay(school, 3000)  # the fee and 2 000 of September
    second = pay(school, 4000, date(2026, 9, 3))
    refund = ask(school, school.september, 5000, on=date(2026, 9, 5))  # nothing used yet
    done(school, refund)
    assert [tuple(r) for r in conn.execute(
        "SELECT pa.payment_id, ra.amount FROM refund_allocations ra "
        "JOIN payment_allocations pa ON pa.id = ra.payment_allocation_id ORDER BY ra.id")] == [
        (second, 4000), (first, 1000)]


# ----- duplicate and rejected requests -----

def test_requests_together_never_pass_the_maximum(conn, school):
    paid_september(school)
    ask(school, school.september, 2000)
    with refused("refund.above_max", amount="1 000 DA"):
        ask(school, school.september, 2000)  # the same request again
    ask(school, school.september, 1000)
    with refused("refund.nothing_left"):
        ask(school, school.september, 500)


def test_a_rejected_request_frees_its_amount(conn, school):
    paid_september(school)
    refund = ask(school, school.september, 3000)
    with pytest.raises(ValidationError):
        refunds.reject(conn, school.boss, refund, " ")
    refunds.reject(conn, school.boss, refund, "Pas de motif valable")
    rejected = refunds.get(conn, school.boss, refund)
    assert (rejected.status, rejected.close_reason, rejected.decided_by) == (
        "rejected", "Pas de motif valable", "directeur")
    with refused("refund.not_pending"):
        refunds.approve(conn, school.boss, refund)
    ask(school, school.september, 3000)  # the same amount, asked again


def test_an_approved_request_is_withdrawn_not_rejected(conn, school):
    paid_september(school)
    refund = ask(school, school.september, 3000)
    refunds.approve(conn, school.boss, refund)
    with refused("refund.not_pending"):
        refunds.reject(conn, school.boss, refund, "Non")
    refunds.withdraw(conn, school.boss, refund, "Le parent ne vient pas")
    assert refunds.get(conn, school.boss, refund).status == "cancelled"
    with refused("refund.closed"):
        refunds.withdraw(conn, school.boss, refund, "Encore")
    ask(school, school.september, 3000)


# ----- the director's decision -----

def test_the_director_approves_the_amount_asked_or_less(conn, school):
    """Never more than asked, even with room left under the maximum (3 000): REVIEW_FIXES,
    decision 3."""
    paid_september(school)
    refund = ask(school, school.september, 1000)
    for amount in (3500, 1001):
        with refused("refund.above_asked", amount="1 000 DA"):
            refunds.approve(conn, school.boss, refund, amount)
    refunds.approve(conn, school.boss, refund, 800)
    assert refunds.get(conn, school.boss, refund).amount == 800


def test_approving_less_frees_the_rest(conn, school):
    """1 000 and 2 000 asked hold the whole 3 000; 600 approved on the first frees 400."""
    paid_september(school)
    first = ask(school, school.september, 1000)
    ask(school, school.september, 2000)
    with refused("refund.nothing_left"):
        ask(school, school.september, 1)
    refunds.approve(conn, school.boss, first, 600)
    with refused("refund.above_max", amount="400 DA"):
        ask(school, school.september, 401)
    ask(school, school.september, 400)


def test_the_count_kept_with_the_request_is_the_one_approved(conn, school):
    """A Wednesday slot and a holiday added after the request change the timetable, never
    the maximum kept with it: 2 of 4 sessions, 3 000."""
    paid_september(school)
    refund = ask(school, school.september, 3000)
    school.today.day = date(2026, 9, 17)
    timetable.add_slot(conn, school.boss, SlotInput(school.group, school.room, 3, "17:00",
                                                    "18:30", valid_from=date(2026, 9, 17)))
    holidays.create(conn, school.boss, "Fête", date(2026, 9, 28))
    now = refunds._sessions_left(conn, school.september)
    assert (now.total, now.left, now.value) == (5, 3, 3600)  # 7, 14, 21 | 23, 30 (28 off)
    with refused("refund.above_asked", amount="3 000 DA"):
        refunds.approve(conn, school.boss, refund, 3001)
    refunds.approve(conn, school.boss, refund)
    kept = refunds.get(conn, school.boss, refund)
    assert (kept.counted_from, kept.sessions_total, kept.sessions_left, kept.sessions_value,
            kept.max_amount, kept.amount) == ("2026-09-16", 4, 2, 3000, 3000, 3000)


# ----- who may do what -----

def test_the_desk_asks_the_director_decides_and_pays(conn, school):
    paid_september(school)
    refund = ask(school, school.september, 1000)
    for step in (lambda: refunds.approve(conn, school.desk, refund),
                 lambda: refunds.reject(conn, school.desk, refund, "Non"),
                 lambda: refunds.pay_out(conn, school.desk, refund, "cash")):
        with pytest.raises(PermissionDenied):
            step()
    refunds.approve(conn, school.boss, refund)
    with pytest.raises(PermissionDenied):
        refunds.pay_out(conn, school.desk, refund, "cash")


def test_the_desk_withdraws_only_its_own_pending_request(conn, school):
    paid_september(school)
    mine = ask(school, school.september, 1000)
    theirs = ask(school, school.september, 1000, ctx=school.desk2)
    with pytest.raises(PermissionDenied):
        refunds.withdraw(conn, school.desk, theirs, "Erreur")
    refunds.withdraw(conn, school.desk, mine, "Erreur de saisie")
    refunds.approve(conn, school.boss, theirs)
    with pytest.raises(PermissionDenied):
        refunds.withdraw(conn, school.desk2, theirs, "Erreur")  # approved: the director's
    refunds.withdraw(conn, school.boss, theirs, "Le parent a changé d'avis")


# ----- paying out -----

def test_paying_out_needs_an_approval_and_a_method(conn, school):
    paid_september(school)
    refund = ask(school, school.september, 1000)
    with refused("refund.not_approved"):
        refunds.pay_out(conn, school.boss, refund, "cash")
    refunds.approve(conn, school.boss, refund)
    with pytest.raises(ValidationError):
        refunds.pay_out(conn, school.boss, refund, "bitcoin")
    assert refunds.pay_out(conn, school.boss, refund, "transfer") == "RB2026-00001"
    with refused("refund.not_approved"):
        refunds.pay_out(conn, school.boss, refund, "cash")  # once only


def test_numbers_follow_each_other(conn, school):
    paid_september(school)
    first = ask(school, school.september, 1000)
    second = ask(school, school.september, 1000)
    assert [done(school, first), done(school, second)] == ["RB2026-00001", "RB2026-00002"]


# ----- voids -----

def test_no_void_while_a_request_is_open_nor_once_money_went_back(conn, school):
    payment = paid_september(school)
    refund = ask(school, school.september, 1000)
    with refused("payment.refund_open"):
        payments.void(conn, school.boss, payment, "Erreur")
    done(school, refund)
    with refused("payment.handed_back"):
        payments.void(conn, school.boss, payment, "Erreur")


def test_a_void_is_possible_again_once_the_request_is_closed(conn, school):
    payment = paid_september(school)
    refund = ask(school, school.september, 1000)
    refunds.reject(conn, school.boss, refund, "Non")
    payments.void(conn, school.boss, payment, "Erreur de saisie")


# ----- the record -----

def test_every_step_is_in_the_audit_log(conn, school):
    paid_september(school)
    first = ask(school, school.september, 1000)
    refunds.reject(conn, school.boss, first, "Non")
    second = ask(school, school.september, 1500)
    refunds.withdraw(conn, school.desk, second, "Erreur")
    third = ask(school, school.september, 2000)
    done(school, third, 1800)
    actions = refund_audit(conn)
    assert [action for action, _ in actions] == [
        "refund.request", "refund.reject", "refund.request", "refund.cancel",
        "refund.request", "refund.approve", "refund.pay"]
    asked = actions[0][1]
    assert (asked["amount"], asked["max_amount"], asked["sessions_total"],
            asked["sessions_left"], asked["sessions_value"]) == (1000, 3000, 4, 2, 3000)
    assert actions[1][1] == {"status": "rejected", "reason": "Non"}
    assert actions[5][1] == {"status": "approved", "amount_approved": 1800}
    assert (actions[6][1]["number"], actions[6][1]["amount"]) == ("RB2026-00001", 1800)
    assert [part["amount"] for part in actions[6][1]["from"]] == [1800]


def test_the_queue_and_a_students_refunds(conn, school):
    paid_september(school)
    first = ask(school, school.september, 1000)
    second = ask(school, school.september, 1000)
    third = ask(school, school.september, 1000)
    refunds.approve(conn, school.boss, second)
    refunds.reject(conn, school.boss, third, "Non")
    assert [r.id for r in refunds.queue(conn, school.desk)] == [first, second]
    assert [r.id for r in refunds.for_student(conn, school.desk, school.amine)] == [
        third, second, first]
    one = refunds.get(conn, school.desk, first)
    assert (one.student_name, one.group_title, one.requested_by) == (
        "Benali Amine", "A · Maths 4AM", "accueil")


# ----- a group closed by the school -----

def test_a_group_closed_during_the_month(conn, school):
    """Closed on 16/09: September gives back 21 and 28 (3 000), October paid ahead all of it
    (6 000)."""
    october = paid_october(school)
    school.today.day = ASKED
    groups.close(conn, school.boss, school.group)
    school.today.day = date(2026, 9, 20)
    maxima = {m.subscription_id: m.max_amount
              for m in refunds.options(conn, school.desk, school.amine)}
    assert maxima == {school.september: 3000, october: 6000}
    done(school, ask(school, october, 6000, on=date(2026, 9, 20)))
    done(school, ask(school, school.september, 3000, on=date(2026, 9, 20)))
    subscriptions.cancel(conn, school.boss, october, "Groupe clôturé, remboursé")


def test_a_group_closed_before_it_starts_hands_its_month_back(conn, school):
    """The review's case: group C (Physique) starts on 01/10, Tuesdays. Amine joins it and
    pays its October in September; the school closes C on 20/09 (too few students). October
    goes back in full (6 000), then the director cancels it. Amine is still in A: that is
    another place, it blocks nothing here."""
    school.today.day = date(2026, 9, 15)
    physique = catalog.create(conn, school.boss, "subject", "Physique")
    group_c = groups.create(conn, school.boss, GroupInput(
        school.year, school.level, physique, "C", 6000, 30, date(2026, 10, 1)), school.teacher)
    timetable.add_slot(conn, school.boss, SlotInput(group_c, school.room, 2, "17:00", "18:30"))
    in_c = enrollments.enroll(conn, school.boss, school.amine, group_c)
    [c_october] = subscriptions.for_enrollment(conn, school.boss, in_c)
    pay(school, 13000, date(2026, 9, 15))  # the fee, A's September, C's October
    school.today.day = date(2026, 9, 20)
    groups.close(conn, school.boss, group_c)
    maxima = {m.subscription_id: m.max_amount
              for m in refunds.options(conn, school.desk, school.amine)}
    assert maxima == {c_october.id: 6000, school.september: 0}  # A's: still in A
    refund = refunds.request(conn, school.desk, c_october.id, 6000, "Groupe clôturé")
    done(school, refund)
    subscriptions.cancel(conn, school.boss, c_october.id, "Groupe clôturé, remboursé")
    assert month(school, c_october.id).status == "cancelled"


def test_a_month_with_no_session_none_of_it_used(conn, school):
    """October paid ahead, all of it a holiday; Amine leaves on the 15th. October gave
    nothing: it goes back in full (REVIEW_FIXES, decision 2)."""
    october = paid_october(school)
    holidays.create(conn, school.boss, "Fermeture", date(2026, 10, 1), date(2026, 10, 31))
    refund = refunds.get(conn, school.boss, ask(school, october, 6000))
    assert (refund.sessions_total, refund.sessions_left, refund.sessions_value,
            refund.max_amount) == (0, 0, 6000, 6000)


def test_only_one_students_months_know_their_refunds(conn, school):
    """The school-wide lists (here the renewals) leave the refund columns out: their months
    cannot say whether « Annuler » is possible, and asking raises (REVIEW_FIXES, finding
    11). One student's months, and one month, read them."""
    paid_september(school)
    school.today.day = date(2026, 9, 25)  # September ends within 7 days
    [soon] = subscriptions.ending_soon(conn, school.boss)
    assert (soon.id, soon.refunded, soon.refund_open) == (school.september, None, None)
    with pytest.raises(ValueError):
        assert soon.can_cancel
    [mine] = subscriptions.for_student(conn, school.boss, school.amine)
    assert (mine.refunded, mine.refund_open, mine.kept, mine.can_cancel) == (0, False, 6000,
                                                                              False)
    assert month(school, school.september).kept == 6000
