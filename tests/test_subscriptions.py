import json
from datetime import date

import pytest

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, PermissionDenied, ValidationError
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

TODAY = date(2026, 10, 18)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(dates, "today", lambda: TODAY)


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
        self.subjects = {}
        self.maths = self.group(conn, ctx, "M1", "Maths", 3000)
        self.physics = self.group(conn, ctx, "P1", "Physique", 2500)
        self.free = self.group(conn, ctx, "Club", "Lecture", 0)

    def group(self, conn, ctx, name, subject, price):
        subject_id = catalog.create(conn, ctx, "subject", subject)
        return groups.create(conn, ctx, GroupInput(self.year, self.level, subject_id, name,
                                                   price, 10, date(2026, 9, 1)), self.teacher)


@pytest.fixture
def school(conn, director):
    return School(conn, director)


@pytest.fixture
def amine(conn, director, school):
    student = students.create(conn, director, StudentInput("Amine", "Benali"))
    registrations.register(conn, director, student, school.level, 0)
    return student


@pytest.fixture
def in_maths(conn, receptionist, school, amine):
    """Amine in M1 since 18/10/2026, with his automatic first month (18/10 to 18/11)."""
    return enrollments.enroll(conn, receptionist, amine, school.maths)


def month_of(conn, ctx, enrollment_id) -> int:
    """The enrollment's one month that is not cancelled."""
    [month] = [s.id for s in subscriptions.for_enrollment(conn, ctx, enrollment_id)
               if s.status != "cancelled"]
    return month


def charge_of(conn, subscription_id):
    return conn.execute("SELECT * FROM charges WHERE subscription_id = ?",
                        (subscription_id,)).fetchone()


def last_audit(conn, action):
    row = conn.execute("SELECT * FROM audit_log WHERE action = ? ORDER BY id DESC",
                       (action,)).fetchone()
    return row


def set_price(conn, director, school, group_id, price):
    g = groups.get(conn, director, group_id)
    groups.update(conn, director, group_id, GroupInput(school.year, g.level_id, g.subject_id,
                                                       g.name, price, g.capacity,
                                                       date.fromisoformat(g.start_date)))


def pay(conn, director, student_id, charge_id, amount):
    cur = conn.execute("INSERT INTO payments(student_id, amount, method, paid_at, received_by) "
                       "VALUES (?, ?, 'cash', '2026-10-18T10:00:00', ?)",
                       (student_id, amount, director.user_id))
    conn.execute("INSERT INTO payment_allocations(payment_id, charge_id, amount) VALUES (?, ?, ?)",
                 (cur.lastrowid, charge_id, amount))


# ----- one month, its charge -----

def test_a_month_from_the_entry_date_with_its_charge(conn, receptionist, in_maths):
    sub_id = month_of(conn, receptionist, in_maths)
    s = subscriptions.get(conn, receptionist, sub_id)
    assert (s.start_date, s.end_date, s.price, s.state) == ("2026-10-18", "2026-11-18", 3000,
                                                            "active")
    assert (s.paid, s.due, s.group_title) == (0, 3000, "M1 · Maths 4AM")
    charge = charge_of(conn, sub_id)
    assert (charge["amount"], charge["status"]) == (3000, "open")
    assert charge["due_date"] == charge["accrual_date"] == "2026-10-18"
    assert charge["description"] == "Abonnement M1 du 18/10/2026 au 18/11/2026"
    entry = json.loads(last_audit(conn, "subscription.create")["new_value"])
    assert (entry["price"], entry["charge_id"]) == (3000, charge["id"])


def test_price_is_a_snapshot(conn, director, receptionist, school, in_maths):
    first = month_of(conn, receptionist, in_maths)
    set_price(conn, director, school, school.maths, 3500)
    assert subscriptions.get(conn, receptionist, first).price == 3000
    second = subscriptions.renew(conn, receptionist, first)
    assert subscriptions.get(conn, receptionist, second).price == 3500


def test_free_group_has_no_charge(conn, receptionist, school, amine):
    enrollment_id = enrollments.enroll(conn, receptionist, amine, school.free)
    sub_id = month_of(conn, receptionist, enrollment_id)
    s = subscriptions.get(conn, receptionist, sub_id)
    assert (s.price, s.charge_id, s.due) == (0, None, 0)
    assert charge_of(conn, sub_id) is None


@pytest.mark.parametrize("today, state", [
    (date(2026, 10, 10), "upcoming"), (date(2026, 10, 18), "active"),
    (date(2026, 11, 11), "expiring"), (date(2026, 11, 17), "expiring"),
    (date(2026, 11, 18), "ended"),
])
def test_display_state(today, state):
    row = {"status": "active", "start_date": "2026-10-18", "end_date": "2026-11-18"}
    assert subscriptions.state_of(row, today) == state
    assert subscriptions.state_of({**row, "status": "cancelled"}, today) == "cancelled"


# ----- rules for a new month -----

def test_trial_has_no_subscription(conn, receptionist, school, amine):
    enrollment_id = enrollments.enroll(conn, receptionist, amine, school.maths, trial=True)
    with pytest.raises(BusinessRuleError) as exc:
        subscriptions.start(conn, receptionist, enrollment_id)
    assert exc.value.message == t["subscription.trial"]


def test_start_dates_stay_in_the_enrollment_and_the_year(conn, director, receptionist,
                                                         in_maths):
    subscriptions.cancel(conn, director, month_of(conn, director, in_maths), "Erreur")
    with pytest.raises(ValidationError) as exc:
        subscriptions.start(conn, receptionist, in_maths, date(2026, 10, 17))
    assert exc.value.message == t["subscription.start_before_entry"].format(date="18/10/2026")
    with pytest.raises(ValidationError) as exc:
        subscriptions.start(conn, receptionist, in_maths, date(2027, 7, 1))
    assert exc.value.message == t["subscription.start_outside_year"].format(end="30/06/2027")


def test_one_running_month_at_a_time(conn, receptionist, in_maths):
    with pytest.raises(BusinessRuleError) as exc:
        subscriptions.start(conn, receptionist, in_maths, date(2026, 11, 1))
    assert exc.value.message == t["subscription.already_running"].format(end="18/11/2026")


# ----- renew -----

def test_renewal_chain_has_no_gap_or_overlap(conn, receptionist, in_maths):
    first = month_of(conn, receptionist, in_maths)
    second = subscriptions.renew(conn, receptionist, first)
    third = subscriptions.renew(conn, receptionist, second)
    months = subscriptions.for_enrollment(conn, receptionist, in_maths)
    assert [(s.start_date, s.end_date) for s in months] == [
        ("2026-10-18", "2026-11-18"), ("2026-11-18", "2026-12-18"), ("2026-12-18", "2027-01-18")]
    assert [s.renewal_of_id for s in months] == [None, first, second]
    assert third == months[-1].id


def test_only_the_latest_month_is_renewed(conn, receptionist, in_maths):
    first = month_of(conn, receptionist, in_maths)
    subscriptions.renew(conn, receptionist, first)
    with pytest.raises(BusinessRuleError) as exc:
        subscriptions.renew(conn, receptionist, first)
    assert exc.value.message == t["subscription.not_latest"].format(end="18/12/2026")


def test_renewal_after_a_gap_never_before_the_end(conn, receptionist, in_maths):
    first = month_of(conn, receptionist, in_maths)
    with pytest.raises(ValidationError) as exc:
        subscriptions.renew(conn, receptionist, first, date(2026, 11, 10))
    assert exc.value.message == t["subscription.start_before_end"].format(end="18/11/2026")
    later = subscriptions.renew(conn, receptionist, first, date(2026, 12, 5))
    assert subscriptions.get(conn, receptionist, later).start_date == "2026-12-05"


def test_month_end_dates_are_stable(conn, receptionist, school, amine):
    """31 Jan -> 28 Feb, then 28 Feb -> 28 Mar: each month starts on the previous end."""
    enrollment_id = enrollments.enroll(conn, receptionist, amine, school.physics,
                                       enrolled_on=date(2027, 1, 31))
    first = month_of(conn, receptionist, enrollment_id)
    second = subscriptions.renew(conn, receptionist, first)
    s1, s2 = (subscriptions.get(conn, receptionist, i) for i in (first, second))
    assert (s1.start_date, s1.end_date) == ("2027-01-31", "2027-02-28")
    assert (s2.start_date, s2.end_date) == ("2027-02-28", "2027-03-28")


def test_no_renewal_once_the_student_left(conn, receptionist, in_maths):
    first = month_of(conn, receptionist, in_maths)
    enrollments.leave(conn, receptionist, in_maths)
    with pytest.raises(BusinessRuleError) as exc:
        subscriptions.renew(conn, receptionist, first)
    assert exc.value.message == t["subscription.enrollment_not_live"]


def test_renew_many_is_all_or_nothing(conn, receptionist, school, amine, in_maths):
    good = month_of(conn, receptionist, in_maths)
    yanis = students.create(conn, receptionist, StudentInput("Yanis", "Haddad"))
    registrations.register(conn, receptionist, yanis, school.level, 0)
    other = enrollments.enroll(conn, receptionist, yanis, school.maths)
    bad = month_of(conn, receptionist, other)
    enrollments.leave(conn, receptionist, other)
    with pytest.raises(BusinessRuleError):
        subscriptions.renew_many(conn, receptionist, [good, bad])
    assert month_of(conn, receptionist, in_maths) == good  # nothing renewed
    new = subscriptions.renew_many(conn, receptionist, [good])
    assert len(new) == 1


# ----- cancel -----

def test_cancel_frees_the_period_and_its_charge(conn, director, in_maths):
    sub_id = month_of(conn, director, in_maths)
    subscriptions.cancel(conn, director, sub_id, "  Erreur de date ")
    s = subscriptions.get(conn, director, sub_id)
    assert (s.status, s.state, s.due) == ("cancelled", "cancelled", 0)
    assert charge_of(conn, sub_id)["status"] == "cancelled"
    entry = json.loads(last_audit(conn, "subscription.cancel")["new_value"])
    assert entry["reason"] == "Erreur de date"
    again = subscriptions.start(conn, director, in_maths)  # same dates are free again
    assert subscriptions.get(conn, director, again).start_date == "2026-10-18"
    with pytest.raises(BusinessRuleError):
        subscriptions.cancel(conn, director, sub_id, "encore")


def test_cancel_is_director_only_with_a_reason(conn, director, receptionist, in_maths):
    sub_id = month_of(conn, receptionist, in_maths)
    with pytest.raises(PermissionDenied):
        subscriptions.cancel(conn, receptionist, sub_id, "motif")
    with pytest.raises(ValidationError):
        subscriptions.cancel(conn, director, sub_id, "  ")


def test_cancel_refused_once_paid(conn, director, amine, in_maths):
    sub_id = month_of(conn, director, in_maths)
    pay(conn, director, amine, charge_of(conn, sub_id)["id"], 1000)
    s = subscriptions.get(conn, director, sub_id)
    assert (s.paid, s.due) == (1000, 2000)
    with pytest.raises(BusinessRuleError) as exc:
        subscriptions.cancel(conn, director, sub_id, "motif")
    assert exc.value.message == t["subscription.paid"].format(amount="1 000 DA")


def test_cancel_refused_once_in_a_teacher_payout(conn, director, school, in_maths):
    sub_id = month_of(conn, director, in_maths)
    charge = charge_of(conn, sub_id)
    payout = conn.execute(
        "INSERT INTO teacher_payouts(teacher_id, period_start, period_end, base_amount, "
        "amount_due) VALUES (?, '2026-10-01', '2026-10-31', 3000, 1800)",
        (school.teacher,)).lastrowid
    line = conn.execute(
        "INSERT INTO payout_lines(payout_id, group_id, revenue_basis, percentage_bp, amount) "
        "VALUES (?, ?, 3000, 6000, 1800)", (payout, school.maths)).lastrowid
    conn.execute("INSERT INTO payout_line_charges(payout_line_id, charge_id, amount) "
                 "VALUES (?, ?, 3000)", (line, charge["id"]))
    with pytest.raises(BusinessRuleError) as exc:
        subscriptions.cancel(conn, director, sub_id, "motif")
    assert exc.value.message == t["subscription.in_payout"]


def test_renewal_after_a_cancelled_renewal(conn, director, in_maths):
    first = month_of(conn, director, in_maths)
    renewal = subscriptions.renew(conn, director, first)
    subscriptions.cancel(conn, director, renewal, "Erreur")
    again = subscriptions.renew(conn, director, first)  # the unique link is taken: left out
    s = subscriptions.get(conn, director, again)
    assert (s.start_date, s.renewal_of_id) == ("2026-11-18", None)


# ----- start-up bookkeeping -----

def test_mark_ended(conn, director, in_maths, monkeypatch):
    sub_id = month_of(conn, director, in_maths)
    assert subscriptions.mark_ended(conn) == 0
    monkeypatch.setattr(dates, "today", lambda: date(2026, 11, 18))
    assert subscriptions.mark_ended(conn) == 1
    assert subscriptions.get(conn, director, sub_id).status == "ended"
    entry = last_audit(conn, "subscription.mark_ended")
    assert entry["user_id"] is None
    assert json.loads(entry["new_value"]) == {"count": 1, "on": "2026-11-18"}
    assert subscriptions.mark_ended(conn) == 0
    # An ended month can still be renewed.
    subscriptions.renew(conn, director, sub_id)


# ----- the desk's lists -----

def test_lists_of_months_to_renew(conn, director, receptionist, school, amine, in_maths,
                                  monkeypatch):
    first = month_of(conn, receptionist, in_maths)  # ends 18/11
    yanis = students.create(conn, receptionist, StudentInput("Yanis", "Haddad"))
    registrations.register(conn, receptionist, yanis, school.level, 0)
    trial = enrollments.enroll(conn, receptionist, yanis, school.maths, trial=True)
    assert subscriptions.ending_soon(conn, receptionist) == []
    monkeypatch.setattr(dates, "today", lambda: date(2026, 11, 12))
    assert [s.id for s in subscriptions.ending_soon(conn, receptionist)] == [first]
    assert subscriptions.lapsed(conn, receptionist) == []
    monkeypatch.setattr(dates, "today", lambda: date(2026, 11, 20))
    assert subscriptions.ending_soon(conn, receptionist) == []
    assert [s.id for s in subscriptions.lapsed(conn, receptionist)] == [first]
    renewal = subscriptions.renew(conn, receptionist, first)
    assert subscriptions.lapsed(conn, receptionist) == []  # renewed: off the list
    assert [s.id for s in subscriptions.ending_soon(conn, receptionist, days=30)] == [renewal]
    assert trial  # a trial is in no list


def test_lists_skip_students_who_left(conn, receptionist, in_maths, monkeypatch):
    month_of(conn, receptionist, in_maths)
    enrollments.leave(conn, receptionist, in_maths)
    monkeypatch.setattr(dates, "today", lambda: date(2026, 11, 20))
    assert subscriptions.lapsed(conn, receptionist) == []


def test_students_without_any_subscription(conn, director, receptionist, in_maths):
    assert subscriptions.missing(conn, receptionist) == []
    subscriptions.cancel(conn, director, month_of(conn, director, in_maths), "Erreur")
    missing = subscriptions.missing(conn, receptionist)
    assert [(m.enrollment_id, m.student_name, m.group_title) for m in missing] == [
        (in_maths, "Benali Amine", "M1 · Maths 4AM")]
    subscriptions.start(conn, receptionist, in_maths)
    assert subscriptions.missing(conn, receptionist) == []


# ----- the first month is automatic -----

def months(conn, ctx, enrollment_id) -> list[tuple]:
    return [(s.start_date, s.end_date, s.price, s.status)
            for s in subscriptions.for_enrollment(conn, ctx, enrollment_id)]


def test_enrolling_starts_the_first_month_on_the_entry_date(conn, receptionist, school, amine):
    enrollment_id = enrollments.enroll(conn, receptionist, amine, school.maths,
                                       enrolled_on=date(2026, 10, 5))
    assert months(conn, receptionist, enrollment_id) == [
        ("2026-10-05", "2026-11-05", 3000, "active")]
    entry = json.loads(last_audit(conn, "subscription.create")["new_value"])
    assert entry["enrollment_id"] == enrollment_id


def test_a_trial_is_free_until_confirmed(conn, receptionist, school, amine, monkeypatch):
    enrollment_id = enrollments.enroll(conn, receptionist, amine, school.maths, trial=True,
                                       enrolled_on=date(2026, 10, 12))
    assert months(conn, receptionist, enrollment_id) == []
    enrollments.confirm_trial(conn, receptionist, enrollment_id)  # today, 18/10
    assert months(conn, receptionist, enrollment_id) == [
        ("2026-10-18", "2026-11-18", 3000, "active")]


def test_confirming_before_the_group_starts(conn, director, receptionist, school, amine):
    subject = catalog.create(conn, director, "subject", "Arabe")
    later = groups.create(conn, director, GroupInput(school.year, school.level, subject, "A1",
                                                     2000, 10, date(2026, 11, 2)),
                          school.teacher)
    enrollment_id = enrollments.enroll(conn, receptionist, amine, later, trial=True)
    enrollments.confirm_trial(conn, receptionist, enrollment_id)
    assert months(conn, receptionist, enrollment_id) == [
        ("2026-11-02", "2026-12-02", 2000, "active")]


def test_switch_keeps_the_running_month_in_the_old_group(conn, receptionist, school, amine):
    old = enrollments.enroll(conn, receptionist, amine, school.maths,
                             enrolled_on=date(2026, 10, 1))  # month 01/10 -> 01/11
    new = enrollments.switch(conn, receptionist, old, school.physics, date(2026, 10, 15))
    assert months(conn, receptionist, old) == [("2026-10-01", "2026-11-01", 3000, "active")]
    # The new group's first month starts when the old one ends, at the new group's price.
    assert months(conn, receptionist, new) == [("2026-11-01", "2026-12-01", 2500, "active")]


def test_switch_after_the_month_is_over(conn, receptionist, school, amine):
    old = enrollments.enroll(conn, receptionist, amine, school.maths,
                             enrolled_on=date(2026, 9, 10))  # month over on 10/10
    new = enrollments.switch(conn, receptionist, old, school.physics, date(2026, 10, 15))
    assert months(conn, receptionist, new) == [("2026-10-15", "2026-11-15", 2500, "active")]


def test_switch_with_no_month_running(conn, director, receptionist, school, amine):
    old = enrollments.enroll(conn, receptionist, amine, school.maths)
    subscriptions.cancel(conn, director, month_of(conn, director, old), "Erreur")
    new = enrollments.switch(conn, receptionist, old, school.physics)
    assert months(conn, receptionist, new) == [("2026-10-18", "2026-11-18", 2500, "active")]


def test_switched_trial_stays_free(conn, receptionist, school, amine):
    old = enrollments.enroll(conn, receptionist, amine, school.maths, trial=True)
    new = enrollments.switch(conn, receptionist, old, school.physics)
    assert months(conn, receptionist, new) == []
    enrollments.confirm_trial(conn, receptionist, new)
    assert months(conn, receptionist, new) == [("2026-10-18", "2026-11-18", 2500, "active")]


def test_switch_at_the_end_of_the_year_needs_no_new_month(conn, receptionist, school, amine,
                                                         monkeypatch):
    monkeypatch.setattr(dates, "today", lambda: date(2027, 6, 20))
    old = enrollments.enroll(conn, receptionist, amine, school.maths,
                             enrolled_on=date(2027, 6, 5))  # month 05/06 -> 05/07
    new = enrollments.switch(conn, receptionist, old, school.physics)
    assert months(conn, receptionist, new) == []  # 05/07 is after the year: no month


def test_leaving_keeps_the_month_as_it_is(conn, receptionist, in_maths):
    enrollments.leave(conn, receptionist, in_maths)
    assert months(conn, receptionist, in_maths) == [("2026-10-18", "2026-11-18", 3000, "active")]


def test_renewable_for_a_group(conn, receptionist, school, amine, in_maths, monkeypatch):
    yanis = students.create(conn, receptionist, StudentInput("Yanis", "Haddad"))
    registrations.register(conn, receptionist, yanis, school.level, 0)
    enrollments.enroll(conn, receptionist, yanis, school.physics,
                       enrolled_on=date(2026, 10, 1))  # over on 01/11
    monkeypatch.setattr(dates, "today", lambda: date(2026, 11, 15))
    everyone = subscriptions.renewable(conn, receptionist)
    assert [s.student_name for s in everyone] == ["Haddad Yanis", "Benali Amine"]  # over first
    maths = subscriptions.renewable(conn, receptionist, school.maths)
    assert [s.student_name for s in maths] == ["Benali Amine"]
