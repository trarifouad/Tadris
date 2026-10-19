import json
from datetime import date

import pytest

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, NotFound, PermissionDenied, ValidationError
from tadris.domain.models import GroupInput, SlotInput, StudentInput, TeacherInput
from tadris.i18n.fr import t
from tadris.services import (
    auth,
    catalog,
    enrollments,
    groups,
    registrations,
    rooms,
    school_years,
    students,
    teachers,
    timetable,
)

TODAY = date(2026, 10, 18)  # a Sunday


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
    """The open year, two levels, three subjects, a teacher per group, four groups."""

    def __init__(self, conn, ctx):
        self.year = school_years.create(conn, ctx, "2026-2027", date(2026, 9, 1),
                                        date(2027, 6, 30))
        self.l4am = catalog.create(conn, ctx, "level", "4AM")
        self.l3am = catalog.create(conn, ctx, "level", "3AM")
        maths = catalog.create(conn, ctx, "subject", "Maths")
        physics = catalog.create(conn, ctx, "subject", "Physique")
        french = catalog.create(conn, ctx, "subject", "Français")

        def group(name, level, subject, capacity=10, start=date(2026, 9, 1)):
            teacher = teachers.create(conn, ctx, TeacherInput(f"Prof {name}"), 6000,
                                      date(2026, 9, 1))
            return groups.create(conn, ctx, GroupInput(self.year, level, subject, name, 3000,
                                                       capacity, start), teacher)

        self.maths = group("M1", self.l4am, maths)
        self.physics = group("P1", self.l4am, physics)
        self.french = group("F1", self.l4am, french, start=date(2026, 11, 2))  # not started
        self.maths_3am = group("M3", self.l3am, maths)


@pytest.fixture
def school(conn, director):
    return School(conn, director)


@pytest.fixture
def amine(conn, director, school):
    """Registered in 4AM."""
    student = students.create(conn, director, StudentInput("Amine", "Benali"))
    registrations.register(conn, director, student, school.l4am, 2000)
    return student


def new_student(conn, ctx, school, first, level=None):
    student = students.create(conn, ctx, StudentInput(first, "Haddad"))
    registrations.register(conn, ctx, student, level or school.l4am, 0)
    return student


def last_audit(conn, action):
    row = conn.execute("SELECT new_value FROM audit_log WHERE action = ? ORDER BY id DESC",
                       (action,)).fetchone()
    return json.loads(row["new_value"])


def overrides_left(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM settings WHERE key LIKE 'override:%'"
                        ).fetchone()[0]


# ----- enroll -----

def test_receptionist_enrolls_a_registered_student(conn, receptionist, school, amine):
    enrollment_id = enrollments.enroll(conn, receptionist, amine, school.maths)
    e = enrollments.get(conn, receptionist, enrollment_id)
    assert (e.status, e.started_as_trial, e.enrolled_on) == ("active", False, "2026-10-18")
    assert e.group_title == "M1 · Maths 4AM"
    assert not e.other_level
    assert groups.get(conn, receptionist, school.maths).enrolled == 1
    assert last_audit(conn, "enrollment.create")["status"] == "active"


def test_one_student_in_several_groups(conn, receptionist, school, amine):
    for group in (school.maths, school.physics, school.french):
        enrollments.enroll(conn, receptionist, amine, group)
    live = [e for e in enrollments.for_student(conn, receptionist, amine) if e.is_live]
    assert {e.group_id for e in live} == {school.maths, school.physics, school.french}
    assert len({e.registration_id for e in live}) == 1  # one registration for all


def test_same_group_twice_at_once_is_refused(conn, receptionist, school, amine):
    enrollments.enroll(conn, receptionist, amine, school.maths)
    with pytest.raises(BusinessRuleError) as exc:
        enrollments.enroll(conn, receptionist, amine, school.maths)
    assert exc.value.message == t["enrollment.already_in"].format(group="M1 · Maths 4AM")


def test_cannot_enroll_without_registration(conn, receptionist, school):
    student = students.create(conn, receptionist, StudentInput("Sans", "Inscription"))
    with pytest.raises(BusinessRuleError) as exc:
        enrollments.enroll(conn, receptionist, student, school.maths)
    assert exc.value.message == t["enrollment.not_registered"].format(label="2026-2027")


def test_cancelled_registration_cannot_enroll(conn, director, school, amine):
    registrations.cancel(conn, director, registrations.current(conn, director, amine).id, "x")
    with pytest.raises(BusinessRuleError, match="inscription annuelle"):
        enrollments.enroll(conn, director, amine, school.maths)


def test_cannot_enroll_across_years(conn, director, school, amine):
    upcoming = school_years.create(conn, director, "2027-2028", date(2027, 9, 1),
                                   date(2028, 6, 30))
    teacher = teachers.create(conn, director, TeacherInput("Prof N"), 6000, date(2026, 9, 1))
    subject = catalog.create(conn, director, "subject", "Arabe")
    next_year = groups.create(conn, director, GroupInput(upcoming, school.l4am, subject, "A1",
                                                         3000, 10, date(2027, 9, 1)), teacher)
    with pytest.raises(BusinessRuleError) as exc:
        enrollments.enroll(conn, director, amine, next_year)
    assert exc.value.message == t["enrollment.group_other_year"].format(label="2026-2027")


def test_closed_group_is_refused(conn, director, school, amine):
    groups.close(conn, director, school.maths)
    with pytest.raises(BusinessRuleError, match="clôturé"):
        enrollments.enroll(conn, director, amine, school.maths)


def test_inactive_student_is_refused(conn, director, school, amine):
    students.deactivate(conn, director, amine)
    with pytest.raises(BusinessRuleError, match="désactivé"):
        enrollments.enroll(conn, director, amine, school.maths)


def test_unknown_student_or_group(conn, director, school, amine):
    with pytest.raises(NotFound):
        enrollments.enroll(conn, director, 999, school.maths)
    with pytest.raises(NotFound):
        enrollments.enroll(conn, director, amine, 999)


# ----- entry date -----

def test_joining_a_running_group_needs_no_override(conn, receptionist, school, amine):
    enrollment_id = enrollments.enroll(conn, receptionist, amine, school.maths,
                                       enrolled_on=date(2026, 10, 5))
    assert enrollments.get(conn, receptionist, enrollment_id).enrolled_on == "2026-10-05"


def test_group_not_started_defaults_to_its_first_day(conn, receptionist, school, amine):
    enrollment_id = enrollments.enroll(conn, receptionist, amine, school.french)
    assert enrollments.get(conn, receptionist, enrollment_id).enrolled_on == "2026-11-02"


@pytest.mark.parametrize("on", [date(2026, 8, 31), date(2027, 7, 1)])
def test_entry_date_between_group_start_and_year_end(conn, receptionist, school, amine, on):
    with pytest.raises(ValidationError) as exc:
        enrollments.enroll(conn, receptionist, amine, school.maths, enrolled_on=on)
    assert exc.value.message == t["enrollment.date_outside"].format(start="01/09/2026",
                                                                    end="30/06/2027")


def test_entry_date_cannot_precede_a_later_group_start(conn, receptionist, school, amine):
    with pytest.raises(ValidationError):
        enrollments.enroll(conn, receptionist, amine, school.french,
                           enrolled_on=date(2026, 10, 18))


# ----- trial -----

def test_trial_only_once_ever(conn, receptionist, school, amine):
    enrollment_id = enrollments.enroll(conn, receptionist, amine, school.maths, trial=True)
    e = enrollments.get(conn, receptionist, enrollment_id)
    assert (e.status, e.started_as_trial) == ("trial", True)
    assert not enrollments.can_take_trial(conn, amine)
    with pytest.raises(BusinessRuleError) as exc:
        enrollments.enroll(conn, receptionist, amine, school.physics, trial=True)
    assert exc.value.message == t["enrollment.trial_used"]
    enrollments.enroll(conn, receptionist, amine, school.physics)  # a paid enrollment is fine


def test_trial_takes_a_seat(conn, director, receptionist, school, amine):
    groups.update(conn, director, school.maths, GroupInput(
        school.year, school.l4am, groups.get(conn, director, school.maths).subject_id, "M1",
        3000, 1, date(2026, 9, 1)))
    enrollments.enroll(conn, receptionist, amine, school.maths, trial=True)
    other = new_student(conn, receptionist, school, "Yanis")
    with pytest.raises(BusinessRuleError, match="complet"):
        enrollments.enroll(conn, receptionist, other, school.maths)


# ----- seats -----

def test_full_group_names_its_seats(conn, director, receptionist, school, amine):
    subject = groups.get(conn, director, school.maths).subject_id
    groups.update(conn, director, school.maths, GroupInput(school.year, school.l4am, subject,
                                                           "M1", 3000, 2, date(2026, 9, 1)))
    enrollments.enroll(conn, receptionist, amine, school.maths)
    enrollments.enroll(conn, receptionist, new_student(conn, receptionist, school, "Yanis"),
                       school.maths)
    with pytest.raises(BusinessRuleError) as exc:
        enrollments.enroll(conn, receptionist, new_student(conn, receptionist, school, "Lina"),
                           school.maths)
    assert exc.value.message == t["enrollment.full"].format(group="M1 · Maths 4AM", seats=2)


def test_small_room_names_the_room(conn, director, receptionist, school, amine):
    small = rooms.create(conn, director, "Salle C", 1)
    timetable.add_slot(conn, director, SlotInput(school.maths, small, 1, "17:00", "18:30"))
    enrollments.enroll(conn, receptionist, amine, school.maths)
    with pytest.raises(BusinessRuleError) as exc:
        enrollments.enroll(conn, receptionist, new_student(conn, receptionist, school, "Yanis"),
                           school.maths)
    assert exc.value.message == t["enrollment.room_full"].format(
        group="M1 · Maths 4AM", room="Salle C", seats=1)


def test_a_student_who_left_frees_the_seat_and_can_come_back(conn, director, receptionist,
                                                             school, amine):
    subject = groups.get(conn, director, school.maths).subject_id
    groups.update(conn, director, school.maths, GroupInput(school.year, school.l4am, subject,
                                                           "M1", 3000, 1, date(2026, 9, 1)))
    first = enrollments.enroll(conn, receptionist, amine, school.maths)
    conn.execute("UPDATE enrollments SET status = 'left', left_on = '2026-10-18' WHERE id = ?",
                 (first,))  # the leave service comes in task 4
    again = enrollments.enroll(conn, receptionist, amine, school.maths)
    assert again != first
    history = enrollments.for_student(conn, receptionist, amine)
    assert [e.status for e in history] == ["active", "left"]


# ----- level override -----

def test_other_level_is_refused_for_the_front_desk(conn, receptionist, school, amine):
    with pytest.raises(BusinessRuleError) as exc:
        enrollments.enroll(conn, receptionist, amine, school.maths_3am)
    assert exc.value.message == t["enrollment.level_mismatch"].format(
        group="M3 · Maths 3AM", group_level="3AM", level="4AM")
    with pytest.raises(PermissionDenied):
        enrollments.enroll(conn, receptionist, amine, school.maths_3am,
                           override_reason="Redouble en maths")
    assert overrides_left(conn) == 0


def test_director_override_needs_a_reason(conn, director, school, amine):
    with pytest.raises(ValidationError) as exc:
        enrollments.enroll(conn, director, amine, school.maths_3am, override_reason="  ")
    assert exc.value.message == t["enrollment.override_reason_required"]


def test_director_override_is_audited_and_never_left_set(conn, director, school, amine):
    enrollment_id = enrollments.enroll(conn, director, amine, school.maths_3am,
                                       override_reason="Rattrapage en maths")
    assert overrides_left(conn) == 0
    e = enrollments.get(conn, director, enrollment_id)
    assert e.other_level and (e.group_level, e.registration_level) == ("3AM", "4AM")
    entry = last_audit(conn, "enrollment.create")
    assert (entry["overrides"], entry["reason"]) == (["level"], "Rattrapage en maths")
    # Without the key, the database still refuses a level mismatch on its own.
    with pytest.raises(Exception, match="level"):
        conn.execute("INSERT INTO enrollments(student_id, group_id, registration_id, "
                     "enrolled_on) VALUES (?, ?, ?, '2026-10-18')",
                     (amine, school.maths_3am, e.registration_id))


def test_failed_override_leaves_no_key(conn, director, school, amine):
    subject = groups.get(conn, director, school.maths_3am).subject_id
    groups.update(conn, director, school.maths_3am, GroupInput(
        school.year, school.l3am, subject, "M3", 3000, 1, date(2026, 9, 1)))
    enrollments.enroll(conn, director, new_student(conn, director, school, "Sami", school.l3am),
                       school.maths_3am)
    with pytest.raises(BusinessRuleError):
        enrollments.enroll(conn, director, amine, school.maths_3am, override_reason="motif")
    assert overrides_left(conn) == 0


def test_reason_is_ignored_when_levels_match(conn, director, school, amine):
    enrollments.enroll(conn, director, amine, school.maths, override_reason="inutile")
    assert "overrides" not in last_audit(conn, "enrollment.create")


# ----- options for the dialog -----

def test_options_list_open_groups_same_level_first(conn, director, receptionist, school, amine):
    enrollments.enroll(conn, receptionist, amine, school.maths)
    groups.close(conn, director, school.physics)
    found = {o.group.id: o for o in enrollments.options(conn, receptionist, amine)}
    assert school.physics not in found  # closed
    order = [o.group.id for o in enrollments.options(conn, receptionist, amine)]
    assert order[-1] == school.maths_3am
    assert found[school.maths].already_in and not found[school.maths].available
    assert found[school.french].available and found[school.french].free == 10
    assert not found[school.maths_3am].same_level


def test_options_empty_without_registration(conn, receptionist, school):
    student = students.create(conn, receptionist, StudentInput("Sans", "Inscription"))
    assert enrollments.options(conn, receptionist, student) == []


def test_group_list_shows_its_students(conn, receptionist, school, amine):
    yanis = new_student(conn, receptionist, school, "Yanis")
    enrollments.enroll(conn, receptionist, yanis, school.maths, trial=True)
    enrollments.enroll(conn, receptionist, amine, school.maths)
    listed = enrollments.for_group(conn, receptionist, school.maths)
    assert [(e.student_name, e.status) for e in listed] == [("Benali Amine", "active"),
                                                            ("Haddad Yanis", "trial")]


# ----- confirm a trial -----

def test_confirm_trial_keeps_the_seat_and_the_trial_flag(conn, director, receptionist, school,
                                                         amine):
    subject = groups.get(conn, director, school.maths).subject_id
    groups.update(conn, director, school.maths, GroupInput(school.year, school.l4am, subject,
                                                           "M1", 3000, 1, date(2026, 9, 1)))
    enrollment_id = enrollments.enroll(conn, receptionist, amine, school.maths, trial=True)
    enrollments.confirm_trial(conn, receptionist, enrollment_id)  # full group: same seat
    e = enrollments.get(conn, receptionist, enrollment_id)
    assert (e.status, e.started_as_trial) == ("active", True)
    assert not enrollments.can_take_trial(conn, amine)
    with pytest.raises(BusinessRuleError) as exc:
        enrollments.confirm_trial(conn, receptionist, enrollment_id)
    assert exc.value.message == t["enrollment.not_trial"]
    assert last_audit(conn, "enrollment.confirm_trial") == {"status": "active"}


# ----- leave -----

def test_leave_frees_the_seat_and_keeps_history(conn, receptionist, school, amine):
    enrollment_id = enrollments.enroll(conn, receptionist, amine, school.maths,
                                       enrolled_on=date(2026, 9, 15))
    enrollments.leave(conn, receptionist, enrollment_id, date(2026, 10, 10), " Déménagement ")
    e = enrollments.get(conn, receptionist, enrollment_id)
    assert (e.status, e.left_on, e.is_live) == ("left", "2026-10-10", False)
    assert groups.get(conn, receptionist, school.maths).enrolled == 0
    assert last_audit(conn, "enrollment.leave") == {
        "status": "left", "left_on": "2026-10-10", "reason": "Déménagement"}
    with pytest.raises(BusinessRuleError) as exc:
        enrollments.leave(conn, receptionist, enrollment_id)
    assert exc.value.message == t["enrollment.not_live"]


def test_leave_defaults_to_today(conn, receptionist, school, amine):
    enrollment_id = enrollments.enroll(conn, receptionist, amine, school.maths)
    enrollments.leave(conn, receptionist, enrollment_id)
    assert enrollments.get(conn, receptionist, enrollment_id).left_on == "2026-10-18"


def test_a_trial_not_followed_up_leaves(conn, receptionist, school, amine):
    enrollment_id = enrollments.enroll(conn, receptionist, amine, school.maths, trial=True)
    enrollments.leave(conn, receptionist, enrollment_id)
    assert enrollments.get(conn, receptionist, enrollment_id).status == "left"
    with pytest.raises(BusinessRuleError, match="essai"):  # the trial stays used
        enrollments.enroll(conn, receptionist, amine, school.physics, trial=True)


def test_leaving_date_rules(conn, receptionist, school, amine):
    enrollment_id = enrollments.enroll(conn, receptionist, amine, school.maths,
                                       enrolled_on=date(2026, 10, 1))
    with pytest.raises(ValidationError) as exc:
        enrollments.leave(conn, receptionist, enrollment_id, date(2026, 10, 19))
    assert exc.value.message == t["enrollment.leave_future"]
    with pytest.raises(ValidationError) as exc:
        enrollments.leave(conn, receptionist, enrollment_id, date(2026, 9, 30))
    assert exc.value.message == t["enrollment.leave_before_entry"].format(date="01/10/2026")
    enrollments.leave(conn, receptionist, enrollment_id, date(2026, 10, 1))  # same day is fine


def test_leaving_date_not_before_a_recorded_attendance(conn, director, receptionist, school,
                                                       amine):
    enrollment_id = enrollments.enroll(conn, receptionist, amine, school.maths,
                                       enrolled_on=date(2026, 10, 1))
    room = rooms.create(conn, director, "Salle A", 20)
    teacher = groups.get(conn, director, school.maths).teacher_id
    session = conn.execute(
        "INSERT INTO sessions(group_id, room_id, teacher_id, date, start_time, end_time) "
        "VALUES (?, ?, ?, '2026-10-12', '17:00', '18:30')",
        (school.maths, room, teacher)).lastrowid
    conn.execute("INSERT INTO attendances(session_id, enrollment_id, status, entered_by) "
                 "VALUES (?, ?, 'present', ?)", (session, enrollment_id, director.user_id))
    with pytest.raises(ValidationError) as exc:
        enrollments.leave(conn, receptionist, enrollment_id, date(2026, 10, 11))
    assert exc.value.message == t["enrollment.leave_before_attendance"].format(
        date="12/10/2026")
    enrollments.leave(conn, receptionist, enrollment_id, date(2026, 10, 12))


def test_left_group_in_a_closed_group_stays_left(conn, director, receptionist, school, amine):
    enrollment_id = enrollments.enroll(conn, receptionist, amine, school.maths)
    enrollments.leave(conn, receptionist, enrollment_id)
    groups.close(conn, director, school.maths)
    assert enrollments.get(conn, receptionist, enrollment_id).left_on == "2026-10-18"


# ----- switch -----

def test_switch_keeps_history_and_links_both(conn, receptionist, school, amine):
    old_id = enrollments.enroll(conn, receptionist, amine, school.maths,
                                enrolled_on=date(2026, 9, 15))
    new_id = enrollments.switch(conn, receptionist, old_id, school.physics, date(2026, 10, 12))
    old = enrollments.get(conn, receptionist, old_id)
    new = enrollments.get(conn, receptionist, new_id)
    assert (old.status, old.left_on) == ("switched", "2026-10-12")
    assert (new.status, new.enrolled_on, new.switched_from_id) == ("active", "2026-10-12",
                                                                   old_id)
    assert new.registration_id == old.registration_id
    assert groups.get(conn, receptionist, school.maths).enrolled == 0
    assert groups.get(conn, receptionist, school.physics).enrolled == 1
    entry = conn.execute("SELECT old_value, new_value FROM audit_log "
                         "WHERE action = 'enrollment.switch'").fetchone()
    assert json.loads(entry["old_value"])["group_id"] == school.maths
    assert json.loads(entry["new_value"])["switched_from_id"] == old_id


def test_switch_of_a_trial_stays_a_trial_without_a_second_trial(conn, receptionist, school,
                                                                amine):
    old_id = enrollments.enroll(conn, receptionist, amine, school.maths, trial=True)
    new_id = enrollments.switch(conn, receptionist, old_id, school.physics)
    new = enrollments.get(conn, receptionist, new_id)
    assert (new.status, new.started_as_trial) == ("trial", False)
    enrollments.confirm_trial(conn, receptionist, new_id)
    assert enrollments.get(conn, receptionist, new_id).status == "active"


def test_switch_to_a_group_not_started_enters_on_its_first_day(conn, receptionist, school,
                                                               amine):
    old_id = enrollments.enroll(conn, receptionist, amine, school.maths)
    new_id = enrollments.switch(conn, receptionist, old_id, school.french)
    assert enrollments.get(conn, receptionist, old_id).left_on == "2026-10-18"
    assert enrollments.get(conn, receptionist, new_id).enrolled_on == "2026-11-02"


def test_switch_to_the_same_group_is_refused(conn, receptionist, school, amine):
    old_id = enrollments.enroll(conn, receptionist, amine, school.maths)
    with pytest.raises(ValidationError) as exc:
        enrollments.switch(conn, receptionist, old_id, school.maths)
    assert exc.value.message == t["enrollment.same_group"]


def test_failed_switch_changes_nothing(conn, director, receptionist, school, amine):
    subject = groups.get(conn, director, school.physics).subject_id
    groups.update(conn, director, school.physics, GroupInput(school.year, school.l4am, subject,
                                                             "P1", 3000, 1, date(2026, 9, 1)))
    enrollments.enroll(conn, receptionist, new_student(conn, receptionist, school, "Yanis"),
                       school.physics)
    old_id = enrollments.enroll(conn, receptionist, amine, school.maths)
    with pytest.raises(BusinessRuleError, match="complet"):
        enrollments.switch(conn, receptionist, old_id, school.physics)
    assert enrollments.get(conn, receptionist, old_id).status == "active"


def test_switch_to_a_group_the_student_is_already_in(conn, receptionist, school, amine):
    enrollments.enroll(conn, receptionist, amine, school.physics)
    old_id = enrollments.enroll(conn, receptionist, amine, school.maths)
    with pytest.raises(BusinessRuleError, match="déjà dans le groupe"):
        enrollments.switch(conn, receptionist, old_id, school.physics)
    assert enrollments.get(conn, receptionist, old_id).status == "active"


def test_switch_to_another_level_needs_the_director(conn, director, receptionist, school,
                                                    amine):
    old_id = enrollments.enroll(conn, receptionist, amine, school.maths)
    with pytest.raises(BusinessRuleError, match="Seul le directeur"):
        enrollments.switch(conn, receptionist, old_id, school.maths_3am)
    new_id = enrollments.switch(conn, director, old_id, school.maths_3am,
                                override_reason="Niveau trop difficile")
    assert enrollments.get(conn, director, new_id).other_level
    assert overrides_left(conn) == 0


def test_switch_out_of_a_level_override_group(conn, director, receptionist, school, amine):
    """Leaving the override group works for the desk: only the new group's level counts."""
    old_id = enrollments.enroll(conn, director, amine, school.maths_3am, override_reason="x")
    new_id = enrollments.switch(conn, receptionist, old_id, school.maths)
    assert not enrollments.get(conn, receptionist, new_id).other_level


def test_switch_date_rules(conn, receptionist, school, amine):
    old_id = enrollments.enroll(conn, receptionist, amine, school.maths,
                                enrolled_on=date(2026, 10, 1))
    with pytest.raises(ValidationError, match="futur"):
        enrollments.switch(conn, receptionist, old_id, school.physics, date(2026, 10, 20))
    with pytest.raises(ValidationError, match="avant la date d'entrée"):
        enrollments.switch(conn, receptionist, old_id, school.physics, date(2026, 9, 20))


def test_switched_twice_keeps_the_chain(conn, receptionist, school, amine):
    first = enrollments.enroll(conn, receptionist, amine, school.maths)
    second = enrollments.switch(conn, receptionist, first, school.physics)
    third = enrollments.switch(conn, receptionist, second, school.maths)
    assert enrollments.get(conn, receptionist, third).switched_from_id == second
    assert enrollments.get(conn, receptionist, second).switched_from_id == first
    statuses = [e.status for e in enrollments.for_student(conn, receptionist, amine)]
    assert statuses.count("switched") == 2 and statuses.count("active") == 1


# ----- closing a group or a year -----

def test_closing_a_group_makes_its_students_leave_today(conn, director, receptionist, school,
                                                        amine):
    yanis = new_student(conn, receptionist, school, "Yanis")
    a = enrollments.enroll(conn, receptionist, amine, school.maths)
    y = enrollments.enroll(conn, receptionist, yanis, school.maths, trial=True)
    enrollments.enroll(conn, receptionist, amine, school.physics)
    groups.close(conn, director, school.maths)
    for enrollment_id in (a, y):
        e = enrollments.get(conn, director, enrollment_id)
        assert (e.status, e.left_on) == ("left", "2026-10-18")
    assert groups.get(conn, director, school.physics).enrolled == 1  # other groups untouched
    entry = last_audit(conn, "group.close")
    assert entry["students_left"] == 2
    # Yanis was only in that group: with no group left, he can now be deactivated.
    students.deactivate(conn, director, yanis)


def test_closing_a_group_not_started_leaves_on_the_entry_date(conn, director, receptionist,
                                                              school, amine):
    enrollment_id = enrollments.enroll(conn, receptionist, amine, school.french)
    groups.close(conn, director, school.french)
    assert enrollments.get(conn, director, enrollment_id).left_on == "2026-11-02"


def test_reopening_a_group_does_not_bring_students_back(conn, director, receptionist, school,
                                                        amine):
    enrollments.enroll(conn, receptionist, amine, school.maths)
    groups.close(conn, director, school.maths)
    groups.reopen(conn, director, school.maths)
    assert groups.get(conn, director, school.maths).enrolled == 0
    enrollments.enroll(conn, receptionist, amine, school.maths)  # can be enrolled again


def test_closing_the_year_makes_every_student_leave(conn, director, receptionist, school,
                                                    amine):
    enrollments.enroll(conn, receptionist, amine, school.maths)
    enrollments.enroll(conn, receptionist, amine, school.physics, trial=True)
    school_years.close(conn, director, school.year)
    assert all(e.status == "left" for e in enrollments.for_student(conn, director, amine))


# ----- one subject once, one place at a time -----

def second_maths(conn, ctx, school, name="M2"):
    teacher = teachers.create(conn, ctx, TeacherInput(f"Prof {name}"), 6000, date(2026, 9, 1))
    subject = groups.get(conn, ctx, school.maths).subject_id
    return groups.create(conn, ctx, GroupInput(school.year, school.l4am, subject, name, 3000,
                                               10, date(2026, 9, 1)), teacher)


def test_second_group_of_a_subject_is_refused_for_the_desk(conn, director, receptionist,
                                                           school, amine):
    m2 = second_maths(conn, director, school)
    enrollments.enroll(conn, receptionist, amine, school.maths)
    with pytest.raises(BusinessRuleError) as exc:
        enrollments.enroll(conn, receptionist, amine, m2)
    assert exc.value.message == t["enrollment.same_subject"].format(
        subject="Maths", level="4AM", other="M1")
    assert "Changer de groupe" in exc.value.message


def test_director_allows_a_second_group_of_a_subject_with_a_reason(conn, director, school,
                                                                   amine):
    m2 = second_maths(conn, director, school)
    enrollments.enroll(conn, director, amine, school.maths)
    with pytest.raises(ValidationError):
        enrollments.enroll(conn, director, amine, m2)
    enrollments.enroll(conn, director, amine, m2, override_reason="Soutien renforcé")
    entry = last_audit(conn, "enrollment.create")
    assert (entry["overrides"], entry["reason"]) == (["same_subject"], "Soutien renforcé")
    assert overrides_left(conn) == 0


def test_switching_within_a_subject_needs_no_override(conn, director, receptionist, school,
                                                      amine):
    m2 = second_maths(conn, director, school)
    old = enrollments.enroll(conn, receptionist, amine, school.maths)
    new = enrollments.switch(conn, receptionist, old, m2)
    assert enrollments.get(conn, receptionist, new).group_id == m2


def test_same_subject_at_another_level_is_only_a_level_override(conn, director, school, amine):
    enrollments.enroll(conn, director, amine, school.maths)
    enrollments.enroll(conn, director, amine, school.maths_3am, override_reason="Rattrapage")
    assert last_audit(conn, "enrollment.create")["overrides"] == ["level"]


def test_a_left_group_no_longer_counts_for_its_subject(conn, director, receptionist, school,
                                                       amine):
    m2 = second_maths(conn, director, school)
    first = enrollments.enroll(conn, receptionist, amine, school.maths)
    enrollments.leave(conn, receptionist, first)
    enrollments.enroll(conn, receptionist, amine, m2)


def test_options_flag_a_subject_already_taken(conn, director, receptionist, school, amine):
    m2 = second_maths(conn, director, school)
    current = enrollments.enroll(conn, receptionist, amine, school.maths)
    found = {o.group.id: o for o in enrollments.options(conn, receptionist, amine)}
    assert found[m2].same_subject and found[m2].needs_override
    assert not found[school.maths].same_subject  # the group itself: already_in
    assert not found[school.physics].same_subject
    # In the switch dialog, the group being left does not count.
    leaving = {o.group.id: o for o in enrollments.options(conn, receptionist, amine,
                                                          leaving_group_id=school.maths)}
    assert not leaving[m2].same_subject and not leaving[school.maths].already_in
    assert current


def slot(conn, ctx, group_id, room, weekday=1, start="17:00", end="18:30"):
    return timetable.add_slot(conn, ctx, SlotInput(group_id, room, weekday, start, end))


def test_time_clash_between_two_groups_is_refused(conn, director, receptionist, school, amine):
    a, b = rooms.create(conn, director, "Salle A", 20), rooms.create(conn, director, "Salle B", 20)
    slot(conn, director, school.maths, a, 1, "17:00", "18:30")
    slot(conn, director, school.physics, b, 1, "18:00", "19:30")
    enrollments.enroll(conn, receptionist, amine, school.maths)
    with pytest.raises(BusinessRuleError) as exc:
        enrollments.enroll(conn, receptionist, amine, school.physics)
    assert exc.value.message == t["enrollment.time_clash"].format(
        group="P1 · Physique 4AM", day=t["weekday.1"], start="18:00", end="19:30",
        other="M1 · Maths 4AM", other_start="17:00", other_end="18:30")
    with pytest.raises(BusinessRuleError, match="Conflit d'horaire"):  # no override for this
        enrollments.enroll(conn, director, amine, school.physics, override_reason="x")


def test_back_to_back_or_other_day_is_fine(conn, director, receptionist, school, amine):
    a, b = rooms.create(conn, director, "Salle A", 20), rooms.create(conn, director, "Salle B", 20)
    slot(conn, director, school.maths, a, 1, "17:00", "18:30")
    slot(conn, director, school.physics, b, 1, "18:30", "20:00")  # right after
    slot(conn, director, school.french, b, 2, "17:00", "18:30")  # another day
    for group in (school.maths, school.physics, school.french):
        enrollments.enroll(conn, receptionist, amine, group)


def test_switch_ignores_the_group_being_left(conn, director, receptionist, school, amine):
    a, b = rooms.create(conn, director, "Salle A", 20), rooms.create(conn, director, "Salle B", 20)
    slot(conn, director, school.maths, a, 1, "17:00", "18:30")
    slot(conn, director, school.physics, b, 1, "17:30", "19:00")
    old = enrollments.enroll(conn, receptionist, amine, school.maths)
    enrollments.switch(conn, receptionist, old, school.physics)


def test_new_slot_cannot_clash_with_a_students_other_group(conn, director, receptionist,
                                                           school, amine):
    a, b = rooms.create(conn, director, "Salle A", 20), rooms.create(conn, director, "Salle B", 20)
    slot(conn, director, school.maths, a, 1, "17:00", "18:30")
    enrollments.enroll(conn, receptionist, amine, school.maths)
    enrollments.enroll(conn, receptionist, amine, school.physics)
    with pytest.raises(BusinessRuleError) as exc:
        slot(conn, receptionist, school.physics, b, 1, "18:00", "19:30")
    assert exc.value.message == t["slot.student_busy"].format(
        student="Benali Amine", day=t["weekday.1"], start="17:00", end="18:30", group="M1")
    yanis = new_student(conn, receptionist, school, "Yanis")
    enrollments.enroll(conn, receptionist, yanis, school.maths)
    enrollments.enroll(conn, receptionist, yanis, school.physics)
    with pytest.raises(BusinessRuleError) as exc:
        slot(conn, receptionist, school.physics, b, 1, "18:00", "19:30")
    assert exc.value.message == t["slot.students_busy"].format(
        student="Benali Amine", others=1, day=t["weekday.1"], start="17:00", end="18:30",
        group="M1")
    slot(conn, receptionist, school.physics, b, 1, "18:30", "20:00")  # after maths: fine


def test_moving_a_slot_onto_a_students_other_group_is_refused(conn, director, receptionist,
                                                              school, amine):
    a, b = rooms.create(conn, director, "Salle A", 20), rooms.create(conn, director, "Salle B", 20)
    slot(conn, director, school.maths, a, 1, "17:00", "18:30")
    physics_slot = slot(conn, director, school.physics, b, 2, "17:00", "18:30")
    enrollments.enroll(conn, receptionist, amine, school.maths)
    enrollments.enroll(conn, receptionist, amine, school.physics)
    with pytest.raises(BusinessRuleError, match="Benali Amine"):
        timetable.update_slot(conn, receptionist, physics_slot,
                              SlotInput(school.physics, b, 1, "17:00", "18:30"))


def test_a_student_who_left_does_not_block_the_timetable(conn, director, receptionist, school,
                                                         amine):
    a, b = rooms.create(conn, director, "Salle A", 20), rooms.create(conn, director, "Salle B", 20)
    slot(conn, director, school.maths, a, 1, "17:00", "18:30")
    m = enrollments.enroll(conn, receptionist, amine, school.maths)
    enrollments.enroll(conn, receptionist, amine, school.physics)
    enrollments.leave(conn, receptionist, m)
    slot(conn, receptionist, school.physics, b, 1, "17:00", "18:30")
