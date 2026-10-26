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
SEPT_END = date(2026, 9, 30)
OCT_END = date(2026, 10, 31)


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


class School:
    """Karim (60 % from 01/09) teaches A (6 000 DA) and B (12 000 DA); Samia (50 %) none."""

    def __init__(self, conn, ctx):
        self.conn, self.ctx = conn, ctx
        self.year = school_years.create(conn, ctx, "2026-2027", date(2026, 9, 1),
                                        date(2027, 6, 30))
        self.level = catalog.create(conn, ctx, "level", "4AM")
        self.karim = teachers.create(conn, ctx, TeacherInput("Karim Haddad"), 6000,
                                     date(2026, 9, 1))
        self.samia = teachers.create(conn, ctx, TeacherInput("Samia Rahmani"), 5000,
                                     date(2026, 9, 1))
        self.a = self.group("A", "Maths", 6000, self.karim)
        self.b = self.group("B", "Physique", 12000, self.karim)
        self.count = 0

    def group(self, name, subject, price, teacher):
        subject_id = catalog.create(self.conn, self.ctx, "subject", subject)
        return groups.create(self.conn, self.ctx, GroupInput(
            self.year, self.level, subject_id, name, price, 30, date(2026, 9, 1)), teacher)

    def pupils(self, group_id, n, on=date(2026, 9, 1)) -> list[int]:
        """n new students in the group from `on`: each gets a month from that day."""
        made = []
        for _ in range(n):
            self.count += 1
            student = students.create(self.conn, self.ctx,
                                      StudentInput(f"Élève{self.count}", "Test"))
            registrations.register(self.conn, self.ctx, student, self.level, 0)
            made.append(enrollments.enroll(self.conn, self.ctx, student, group_id,
                                           enrolled_on=on))
        return made


@pytest.fixture
def school(conn, director):
    return School(conn, director)


def rate_starts_late(conn, teacher_id: int, day: str) -> None:
    """Legacy data: the teacher's only rate starting after they took their first group, as
    DAYDA's did (rate from 21/10, his group from 18/10). The services refuse to make it now
    (test_academic: test_a_teacher_takes_a_group_only_from_a_day_with_a_rate); only a
    database from before that check holds it. Nothing else is bypassed: one rate row, its
    start moved, the overlap triggers still run."""
    [rate] = conn.execute("SELECT id FROM teacher_rates WHERE teacher_id = ?",
                          (teacher_id,)).fetchall()
    conn.execute("UPDATE teacher_rates SET valid_from = ? WHERE id = ?", (day, rate[0]))
    first_group = conn.execute("SELECT MIN(valid_from) FROM group_teachers WHERE teacher_id = ?",
                               (teacher_id,)).fetchone()[0]
    assert first_group < day  # the legacy shape itself, not another one


def last_audit(conn, action):
    row = conn.execute("SELECT * FROM audit_log WHERE action = ? ORDER BY id DESC",
                       (action,)).fetchone()
    return json.loads(row["new_value"])


# ----- the plan's example -----

def test_sixty_percent_of_two_groups(conn, director, school):
    """60 % of 60 000 plus 60 % of 120 000 = 108 000."""
    school.pupils(school.a, 10)  # 10 x 6 000
    school.pupils(school.b, 10)  # 10 x 12 000
    payout_id = payouts.build_draft(conn, director, school.karim, SEPT_END)
    p = payouts.get(conn, director, payout_id)
    assert (p.status, p.period_start, p.period_end, p.months) == (
        "draft", "2026-09-01", "2026-09-30", 20)
    assert (p.base_amount, p.amount_due) == (180_000, 108_000)
    assert [(line.group_title, line.revenue_basis, line.percentage_bp, line.amount,
             line.students) for line in payouts.lines(conn, director, payout_id)] == [
        ("A · Maths 4AM", 60_000, 6000, 36_000, 10),
        ("B · Physique 4AM", 120_000, 6000, 72_000, 10)]


def test_unpaid_months_count_too(conn, director, school):
    """Accrual: the full price of the month, whether the student paid or not."""
    [enrollment] = school.pupils(school.a, 1)
    student = enrollments.get(conn, director, enrollment).student_id
    payments.record(conn, director, student, 1000, "cash")  # 1 000 of 6 000 paid
    payout_id = payouts.build_draft(conn, director, school.karim, SEPT_END)
    assert payouts.get(conn, director, payout_id).amount_due == 3600


def test_a_line_is_rounded_down_once(conn, director, school):
    """3 months of 1 001 DA at 62,5 %: 3 003 x 62,5 % = 1 876,875 -> 1 876 (not 3 x 625)."""
    teachers.set_rate(conn, director, school.samia, 6250, date(2026, 9, 1))
    group = school.group("C", "Lecture", 1001, school.samia)
    school.pupils(group, 3)
    payout_id = payouts.build_draft(conn, director, school.samia, SEPT_END)
    assert payouts.get(conn, director, payout_id).amount_due == 1876


# ----- rates and teachers over time -----

def test_a_rate_change_leaves_old_payouts_unchanged(conn, director, school):
    school.pupils(school.a, 2)  # September: 12 000
    september = payouts.build_draft(conn, director, school.karim, SEPT_END)
    payouts.approve(conn, director, september)
    teachers.set_rate(conn, director, school.karim, 5000, date(2026, 10, 1))
    school.pupils(school.a, 1, on=date(2026, 10, 5))  # October: 6 000 at 50 %
    october = payouts.build_draft(conn, director, school.karim, OCT_END)
    assert payouts.get(conn, director, september).amount_due == 7200  # 60 %, untouched
    p = payouts.get(conn, director, october)
    assert (p.period_start, p.amount_due) == ("2026-10-05", 3000)
    [line] = payouts.lines(conn, director, october)
    assert line.percentage_bp == 5000


def test_a_rate_that_changed_gives_two_lines_for_one_group(conn, director, school):
    teachers.set_rate(conn, director, school.karim, 5000, date(2026, 10, 1))
    school.pupils(school.a, 1)  # 01/09 at 60 %
    school.pupils(school.a, 1, on=date(2026, 10, 2))  # 02/10 at 50 %
    payout_id = payouts.build_draft(conn, director, school.karim, OCT_END)
    assert sorted((line.percentage_bp, line.amount)
                  for line in payouts.lines(conn, director, payout_id)) == [
        (5000, 3000), (6000, 3600)]
    assert payouts.get(conn, director, payout_id).amount_due == 6600


def test_a_teacher_change_splits_by_the_months_first_day(conn, director, school):
    school.pupils(school.a, 1, on=date(2026, 10, 5))  # Karim's
    groups.change_teacher(conn, director, school.a, school.samia, date(2026, 10, 10))
    school.pupils(school.a, 1, on=date(2026, 10, 15))  # Samia's
    karim = payouts.build_draft(conn, director, school.karim, OCT_END)
    samia = payouts.build_draft(conn, director, school.samia, OCT_END)
    assert (payouts.get(conn, director, karim).amount_due,
            payouts.get(conn, director, samia).amount_due) == (3600, 3000)


def test_no_rate_on_the_months_first_day(conn, director, school):
    teacher = teachers.create(conn, director, TeacherInput("Nadia Kaci"), 5000,
                              date(2026, 9, 1))
    group = school.group("D", "Anglais", 2000, teacher)
    school.pupils(group, 1)  # 01/09
    rate_starts_late(conn, teacher, "2026-10-01")  # before her rate starts
    with pytest.raises(BusinessRuleError) as caught:
        payouts.build_draft(conn, director, teacher, SEPT_END)
    assert caught.value.message == t["payout.no_rate"].format(teacher="Nadia Kaci",
                                                              date="01/09/2026")


def test_a_rate_set_to_start_too_late_is_fixed_from_the_teachers_page(conn, director, school):
    """DAYDA's case: his rate saved from 21/09 while his group's first month starts on 19/09.
    The draft is refused until the same 40 % starts on his arrival (01/09)."""
    dayda = teachers.create(conn, director, TeacherInput("DAYDA", hire_date=date(2026, 9, 1)),
                            4000, date(2026, 9, 1))
    group = school.group("D", "Anglais", 2000, dayda)
    school.pupils(group, 1, on=date(2026, 9, 19))
    rate_starts_late(conn, dayda, "2026-09-21")
    with pytest.raises(BusinessRuleError) as caught:
        payouts.build_draft(conn, director, dayda, SEPT_END)
    assert caught.value.message == t["payout.no_rate"].format(teacher="DAYDA",
                                                              date="19/09/2026")
    teachers.update(conn, director, dayda, TeacherInput("DAYDA", hire_date=date(2026, 9, 1)),
                    4000, date(2026, 9, 1))
    p = payouts.get(conn, director, payouts.build_draft(conn, director, dayda, SEPT_END))
    assert (p.months, p.base_amount, p.amount_due) == (1, 2000, 800)


def test_a_rate_change_builds_the_teachers_draft_again(conn, director, school):
    school.pupils(school.a, 1)  # 01/09, 6 000 DA at 60 %
    payouts.build_draft(conn, director, school.karim, SEPT_END)
    first = payouts.listing(conn, director)[0].id
    teachers.set_rate(conn, director, school.karim, 5000, date(2026, 9, 1))  # corrected
    [p] = payouts.listing(conn, director)
    assert (p.status, p.amount_due) == ("draft", 3000)  # at the rate now set
    assert last_audit(conn, "payout.build")["replaced"] == first  # never silently
    teachers.set_rate(conn, director, school.karim, 0, date(2026, 9, 1))  # nothing to pay
    assert payouts.listing(conn, director) == []
    assert last_audit(conn, "payout.delete") == {"reason": "rate_changed"}


@pytest.mark.parametrize("status", ["approved", "paid"])
def test_approved_and_paid_payouts_never_change_with_the_rates(conn, director, school, status):
    """What would change the months it paid is refused; the rest leaves it as it is."""
    school.pupils(school.a, 1)  # 01/09, 6 000 DA at 60 %
    payout_id = payouts.build_draft(conn, director, school.karim, SEPT_END)
    payouts.approve(conn, director, payout_id)
    if status == "paid":
        payouts.mark_paid(conn, director, payout_id, "cash")

    def kept():
        p = payouts.get(conn, director, payout_id)
        return (p.status, p.base_amount, p.amount_due, p.amount_paid,
                [(x.revenue_basis, x.percentage_bp, x.amount)
                 for x in payouts.lines(conn, director, payout_id)])

    before = kept()
    for bp, day in ((5000, date(2026, 9, 1)),  # corrected on its own start day
                    (5000, date(2026, 8, 15))):  # another percentage from an earlier day
        with pytest.raises(BusinessRuleError) as caught:
            teachers.set_rate(conn, director, school.karim, bp, day)
        assert caught.value.message == t["rate.locked"]
    teachers.set_rate(conn, director, school.karim, 6000, date(2026, 8, 15))  # same, earlier
    teachers.set_rate(conn, director, school.karim, 7000, date(2026, 10, 1))  # a new rate
    assert kept() == before
    assert [(r.percentage_bp, r.valid_from) for r in teachers.rates(conn, director,
                                                                    school.karim)] == [
        (7000, "2026-10-01"), (6000, "2026-08-15")]


def test_a_rate_from_after_the_drafts_months_leaves_it(conn, director, school):
    school.pupils(school.a, 1)
    draft = payouts.build_draft(conn, director, school.karim, SEPT_END)
    teachers.set_rate(conn, director, school.karim, 7000, date(2026, 10, 1))
    [p] = payouts.listing(conn, director)
    assert (p.id, p.amount_due) == (draft, 3600)


# ----- drafts: rebuilt, never counted twice -----

def test_rebuilding_never_counts_a_month_twice(conn, director, school):
    school.pupils(school.a, 2)
    first = payouts.build_draft(conn, director, school.karim, SEPT_END)
    school.pupils(school.a, 1, on=date(2026, 9, 10))
    assert payouts.stale(conn, director, first) == 1
    second = payouts.rebuild(conn, director, first)
    with pytest.raises(NotFound):  # the old draft is gone
        payouts.get(conn, director, first)
    p = payouts.get(conn, director, second)
    assert (p.months, p.amount_due) == (3, 10_800)
    assert payouts.stale(conn, director, second) == 0
    assert conn.execute("SELECT COUNT(*) FROM payout_line_charges").fetchone()[0] == 3
    assert [x.id for x in payouts.listing(conn, director)] == [second]  # one draft


def test_building_again_replaces_the_teachers_draft(conn, director, school):
    school.pupils(school.a, 1)
    first = payouts.build_draft(conn, director, school.karim, SEPT_END)
    second = payouts.build_draft(conn, director, school.karim, OCT_END)
    assert [x.id for x in payouts.listing(conn, director)] == [second]
    assert last_audit(conn, "payout.build")["replaced"] == first


def test_a_month_renewed_late_goes_into_the_next_payout(conn, director, school):
    """September is approved; a month starting 20/09 is entered afterwards: October's payout
    takes it, its period starting 20/09."""
    school.pupils(school.a, 1)
    september = payouts.build_draft(conn, director, school.karim, SEPT_END)
    payouts.approve(conn, director, september)
    school.pupils(school.a, 1, on=date(2026, 9, 20))  # backdated entry
    assert payouts.stale(conn, director, september) == 1
    october = payouts.build_draft(conn, director, school.karim, OCT_END)
    p = payouts.get(conn, director, october)
    assert (p.period_start, p.months, p.amount_due) == ("2026-09-20", 1, 3600)


def test_a_cancelled_month_is_not_paid(conn, director, school):
    [enrollment] = school.pupils(school.a, 1)
    [month] = subscriptions.for_enrollment(conn, director, enrollment)
    subscriptions.cancel(conn, director, month.id, "Erreur")
    with pytest.raises(BusinessRuleError) as caught:
        payouts.build_draft(conn, director, school.karim, SEPT_END)
    assert caught.value.message == t["payout.nothing"].format(teacher="Karim Haddad",
                                                              date="30/09/2026")


def test_an_approved_month_can_no_longer_be_cancelled(conn, director, school):
    [enrollment] = school.pupils(school.a, 1)
    payouts.approve(conn, director, payouts.build_draft(conn, director, school.karim,
                                                        SEPT_END))
    [month] = subscriptions.for_enrollment(conn, director, enrollment)
    with pytest.raises(BusinessRuleError) as caught:
        subscriptions.cancel(conn, director, month.id, "Erreur")
    assert caught.value.message == t["subscription.in_payout"]


def test_a_month_cancelled_leaves_the_draft(conn, director, school):
    """Two months of A (6 000 each) and one of B (12 000) in a draft: cancelling one month
    of A works the line and the totals out again, as building the draft again would."""
    first, _second = school.pupils(school.a, 2)
    school.pupils(school.b, 1)
    draft = payouts.build_draft(conn, director, school.karim, SEPT_END)
    assert payouts.get(conn, director, draft).amount_due == 14400
    [month] = subscriptions.for_enrollment(conn, director, first)
    assert month.can_cancel  # a draft does not hold a month
    subscriptions.cancel(conn, director, month.id, "Erreur")
    p = payouts.get(conn, director, draft)
    assert (p.status, p.base_amount, p.amount_due, p.months) == ("draft", 18000, 10800, 2)
    assert sorted((line.revenue_basis, line.amount, line.months)
                  for line in payouts.lines(conn, director, draft)) == [
        (6000, 3600, 1), (12000, 7200, 1)]
    assert payouts.stale(conn, director, draft) == 0
    payouts.approve(conn, director, draft)  # the totals still match its lines
    assert last_audit(conn, "payout.drop_month") == {
        "charge_id": month.charge_id, "amount_due": 10800, "deleted": False}


def test_the_last_month_cancelled_deletes_the_draft(conn, director, school):
    [enrollment] = school.pupils(school.a, 1)
    draft = payouts.build_draft(conn, director, school.karim, SEPT_END)
    [month] = subscriptions.for_enrollment(conn, director, enrollment)
    subscriptions.cancel(conn, director, month.id, "Erreur")
    with pytest.raises(NotFound):
        payouts.get(conn, director, draft)
    assert last_audit(conn, "payout.drop_month")["deleted"] is True


def test_the_same_period_twice(conn, director, school):
    school.pupils(school.a, 1)
    september = payouts.build_draft(conn, director, school.karim, SEPT_END)
    payouts.approve(conn, director, september)
    school.pupils(school.a, 1)  # also from 01/09, entered late
    with pytest.raises(BusinessRuleError) as caught:
        payouts.build_draft(conn, director, school.karim, SEPT_END)
    assert caught.value.message == t["payout.same_period"].format(start="01/09/2026",
                                                                  end="30/09/2026")
    payouts.build_draft(conn, director, school.karim, TODAY)  # another end: fine


def test_until_at_most_the_end_of_this_month(conn, director, school):
    school.pupils(school.a, 1)
    with pytest.raises(ValidationError):
        payouts.build_draft(conn, director, school.karim, date(2026, 11, 1))
    payouts.build_draft(conn, director, school.karim, OCT_END)


def test_delete_a_draft(conn, director, school):
    school.pupils(school.a, 1)
    payout_id = payouts.build_draft(conn, director, school.karim, SEPT_END)
    payouts.delete_draft(conn, director, payout_id)
    assert payouts.listing(conn, director) == []
    assert [d.months for d in payouts.due(conn, director, SEPT_END)] == [1]  # owed again


# ----- approving, paying, locking -----

def test_approve_then_pay(conn, director, school):
    school.pupils(school.a, 1)
    payout_id = payouts.build_draft(conn, director, school.karim, SEPT_END)
    with pytest.raises(BusinessRuleError):
        payouts.mark_paid(conn, director, payout_id, "cash")  # approve first
    payouts.approve(conn, director, payout_id)
    with pytest.raises(ValidationError):
        payouts.mark_paid(conn, director, payout_id, "bitcoin")
    assert payouts.mark_paid(conn, director, payout_id, "cash") == "PE2026-00001"
    p = payouts.get(conn, director, payout_id)
    assert (p.status, p.amount_paid, p.method, p.paid_by, p.approved_by) == (
        "paid", 3600, "cash", "directeur", "directeur")
    with pytest.raises(BusinessRuleError):
        payouts.mark_paid(conn, director, payout_id, "cash")


def test_a_locked_payout_refuses_changes(conn, director, school):
    school.pupils(school.a, 1)
    payout_id = payouts.build_draft(conn, director, school.karim, SEPT_END)
    payouts.approve(conn, director, payout_id)
    for action in (payouts.rebuild, payouts.delete_draft, payouts.approve):
        with pytest.raises(BusinessRuleError) as caught:
            action(conn, director, payout_id)
        assert caught.value.message == t["payout.not_draft"]


def test_payout_numbers_are_sequential(conn, director, school):
    school.pupils(school.a, 1)
    school.pupils(school.a, 1, on=date(2026, 10, 1))
    numbers = []
    for until in (SEPT_END, OCT_END):
        payout_id = payouts.build_draft(conn, director, school.karim, until)
        payouts.approve(conn, director, payout_id)
        numbers.append(payouts.mark_paid(conn, director, payout_id, "cash"))
    assert numbers == ["PE2026-00001", "PE2026-00002"]


def test_the_director_only(conn, director, desk, school):
    school.pupils(school.a, 1)
    with pytest.raises(PermissionDenied):
        payouts.build_draft(conn, desk, school.karim, SEPT_END)
    with pytest.raises(PermissionDenied):
        payouts.listing(conn, desk)
    with pytest.raises(PermissionDenied):
        payouts.due(conn, desk, SEPT_END)


# ----- the monthly run -----

def test_the_monthly_run_prepares_every_teacher(conn, director, school):
    school.pupils(school.a, 2)
    samias = school.group("C", "Lecture", 2000, school.samia)
    school.pupils(samias, 1)
    nadia = teachers.create(conn, director, TeacherInput("Nadia Kaci"), 5000, date(2026, 9, 1))
    school.pupils(school.group("D", "Anglais", 2000, nadia), 1)
    rate_starts_late(conn, nadia, "2026-10-01")  # no rate in September
    due = payouts.due(conn, director, SEPT_END)
    assert [(d.teacher, d.months, d.revenue) for d in due] == [
        ("Karim Haddad", 2, 12_000), ("Nadia Kaci", 1, 2000), ("Samia Rahmani", 1, 2000)]
    built, refused = payouts.run(conn, director, SEPT_END)
    assert sorted(payouts.get(conn, director, p).teacher for p in built) == [
        "Karim Haddad", "Samia Rahmani"]
    assert refused == [t["payout.no_rate"].format(teacher="Nadia Kaci", date="01/09/2026")]
    assert {d.teacher: d.draft_id is not None
            for d in payouts.due(conn, director, SEPT_END)} == {"Nadia Kaci": False}


def test_breakdown_per_student(conn, director, school):
    school.pupils(school.a, 2)
    payout_id = payouts.build_draft(conn, director, school.karim, SEPT_END)
    months = payouts.months(conn, director, payout_id)
    assert [(m.student_name, m.amount, m.share) for m in months] == [
        ("Test Élève1", 6000, 3600), ("Test Élève2", 6000, 3600)]
    assert months[0].description == "Abonnement A du 01/09/2026 au 01/10/2026"


# ----- the cash of the day and the audit trail -----

def test_cash_report_shows_teachers_paid_to_the_director_only(conn, director, desk, school):
    [enrollment] = school.pupils(school.a, 1)
    student = enrollments.get(conn, director, enrollment).student_id
    payments.record(conn, desk, student, 6000, "cash")
    payout_id = payouts.build_draft(conn, director, school.karim, SEPT_END)
    payouts.approve(conn, director, payout_id)
    payouts.mark_paid(conn, director, payout_id, "cash")
    report = payments.cash_report(conn, director, TODAY)
    assert (report.paid_to_teachers, report.cash_in_drawer) == (3600, 2400)
    assert payments.cash_report(conn, desk, TODAY).payouts == ()  # teacher pay is not theirs


def test_every_step_is_in_the_audit_log(conn, director, school):
    school.pupils(school.a, 1)
    first = payouts.build_draft(conn, director, school.karim, SEPT_END)
    payout_id = payouts.rebuild(conn, director, first)
    payouts.approve(conn, director, payout_id)
    payouts.mark_paid(conn, director, payout_id, "transfer")
    actions = [row[0] for row in conn.execute(
        "SELECT action FROM audit_log WHERE entity_name = 'teacher_payouts' ORDER BY id")]
    assert actions == ["payout.build", "payout.build", "payout.approve", "payout.pay"]


# ----- the slip -----

def test_payout_slip(conn, director, school, tmp_path):
    school.pupils(school.a, 10)
    school.pupils(school.b, 10)
    payout_id = payouts.build_draft(conn, director, school.karim, SEPT_END)
    draft = printing.payout_slip_content(conn, director, payout_id)
    assert (draft.number, draft.stamp) == ("BROUILLON", "BROUILLON")
    payouts.approve(conn, director, payout_id)
    payouts.mark_paid(conn, director, payout_id, "cash")
    slip = printing.payout_slip_content(conn, director, payout_id)
    assert (slip.number, slip.stamp, slip.total, slip.copy_mark) == (
        "PE2026-00001", "PAYÉ", "108 000 DA", "")
    settings.save_school(conn, director, "École Ennour", "", "", "08:00", "20:00",
                         receipt_header="Agrément n° 12")
    assert printing.payout_slip_content(conn, director, payout_id).school.header == (
        "Agrément n° 12")
    assert dict(slip.details)["Enseignant"] == "Karim Haddad"
    assert dict(slip.details)["Versé"] == "le 18/10/2026, en Espèces, par directeur"
    assert slip.group_rows == [
        ["A · Maths 4AM", "10", "10", "60 000 DA", "60 %", "36 000 DA"],
        ["B · Physique 4AM", "10", "10", "120 000 DA", "60 %", "72 000 DA"]]
    assert len(slip.detail_rows) == 20
    assert slip.detail_rows[0] == ["Test Élève1", "A · Maths 4AM", "01/09/2026", "6 000 DA",
                                   "60 %", "3 600 DA"]
    path = printing.payout_slip(conn, director, payout_id, tmp_path)
    assert path.name == "paiement-enseignant_karim-haddad_2026-09-30.pdf"
    assert path.read_bytes().startswith(b"%PDF")
    assert printing.payout_slip_content(conn, director, payout_id).copy_mark == "DUPLICATA"


def test_payout_slip_is_the_directors(conn, director, desk, school):
    school.pupils(school.a, 1)
    payout_id = payouts.build_draft(conn, director, school.karim, SEPT_END)
    with pytest.raises(PermissionDenied):
        printing.payout_slip_content(conn, desk, payout_id)
