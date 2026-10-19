import json
from datetime import date

import pytest

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, ValidationError
from tadris.domain.models import GroupInput, SlotInput, StudentInput, TeacherInput
from tadris.i18n.fr import t
from tadris.services import (
    attendance,
    auth,
    catalog,
    enrollments,
    groups,
    registrations,
    rooms,
    school_years,
    sessions,
    students,
    subscriptions,
    teachers,
    timetable,
)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(dates, "today", lambda: date(2026, 10, 18))  # Sunday


@pytest.fixture
def director(conn):
    return auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")


@pytest.fixture
def desk(conn, director):
    user_id = auth.create_user(conn, director, "accueil", "password2", "receptionist")
    return UserContext(user_id=user_id, username="accueil", role="receptionist")


class School:
    def __init__(self, conn, ctx):
        year = school_years.create(conn, ctx, "2026-2027", date(2026, 9, 1), date(2027, 6, 30))
        self.level = catalog.create(conn, ctx, "level", "4AM")
        room = rooms.create(conn, ctx, "Salle A", 20)
        other_room = rooms.create(conn, ctx, "Salle B", 20)
        teacher = teachers.create(conn, ctx, TeacherInput("Karim"), 6000, date(2026, 9, 1))
        other = teachers.create(conn, ctx, TeacherInput("Samia"), 5000, date(2026, 9, 1))

        def group(name, subject, who):
            subject_id = catalog.create(conn, ctx, "subject", subject)
            return groups.create(conn, ctx, GroupInput(year, self.level, subject_id, name, 3000,
                                                       15, date(2026, 9, 1)), who)

        self.maths = group("M1", "Maths", teacher)
        self.physics = group("P1", "Physique", other)
        timetable.add_slot(conn, ctx, SlotInput(self.maths, room, 1, "17:00", "18:30"))
        timetable.add_slot(conn, ctx, SlotInput(self.physics, other_room, 1, "10:00", "11:30"))


@pytest.fixture
def school(conn, director):
    return School(conn, director)


def student(conn, ctx, school, first, group_key="maths", entered=date(2026, 10, 1),
            trial=False):
    sid = students.create(conn, ctx, StudentInput(first, "Benali"))
    registrations.register(conn, ctx, sid, school.level, 0)
    return sid, enrollments.enroll(conn, ctx, sid, getattr(school, group_key), trial=trial,
                                   enrolled_on=entered)


def session_id(conn, day, group_id):
    return conn.execute("SELECT id FROM sessions WHERE date = ? AND group_id = ?",
                        (day, group_id)).fetchone()[0]


def names(lines) -> list[str]:
    return [line.student_name for line in lines]


@pytest.fixture
def on_monday(monkeypatch):
    monkeypatch.setattr(dates, "today", lambda: date(2026, 10, 19))


# ----- who is expected -----

def test_roster_is_the_group_on_that_day(conn, director, school):
    student(conn, director, school, "Amine")
    student(conn, director, school, "Yanis", trial=True)
    student(conn, director, school, "Lina", entered=date(2026, 10, 20))  # after 19/10
    _, gone = student(conn, director, school, "Sara", entered=date(2026, 10, 1))
    enrollments.leave(conn, director, gone, date(2026, 10, 18))  # before 19/10
    lines = attendance.roster(conn, director, session_id(conn, "2026-10-19", school.maths))
    assert names(lines) == ["Benali Amine", "Benali Yanis"]
    amine, yanis = lines
    assert (amine.trial, amine.not_renewed, amine.status) == (False, False, None)
    assert (yanis.trial, yanis.not_renewed) == (True, False)  # a trial is never flagged
    assert names(attendance.roster(conn, director, session_id(conn, "2026-10-26",
                                                               school.maths))) == [
        "Benali Amine", "Benali Lina", "Benali Yanis"]


def test_a_student_who_left_that_day_is_still_expected(conn, director, school, on_monday):
    _, enrollment = student(conn, director, school, "Amine")
    enrollments.switch(conn, director, enrollment, school.physics)  # switched on 19/10
    for group in (school.maths, school.physics):
        assert names(attendance.roster(conn, director, session_id(conn, "2026-10-19", group))
                     ) == ["Benali Amine"]


def test_month_not_renewed_is_flagged(conn, director, school, monkeypatch):
    _, enrollment = student(conn, director, school, "Amine")  # month 01/10 -> 01/11
    monkeypatch.setattr(dates, "today", lambda: date(2026, 11, 2))
    sessions.generate(conn, director)
    november = session_id(conn, "2026-11-02", school.maths)
    [line] = attendance.roster(conn, director, november)
    assert line.not_renewed
    month = subscriptions.for_enrollment(conn, director, enrollment)[0]
    subscriptions.renew(conn, director, month.id)
    [line] = attendance.roster(conn, director, november)
    assert not line.not_renewed


# ----- saving -----

def test_save_marks_the_session_held_and_is_audited(conn, desk, school, on_monday):
    _, amine = student(conn, desk, school, "Amine")
    _, yanis = student(conn, desk, school, "Yanis", trial=True)
    monday = session_id(conn, "2026-10-19", school.maths)
    assert attendance.save(conn, desk, monday, {amine: "present", yanis: "late"}) == 2
    assert [line.status for line in attendance.roster(conn, desk, monday)] == ["present", "late"]
    assert sessions.get(conn, desk, monday).status == "held"
    entry = conn.execute("SELECT * FROM audit_log WHERE action = 'attendance.save'").fetchone()
    assert entry["user_id"] == desk.user_id
    assert json.loads(entry["new_value"])["changes"] == [
        {"enrollment_id": amine, "old": None, "new": "present"},
        {"enrollment_id": yanis, "old": None, "new": "late"}]


def test_corrections_write_only_what_changed(conn, director, desk, school, on_monday):
    _, amine = student(conn, desk, school, "Amine")
    _, yanis = student(conn, desk, school, "Yanis")
    monday = session_id(conn, "2026-10-19", school.maths)
    attendance.save(conn, desk, monday, {amine: "present", yanis: "absent"})
    assert attendance.save(conn, desk, monday, {amine: "present", yanis: "absent"}) == 0
    assert attendance.save(conn, director, monday, {amine: "present", yanis: "excused"}) == 1
    entries = conn.execute("SELECT new_value FROM audit_log WHERE action = 'attendance.save' "
                           "ORDER BY id").fetchall()
    assert len(entries) == 2  # the save without change wrote nothing
    assert json.loads(entries[-1][0])["changes"] == [
        {"enrollment_id": yanis, "old": "absent", "new": "excused"}]


def test_corrected_later_on(conn, desk, school, on_monday, monkeypatch):
    _, amine = student(conn, desk, school, "Amine")
    monday = session_id(conn, "2026-10-19", school.maths)
    attendance.save(conn, desk, monday, {amine: "absent"})
    monkeypatch.setattr(dates, "today", lambda: date(2026, 11, 30))  # weeks later
    attendance.save(conn, desk, monday, {amine: "excused"})
    assert attendance.roster(conn, desk, monday)[0].status == "excused"


def test_not_before_the_session_day(conn, desk, school):
    _, amine = student(conn, desk, school, "Amine")
    monday = session_id(conn, "2026-10-19", school.maths)  # today is 18/10
    with pytest.raises(BusinessRuleError) as exc:
        attendance.save(conn, desk, monday, {amine: "present"})
    assert exc.value.message == t["attendance.future"].format(date="19/10/2026")


def test_not_for_a_cancelled_session(conn, desk, school, on_monday):
    _, amine = student(conn, desk, school, "Amine")
    monday = session_id(conn, "2026-10-19", school.maths)
    sessions.cancel(conn, desk, monday, "Grève")
    with pytest.raises(BusinessRuleError) as exc:
        attendance.save(conn, desk, monday, {amine: "present"})
    assert exc.value.message == t["attendance.session_cancelled"]


def test_only_the_sessions_students_and_valid_statuses(conn, desk, school, on_monday):
    _, amine = student(conn, desk, school, "Amine")
    _, other = student(conn, desk, school, "Lina", group_key="physics")
    monday = session_id(conn, "2026-10-19", school.maths)
    with pytest.raises(ValidationError):
        attendance.save(conn, desk, monday, {amine: "sick"})
    with pytest.raises(BusinessRuleError) as exc:
        attendance.save(conn, desk, monday, {amine: "present", other: "present"})
    assert exc.value.message == t["attendance.not_in_session"]
    assert attendance.roster(conn, desk, monday)[0].status is None  # nothing saved


def test_a_held_session_is_kept_by_the_generator(conn, director, desk, school, on_monday):
    _, amine = student(conn, desk, school, "Amine")
    monday = session_id(conn, "2026-10-19", school.maths)
    attendance.save(conn, desk, monday, {amine: "present"})
    slot = conn.execute("SELECT slot_id FROM sessions WHERE id = ?", (monday,)).fetchone()[0]
    room = conn.execute("SELECT room_id FROM sessions WHERE id = ?", (monday,)).fetchone()[0]
    timetable.update_slot(conn, director, slot, SlotInput(school.maths, room, 2, "17:00",
                                                          "18:30"))
    assert sessions.get(conn, desk, monday).status == "held"  # history stays


# ----- a student's history -----

def test_history_and_counts(conn, desk, school, monkeypatch):
    sid, amine = student(conn, desk, school, "Amine")
    in_physics = enrollments.enroll(conn, desk, sid, school.physics,
                                    enrolled_on=date(2026, 10, 1))
    monkeypatch.setattr(dates, "today", lambda: date(2026, 10, 26))
    attendance.save(conn, desk, session_id(conn, "2026-10-19", school.maths), {amine: "absent"})
    attendance.save(conn, desk, session_id(conn, "2026-10-26", school.maths), {amine: "late"})
    attendance.save(conn, desk, session_id(conn, "2026-10-19", school.physics),
                    {in_physics: "present"})
    history = attendance.for_student(conn, desk, sid)
    assert [(r.date, r.group_title, r.status) for r in history] == [
        ("2026-10-26", "M1 · Maths 4AM", "late"),
        ("2026-10-19", "M1 · Maths 4AM", "absent"),
        ("2026-10-19", "P1 · Physique 4AM", "present"),
    ]
    summary = attendance.summarize(r.status for r in history)
    assert (summary.present, summary.late, summary.absent, summary.excused, summary.total) == (
        1, 1, 1, 0, 3)
