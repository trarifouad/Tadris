import json
from datetime import date

import pytest

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, PermissionDenied, ValidationError
from tadris.domain.models import GroupInput, SlotInput, TeacherInput
from tadris.i18n.fr import t
from tadris.services import (
    auth,
    catalog,
    groups,
    holidays,
    rooms,
    school_years,
    sessions,
    teachers,
    timetable,
)

TODAY = date(2026, 10, 18)  # a Sunday: the next 14 days run to Saturday 31/10


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(dates, "today", lambda: TODAY)


@pytest.fixture
def director(conn):
    return auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")


class School:
    def __init__(self, conn, ctx):
        self.year = school_years.create(conn, ctx, "2026-2027", date(2026, 9, 1),
                                        date(2027, 6, 30))
        self.level = catalog.create(conn, ctx, "level", "4AM")
        self.room_a = rooms.create(conn, ctx, "Salle A", 20)
        self.room_b = rooms.create(conn, ctx, "Salle B", 20)
        self.karim = teachers.create(conn, ctx, TeacherInput("Karim"), 6000, date(2026, 9, 1))
        self.samia = teachers.create(conn, ctx, TeacherInput("Samia"), 5000, date(2026, 9, 1))
        self.nabil = teachers.create(conn, ctx, TeacherInput("Nabil"), 5000, date(2026, 9, 1))
        self.maths = self.group(conn, ctx, "M1", "Maths", self.karim)
        self.physics = self.group(conn, ctx, "P1", "Physique", self.samia)

    def group(self, conn, ctx, name, subject, teacher, start=date(2026, 9, 1)):
        subject_id = catalog.create(conn, ctx, "subject", subject)
        return groups.create(conn, ctx, GroupInput(self.year, self.level, subject_id, name,
                                                   3000, 15, start), teacher)


@pytest.fixture
def school(conn, director):
    return School(conn, director)


@pytest.fixture
def monday(conn, director, school):
    """M1 meets on Mondays 17:00-18:30 in Salle A: 19/10 and 26/10 in the window."""
    return timetable.add_slot(conn, director, SlotInput(school.maths, school.room_a, 1,
                                                        "17:00", "18:30"))


def listed(conn, first="2026-10-01", last="2027-12-31") -> list[tuple]:
    return [(s["date"], s["group_id"], s["start_time"], s["status"])
            for s in conn.execute("SELECT * FROM sessions WHERE date BETWEEN ? AND ? "
                                  "ORDER BY date, start_time", (first, last))]


def session_on(conn, day, group_id):
    return conn.execute("SELECT * FROM sessions WHERE date = ? AND group_id = ?",
                        (day, group_id)).fetchone()


def hold(conn, day, group_id):
    """Make a session history (held), as attendance will in task 4."""
    conn.execute("UPDATE sessions SET status = 'held' WHERE date = ? AND group_id = ?",
                 (day, group_id))


# ----- generation -----

def test_a_new_slot_gets_its_sessions_for_the_next_14_days(conn, school, monday):
    assert listed(conn) == [("2026-10-19", school.maths, "17:00", "planned"),
                            ("2026-10-26", school.maths, "17:00", "planned")]
    s = session_on(conn, "2026-10-19", school.maths)
    assert (s["slot_id"], s["room_id"], s["teacher_id"], s["end_time"], s["source"]) == (
        monday, school.room_a, school.karim, "18:30", "generated")


def test_generation_is_idempotent_and_moves_with_the_days(conn, director, school, monday,
                                                          monkeypatch):
    assert sessions.generate(conn, director).created == 0
    monkeypatch.setattr(dates, "today", lambda: date(2026, 10, 25))
    result = sessions.generate(conn, director)
    assert result.created == 1  # Monday 02/11 enters the window
    assert [d for d, *_ in listed(conn)] == ["2026-10-19", "2026-10-26", "2026-11-02"]


def test_today_counts_and_slot_validity_is_respected(conn, director, school, monkeypatch):
    monkeypatch.setattr(dates, "today", lambda: date(2026, 10, 19))  # a Monday: to 01/11
    timetable.add_slot(conn, director, SlotInput(school.maths, school.room_a, 1, "17:00",
                                                 "18:30"))
    assert [d for d, *_ in listed(conn)] == ["2026-10-19", "2026-10-26"]  # today included
    timetable.add_slot(conn, director, SlotInput(school.physics, school.room_b, 2, "17:00",
                                                 "18:30", date(2026, 10, 27)))
    assert [d for d, g, *_ in listed(conn) if g == school.physics] == ["2026-10-27"]


def test_a_group_that_has_not_started(conn, director, school):
    later = school.group(conn, director, "A1", "Arabe", school.nabil, start=date(2026, 10, 28))
    timetable.add_slot(conn, director, SlotInput(later, school.room_b, 3, "17:00", "18:30"))
    assert listed(conn) == [("2026-10-28", later, "17:00", "planned")]


def test_nothing_after_the_end_of_the_year(conn, director, school, monday, monkeypatch):
    monkeypatch.setattr(dates, "today", lambda: date(2027, 6, 25))
    sessions.generate(conn, director)
    assert [d for d, *_ in listed(conn, "2027-06-01")] == ["2027-06-28"]  # not 05/07


def test_a_cancelled_session_is_not_generated_again(conn, director, school, monday):
    conn.execute("UPDATE sessions SET status = 'cancelled', cancellation_reason = 'x' "
                 "WHERE date = '2026-10-19'")
    sessions.generate(conn, director)
    assert listed(conn)[0] == ("2026-10-19", school.maths, "17:00", "cancelled")
    assert len(listed(conn)) == 2


def test_a_clash_is_skipped_and_reported(conn, director, school, monday):
    conn.execute("DELETE FROM sessions WHERE date = '2026-10-26'")
    conn.execute(  # a makeup of P1 holds Salle A on Monday 26/10 at 17:30
        "INSERT INTO sessions(group_id, room_id, teacher_id, date, start_time, end_time, "
        "source) VALUES (?, ?, ?, '2026-10-26', '17:30', '18:30', 'makeup')",
        (school.physics, school.room_a, school.samia))
    result = sessions.generate(conn, director)
    assert result.created == 0
    assert result.conflicts == [("2026-10-26", school.maths,
                                 "Chevauchement de salles pour cette séance.")]


def test_permissions_and_audit(conn, director, school, monday, monkeypatch):
    desk_id = auth.create_user(conn, director, "accueil", "password2", "receptionist")
    desk = UserContext(user_id=desk_id, username="accueil", role="receptionist")
    monkeypatch.setattr(dates, "today", lambda: date(2026, 10, 25))
    sessions.generate(conn, desk)  # both roles may regenerate
    entry = conn.execute("SELECT * FROM audit_log WHERE action = 'session.generate'").fetchone()
    assert json.loads(entry["new_value"]) == {"created": 1, "conflicts": 0}
    monkeypatch.setattr(dates, "today", lambda: date(2026, 11, 1))
    assert sessions.generate_at_start(conn).created == 1
    last = conn.execute("SELECT user_id FROM audit_log WHERE action = 'session.generate' "
                        "ORDER BY id DESC").fetchone()
    assert last["user_id"] is None
    ghost = UserContext(user_id=99, username="x", role="teacher")
    with pytest.raises(PermissionDenied):
        sessions.generate(conn, ghost)


# ----- holidays -----

def test_holidays_remove_and_give_back_sessions(conn, director, school, monday):
    holiday = holidays.create(conn, director, "Fête", date(2026, 10, 26))
    assert [d for d, *_ in listed(conn)] == ["2026-10-19"]
    sessions.generate(conn, director)
    assert [d for d, *_ in listed(conn)] == ["2026-10-19"]  # not generated on a holiday
    holidays.update(conn, director, holiday, "Fête", date(2026, 10, 19))
    assert [d for d, *_ in listed(conn)] == ["2026-10-26"]  # moved: 26/10 is back
    holidays.remove(conn, director, holiday)
    assert [d for d, *_ in listed(conn)] == ["2026-10-19", "2026-10-26"]


def test_a_holiday_keeps_a_held_session(conn, director, school, monday):
    hold(conn, "2026-10-19", school.maths)
    holidays.create(conn, director, "Fête", date(2026, 10, 19))
    assert listed(conn)[0] == ("2026-10-19", school.maths, "17:00", "held")


# ----- the timetable changes -----

def test_moving_a_slot_without_history_moves_its_sessions(conn, director, school, monday):
    timetable.update_slot(conn, director, monday, SlotInput(school.maths, school.room_a, 2,
                                                            "18:00", "19:30"))
    assert listed(conn) == [("2026-10-20", school.maths, "18:00", "planned"),
                            ("2026-10-27", school.maths, "18:00", "planned")]
    assert session_on(conn, "2026-10-20", school.maths)["slot_id"] == monday  # same slot


def test_moving_a_slot_with_history_ends_it_and_keeps_the_history(conn, director, school,
                                                                  monday):
    hold(conn, "2026-10-19", school.maths)
    new_slot = timetable.update_slot(conn, director, monday, SlotInput(
        school.maths, school.room_a, 2, "18:00", "19:30"))
    assert new_slot != monday
    assert listed(conn) == [("2026-10-19", school.maths, "17:00", "held"),
                            ("2026-10-20", school.maths, "18:00", "planned"),
                            ("2026-10-27", school.maths, "18:00", "planned")]
    assert session_on(conn, "2026-10-19", school.maths)["slot_id"] == monday


def test_removing_a_slot(conn, director, school, monday):
    timetable.remove_slot(conn, director, monday)
    assert listed(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM timetable_slots").fetchone()[0] == 0  # deleted


def test_removing_a_slot_with_history_ends_it(conn, director, school, monday):
    hold(conn, "2026-10-19", school.maths)
    timetable.remove_slot(conn, director, monday)
    assert listed(conn) == [("2026-10-19", school.maths, "17:00", "held")]
    assert conn.execute("SELECT valid_to FROM timetable_slots").fetchone()[0] is not None


def test_closing_a_group_removes_its_planned_sessions(conn, director, school, monday):
    groups.close(conn, director, school.maths)
    assert listed(conn) == []
    sessions.generate(conn, director)
    assert listed(conn) == []


def test_a_teacher_change_redoes_the_sessions_from_its_date(conn, director, school, monday):
    groups.change_teacher(conn, director, school.maths, school.nabil, date(2026, 10, 26))
    assert session_on(conn, "2026-10-19", school.maths)["teacher_id"] == school.karim
    assert session_on(conn, "2026-10-26", school.maths)["teacher_id"] == school.nabil


def test_a_substitute_survives_a_teacher_change(conn, director, school, monday):
    conn.execute("UPDATE sessions SET teacher_id = ? WHERE date = '2026-10-26'",
                 (school.samia,))  # chosen by hand for that day (task 3)
    groups.change_teacher(conn, director, school.maths, school.nabil, date(2026, 10, 19))
    assert session_on(conn, "2026-10-19", school.maths)["teacher_id"] == school.nabil
    assert session_on(conn, "2026-10-26", school.maths)["teacher_id"] == school.samia


def test_moving_the_group_start_redoes_its_sessions(conn, director, school, monday):
    g = groups.get(conn, director, school.maths)
    groups.update(conn, director, school.maths, GroupInput(
        school.year, g.level_id, g.subject_id, g.name, g.price, g.capacity, date(2026, 10, 20)))
    assert [d for d, *_ in listed(conn)] == ["2026-10-26"]


# ----- cancel, restore, makeup, substitute -----

def sid(conn, day, group_id):
    return session_on(conn, day, group_id)["id"]


def test_cancel_with_a_reason_and_restore(conn, director, school, monday):
    session_id = sid(conn, "2026-10-19", school.maths)
    with pytest.raises(ValidationError) as exc:
        sessions.cancel(conn, director, session_id, "  ")
    assert exc.value.message == t["session.reason_required"]
    sessions.cancel(conn, director, session_id, " Enseignant malade ")
    s = sessions.get(conn, director, session_id)
    assert (s.status, s.cancellation_reason) == ("cancelled", "Enseignant malade")
    entry = json.loads(conn.execute("SELECT new_value FROM audit_log WHERE action = "
                                    "'session.cancel'").fetchone()[0])
    assert entry["reason"] == "Enseignant malade"
    with pytest.raises(BusinessRuleError):
        sessions.cancel(conn, director, session_id, "encore")
    sessions.restore(conn, director, session_id)
    assert sessions.get(conn, director, session_id).status == "planned"
    with pytest.raises(BusinessRuleError) as exc:
        sessions.restore(conn, director, session_id)
    assert exc.value.message == t["session.not_cancelled"]


def test_a_held_session_cannot_be_cancelled(conn, director, school, monday):
    hold(conn, "2026-10-19", school.maths)
    with pytest.raises(BusinessRuleError) as exc:
        sessions.cancel(conn, director, sid(conn, "2026-10-19", school.maths), "x")
    assert exc.value.message == t["session.held"]


def test_a_cancelled_session_frees_its_room(conn, director, school, monday):
    sessions.cancel(conn, director, sid(conn, "2026-10-19", school.maths), "Grève")
    conn.execute(  # someone else uses Salle A at that time meanwhile
        "INSERT INTO sessions(group_id, room_id, teacher_id, date, start_time, end_time, "
        "source) VALUES (?, ?, ?, '2026-10-19', '17:00', '18:00', 'manual')",
        (school.physics, school.room_a, school.samia))
    with pytest.raises(BusinessRuleError) as exc:
        sessions.restore(conn, director, sid(conn, "2026-10-19", school.maths))
    assert exc.value.message == t["slot.room_busy"].format(
        room="Salle A", day="19/10/2026", start="17:00", end="18:00", group="P1")


def test_makeup_for_a_cancelled_session(conn, director, school, monday):
    cancelled = sid(conn, "2026-10-19", school.maths)
    with pytest.raises(BusinessRuleError) as exc:
        sessions.schedule_makeup(conn, director, cancelled, date(2026, 10, 24), "9h", "10h30",
                                 school.room_b)
    assert exc.value.message == t["session.makeup_needs_cancel"]
    sessions.cancel(conn, director, cancelled, "Enseignant malade")
    makeup_id = sessions.schedule_makeup(conn, director, cancelled, date(2026, 10, 24), "9h",
                                         "10h30", school.room_b)
    m = sessions.get(conn, director, makeup_id)
    assert (m.date, m.start_time, m.end_time, m.room, m.teacher_id, m.source, m.slot_id) == (
        "2026-10-24", "09:00", "10:30", "Salle B", school.karim, "makeup", None)
    assert m.makeup_of_session_id == cancelled
    assert sessions.get(conn, director, cancelled).makeup_id == makeup_id
    with pytest.raises(BusinessRuleError) as exc:  # one makeup per cancelled session
        sessions.schedule_makeup(conn, director, cancelled, date(2026, 10, 25), "9h", "10h",
                                 school.room_b)
    assert exc.value.message == t["session.has_makeup"]
    with pytest.raises(BusinessRuleError):  # nor restore while it has one
        sessions.restore(conn, director, cancelled)
    sessions.cancel(conn, director, makeup_id, "Salle indisponible")
    sessions.schedule_makeup(conn, director, cancelled, date(2026, 10, 25), "9h", "10h",
                             school.room_b)  # a cancelled makeup frees the place


# ----- reschedule one session of the week (« Reporter ») -----

def test_reschedule_moves_one_session_of_the_week(conn, director, school, monday):
    """Monday 19/10 17:00 in Salle A moves to Wednesday 21/10 18:00 in Salle B; the slot and
    next Monday stay as they are."""
    original = sid(conn, "2026-10-19", school.maths)
    makeup_id = sessions.reschedule(conn, director, original, date(2026, 10, 21), "18h",
                                    "19h30", school.room_b, "Enseignant en formation")
    old = sessions.get(conn, director, original)
    assert (old.status, old.cancellation_reason, old.makeup_id, old.makeup_date) == (
        "cancelled", "Enseignant en formation", makeup_id, "2026-10-21")
    m = sessions.get(conn, director, makeup_id)
    assert (m.date, m.start_time, m.end_time, m.room, m.teacher_id, m.source) == (
        "2026-10-21", "18:00", "19:30", "Salle B", school.karim, "makeup")
    assert m.makeup_of_session_id == original
    [slot] = timetable.group_slots(conn, director, school.maths)  # the timetable is untouched
    assert (slot.weekday, slot.start_time, slot.room_id) == (1, "17:00", school.room_a)
    assert session_on(conn, "2026-10-26", school.maths)["status"] == "planned"
    entry = conn.execute("SELECT old_value, new_value FROM audit_log "
                         "WHERE action = 'session.reschedule'").fetchone()
    old_value, new_value = json.loads(entry[0]), json.loads(entry[1])
    assert (old_value["date"], old_value["start_time"]) == ("2026-10-19", "17:00")
    assert (new_value["date"], new_value["start_time"], new_value["reason"]) == (
        "2026-10-21", "18:00", "Enseignant en formation")


def test_reschedule_the_same_day_over_its_own_time(conn, director, school, monday):
    """Half an hour later the same day: the old place is freed first."""
    original = sid(conn, "2026-10-19", school.maths)
    makeup_id = sessions.reschedule(conn, director, original, date(2026, 10, 19), "17h30",
                                    "19h", school.room_a, "Salle occupée par un examen")
    assert sessions.get(conn, director, makeup_id).start_time == "17:30"


def test_reschedule_stays_in_the_week(conn, director, school, monday):
    original = sid(conn, "2026-10-19", school.maths)
    for day in (date(2026, 10, 24), date(2026, 10, 17)):  # next Saturday; yesterday
        with pytest.raises(ValidationError) as exc:
            sessions.reschedule(conn, director, original, day, "10h", "11h30", school.room_a,
                                "Report")
        assert exc.value.message == t["session.reschedule_week"].format(
            first="18/10/2026", last="23/10/2026")
    with pytest.raises(ValidationError) as exc:
        sessions.reschedule(conn, director, original, date(2026, 10, 19), "17h", "18h30",
                            school.room_a, "Report")
    assert exc.value.message == t["session.reschedule_same"]
    with pytest.raises(ValidationError):
        sessions.reschedule(conn, director, original, date(2026, 10, 21), "17h", "18h30",
                            school.room_a, "  ")
    assert session_on(conn, "2026-10-19", school.maths)["status"] == "planned"


def test_reschedule_refuses_a_clash_and_changes_nothing(conn, director, school, monday):
    timetable.add_slot(conn, director, SlotInput(school.physics, school.room_b, 3, "18:00",
                                                 "19:30"))  # Wednesday 21/10 in Salle B
    original = sid(conn, "2026-10-19", school.maths)
    with pytest.raises(BusinessRuleError) as exc:
        sessions.reschedule(conn, director, original, date(2026, 10, 21), "18h30", "20h",
                            school.room_b, "Report")
    assert "Salle B" in exc.value.message
    assert session_on(conn, "2026-10-19", school.maths)["status"] == "planned"
    assert conn.execute("SELECT COUNT(*) FROM sessions WHERE source = 'makeup'").fetchone()[0] == 0


def test_reschedule_only_a_planned_session_from_today(conn, director, school, monday,
                                                       monkeypatch):
    original = sid(conn, "2026-10-19", school.maths)
    hold(conn, "2026-10-19", school.maths)
    with pytest.raises(BusinessRuleError) as exc:
        sessions.reschedule(conn, director, original, date(2026, 10, 21), "10h", "11h30",
                            school.room_a, "Report")
    assert exc.value.message == t["session.held"]
    conn.execute("UPDATE sessions SET status = 'planned' WHERE id = ?", (original,))
    monkeypatch.setattr(dates, "today", lambda: date(2026, 10, 20))
    with pytest.raises(BusinessRuleError) as exc:
        sessions.reschedule(conn, director, original, date(2026, 10, 21), "10h", "11h30",
                            school.room_a, "Report")
    assert exc.value.message == t["session.reschedule_past"]


def test_undo_a_reschedule(conn, director, school, monday):
    original = sid(conn, "2026-10-19", school.maths)
    with pytest.raises(BusinessRuleError) as exc:
        sessions.undo_reschedule(conn, director, original)
    assert exc.value.message == t["session.not_rescheduled"]
    makeup_id = sessions.reschedule(conn, director, original, date(2026, 10, 21), "18h",
                                    "19h30", school.room_b, "Enseignant absent")
    sessions.undo_reschedule(conn, director, original)
    old = sessions.get(conn, director, original)
    assert (old.status, old.cancellation_reason, old.makeup_id) == ("planned", None, None)
    assert sessions.get(conn, director, makeup_id).status == "cancelled"
    # It can be moved again.
    sessions.reschedule(conn, director, original, date(2026, 10, 22), "18h", "19h30",
                        school.room_b, "Enseignant absent")
    assert [row[0] for row in conn.execute(
        "SELECT action FROM audit_log WHERE action LIKE 'session.%reschedule' ORDER BY id")] == [
        "session.reschedule", "session.undo_reschedule", "session.reschedule"]


def test_makeup_survives_regeneration_and_teacher_changes(conn, director, school, monday):
    cancelled = sid(conn, "2026-10-19", school.maths)
    sessions.cancel(conn, director, cancelled, "Grève")
    makeup_id = sessions.schedule_makeup(conn, director, cancelled, date(2026, 10, 27), "9h",
                                         "10h30", school.room_b)
    groups.change_teacher(conn, director, school.maths, school.nabil, date(2026, 10, 19))
    sessions.generate(conn, director)
    assert sessions.get(conn, director, makeup_id).teacher_id == school.karim  # kept


def test_makeup_checks(conn, director, school, monday):
    cancelled = sid(conn, "2026-10-19", school.maths)
    sessions.cancel(conn, director, cancelled, "Grève")
    timetable.add_slot(conn, director, SlotInput(school.physics, school.room_b, 2, "17:00",
                                                 "18:30"))  # P1 on Tuesday in Salle B
    with pytest.raises(BusinessRuleError) as exc:
        sessions.schedule_makeup(conn, director, cancelled, date(2026, 10, 20), "17h30", "19h",
                                 school.room_b)
    assert exc.value.message == t["slot.room_busy"].format(
        room="Salle B", day="20/10/2026", start="17:00", end="18:30", group="P1")
    with pytest.raises(BusinessRuleError) as exc:
        sessions.schedule_makeup(conn, director, cancelled, date(2026, 10, 20), "17h30", "19h",
                                 school.room_a, school.samia)
    assert exc.value.message == t["slot.teacher_busy"].format(
        teacher="Samia", day="20/10/2026", start="17:00", end="18:30", group="P1")
    with pytest.raises(ValidationError):  # outside opening hours (08:00-20:00)
        sessions.schedule_makeup(conn, director, cancelled, date(2026, 10, 20), "7h", "8h30",
                                 school.room_a)
    with pytest.raises(ValidationError) as exc:
        sessions.schedule_makeup(conn, director, cancelled, date(2027, 7, 2), "9h", "10h",
                                 school.room_a)
    assert exc.value.message == t["session.makeup_outside"].format(start="01/09/2026",
                                                                  end="30/06/2027")


def test_makeup_checks_the_students_other_groups(conn, director, school, monday):
    from tadris.domain.models import StudentInput
    from tadris.services import enrollments, registrations, students

    amine = students.create(conn, director, StudentInput("Amine", "Benali"))
    registrations.register(conn, director, amine, school.level, 0)
    enrollments.enroll(conn, director, amine, school.maths)
    enrollments.enroll(conn, director, amine, school.physics)
    timetable.add_slot(conn, director, SlotInput(school.physics, school.room_b, 2, "17:00",
                                                 "18:30"))
    cancelled = sid(conn, "2026-10-19", school.maths)
    sessions.cancel(conn, director, cancelled, "Grève")
    with pytest.raises(BusinessRuleError) as exc:
        sessions.schedule_makeup(conn, director, cancelled, date(2026, 10, 20), "18h", "19h",
                                 school.room_a)
    assert exc.value.message == t["slot.student_busy"].format(
        student="Benali Amine", day="20/10/2026", start="17:00", end="18:30", group="P1")


def test_a_substitute_for_one_session(conn, director, school, monday):
    session_id = sid(conn, "2026-10-19", school.maths)
    sessions.set_teacher(conn, director, session_id, school.nabil)
    s = sessions.get(conn, director, session_id)
    assert (s.teacher_id, s.substitute) == (school.nabil, True)
    other = sessions.get(conn, director, sid(conn, "2026-10-26", school.maths))
    assert (other.teacher_id, other.substitute) == (school.karim, False)
    sessions.set_teacher(conn, director, session_id, school.karim)  # back to the group's
    assert not sessions.get(conn, director, session_id).substitute
    entry = json.loads(conn.execute("SELECT new_value FROM audit_log WHERE action = "
                                    "'session.set_teacher' ORDER BY id DESC").fetchone()[0])
    assert entry == {"teacher_id": school.karim, "substitute": False}


def test_a_substitute_must_be_free(conn, director, school, monday):
    timetable.add_slot(conn, director, SlotInput(school.physics, school.room_b, 1, "17:30",
                                                 "19:00"))  # Samia teaches P1 on Mondays
    with pytest.raises(BusinessRuleError) as exc:
        sessions.set_teacher(conn, director, sid(conn, "2026-10-19", school.maths), school.samia)
    assert exc.value.message == t["slot.teacher_busy"].format(
        teacher="Samia", day="19/10/2026", start="17:30", end="19:00", group="P1")


def test_listing_by_date_group_and_teacher(conn, director, school, monday):
    timetable.add_slot(conn, director, SlotInput(school.physics, school.room_b, 3, "17:00",
                                                 "18:30"))
    week = sessions.listing(conn, director, date(2026, 10, 19), date(2026, 10, 25))
    assert [(s.date, s.group_name) for s in week] == [("2026-10-19", "M1"), ("2026-10-21", "P1")]
    assert [s.date for s in sessions.listing(conn, director, date(2026, 10, 19),
                                             date(2026, 10, 31), group_id=school.maths)] == [
        "2026-10-19", "2026-10-26"]
    assert [s.group_name for s in sessions.listing(conn, director, date(2026, 10, 19),
                                                   date(2026, 10, 31),
                                                   teacher_id=school.samia)] == ["P1", "P1"]


def test_closing_a_group_cancels_its_planned_makeups(conn, director, school, monday):
    cancelled = sid(conn, "2026-10-19", school.maths)
    sessions.cancel(conn, director, cancelled, "Grève")
    makeup_id = sessions.schedule_makeup(conn, director, cancelled, date(2026, 10, 24), "9h",
                                         "10h30", school.room_b)
    groups.close(conn, director, school.maths)
    m = sessions.get(conn, director, makeup_id)
    assert (m.status, m.cancellation_reason) == ("cancelled", t["session.group_closed_reason"])
    assert listed(conn) == [("2026-10-19", school.maths, "17:00", "cancelled"),
                            ("2026-10-24", school.maths, "09:00", "cancelled")]
