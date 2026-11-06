"""Refunds, step 2: the sessions left in a month, from the timetable minus the holidays.

September 2026 (a month from 01/09 to 01/10): Mondays 7, 14, 21, 28; Wednesdays 2, 9, 16,
23, 30."""

import re
import sqlite3
from datetime import date, timedelta

import pytest

from tadris.core import dates
from tadris.core.errors import BusinessRuleError, NotFound
from tadris.db.connection import connect
from tadris.db.migrate import _files, migrate
from tadris.domain.models import GroupInput, SessionsLeft, SlotInput, StudentInput, TeacherInput
from tadris.services import (
    attendance,
    auth,
    catalog,
    enrollments,
    groups,
    holidays,
    payments,
    refunds,
    registrations,
    rooms,
    school_years,
    sessions,
    students,
    subscriptions,
    teachers,
    timetable,
)
from tadris.services.refunds import (
    count_left,
    first_unused_day,
    last_day_open,
    until_closure,
    value_of,
)

START, END = date(2026, 9, 1), date(2026, 10, 1)
SINCE_AUGUST = date(2026, 8, 1)
MONDAY, WEDNESDAY, THURSDAY = 1, 3, 4


def left(counted_from, slots, holidays=(), price=6000, **bounds) -> SessionsLeft:
    return count_left(START, END, price, counted_from, slots, holidays, **bounds)


MON_WED = [(MONDAY, SINCE_AUGUST, None), (WEDNESDAY, SINCE_AUGUST, None)]


# ----- the calculation (pure) -----

def test_a_month_not_started_has_every_session_left():
    assert left(START, MON_WED) == SessionsLeft("2026-09-01", total=9, left=9, value=6000)
    assert left(date(2026, 8, 20), MON_WED).value == 6000  # left the group before it


def test_counted_from_the_first_day_not_used():
    """From Wednesday 16 on (that day's session is left): 16, 21, 23, 28, 30."""
    counted = left(date(2026, 9, 16), MON_WED)
    assert (counted.total, counted.left) == (9, 5)
    assert counted.value == 3333  # 6 000 × 5 ÷ 9 = 3 333.33, rounded down


def test_holidays_are_left_out_of_the_month_and_of_what_is_left():
    """21 to 25 off: Monday 21 and Wednesday 23 go; left from the 16th: 16, 28, 30."""
    counted = left(date(2026, 9, 16), MON_WED, [(date(2026, 9, 21), date(2026, 9, 25))])
    assert (counted.total, counted.left, counted.value) == (7, 3, 2571)


def test_a_timetable_changed_during_the_month():
    """Mondays until the 15th, then Thursdays: 7, 14, then 17, 24."""
    slots = [(MONDAY, SINCE_AUGUST, date(2026, 9, 15)), (THURSDAY, date(2026, 9, 15), None)]
    counted = left(date(2026, 9, 16), slots)
    assert (counted.total, counted.left, counted.value) == (4, 2, 3000)


def test_two_slots_on_a_day_are_two_sessions():
    slots = [(MONDAY, SINCE_AUGUST, None), (MONDAY, SINCE_AUGUST, None)]
    counted = left(date(2026, 9, 21), slots)
    assert (counted.total, counted.left, counted.value) == (8, 4, 3000)


def test_a_month_over_has_nothing_left():
    counted = left(END, MON_WED)
    assert (counted.left, counted.value) == (0, 0)


def test_a_month_without_a_session():
    """No timetable, or all of it on holiday: worth its price if none of it was used
    (counted from its first day or before), else nothing (REVIEW_FIXES, decision 2)."""
    assert left(START, []) == SessionsLeft("2026-09-01", total=0, left=0, value=6000)
    assert left(date(2026, 8, 20), []).value == 6000
    assert left(date(2026, 9, 10), []).value == 0
    all_off = [(date(2026, 8, 30), date(2026, 10, 5))]
    assert left(START, MON_WED, all_off) == SessionsLeft("2026-09-01", 0, 0, 6000)
    assert left(date(2026, 9, 5), [], group_start=date(2026, 9, 10)).value == 6000
    assert left(date(2026, 9, 12), [], group_start=date(2026, 9, 10)).value == 0


def test_after_a_closure_each_slot_kept_keeps_its_own_dates():
    """Closed on Wednesday 16/09. Before: Mondays 7, 14, and a Wednesday slot over on the
    10th (2, 9). Kept: Mondays with no end, Thursdays planned from 24/09 to 08/10. After:
    Mondays 21, 28 and Thursday 24: 3 left of 7."""
    closed = date(2026, 9, 16)
    timetable_then = [(MONDAY, SINCE_AUGUST, closed),
                      (WEDNESDAY, SINCE_AUGUST, date(2026, 9, 10))]
    kept = [(MONDAY, SINCE_AUGUST, None), (THURSDAY, date(2026, 9, 24), date(2026, 10, 8))]
    counted = left(closed, until_closure(timetable_then, closed, kept))
    assert (counted.total, counted.left, counted.value) == (7, 3, 2571)
    october = count_left(END, date(2026, 11, 1), 6000, closed,
                         until_closure(timetable_then, closed, kept), [])
    assert (october.total, october.left) == (5, 5)  # Mondays 5 to 26, Thursday 1 (not the 8th)


def test_no_session_before_the_group_starts_or_after_its_year():
    assert left(START, MON_WED, group_start=date(2026, 9, 10)).total == 6  # 14 on
    assert left(START, MON_WED, year_end=date(2026, 9, 20)).total == 5  # 2, 7, 9, 14, 16


def test_the_value_is_rounded_down_to_the_dinar():
    assert value_of(3000, 4, 9) == 1333
    assert value_of(3000, 9, 9) == 3000
    assert value_of(3000, 0, 0) == 0


def test_the_first_day_not_used():
    """The day after the last day, or the last day itself when it may not have been used."""
    last = date(2026, 9, 14)
    assert first_unused_day(last, open_last_day=False) == date(2026, 9, 15)
    assert first_unused_day(last, open_last_day=True) == last


def test_a_last_day_that_may_not_have_been_used():
    """The school closed the group that day, or the place ended on its entry day."""
    assert last_day_open(True, "2026-09-16", "2026-09-01")
    assert last_day_open(False, "2026-10-01", "2026-10-01")  # left before it started
    assert not last_day_open(False, "2026-09-10", "2026-09-01")


def test_sessions_of_the_first_day_already_given_are_used():
    """Two Monday sessions; counted from Monday 14, one of them already given."""
    two = [(MONDAY, SINCE_AUGUST, None), (MONDAY, SINCE_AUGUST, None)]
    counted = left(date(2026, 9, 14), two, used=1)
    assert (counted.total, counted.left, counted.value) == (8, 5, 3750)  # 14 (1), 21, 28
    assert left(date(2026, 9, 14), two, used=5).left == 4  # never more than that day has
    assert left(date(2026, 9, 15), two, used=1).left == 4  # nothing on the 15th to take off


# ----- read from the database -----

class Today:
    def __init__(self, day: date):
        self.day = day

    def __call__(self) -> date:
        return self.day


@pytest.fixture
def today(monkeypatch):
    clock = Today(date(2026, 9, 1))
    monkeypatch.setattr(dates, "today", clock)
    return clock


class School:
    pass


@pytest.fixture
def school(conn, today):
    """Group A (6 000 DA a month) meets on Mondays from 01/09; Amine is in it from 01/09,
    his first month runs to 01/10."""
    ctx = auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")
    year = school_years.create(conn, ctx, "2026-2027", date(2026, 9, 1), date(2027, 6, 30))
    s = School()
    level = catalog.create(conn, ctx, "level", "4AM")
    subject = catalog.create(conn, ctx, "subject", "Maths")
    teacher = teachers.create(conn, ctx, TeacherInput("Karim Haddad"), 6000, date(2026, 9, 1))
    group = groups.create(conn, ctx, GroupInput(year, level, subject, "A", 6000, 30,
                                                date(2026, 9, 1)), teacher)
    room = rooms.create(conn, ctx, "Salle 1", 20)
    slot = timetable.add_slot(conn, ctx, SlotInput(group, room, MONDAY, "17:00", "18:30",
                                                   valid_from=date(2026, 9, 1)))
    amine = students.create(conn, ctx, StudentInput("Amine", "Benali"))
    registrations.register(conn, ctx, amine, level, 0)
    enrollment = enrollments.enroll(conn, ctx, amine, group, enrolled_on=date(2026, 9, 1))
    [month] = subscriptions.for_enrollment(conn, ctx, enrollment)
    s.ctx, s.group, s.enrollment, s.month = ctx, group, enrollment, month.id
    s.level, s.teacher = level, teacher
    s.year, s.room, s.slot, s.student = year, room, slot, amine
    return s


def gone(conn, school, today, day=date(2026, 9, 16)) -> None:
    """Amine's last day is the day before `day`: counted from `day` on."""
    today.day = day
    enrollments.leave(conn, school.ctx, school.enrollment, day - timedelta(days=1))


def test_still_in_the_group_nothing_is_counted(conn, school, today):
    today.day = date(2026, 9, 16)
    with pytest.raises(BusinessRuleError, match="A · Maths 4AM"):
        refunds._sessions_left(conn, school.month)


def test_left_the_group_counted_from_the_day_after(conn, school, today):
    """Last day the 10th: counted from the 11th (14, 21, 28), whatever the request's day."""
    today.day = date(2026, 9, 10)
    enrollments.leave(conn, school.ctx, school.enrollment, date(2026, 9, 10))
    today.day = date(2026, 9, 25)
    counted = refunds._sessions_left(conn, school.month)
    assert counted == SessionsLeft("2026-09-11", total=4, left=3, value=4500)


def test_holidays_from_the_database(conn, school, today):
    holidays.create(conn, school.ctx, "Mawlid", date(2026, 9, 28))
    gone(conn, school, today)
    counted = refunds._sessions_left(conn, school.month)
    assert (counted.total, counted.left, counted.value) == (3, 1, 2000)


def test_absences_are_used_sessions(conn, school, today):
    """Absent on the 7th and the 14th: they still count as used, like any session before the
    first day not used."""
    today.day = date(2026, 9, 7)
    sessions.generate_in(conn)  # Mondays 7 and 14
    today.day = date(2026, 9, 14)
    held = [row[0] for row in conn.execute("SELECT id FROM sessions ORDER BY date")]
    assert len(held) == 2
    for session_id in held:
        attendance.save(conn, school.ctx, session_id, {school.enrollment: "absent"})
    gone(conn, school, today)
    counted = refunds._sessions_left(conn, school.month)
    assert (counted.total, counted.left, counted.value) == (4, 2, 3000)


def test_an_unknown_month(conn, school):
    with pytest.raises(NotFound):
        refunds._sessions_left(conn, 999)


# ----- a group closed by the school (migration 0022) -----
# Closed on Wednesday 16/09: Amine's last day is the 16th, with no session that day, so
# counted from the 16th. September and an October paid ahead (Mondays 5, 12, 19, 26) keep the
# sessions the school no longer gives.

def october_paid(conn, school, today) -> int:
    """October renewed and both months paid (12 000), before the closure."""
    today.day = date(2026, 9, 2)
    october = subscriptions.renew(conn, school.ctx, school.month)
    payments.record(conn, school.ctx, school.student, 12000, "cash")
    return october


def counts(conn, school, october) -> tuple[tuple, tuple]:
    return tuple((c.total, c.left, c.value)
                 for c in (refunds._sessions_left(conn, school.month),
                           refunds._sessions_left(conn, october)))


def kept_week(conn, group) -> list[tuple]:
    """(closing day, weekday) of the slots each closure of the group kept, in order."""
    return [tuple(r) for r in conn.execute(
        "SELECT c.closed_on, s.weekday FROM group_closure_slots s "
        "JOIN group_closures c ON c.id = s.closure_id WHERE c.group_id = ? ORDER BY s.id",
        (group,))]


def closed_on(conn, group) -> str | None:
    """The day of the closure the group is under."""
    return conn.execute(
        "SELECT c.closed_on FROM class_groups g LEFT JOIN group_closures c "
        "ON c.id = g.closure_id WHERE g.id = ?", (group,)).fetchone()[0]


def test_a_group_closed_during_the_month(conn, school, today):
    """September: 7, 14 held, 21 and 28 not given: 3 000. October: all four: 6 000."""
    october = october_paid(conn, school, today)
    today.day = date(2026, 9, 16)
    groups.close(conn, school.ctx, school.group)
    assert closed_on(conn, school.group) == "2026-09-16"
    assert kept_week(conn, school.group) == [("2026-09-16", MONDAY)]
    assert counts(conn, school, october) == ((4, 2, 3000), (4, 4, 6000))
    assert refunds._sessions_left(conn, school.month).counted_from == "2026-09-16"


def monday_session(conn, school, today) -> int:
    """The forecast of Monday 14/09, generated on the 14th."""
    today.day = date(2026, 9, 14)
    sessions.generate_in(conn)
    return conn.execute("SELECT id FROM sessions WHERE date = '2026-09-14'").fetchone()[0]


def test_closed_on_a_monday_before_its_session(conn, school, today):
    """Closed on Monday 14/09 in the morning: that evening's session is never given, so it is
    left (14, 21, 28 of four: 4 500)."""
    monday_session(conn, school, today)
    groups.close(conn, school.ctx, school.group)
    counted = refunds._sessions_left(conn, school.month)
    assert counted == SessionsLeft("2026-09-14", total=4, left=3, value=4500)


def test_closed_on_a_monday_after_its_session(conn, school, today):
    """Closed on Monday 14/09 in the evening, the session held (attendance taken): used (21,
    28 of four: 3 000)."""
    session = monday_session(conn, school, today)
    attendance.save(conn, school.ctx, session, {school.enrollment: "present"})
    groups.close(conn, school.ctx, school.group)
    counted = refunds._sessions_left(conn, school.month)
    assert counted == SessionsLeft("2026-09-14", total=4, left=2, value=3000)


def test_closed_between_two_sessions_of_the_same_day(conn, school, today):
    """Mondays at 09:00 and 17:00; closed at noon on the 14th, the morning one held: the
    evening one, cancelled by the closure, is left with 21 and 28 (5 of 8: 3 750)."""
    timetable.add_slot(conn, school.ctx, SlotInput(school.group, school.room, MONDAY, "09:00",
                                                   "10:30", valid_from=date(2026, 9, 1)))
    today.day = date(2026, 9, 14)
    sessions.generate_in(conn)
    morning = conn.execute("SELECT id FROM sessions WHERE date = '2026-09-14' "
                           "AND start_time = '09:00'").fetchone()[0]
    attendance.save(conn, school.ctx, morning, {school.enrollment: "present"})
    groups.close(conn, school.ctx, school.group)
    counted = refunds._sessions_left(conn, school.month)
    assert counted == SessionsLeft("2026-09-14", total=8, left=5, value=3750)


def test_left_on_their_own_the_last_day_is_used(conn, school, today):
    """Left on Monday 14/09, the group still running: that day is the last one used, its
    session given or not."""
    monday_session(conn, school, today)
    enrollments.leave(conn, school.ctx, school.enrollment, date(2026, 9, 14))
    assert refunds._sessions_left(conn, school.month).counted_from == "2026-09-15"


def test_a_timetable_changed_before_the_closure(conn, school, today):
    """Mondays until the 10th, then Thursdays: the closure keeps Thursday, never the Monday
    slot over before it. September: 7, 10, then 17, 24 (2 left: 3 000); October: Thursdays
    1, 8, 15, 22, 29 (6 000)."""
    october = october_paid(conn, school, today)
    today.day = date(2026, 9, 7)
    sessions.generate_in(conn)  # the 7th is kept once past: the change splits the slot
    today.day = date(2026, 9, 10)
    timetable.update_slot(conn, school.ctx, school.slot,
                          SlotInput(school.group, school.room, THURSDAY, "17:00", "18:30"))
    today.day = date(2026, 9, 16)
    groups.close(conn, school.ctx, school.group)
    assert kept_week(conn, school.group) == [("2026-09-16", THURSDAY)]
    assert counts(conn, school, october) == ((4, 2, 3000), (5, 5, 6000))


def test_a_slot_over_before_the_closure_is_not_revived(conn, school, today):
    """A Wednesday slot ended on the 5th: September has Wednesday 2, Mondays 7, 14, then 21,
    28 (2 of 5: 2 400); October has Mondays only (6 000)."""
    wednesday = timetable.add_slot(conn, school.ctx, SlotInput(
        school.group, school.room, WEDNESDAY, "17:00", "18:30", valid_from=date(2026, 9, 1)))
    october = october_paid(conn, school, today)
    today.day = date(2026, 9, 5)
    timetable.remove_slot(conn, school.ctx, wednesday)
    today.day = date(2026, 9, 16)
    groups.close(conn, school.ctx, school.group)
    assert kept_week(conn, school.group) == [("2026-09-16", MONDAY)]
    assert counts(conn, school, october) == ((5, 2, 2400), (4, 4, 6000))


def test_a_timetable_changed_the_same_day_as_the_closure(conn, school, today):
    """Changed to Thursday on the 16th, then closed: the Thursday slot, removed by the
    closure (not started, no session), is the week kept; the Monday slot, over before it,
    is not. September: 7, 14, then 17, 24 (3 000); October: five Thursdays (6 000)."""
    october = october_paid(conn, school, today)
    today.day = date(2026, 9, 7)
    sessions.generate_in(conn)
    today.day = date(2026, 9, 16)
    timetable.update_slot(conn, school.ctx, school.slot,
                          SlotInput(school.group, school.room, THURSDAY, "17:00", "18:30"))
    groups.close(conn, school.ctx, school.group)
    assert conn.execute("SELECT COUNT(*) FROM timetable_slots WHERE weekday = ?",
                        (THURSDAY,)).fetchone()[0] == 0  # removed by the closure
    assert kept_week(conn, school.group) == [("2026-09-16", THURSDAY)]
    assert counts(conn, school, october) == ((4, 2, 3000), (5, 5, 6000))


def test_a_slot_planned_to_start_later_is_kept(conn, school, today):
    """A Wednesday slot planned from 23/09, the group closed on the 16th: kept from its own
    first day. September: Mondays 7, 14 used, then 21, 28 and Wednesdays 23, 30 (4 of 6:
    4 000); October: its Mondays and Wednesdays, all eight (6 000)."""
    october = october_paid(conn, school, today)
    timetable.add_slot(conn, school.ctx, SlotInput(
        school.group, school.room, WEDNESDAY, "17:00", "18:30", valid_from=date(2026, 9, 23)))
    today.day = date(2026, 9, 16)
    groups.close(conn, school.ctx, school.group)
    assert kept_week(conn, school.group) == [("2026-09-16", MONDAY), ("2026-09-16", WEDNESDAY)]
    assert counts(conn, school, october) == ((6, 4, 4000), (8, 8, 6000))


def test_a_group_closed_before_it_starts(conn, school, today):
    """Group C (Physique) starts on 01/10, Tuesdays from then. Amine joins it in September
    from its first day and pays its October; the school closes C on 20/09. His place ends on
    his entry day, and October keeps C's Tuesdays 6, 13, 20, 27: 6 000."""
    today.day = date(2026, 9, 15)
    physique = catalog.create(conn, school.ctx, "subject", "Physique")
    group_c = groups.create(conn, school.ctx, GroupInput(
        school.year, school.level, physique, "C", 6000, 30, date(2026, 10, 1)), school.teacher)
    timetable.add_slot(conn, school.ctx, SlotInput(group_c, school.room, 2, "17:00", "18:30"))
    in_c = enrollments.enroll(conn, school.ctx, school.student, group_c)
    [c_october] = subscriptions.for_enrollment(conn, school.ctx, in_c)
    payments.record(conn, school.ctx, school.student, 12000, "cash")  # A's September, C's October
    today.day = date(2026, 9, 20)
    groups.close(conn, school.ctx, group_c)
    assert kept_week(conn, group_c) == [("2026-09-20", 2)]
    assert refunds._sessions_left(conn, c_october.id) == SessionsLeft(
        "2026-10-01", total=4, left=4, value=6000)


def test_closed_reopened_and_closed_again_the_same_day(conn, school, today):
    """Closed on the 16th, reopened, its Monday slot added back, closed again that day: two
    closures, each with its week; Amine left with the first, counted once (21, 28 of four)."""
    october = october_paid(conn, school, today)
    today.day = date(2026, 9, 16)
    groups.close(conn, school.ctx, school.group)
    groups.reopen(conn, school.ctx, school.group)
    timetable.add_slot(conn, school.ctx, SlotInput(
        school.group, school.room, MONDAY, "17:00", "18:30", valid_from=date(2026, 9, 16)))
    groups.close(conn, school.ctx, school.group)
    assert kept_week(conn, school.group) == [("2026-09-16", MONDAY)] * 2  # one per closure
    assert counts(conn, school, october) == ((4, 2, 3000), (4, 4, 6000))


def test_closing_the_school_year_closes_its_groups_the_same_way(conn, school, today):
    october = october_paid(conn, school, today)
    today.day = date(2026, 9, 16)
    school_years.close(conn, school.ctx, school.year)
    assert closed_on(conn, school.group) == "2026-09-16"
    assert counts(conn, school, october) == ((4, 2, 3000), (4, 4, 6000))


def test_a_reopened_group_keeps_the_closure_that_ended_the_place(conn, school, today):
    """Amine left with the closure; a reopen must not drop September's 3 000 DA
    (REVIEW_FIXES round 2, finding 2)."""
    october = october_paid(conn, school, today)
    today.day = date(2026, 9, 16)
    groups.close(conn, school.ctx, school.group)
    first = conn.execute("SELECT closure_id FROM enrollments WHERE id = ?",
                         (school.enrollment,)).fetchone()[0]
    groups.reopen(conn, school.ctx, school.group)
    assert closed_on(conn, school.group) is None
    assert kept_week(conn, school.group) == [("2026-09-16", MONDAY)]
    assert conn.execute("SELECT closure_id FROM enrollments WHERE id = ?",
                        (school.enrollment,)).fetchone()[0] == first
    assert counts(conn, school, october) == ((4, 2, 3000), (4, 4, 6000))


def test_closed_reopened_and_closed_again_without_a_slot(conn, school, today):
    """Closed on the 16th, reopened, closed again that day with no slot put back: the second
    closure keeps nothing and the group points to it; Amine's month still counts the first
    (REVIEW_FIXES round 2, finding 3)."""
    october = october_paid(conn, school, today)
    today.day = date(2026, 9, 16)
    groups.close(conn, school.ctx, school.group)
    first = conn.execute("SELECT closure_id FROM enrollments WHERE id = ?",
                         (school.enrollment,)).fetchone()[0]
    groups.reopen(conn, school.ctx, school.group)
    groups.close(conn, school.ctx, school.group)
    second = closed_on(conn, school.group)
    assert second == "2026-09-16"
    assert conn.execute("SELECT COUNT(*) FROM group_closure_slots s JOIN group_closures c "
                        "ON c.id = s.closure_id WHERE c.group_id = ? AND c.id <> ?",
                        (school.group, first)).fetchone()[0] == 0
    assert conn.execute("SELECT closure_id FROM enrollments WHERE id = ?",
                        (school.enrollment,)).fetchone()[0] == first
    assert counts(conn, school, october) == ((4, 2, 3000), (4, 4, 6000))


def test_a_same_day_switch_keeps_the_session_already_given(conn, school, today):
    """Attended Monday in A, switched to B that day, left B: that Monday is used (3 of 4:
    4 500), not refunded as if B had no attendance. The day is used because A still
    occupied it, even without a mark (the second leave)."""
    today.day = date(2026, 9, 2)
    payments.record(conn, school.ctx, school.student, 6000, "cash")
    today.day = date(2026, 9, 7)
    sessions.generate_in(conn, days=7)
    session = conn.execute("SELECT id FROM sessions WHERE group_id = ? AND date = '2026-09-07'",
                           (school.group,)).fetchone()[0]
    attendance.save(conn, school.ctx, session, {school.enrollment: "present"})
    physique = catalog.create(conn, school.ctx, "subject", "Physique")
    group_b = groups.create(conn, school.ctx, GroupInput(
        school.year, school.level, physique, "B", 6000, 30, date(2026, 9, 1)),
        school.teacher)
    timetable.add_slot(conn, school.ctx, SlotInput(group_b, school.room, WEDNESDAY, "17:00",
                                                   "18:30", valid_from=date(2026, 9, 1)))
    in_b = enrollments.switch(conn, school.ctx, school.enrollment, group_b, date(2026, 9, 7))
    enrollments.leave(conn, school.ctx, in_b, date(2026, 9, 7))
    counted = refunds._sessions_left(conn, school.month)
    assert counted == SessionsLeft("2026-09-08", total=4, left=3, value=4500)


def test_a_same_day_switch_without_attendance_still_uses_that_day(conn, school, today):
    """Switched and left B on Monday without a mark in A: the Monday is still used."""
    today.day = date(2026, 9, 2)
    payments.record(conn, school.ctx, school.student, 6000, "cash")
    today.day = date(2026, 9, 7)
    physique = catalog.create(conn, school.ctx, "subject", "Anglais")
    group_b = groups.create(conn, school.ctx, GroupInput(
        school.year, school.level, physique, "B", 6000, 30, date(2026, 9, 1)),
        school.teacher)
    timetable.add_slot(conn, school.ctx, SlotInput(group_b, school.room, WEDNESDAY, "17:00",
                                                   "18:30", valid_from=date(2026, 9, 1)))
    in_b = enrollments.switch(conn, school.ctx, school.enrollment, group_b, date(2026, 9, 7))
    enrollments.leave(conn, school.ctx, in_b, date(2026, 9, 7))
    assert refunds._sessions_left(conn, school.month) == SessionsLeft(
        "2026-09-08", total=4, left=3, value=4500)


def test_leaving_a_later_group_before_it_starts_counts_from_the_switch(conn, school, today):
    """Switched on 10/09 to D starting 01/10, left D on 20/09 before it started: September
    of A is unused from the 11th (14, 21, 28: 4 500), not from D's entry day."""
    today.day = date(2026, 9, 2)
    payments.record(conn, school.ctx, school.student, 6000, "cash")
    today.day = date(2026, 9, 10)
    svt = catalog.create(conn, school.ctx, "subject", "SVT")
    group_d = groups.create(conn, school.ctx, GroupInput(
        school.year, school.level, svt, "D", 6000, 30, date(2026, 10, 1)),
        school.teacher)
    timetable.add_slot(conn, school.ctx, SlotInput(group_d, school.room, THURSDAY, "17:00",
                                                   "18:30", valid_from=date(2026, 10, 1)))
    in_d = enrollments.switch(conn, school.ctx, school.enrollment, group_d, date(2026, 9, 10))
    today.day = date(2026, 9, 20)
    enrollments.leave(conn, school.ctx, in_d)
    counted = refunds._sessions_left(conn, school.month)
    assert counted == SessionsLeft("2026-09-11", total=4, left=3, value=4500)


def cancel_monday_7(conn, school, today) -> int:
    """The school cancels Monday 7's session (teacher away)."""
    today.day = date(2026, 9, 7)
    sessions.generate_in(conn)
    monday = conn.execute("SELECT id FROM sessions WHERE date = '2026-09-07'").fetchone()[0]
    sessions.cancel(conn, school.ctx, monday, "Enseignant absent")
    return monday


def test_a_session_the_school_cancelled_before_the_leave_is_used(conn, school, today):
    """Monday 7 cancelled, left on the 15th: like any session before the count, it is used;
    handing it back is beyond V1 (21, 28 of 4: 3 000)."""
    cancel_monday_7(conn, school, today)
    today.day = date(2026, 9, 16)
    enrollments.leave(conn, school.ctx, school.enrollment, date(2026, 9, 15))
    counted = refunds._sessions_left(conn, school.month)
    assert counted == SessionsLeft("2026-09-16", total=4, left=2, value=3000)


def test_a_made_up_session_is_used(conn, school, today):
    """Monday 7 cancelled, made up on Tuesday 8 and attended: given, never handed back (the
    step 8 review: it was refunded, 4 500 instead of 3 000)."""
    monday = cancel_monday_7(conn, school, today)
    makeup = sessions.schedule_makeup(conn, school.ctx, monday, date(2026, 9, 8),
                                      "17:00", "18:30", school.room)
    today.day = date(2026, 9, 8)
    attendance.save(conn, school.ctx, makeup, {school.enrollment: "present"})
    today.day = date(2026, 9, 16)
    enrollments.leave(conn, school.ctx, school.enrollment, date(2026, 9, 15))
    counted = refunds._sessions_left(conn, school.month)
    assert counted == SessionsLeft("2026-09-16", total=4, left=2, value=3000)


def test_a_cancellation_in_the_old_group_after_a_switch_is_used(conn, school, today):
    """Switched from A (Mondays) to B (Wednesdays) on 10/09; A cancels Monday 14 while Amine
    attends B; he leaves B on the 16th. A's month counts from the 17th: 21, 28 (3 000), not
    the 14th too (the step 8 review: 4 500)."""
    subject = conn.execute("SELECT subject_id FROM class_groups WHERE id = ?",
                           (school.group,)).fetchone()[0]
    group_b = groups.create(conn, school.ctx, GroupInput(
        school.year, school.level, subject, "B", 6000, 30, date(2026, 9, 1)), school.teacher)
    timetable.add_slot(conn, school.ctx, SlotInput(group_b, school.room, WEDNESDAY, "17:00",
                                                   "18:30", valid_from=date(2026, 9, 1)))
    today.day = date(2026, 9, 10)
    in_b = enrollments.switch(conn, school.ctx, school.enrollment, group_b, date(2026, 9, 10))
    today.day = date(2026, 9, 14)
    sessions.generate_in(conn)
    a_14 = conn.execute("SELECT id FROM sessions WHERE date = '2026-09-14' AND group_id = ?",
                        (school.group,)).fetchone()[0]
    sessions.cancel(conn, school.ctx, a_14, "Enseignant absent")
    today.day = date(2026, 9, 16)
    enrollments.leave(conn, school.ctx, in_b, date(2026, 9, 16))
    counted = refunds._sessions_left(conn, school.month)
    assert counted == SessionsLeft("2026-09-17", total=4, left=2, value=3000)


def test_left_before_the_group_starts_the_month_is_unused(conn, school, today):
    """Amine joins C from 01/10, pays October in September, leaves on 20/09: last day is the
    entry day, none of it used, 6 000 back (REVIEW_FIXES round 2, decision 4)."""
    today.day = date(2026, 9, 15)
    physique = catalog.create(conn, school.ctx, "subject", "Physique")
    group_c = groups.create(conn, school.ctx, GroupInput(
        school.year, school.level, physique, "C", 6000, 30, date(2026, 10, 1)), school.teacher)
    timetable.add_slot(conn, school.ctx, SlotInput(group_c, school.room, 2, "17:00", "18:30"))
    in_c = enrollments.enroll(conn, school.ctx, school.student, group_c)
    [c_october] = subscriptions.for_enrollment(conn, school.ctx, in_c)
    payments.record(conn, school.ctx, school.student, 12000, "cash")
    today.day = date(2026, 9, 20)
    enrollments.leave(conn, school.ctx, in_c)
    assert enrollments.get(conn, school.ctx, in_c).left_on == "2026-10-01"
    assert refunds._sessions_left(conn, c_october.id) == SessionsLeft(
        "2026-10-01", total=4, left=4, value=6000)
    refund = refunds.request(conn, school.ctx, c_october.id, 6000, "Avant la rentrée")
    assert refunds.get(conn, school.ctx, refund).max_amount == 6000


def test_left_on_their_own_after_a_reopen_is_not_a_closure(conn, school, today):
    """Closed and reopened before Amine's entry: leaving on the entry day on his own must not
    reuse the old closure's week (REVIEW_FIXES round 2, finding 6)."""
    today.day = date(2026, 9, 15)
    physique = catalog.create(conn, school.ctx, "subject", "Physique")
    group_c = groups.create(conn, school.ctx, GroupInput(
        school.year, school.level, physique, "C", 6000, 30, date(2026, 10, 1)), school.teacher)
    timetable.add_slot(conn, school.ctx, SlotInput(group_c, school.room, 2, "17:00", "18:30"))
    today.day = date(2026, 9, 20)
    groups.close(conn, school.ctx, group_c)
    groups.reopen(conn, school.ctx, group_c)
    timetable.add_slot(conn, school.ctx, SlotInput(
        group_c, school.room, THURSDAY, "17:00", "18:30", valid_from=date(2026, 10, 1)))
    in_c = enrollments.enroll(conn, school.ctx, school.student, group_c)
    [c_october] = subscriptions.for_enrollment(conn, school.ctx, in_c)
    payments.record(conn, school.ctx, school.student, 12000, "cash")
    today.day = date(2026, 10, 1)
    enrollments.leave(conn, school.ctx, in_c, date(2026, 10, 1))
    assert conn.execute("SELECT closure_id FROM enrollments WHERE id = ?",
                        (in_c,)).fetchone()[0] is None
    counted = refunds._sessions_left(conn, c_october.id)
    assert counted.counted_from == "2026-10-01"
    assert counted.total == 5  # Thursdays 1, 8, 15, 22, 29, not the closed Tuesdays


def test_the_closure_and_its_week_are_read_only(conn, school, today):
    today.day = date(2026, 9, 16)
    groups.close(conn, school.ctx, school.group)
    for table, sql in (("group_closure_slots", "UPDATE group_closure_slots SET weekday = 2"),
                       ("group_closure_slots", "DELETE FROM group_closure_slots"),
                       ("group_closures", "UPDATE group_closures SET closed_on = '2026-09-17'"),
                       ("group_closures", "DELETE FROM group_closures")):
        with pytest.raises(sqlite3.IntegrityError, match=re.escape(f"{table} are immutable")):
            conn.execute(sql)


def test_a_group_points_only_to_its_own_closure(conn, school, today):
    today.day = date(2026, 9, 16)
    groups.close(conn, school.ctx, school.group)
    other = groups.create(conn, school.ctx, GroupInput(
        school.year, school.level, catalog.create(conn, school.ctx, "subject", "Physique"),
        "B", 6000, 30, date(2026, 9, 1)), school.teacher)
    with pytest.raises(sqlite3.IntegrityError,
                       match=re.escape("closure belongs to another group")):
        conn.execute("UPDATE class_groups SET closure_id = "
                     "(SELECT closure_id FROM class_groups WHERE id = ?) WHERE id = ?",
                     (school.group, other))


def test_an_enrollment_keeps_the_closure_that_ended_it(conn, school, today):
    today.day = date(2026, 9, 16)
    groups.close(conn, school.ctx, school.group)
    groups.reopen(conn, school.ctx, school.group)
    groups.close(conn, school.ctx, school.group)
    second = conn.execute("SELECT closure_id FROM class_groups WHERE id = ?",
                          (school.group,)).fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError,
                       match=re.escape("enrollment closure is set once")):
        conn.execute("UPDATE enrollments SET closure_id = ? WHERE id = ?",
                     (second, school.enrollment))


# ----- groups closed before migration 0022 -----

def test_groups_closed_before_keep_their_day_from_the_audit_log_only():
    """A version 21 database, closed as the app did then. A: closed on 16/09 (« group.close »),
    a Monday slot ended by it and a Wednesday slot over on the 5th. B: closed with its year
    on 20/09 (« school_year.close »). C: closed, nothing in the audit log. D: closed on 10/09,
    reopened on 12/09 (audit), closed again with nothing in the audit log."""
    c = connect(":memory:")
    for version, file in _files():
        if version > 21:
            break
        c.executescript(f"BEGIN IMMEDIATE;\n{file.read_text(encoding='utf-8')}\n"
                        f"PRAGMA user_version = {version};\nCOMMIT;")
    c.executescript("""
    INSERT INTO school_years(label,start_date,end_date) VALUES('2026-2027','2026-09-01','2027-06-30');
    INSERT INTO levels(name) VALUES('4AM');
    INSERT INTO subjects(name) VALUES('Maths');
    INSERT INTO users(username,password_hash,role) VALUES('u','x','director');
    INSERT INTO rooms(name,capacity) VALUES('Salle 1',20);
    INSERT INTO class_groups(school_year_id,level_id,subject_id,name,price,capacity,start_date)
      VALUES(1,1,1,'A',6000,30,'2026-09-01'), (1,1,1,'B',6000,30,'2026-09-01'),
            (1,1,1,'C',6000,30,'2026-09-01'), (1,1,1,'D',6000,30,'2026-09-01');
    INSERT INTO timetable_slots(group_id,room_id,weekday,start_time,end_time,valid_from,valid_to)
      VALUES(1,1,1,'17:00','18:30','2026-09-01','2026-09-16'),
            (1,1,3,'17:00','18:30','2026-09-01','2026-09-05');
    INSERT INTO students(student_number,first_name,last_name) VALUES('2026-0001','Amine','B');
    INSERT INTO registrations(student_id,school_year_id,level_id,fee_amount) VALUES(1,1,1,0);
    INSERT INTO enrollments(student_id,group_id,registration_id,enrolled_on)
      VALUES(1,1,1,'2026-09-01');
    INSERT INTO subscriptions(enrollment_id,price,start_date,end_date)
      VALUES(1,6000,'2026-09-01','2026-10-01'), (1,6000,'2026-10-01','2026-11-01');
    UPDATE enrollments SET status='left', left_on='2026-09-16' WHERE id=1;
    UPDATE class_groups SET status='closed';
    INSERT INTO audit_log(user_id,action,entity_name,entity_id,new_value,created_at) VALUES
      (1,'group.close','class_groups',1,'{"status": "closed"}','2026-09-16T10:00:00'),
      (1,'school_year.close','school_years',1,'{"groups_closed": [2]}','2026-09-20T09:00:00'),
      (1,'group.close','class_groups',4,'{"status": "closed"}','2026-09-10T10:00:00'),
      (1,'group.reopen','class_groups',4,'{"status": "active"}','2026-09-12T10:00:00');
    """)
    migrate(c)
    days = dict(c.execute(
        "SELECT g.name, gc.closed_on FROM class_groups g "
        "LEFT JOIN group_closures gc ON gc.id = g.closure_id").fetchall())
    assert days == {"A": "2026-09-16", "B": "2026-09-20", "C": None, "D": None}
    assert [tuple(r) for r in c.execute(
        "SELECT gc.group_id, gc.closed_on, s.weekday, s.valid_from, s.valid_to "
        "FROM group_closure_slots s JOIN group_closures gc ON gc.id = s.closure_id")] == [
        (1, "2026-09-16", MONDAY, "2026-09-01", None)]  # not the Wednesday slot, over before
    september, october = (refunds._sessions_left(c, month) for month in (1, 2))
    assert (september.counted_from, september.total, september.left, september.value) == (
        "2026-09-16", 5, 2, 2400)  # Wednesday 2, Mondays 7, 14, then 21, 28
    assert (october.total, october.left, october.value) == (4, 4, 6000)
    assert c.execute("SELECT closure_id FROM enrollments WHERE id = 1").fetchone()[0] is not None
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []


# ----- the third review (REVIEW_FIXES round 3) -----

def test_an_open_last_day_spent_in_the_new_group(conn, school, today):
    """A on Thursdays, October paid ahead in A; switched on 10/09 to B (Thursdays, from
    01/10). On 01/10 Amine attends B's first session, then leaves B that day. That session
    was given, paid by A's October: October keeps 4 of its 5 Thursdays (4 800), not 5
    (finding 1: the attendance was looked for in A)."""
    conn.execute("UPDATE timetable_slots SET weekday = ? WHERE id = ?", (THURSDAY, school.slot))
    october = october_paid(conn, school, today)
    subject = conn.execute("SELECT subject_id FROM class_groups WHERE id = ?",
                           (school.group,)).fetchone()[0]
    group_b = groups.create(conn, school.ctx, GroupInput(
        school.year, school.level, subject, "B", 6000, 30, date(2026, 10, 1)), school.teacher)
    timetable.add_slot(conn, school.ctx, SlotInput(group_b, school.room, THURSDAY, "18:30",
                                                   "20:00"))
    today.day = date(2026, 9, 10)
    in_b = enrollments.switch(conn, school.ctx, school.enrollment, group_b, date(2026, 9, 10))
    today.day = date(2026, 10, 1)
    sessions.generate_in(conn)
    first_b = conn.execute("SELECT id FROM sessions WHERE group_id = ? AND date = '2026-10-01'",
                           (group_b,)).fetchone()[0]
    attendance.save(conn, school.ctx, first_b, {in_b: "present"})
    enrollments.leave(conn, school.ctx, in_b, date(2026, 10, 1))
    assert refunds._sessions_left(conn, october) == SessionsLeft(
        "2026-10-01", total=5, left=4, value=4800)


def test_a_makeup_on_the_closing_day_is_not_that_days_session(conn, school, today):
    """Monday 7 cancelled, made up on Monday 14 at 10:00 (held); the group closes at noon and
    its 17:00 session is dropped. The makeup replaced the 7th, already used: the 17:00 one is
    left with 21 and 28 (3 of 4: 4 500; finding 2: 3 000)."""
    monday = cancel_monday_7(conn, school, today)
    makeup = sessions.schedule_makeup(conn, school.ctx, monday, date(2026, 9, 14), "10:00",
                                      "11:30", school.room)
    today.day = date(2026, 9, 14)
    attendance.save(conn, school.ctx, makeup, {school.enrollment: "present"})
    groups.close(conn, school.ctx, school.group)
    assert refunds._sessions_left(conn, school.month) == SessionsLeft(
        "2026-09-14", total=4, left=3, value=4500)
