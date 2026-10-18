import json
import sqlite3
from datetime import date, timedelta

import pytest

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, NotFound, PermissionDenied, ValidationError
from tadris.domain.models import GroupInput, SlotInput, TeacherInput
from tadris.i18n.fr import t
from tadris.services import (
    auth,
    catalog,
    groups,
    rooms,
    school_years,
    settings,
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
    """A year, two levels, two subjects, two rooms and two teachers."""

    def __init__(self, conn, ctx):
        self.year = school_years.create(conn, ctx, "2026-2027", date(2026, 9, 1),
                                        date(2027, 6, 30))
        self.level_4am = catalog.create(conn, ctx, "level", "4AM")
        self.level_3as = catalog.create(conn, ctx, "level", "3AS")
        self.maths = catalog.create(conn, ctx, "subject", "Mathématiques")
        self.physics = catalog.create(conn, ctx, "subject", "Physique")
        self.room_a = rooms.create(conn, ctx, "Salle A", 20)
        self.room_b = rooms.create(conn, ctx, "Salle B", 12)
        self.karim = teachers.create(conn, ctx, TeacherInput("Karim Haddad", "0661 11 22 33"),
                                     6000, date(2026, 9, 1))
        self.samia = teachers.create(conn, ctx, TeacherInput("Samia Rahmani"), 5000,
                                     date(2026, 9, 1))


@pytest.fixture
def school(conn, director):
    return School(conn, director)


def group_input(school, name="G1", level=None, subject=None, price=3000, capacity=12,
                start=date(2026, 9, 15), year=None) -> GroupInput:
    return GroupInput(year or school.year, level or school.level_4am, subject or school.maths,
                      name, price, capacity, start)


@pytest.fixture
def g1(conn, director, school):
    return groups.create(conn, director, group_input(school), school.karim)


def slot(group_id, room_id, weekday=2, start="17:00", end="18:30", valid_from=None):
    return SlotInput(group_id, room_id, weekday, start, end, valid_from)


def next_weekday(weekday: int, after: date = TODAY) -> date:
    days = (weekday - dates.weekday_1_to_7(after)) % 7 or 7
    return after + timedelta(days=days)


def add_session(conn, slot_id):
    """A generated session for the slot's next occurrence (phase 6 will do this)."""
    row = conn.execute(
        "SELECT s.group_id, s.room_id, s.weekday, s.start_time, s.end_time, gt.teacher_id "
        "FROM timetable_slots s JOIN group_teachers gt ON gt.group_id = s.group_id "
        "AND gt.valid_to IS NULL WHERE s.id = ?", (slot_id,)).fetchone()
    conn.execute(
        "INSERT INTO sessions(group_id, slot_id, room_id, teacher_id, date, start_time, end_time)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (row["group_id"], slot_id, row["room_id"], row["teacher_id"],
         dates.iso(next_weekday(row["weekday"])), row["start_time"], row["end_time"]),
    )


def enroll(conn, school, group_id, count):
    """Put `count` new students in a group (phase 4 will have a service for this)."""
    for _ in range(count):
        n = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0] + 1
        student = conn.execute(
            "INSERT INTO students(student_number, first_name, last_name) VALUES (?, 'E', ?)",
            (f"2026-{n:04d}", f"N{n}")).lastrowid
        registration = conn.execute(
            "INSERT INTO registrations(student_id, school_year_id, level_id, fee_amount) "
            "VALUES (?, ?, ?, 0)", (student, school.year, school.level_4am)).lastrowid
        conn.execute(
            "INSERT INTO enrollments(student_id, group_id, registration_id, enrolled_on) "
            "VALUES (?, ?, ?, '2026-09-15')", (student, group_id, registration))


def actions(conn) -> list[str]:
    return [r[0] for r in conn.execute("SELECT action FROM audit_log ORDER BY id")]


# ----- school years -----

def test_first_year_opens_next_one_waits(conn, director):
    first = school_years.create(conn, director, "2026-2027", date(2026, 9, 1), date(2027, 6, 30))
    upcoming = school_years.create(conn, director, "2027-2028", date(2027, 9, 1),
                                   date(2028, 6, 30))
    past = school_years.create(conn, director, "2025-2026", date(2025, 9, 1), date(2026, 6, 30))
    states = {y.label: y.state for y in school_years.list_years(conn, director)}
    assert states == {"2026-2027": "open", "2027-2028": "upcoming", "2025-2026": "closed"}
    assert school_years.current(conn, director).id == first
    assert [y.id for y in school_years.usable(conn, director)] == [upcoming, first]
    assert past


@pytest.mark.parametrize("label, start, end, key", [
    ("  ", date(2026, 9, 1), date(2027, 6, 30), "year.label_required"),
    ("2026-2027", date(2027, 6, 30), date(2026, 9, 1), "year.dates_order"),
])
def test_year_validation(conn, director, label, start, end, key):
    with pytest.raises(ValidationError) as exc:
        school_years.create(conn, director, label, start, end)
    assert exc.value.message == t[key]


def test_year_overlap_and_duplicate_label(conn, director):
    school_years.create(conn, director, "2026-2027", date(2026, 9, 1), date(2027, 6, 30))
    with pytest.raises(ValidationError) as exc:
        school_years.create(conn, director, "Été 2027", date(2027, 6, 30), date(2027, 8, 31))
    assert exc.value.message == t["year.overlap"].format(label="2026-2027")
    with pytest.raises(ValidationError) as exc:
        school_years.create(conn, director, "2026-2027", date(2030, 9, 1), date(2031, 6, 30))
    assert exc.value.message == t["year.label_taken"]
    school_years.create(conn, director, "Été 2027", date(2027, 7, 1), date(2027, 8, 31))


def test_only_one_open_year(conn, director):
    school_years.create(conn, director, "2026-2027", date(2026, 9, 1), date(2027, 6, 30))
    upcoming = school_years.create(conn, director, "2027-2028", date(2027, 9, 1),
                                   date(2028, 6, 30))
    with pytest.raises(BusinessRuleError) as exc:
        school_years.open_year(conn, director, upcoming)
    assert exc.value.message == t["year.other_open"].format(label="2026-2027")
    # The database refuses it too.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE school_years SET status = 'open' WHERE id = ?", (upcoming,))


def test_close_year_closes_groups_and_frees_rooms(conn, director, school, g1):
    timetable.add_slot(conn, director, slot(g1, school.room_a))
    assert school_years.close(conn, director, school.year) == 1
    assert groups.get(conn, director, g1).status == "closed"
    assert timetable.week(conn, director, next_weekday(2), room_id=school.room_a) == []
    # Next year opens and reuses the room at the same hour.
    next_year = school_years.create(conn, director, "2027-2028", date(2027, 9, 1),
                                    date(2028, 6, 30))
    assert school_years.get(conn, director, next_year).state == "open"
    g2 = groups.create(conn, director, group_input(school, year=next_year,
                                                   start=date(2027, 9, 15)), school.karim)
    timetable.add_slot(conn, director, slot(g2, school.room_a))
    with pytest.raises(BusinessRuleError) as exc:
        school_years.close(conn, director, school.year)
    assert exc.value.message == t["year.not_open"]


def test_year_dates_cannot_leave_groups_outside(conn, director, school, g1):
    with pytest.raises(BusinessRuleError) as exc:
        school_years.update(conn, director, school.year, "2026-2027", date(2026, 10, 1),
                            date(2027, 6, 30))
    assert exc.value.message == t["year.groups_outside"]
    school_years.update(conn, director, school.year, "2026/2027", date(2026, 9, 1),
                        date(2027, 7, 15))
    assert school_years.get(conn, director, school.year).label == "2026/2027"


def test_receptionist_reads_but_cannot_manage_setup(conn, receptionist, school):
    assert [y.label for y in school_years.list_years(conn, receptionist)] == ["2026-2027"]
    assert len(rooms.list_rooms(conn, receptionist)) == 2
    for call in (
        lambda: school_years.create(conn, receptionist, "X", date(2030, 9, 1), date(2031, 6, 1)),
        lambda: catalog.create(conn, receptionist, "level", "1AM"),
        lambda: rooms.create(conn, receptionist, "Salle C", 10),
        lambda: teachers.create(conn, receptionist, TeacherInput("T"), 5000),
        lambda: groups.create(conn, receptionist, group_input(school), school.karim),
    ):
        with pytest.raises(PermissionDenied):
            call()


# ----- levels and subjects -----

def test_levels_keep_their_order_and_move(conn, director, school):
    first_am = catalog.create(conn, director, "level", "1AM")
    names = lambda: [i.name for i in catalog.list_items(conn, director, "level")]
    assert names() == ["4AM", "3AS", "1AM"]
    catalog.move_level(conn, director, first_am, -1)
    catalog.move_level(conn, director, first_am, -1)
    catalog.move_level(conn, director, first_am, -1)  # already first: no-op
    assert names() == ["1AM", "4AM", "3AS"]
    catalog.move_level(conn, director, school.level_4am, +1)
    assert names() == ["1AM", "3AS", "4AM"]


def test_names_are_unique_ignoring_case_and_accents(conn, director, school):
    with pytest.raises(ValidationError) as exc:
        catalog.create(conn, director, "subject", "mathematiques")
    assert exc.value.message == t["name.taken"]
    with pytest.raises(ValidationError):
        catalog.rename(conn, director, "level", school.level_3as, "4am")
    catalog.rename(conn, director, "subject", school.maths, "Maths")
    assert "subject.rename" in actions(conn)


def test_inactive_level_is_hidden_and_refused_for_new_groups(conn, director, school):
    catalog.set_active(conn, director, "level", school.level_3as, False)
    active = [i.name for i in catalog.list_items(conn, director, "level", active_only=True)]
    assert active == ["4AM"]
    with pytest.raises(ValidationError) as exc:
        groups.create(conn, director, group_input(school, level=school.level_3as), school.karim)
    assert exc.value.message == t["level.inactive"]


# ----- rooms -----

def test_room_validation(conn, director, school):
    with pytest.raises(ValidationError) as exc:
        rooms.create(conn, director, "salle a", 10)
    assert exc.value.message == t["name.taken"]
    with pytest.raises(ValidationError) as exc:
        rooms.create(conn, director, "Salle C", 0)
    assert exc.value.message == t["room.capacity_invalid"]


def test_room_cannot_shrink_below_the_students_using_it(conn, director, school, g1):
    timetable.add_slot(conn, director, slot(g1, school.room_a))
    enroll(conn, school, g1, 6)
    rooms.update(conn, director, school.room_a, "Salle A", 6)  # below the group's 12 places
    with pytest.raises(BusinessRuleError) as exc:
        rooms.update(conn, director, school.room_a, "Salle A", 5)  # below its 6 students
    assert exc.value.message == t["db.room_below_group"]


def test_room_in_use_cannot_be_deactivated(conn, director, school, g1):
    slot_id = timetable.add_slot(conn, director, slot(g1, school.room_a))
    with pytest.raises(BusinessRuleError) as exc:
        rooms.set_active(conn, director, school.room_a, False)
    assert exc.value.message == t["room.in_use"]
    timetable.remove_slot(conn, director, slot_id)
    rooms.set_active(conn, director, school.room_a, False)
    assert [r.name for r in rooms.list_rooms(conn, director, active_only=True)] == ["Salle B"]


# ----- teachers and rates -----

def test_rate_change_keeps_history_without_gap_or_overlap(conn, director, school):
    teachers.set_rate(conn, director, school.karim, 6500, date(2027, 1, 1))
    teachers.set_rate(conn, director, school.karim, 7000, date(2027, 3, 1))
    history = teachers.rates(conn, director, school.karim)
    assert [(r.percentage_bp, r.valid_from, r.valid_to) for r in history] == [
        (7000, "2027-03-01", None),
        (6500, "2027-01-01", "2027-03-01"),
        (6000, "2026-09-01", "2027-01-01"),
    ]
    assert teachers.rate_on(conn, school.karim, date(2026, 12, 31)) == 6000
    assert teachers.rate_on(conn, school.karim, date(2027, 1, 1)) == 6500
    assert teachers.rate_on(conn, school.karim, date(2026, 8, 31)) is None
    assert teachers.get(conn, director, school.karim).current_rate_bp == 7000


def test_rate_cannot_start_before_the_current_one(conn, director, school):
    with pytest.raises(ValidationError) as exc:
        teachers.set_rate(conn, director, school.karim, 6500, date(2026, 8, 1))
    assert exc.value.message == t["rate.before_current"].format(date="01/09/2026")


def test_same_day_rate_corrects_until_a_payout_used_it(conn, director, school):
    teachers.set_rate(conn, director, school.karim, 6200, date(2026, 9, 1))
    assert [r.percentage_bp for r in teachers.rates(conn, director, school.karim)] == [6200]
    conn.execute(
        "INSERT INTO teacher_payouts(teacher_id, period_start, period_end, base_amount, "
        "amount_due, status) VALUES (?, '2026-09-01', '2026-09-30', 100, 62, 'approved')",
        (school.karim,))
    with pytest.raises(BusinessRuleError) as exc:
        teachers.set_rate(conn, director, school.karim, 6300, date(2026, 9, 1))
    assert exc.value.message == t["rate.locked"]


def test_receptionist_sees_teachers_without_rates(conn, receptionist, school):
    listed = teachers.search(conn, receptionist)
    assert [(x.full_name, x.current_rate_bp) for x in listed] == [
        ("Karim Haddad", None), ("Samia Rahmani", None),
    ]
    with pytest.raises(PermissionDenied):
        teachers.rates(conn, receptionist, school.karim)


def test_teacher_search_and_phone(conn, director, school):
    assert [x.full_name for x in teachers.search(conn, director, "hadd")] == ["Karim Haddad"]
    assert teachers.get(conn, director, school.karim).phone == "0661112233"


def test_teacher_with_open_groups_cannot_be_deactivated(conn, director, school, g1):
    with pytest.raises(BusinessRuleError) as exc:
        teachers.deactivate(conn, director, school.karim)
    assert exc.value.message == t["teacher.has_groups"]
    teachers.deactivate(conn, director, school.samia)
    with pytest.raises(ValidationError) as exc:
        groups.change_teacher(conn, director, g1, school.samia, date(2026, 11, 1))
    assert exc.value.message == t["teacher.inactive"]


# ----- groups -----

def test_create_group_opens_its_teacher_history(conn, director, school, g1):
    group = groups.get(conn, director, g1)
    assert (group.teacher, group.price, group.capacity, group.state) == (
        "Karim Haddad", 3000, 12, "active")
    [period] = groups.teacher_history(conn, director, g1)
    assert (period.teacher, period.valid_from, period.valid_to) == (
        "Karim Haddad", "2026-09-15", None)


def test_group_names_are_unique_per_year(conn, director, school, g1):
    with pytest.raises(ValidationError) as exc:
        groups.create(conn, director, group_input(school, name="g1"), school.karim)
    assert exc.value.message == t["group.name_taken"]
    upcoming = school_years.create(conn, director, "2027-2028", date(2027, 9, 1),
                                   date(2028, 6, 30))
    groups.create(conn, director, group_input(school, year=upcoming, start=date(2027, 9, 15)),
                  school.karim)  # same name, another year


def test_group_start_must_be_in_its_year(conn, director, school):
    with pytest.raises(ValidationError) as exc:
        groups.create(conn, director, group_input(school, start=date(2027, 7, 1)), school.karim)
    assert exc.value.message == t["group.start_outside_year"].format(label="2026-2027")


def test_groups_only_in_open_or_upcoming_years(conn, director, school):
    past = school_years.create(conn, director, "2025-2026", date(2025, 9, 1), date(2026, 6, 30))
    with pytest.raises(BusinessRuleError) as exc:
        groups.create(conn, director, group_input(school, year=past, start=date(2025, 9, 15)),
                      school.karim)
    assert exc.value.message == t["year.not_usable"]
    upcoming = school_years.create(conn, director, "2027-2028", date(2027, 9, 1),
                                   date(2028, 6, 30))
    new = groups.create(conn, director,
                        group_input(school, year=upcoming, start=date(2027, 9, 15)),
                        school.karim)
    assert groups.get(conn, director, new).state == "upcoming"


def test_price_change_affects_only_new_subscriptions(conn, director, school, g1):
    conn.executescript(f"""
    INSERT INTO students(student_number, first_name, last_name) VALUES ('2026-0001', 'A', 'B');
    INSERT INTO registrations(student_id, school_year_id, level_id, fee_amount)
      VALUES (1, {school.year}, {school.level_4am}, 0);
    INSERT INTO enrollments(student_id, group_id, registration_id, enrolled_on)
      VALUES (1, {g1}, 1, '2026-09-15');
    INSERT INTO subscriptions(enrollment_id, price, start_date, end_date)
      VALUES (1, 3000, '2026-09-15', '2026-10-15');
    """)
    groups.update(conn, director, g1, group_input(school, price=3500))
    assert groups.get(conn, director, g1).price == 3500
    assert conn.execute("SELECT price FROM subscriptions").fetchone()[0] == 3000
    row = conn.execute(
        "SELECT old_value, new_value FROM audit_log WHERE action = 'group.update'").fetchone()
    assert (json.loads(row["old_value"]), json.loads(row["new_value"])) == (
        {"price": 3000}, {"price": 3500})
    # With a student, level, subject and start date are fixed.
    with pytest.raises(BusinessRuleError) as exc:
        groups.update(conn, director, g1, group_input(school, price=3500, subject=school.physics))
    assert exc.value.message == t["group.has_enrollments"]


def test_group_capacity_may_exceed_its_room_which_limits_seats(conn, director, school, g1):
    timetable.add_slot(conn, director, slot(g1, school.room_b))  # 12 places
    groups.update(conn, director, g1, group_input(school, capacity=15))
    group = groups.get(conn, director, g1)
    assert (group.capacity, group.seats, group.room_limited, group.limiting_room) == (
        15, 12, True, "Salle B")
    enroll(conn, school, g1, 12)
    with pytest.raises(sqlite3.IntegrityError, match="room is full"):
        enroll(conn, school, g1, 1)
    assert groups.get(conn, director, g1).enrolled == 12


def test_group_capacity_stays_above_enrolled(conn, director, school, g1):
    conn.executescript(f"""
    INSERT INTO students(student_number, first_name, last_name) VALUES ('2026-0001', 'A', 'B');
    INSERT INTO students(student_number, first_name, last_name) VALUES ('2026-0002', 'C', 'D');
    INSERT INTO registrations(student_id, school_year_id, level_id, fee_amount)
      VALUES (1, {school.year}, {school.level_4am}, 0), (2, {school.year}, {school.level_4am}, 0);
    INSERT INTO enrollments(student_id, group_id, registration_id, enrolled_on)
      VALUES (1, {g1}, 1, '2026-09-15'), (2, {g1}, 2, '2026-09-15');
    """)
    with pytest.raises(BusinessRuleError) as exc:
        groups.update(conn, director, g1, group_input(school, capacity=1))
    assert exc.value.message == t["db.capacity_below_enrolled"]
    assert groups.get(conn, director, g1).enrolled == 2


def test_start_date_moves_the_first_teacher_period(conn, director, school, g1):
    groups.update(conn, director, g1, group_input(school, start=date(2026, 10, 1)))
    [period] = groups.teacher_history(conn, director, g1)
    assert period.valid_from == "2026-10-01"


def test_teacher_change_keeps_history(conn, director, school, g1):
    groups.change_teacher(conn, director, g1, school.samia, date(2026, 11, 1))
    history = groups.teacher_history(conn, director, g1)
    assert [(p.teacher, p.valid_from, p.valid_to) for p in history] == [
        ("Samia Rahmani", "2026-11-01", None),
        ("Karim Haddad", "2026-09-15", "2026-11-01"),
    ]
    # Planned for 1 November: Karim still teaches the group today.
    assert groups.get(conn, director, g1).teacher == "Karim Haddad"
    with pytest.raises(ValidationError) as exc:
        groups.change_teacher(conn, director, g1, school.karim, date(2026, 10, 1))
    assert exc.value.message == t["group.teacher_before_current"].format(date="01/11/2026")
    with pytest.raises(BusinessRuleError) as exc:
        groups.change_teacher(conn, director, g1, school.samia, date(2026, 12, 1))
    assert exc.value.message == t["group.same_teacher"]


def test_same_day_teacher_change_corrects_until_paid(conn, director, school, g1):
    groups.change_teacher(conn, director, g1, school.samia, date(2026, 9, 15))
    assert [p.teacher for p in groups.teacher_history(conn, director, g1)] == ["Samia Rahmani"]
    payout = conn.execute(
        "INSERT INTO teacher_payouts(teacher_id, period_start, period_end, base_amount, "
        "amount_due) VALUES (?, '2026-09-01', '2026-09-30', 3000, 1500)",
        (school.samia,)).lastrowid
    conn.execute("INSERT INTO payout_lines(payout_id, group_id, revenue_basis, percentage_bp, "
                 "amount) VALUES (?, ?, 3000, 5000, 1500)", (payout, g1))
    conn.execute("UPDATE teacher_payouts SET status = 'approved' WHERE id = ?", (payout,))
    with pytest.raises(BusinessRuleError) as exc:
        groups.change_teacher(conn, director, g1, school.karim, date(2026, 9, 15))
    assert exc.value.message == t["group.teacher_locked"]


def test_new_teacher_must_be_free_at_the_group_slots(conn, director, school, g1):
    g2 = groups.create(conn, director, group_input(school, name="G2", subject=school.physics),
                       school.samia)
    timetable.add_slot(conn, director, slot(g1, school.room_a, 2, "17:00", "18:30"))
    timetable.add_slot(conn, director, slot(g2, school.room_b, 2, "18:00", "19:30"))
    with pytest.raises(BusinessRuleError) as exc:
        groups.change_teacher(conn, director, g2, school.karim, date(2026, 11, 1))
    assert exc.value.message == t["slot.teacher_busy"].format(
        teacher="Karim Haddad", day="mardi", start="17:00", end="18:30", group="G1")


def test_close_and_reopen_group(conn, director, school, g1):
    timetable.add_slot(conn, director, slot(g1, school.room_a))
    groups.close(conn, director, g1)
    assert groups.get(conn, director, g1).state == "closed"
    assert timetable.group_slots(conn, director, g1) == []
    with pytest.raises(BusinessRuleError) as exc:
        timetable.add_slot(conn, director, slot(g1, school.room_a))
    assert exc.value.message == t["group.closed"]
    groups.reopen(conn, director, g1)
    assert groups.get(conn, director, g1).status == "active"


def test_group_search_filters(conn, director, school, g1):
    groups.create(conn, director, group_input(school, name="P1", subject=school.physics,
                                              level=school.level_3as), school.samia)
    names = lambda **kw: [g.name for g in groups.search(conn, director, **kw)]
    assert names() == ["G1", "P1"]
    assert names(level_id=school.level_3as) == ["P1"]
    assert names(teacher_id=school.karim) == ["G1"]
    assert names(query="physi") == ["P1"]
    assert names(query="samia") == ["P1"]


def test_receptionist_sees_groups(conn, receptionist, school):
    assert groups.search(conn, receptionist) == []


# ----- timetable -----

def test_slot_defaults_to_today_or_group_start(conn, director, school, g1):
    slot_id = timetable.add_slot(conn, director, slot(g1, school.room_a))
    [added] = timetable.group_slots(conn, director, g1)
    assert (added.id, added.valid_from, added.room, added.teacher) == (
        slot_id, "2026-10-18", "Salle A", "Karim Haddad")
    later = groups.create(conn, director, group_input(school, name="G2", start=date(2026, 11, 2)),
                          school.samia)
    timetable.add_slot(conn, director, slot(later, school.room_b, 3))
    assert timetable.group_slots(conn, director, later)[0].valid_from == "2026-11-02"


def test_room_clash_names_the_other_group(conn, director, school, g1):
    g2 = groups.create(conn, director, group_input(school, name="G2"), school.samia)
    timetable.add_slot(conn, director, slot(g1, school.room_a, 2, "17:00", "18:30"))
    with pytest.raises(BusinessRuleError) as exc:
        timetable.add_slot(conn, director, slot(g2, school.room_a, 2, "18:00", "19:00"))
    assert exc.value.message == t["slot.room_busy"].format(
        room="Salle A", day="mardi", start="17:00", end="18:30", group="G1")


def test_group_and_teacher_clashes(conn, director, school, g1):
    timetable.add_slot(conn, director, slot(g1, school.room_a, 2, "17:00", "18:30"))
    with pytest.raises(BusinessRuleError) as exc:
        timetable.add_slot(conn, director, slot(g1, school.room_b, 2, "18:00", "19:00"))
    assert exc.value.message == t["slot.group_busy"].format(
        group="G1", day="mardi", start="17:00", end="18:30")
    g2 = groups.create(conn, director, group_input(school, name="G2"), school.karim)
    with pytest.raises(BusinessRuleError) as exc:
        timetable.add_slot(conn, director, slot(g2, school.room_b, 2, "16:00", "17:30"))
    assert exc.value.message == t["slot.teacher_busy"].format(
        teacher="Karim Haddad", day="mardi", start="17:00", end="18:30", group="G1")


def test_adjacent_slots_do_not_clash(conn, director, school, g1):
    g2 = groups.create(conn, director, group_input(school, name="G2"), school.karim)
    timetable.add_slot(conn, director, slot(g1, school.room_a, 2, "17:00", "18:30"))
    timetable.add_slot(conn, director, slot(g2, school.room_a, 2, "18:30", "20:00"))
    assert len(timetable.week(conn, director, room_id=school.room_a)) == 2


def test_empty_big_group_fits_a_small_room(conn, director, school):
    """A group planned for 16 with no student yet can meet in a 5-seat room."""
    small = rooms.create(conn, director, "Salle 02", 5)
    big = groups.create(conn, director, group_input(school, name="Grand", capacity=16),
                        school.karim)
    timetable.add_slot(conn, director, slot(big, small))
    group = groups.get(conn, director, big)
    assert (group.enrolled, group.seats, group.capacity) == (0, 5, 16)


def test_room_too_small_for_the_enrolled_students(conn, director, school):
    big = groups.create(conn, director, group_input(school, name="Grand", capacity=18),
                        school.karim)
    enroll(conn, school, big, 13)
    with pytest.raises(BusinessRuleError) as exc:
        timetable.add_slot(conn, director, slot(big, school.room_b))
    assert exc.value.message == t["room.too_small"].format(
        room="Salle B", room_capacity=12, enrolled=13)
    timetable.add_slot(conn, director, slot(big, school.room_a))  # 20 places: fine


@pytest.mark.parametrize("data, key", [
    ({"weekday": 8}, "slot.weekday_invalid"),
    ({"start": "18:00", "end": "17:00"}, "slot.times_order"),
    ({"start": "18:00", "end": "18:00"}, "slot.times_order"),
])
def test_slot_validation(conn, director, school, g1, data, key):
    with pytest.raises(ValidationError) as exc:
        timetable.add_slot(conn, director, slot(g1, school.room_a, **data))
    assert exc.value.message == t[key]


def test_inactive_room_refused(conn, director, school, g1):
    rooms.set_active(conn, director, school.room_b, False)
    with pytest.raises(ValidationError) as exc:
        timetable.add_slot(conn, director, slot(g1, school.room_b))
    assert exc.value.message == t["room.inactive"]


def test_receptionist_manages_the_timetable(conn, receptionist, director, school, g1):
    slot_id = timetable.add_slot(conn, receptionist, slot(g1, school.room_a))
    timetable.update_slot(conn, receptionist, slot_id, slot(g1, school.room_a, 4))
    assert timetable.group_slots(conn, receptionist, g1)[0].weekday == 4


def test_update_slot_without_sessions_is_in_place(conn, director, school, g1):
    slot_id = timetable.add_slot(conn, director, slot(g1, school.room_a))
    same = timetable.update_slot(conn, director, slot_id,
                                 slot(g1, school.room_b, 3, "15:00", "16:30"))
    assert same == slot_id
    [moved] = timetable.group_slots(conn, director, g1)
    assert (moved.room, moved.weekday, moved.start_time) == ("Salle B", 3, "15:00")


def test_update_slot_with_sessions_keeps_history(conn, director, school, g1, monkeypatch):
    monkeypatch.setattr(dates, "today", lambda: date(2026, 10, 1))
    slot_id = timetable.add_slot(conn, director, slot(g1, school.room_a))
    add_session(conn, slot_id)
    monkeypatch.setattr(dates, "today", lambda: TODAY)
    new_id = timetable.update_slot(conn, director, slot_id, slot(g1, school.room_a, 4))
    assert new_id != slot_id
    rows = conn.execute("SELECT id, weekday, valid_from, valid_to FROM timetable_slots "
                        "ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [
        (slot_id, 2, "2026-10-01", "2026-10-18"),
        (new_id, 4, "2026-10-18", None),
    ]
    assert "slot.replace" in actions(conn)


def test_remove_slot_deletes_or_ends(conn, director, school, g1, monkeypatch):
    fresh = timetable.add_slot(conn, director, slot(g1, school.room_a, 2))
    timetable.remove_slot(conn, director, fresh)  # never used: removed
    assert conn.execute("SELECT COUNT(*) FROM timetable_slots").fetchone()[0] == 0
    monkeypatch.setattr(dates, "today", lambda: date(2026, 10, 1))
    used = timetable.add_slot(conn, director, slot(g1, school.room_a, 2))
    add_session(conn, used)
    monkeypatch.setattr(dates, "today", lambda: TODAY)
    timetable.remove_slot(conn, director, used)
    assert conn.execute("SELECT valid_to FROM timetable_slots WHERE id = ?",
                        (used,)).fetchone()[0] == "2026-10-18"
    with pytest.raises(BusinessRuleError) as exc:
        timetable.remove_slot(conn, director, used)
    assert exc.value.message == t["slot.ended"]


def test_week_view_by_room_group_and_teacher(conn, director, school, g1):
    g2 = groups.create(conn, director, group_input(school, name="G2", subject=school.physics),
                       school.samia)
    timetable.add_slot(conn, director, slot(g1, school.room_a, 2, "17:00", "18:30"))
    timetable.add_slot(conn, director, slot(g1, school.room_b, 6, "09:00", "10:30"))
    timetable.add_slot(conn, director, slot(g2, school.room_a, 6, "09:00", "10:30"))
    week = lambda **kw: [(s.group, s.weekday) for s in timetable.week(conn, director, **kw)]
    assert week(room_id=school.room_a) == [("G1", 2), ("G2", 6)]
    assert week(group_id=g1) == [("G1", 2), ("G1", 6)]
    assert week(teacher_id=school.samia) == [("G2", 6)]
    assert week(on=date(2026, 10, 17), room_id=school.room_a) == []  # before they start


def test_unknown_slot(conn, director):
    with pytest.raises(NotFound):
        timetable.remove_slot(conn, director, 99)


# ----- phase 3 acceptance -----

def test_phase_3_acceptance_full_week(conn, director, receptionist, school):
    """A full week timetable for several groups is built with no conflict, and invalid
    changes get readable messages."""
    room_c = rooms.create(conn, director, "Salle C", 25)
    plan = [  # (name, level, subject, teacher, room, weekday, start, end)
        ("Maths 4AM G1", school.level_4am, school.maths, school.karim, school.room_a, 6, "09:00", "10:30"),
        ("Maths 4AM G1", school.level_4am, school.maths, school.karim, school.room_a, 2, "17:00", "18:30"),
        ("Maths 4AM G2", school.level_4am, school.maths, school.karim, school.room_a, 6, "10:30", "12:00"),
        ("Maths 4AM G2", school.level_4am, school.maths, school.karim, school.room_b, 4, "17:00", "18:30"),
        ("Physique 3AS", school.level_3as, school.physics, school.samia, room_c, 6, "09:00", "11:00"),
        ("Physique 3AS", school.level_3as, school.physics, school.samia, school.room_a, 7, "14:00", "16:00"),
        ("Maths 3AS", school.level_3as, school.maths, school.karim, room_c, 5, "15:00", "17:00"),
    ]
    ids = {}
    for name, level, subject, teacher, room, weekday, start, end in plan:
        if name not in ids:
            ids[name] = groups.create(conn, director, group_input(
                school, name=name, level=level, subject=subject), teacher)
        timetable.add_slot(conn, receptionist, slot(ids[name], room, weekday, start, end))
    assert len(timetable.week(conn, receptionist)) == len(plan)
    assert [s.group for s in timetable.week(conn, receptionist, teacher_id=school.karim)] == [
        "Maths 4AM G1", "Maths 4AM G2", "Maths 3AS", "Maths 4AM G1", "Maths 4AM G2",
    ]
    errors = []
    for bad in (
        slot(ids["Maths 3AS"], school.room_a, 6, "10:00", "11:00"),       # room taken
        slot(ids["Physique 3AS"], school.room_b, 6, "10:30", "11:30"),    # group busy
        slot(ids["Maths 3AS"], school.room_b, 2, "18:00", "19:00"),       # teacher busy
        slot(ids["Physique 3AS"], school.room_b, 1, "18:00", "17:00"),    # times
    ):
        with pytest.raises(BusinessRuleError) as exc:
            timetable.add_slot(conn, receptionist, bad)
        errors.append(exc.value.message)
    assert errors[0].startswith("La salle Salle A est déjà occupée le samedi")
    assert errors[1].startswith("Le groupe Physique 3AS a déjà cours le samedi")
    assert errors[2].startswith("Karim Haddad enseigne déjà le mardi")
    assert errors[3] == t["slot.times_order"]


# ----- opening hours -----

def test_school_hours_default_and_change(conn, director, school):
    assert settings.school_hours(conn) == ("08:00", "20:00")
    settings.set_school_hours(conn, director, "8h", "19")
    assert settings.school_hours(conn) == ("08:00", "19:00")
    settings.set_school_hours(conn, director, "08:00", "18:30")
    keys = [json.loads(r[0])["key"] for r in conn.execute(
        "SELECT new_value FROM audit_log WHERE action = 'settings.set' ORDER BY id")]
    # First save stores both; the second changes only the closing time.
    assert keys == ["school.opens_at", "school.closes_at", "school.closes_at"]


@pytest.mark.parametrize("opens, closes, key", [
    ("19:00", "08:00", "hours.order"),
    ("08:00", "08:00", "hours.order"),
    ("25h", "19:00", "time.invalid"),
])
def test_school_hours_validation(conn, director, opens, closes, key):
    with pytest.raises(ValidationError) as exc:
        settings.set_school_hours(conn, director, opens, closes)
    assert exc.value.message == t[key]


def test_school_hours_are_set_together_and_by_the_director(conn, director, receptionist):
    with pytest.raises(ValidationError):
        settings.set_value(conn, director, "school.closes_at", "19:00")
    with pytest.raises(PermissionDenied):
        settings.set_school_hours(conn, receptionist, "08:00", "19:00")


def test_slots_must_fit_the_school_hours(conn, director, school, g1):
    settings.set_school_hours(conn, director, "08:00", "19:00")
    with pytest.raises(ValidationError) as exc:
        timetable.add_slot(conn, director, slot(g1, school.room_a, 2, "18:00", "19:30"))
    assert exc.value.message == t["slot.outside_hours"].format(opens="08:00", closes="19:00")
    with pytest.raises(ValidationError):
        timetable.add_slot(conn, director, slot(g1, school.room_a, 2, "07:30", "09:00"))
    slot_id = timetable.add_slot(conn, director, slot(g1, school.room_a, 2, "17:30", "19:00"))
    with pytest.raises(ValidationError):
        timetable.update_slot(conn, director, slot_id, slot(g1, school.room_a, 2, "18:00", "19:30"))


def test_hours_cannot_cut_existing_slots(conn, director, school, g1):
    slot_id = timetable.add_slot(conn, director, slot(g1, school.room_a, 6, "09:00", "10:30"))
    timetable.add_slot(conn, director, slot(g1, school.room_a, 2, "18:30", "20:00"))
    with pytest.raises(BusinessRuleError) as exc:
        settings.set_school_hours(conn, director, "10:00", "19:00")
    assert exc.value.message == t["hours.slots_outside"].format(
        count=2, group="G1", day="mardi", start="18:30", end="20:00")
    assert settings.school_hours(conn) == ("08:00", "20:00")
    # A closed group's slots no longer count.
    timetable.remove_slot(conn, director, slot_id)
    groups.close(conn, director, g1)
    settings.set_school_hours(conn, director, "10:00", "19:00")


# ----- review fixes -----

def test_planned_teacher_change_shows_from_its_date(conn, director, school, g1, monkeypatch):
    timetable.add_slot(conn, director, slot(g1, school.room_a))
    groups.change_teacher(conn, director, g1, school.samia, date(2026, 12, 1))
    # Until 1 December Karim teaches the group: views and clash checks follow.
    assert groups.get(conn, director, g1).teacher == "Karim Haddad"
    assert [s.group for s in timetable.week(conn, director, teacher_id=school.karim)] == ["G1"]
    assert timetable.week(conn, director, teacher_id=school.samia) == []
    december = date(2026, 12, 8)
    assert [s.group for s in timetable.week(conn, director, december,
                                            teacher_id=school.samia)] == ["G1"]
    assert [s.teacher for s in timetable.week(conn, director, december)] == ["Samia Rahmani"]
    assert [g.name for g in groups.search(conn, director, teacher_id=school.karim)] == ["G1"]

    g2 = groups.create(conn, director, group_input(school, name="G2"), school.karim)
    with pytest.raises(BusinessRuleError) as exc:
        timetable.add_slot(conn, director, slot(g2, school.room_b))
    assert "Karim Haddad" in exc.value.message
    g3 = groups.create(conn, director, group_input(school, name="G3"), school.samia)
    with pytest.raises(BusinessRuleError) as exc:  # Samia takes the Tuesday from December
        timetable.add_slot(conn, director, slot(g3, school.room_b))
    assert "Samia Rahmani" in exc.value.message
    with pytest.raises(BusinessRuleError) as exc:  # planned in a group: still needed
        teachers.deactivate(conn, director, school.samia)
    assert exc.value.message == t["teacher.has_groups"]

    monkeypatch.setattr(dates, "today", lambda: december)
    assert groups.get(conn, director, g1).teacher == "Samia Rahmani"


def test_teacher_change_date_stays_in_group_and_year(conn, director, school, g1):
    for day in (date(2026, 9, 14), date(2027, 7, 1)):
        with pytest.raises(ValidationError) as exc:
            groups.change_teacher(conn, director, g1, school.samia, day)
        assert exc.value.message == t["group.teacher_date_outside"].format(
            start="15/09/2026", end="30/06/2027")
    groups.change_teacher(conn, director, g1, school.samia, date(2027, 6, 30))


def test_upcoming_year_waits_to_be_opened(conn, director, school, monkeypatch):
    next_year = school_years.create(conn, director, "2027-2028", date(2027, 9, 1),
                                    date(2028, 6, 30))
    # La rentrée: 2026-2027 is still open, the new year has started but was never opened.
    monkeypatch.setattr(dates, "today", lambda: date(2027, 9, 2))
    assert school_years.get(conn, director, next_year).state == "upcoming"
    groups.create(conn, director, group_input(school, name="G 27", start=date(2027, 9, 15),
                                              year=next_year), school.karim)
    school_years.close(conn, director, school.year)
    school_years.open_year(conn, director, next_year)
    assert school_years.get(conn, director, next_year).state == "open"
    # A finished year cannot be opened again.
    school_years.close(conn, director, next_year)
    year = school_years.get(conn, director, school.year)
    assert year.state == "closed" and not school_years.can_open(year)
    with pytest.raises(BusinessRuleError) as exc:
        school_years.open_year(conn, director, school.year)
    assert exc.value.message == t["year.ended"]


def test_year_closed_by_mistake_can_be_reopened(conn, director, school):
    school_years.close(conn, director, school.year)
    year = school_years.get(conn, director, school.year)
    assert year.state == "closed" and school_years.can_open(year)
    school_years.open_year(conn, director, school.year)
    assert school_years.get(conn, director, school.year).state == "open"


def test_slot_times_are_normalised(conn, director, school, g1):
    slot_id = timetable.add_slot(conn, director, slot(g1, school.room_a, start="9h",
                                                      end="10h30"))
    added = timetable.group_slots(conn, director, g1)[0]
    assert (added.id, added.start_time, added.end_time) == (slot_id, "09:00", "10:30")
    with pytest.raises(ValidationError):
        timetable.add_slot(conn, director, slot(g1, school.room_a, start="25:00"))


def test_group_start_moved_later_moves_its_slots(conn, director, school):
    group = groups.create(conn, director, group_input(school, start=date(2026, 10, 1)),
                          school.karim)
    timetable.add_slot(conn, director, slot(group, school.room_a))
    assert timetable.group_slots(conn, director, group)[0].valid_from == "2026-10-18"
    groups.update(conn, director, group, group_input(school, start=date(2026, 11, 15)))
    assert timetable.group_slots(conn, director, group)[0].valid_from == "2026-11-15"
    history = groups.teacher_history(conn, director, group)
    assert [p.valid_from for p in history] == ["2026-11-15"]


def test_group_start_cannot_pass_a_teacher_change(conn, director, school):
    group = groups.create(conn, director, group_input(school, start=date(2026, 10, 1)),
                          school.karim)
    groups.change_teacher(conn, director, group, school.samia, date(2026, 11, 1))
    with pytest.raises(BusinessRuleError) as exc:
        groups.update(conn, director, group, group_input(school, start=date(2026, 11, 15)))
    assert exc.value.message == t["group.start_after_teacher_change"].format(date="01/11/2026")


def test_group_start_cannot_move_past_held_sessions(conn, director, school):
    group = groups.create(conn, director, group_input(school, start=date(2026, 10, 1)),
                          school.karim)
    slot_id = timetable.add_slot(conn, director, slot(group, school.room_a))
    add_session(conn, slot_id)
    with pytest.raises(BusinessRuleError) as exc:
        groups.update(conn, director, group, group_input(school, start=date(2026, 11, 15)))
    assert exc.value.message == t["group.slots_have_sessions"]


def test_past_weeks_keep_closed_groups(conn, director, school, g1):
    timetable.add_slot(conn, director, slot(g1, school.room_a, valid_from=date(2026, 9, 15)))
    groups.close(conn, director, g1)
    assert timetable.week(conn, director) == []
    assert [s.group for s in timetable.week(conn, director, date(2026, 10, 1))] == ["G1"]


def test_school_tab_saves_all_or_nothing(conn, director):
    with pytest.raises(ValidationError):
        settings.save_school(conn, director, "  ", "", "", "09:00", "18:00")
    assert settings.school_hours(conn) == (settings.DEFAULT_OPENS_AT,
                                           settings.DEFAULT_CLOSES_AT)
    settings.save_school(conn, director, "École Ennour", "0550 12 34 56", "Oran",
                         "9h", "18h")
    assert settings.school_hours(conn) == ("09:00", "18:00")
    assert settings.get(conn, "school.address") == "Oran"
