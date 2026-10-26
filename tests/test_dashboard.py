"""The dashboard (« Aujourd'hui »): what it reads, for the director and for the desk."""

from datetime import date

import pytest

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.domain.models import GroupInput, StudentInput, TeacherInput
from tadris.services import (
    auth,
    catalog,
    dashboard,
    debt,
    enrollments,
    groups,
    payments,
    payouts,
    registrations,
    school_years,
    students,
    subscriptions,
    teachers,
)

TODAY = date(2026, 10, 18)


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
    """Karim (60 %) teaches A, Maths, 6 000 DA; Samia (50 %) teaches B, Physique, 4 000 DA.

    01/09  Amine: fee 1 000, A from 01/09.  Badis: fee 1 000, B from 01/09.
    02/09  Amine pays 7 000 (fee + September).  05/09  Badis pays 2 000 (fee + 1 000).
    10/09  Badis pays 500, voided the same day.
    01/10  Amine and Badis renewed for October.
    02/10  Karim's September (3 600) paid; Samia's September (2 000) left as a draft.
    03/10  Amine pays 6 000 (October).
    05/10  Chahinez: fee 1 000, A from 05/10.  06/10  she pays 8 000 (1 000 left as credit).
    Today 18/10.

    By hand: September charged 12 000, settled 9 000, collected 9 000.
             October charged 17 000, settled 13 000, collected 14 000.
             Badis owes 3 000 from 01/09 (47 days) and 4 000 from 01/10 (17 days).
    """

    def __init__(self, conn, ctx, monkeypatch):
        self.conn, self.ctx = conn, ctx
        move_to(monkeypatch, date(2026, 9, 1))
        self.year = school_years.create(conn, ctx, "2026-2027", date(2026, 9, 1),
                                        date(2027, 6, 30))
        self.level = catalog.create(conn, ctx, "level", "4AM")
        self.karim = teachers.create(conn, ctx, TeacherInput("Karim Haddad"), 6000,
                                     date(2026, 9, 1))
        self.samia = teachers.create(conn, ctx, TeacherInput("Samia Rahmani"), 5000,
                                     date(2026, 9, 1))
        self.a = self.group("A", "Maths", 6000, self.karim)
        self.b = self.group("B", "Physique", 4000, self.samia)

        self.amine = self.pupil("Amine", "Benali", self.a)
        self.badis = self.pupil("Badis", "Cherif", self.b)
        move_to(monkeypatch, date(2026, 9, 2))
        payments.record(conn, ctx, self.amine, 7000, "cash")
        move_to(monkeypatch, date(2026, 9, 5))
        payments.record(conn, ctx, self.badis, 2000, "cash")
        move_to(monkeypatch, date(2026, 9, 10))
        voided = payments.record(conn, ctx, self.badis, 500, "cash")
        payments.void(conn, ctx, voided, "Erreur de saisie")

        move_to(monkeypatch, date(2026, 10, 1))
        for student in (self.amine, self.badis):
            [month] = subscriptions.for_student(conn, ctx, student)
            subscriptions.renew(conn, ctx, month.id)
        move_to(monkeypatch, date(2026, 10, 2))
        paid = payouts.build_draft(conn, ctx, self.karim, date(2026, 9, 30))
        payouts.approve(conn, ctx, paid)
        payouts.mark_paid(conn, ctx, paid, "cash")
        payouts.build_draft(conn, ctx, self.samia, date(2026, 9, 30))
        move_to(monkeypatch, date(2026, 10, 3))
        payments.record(conn, ctx, self.amine, 6000, "cash")

        move_to(monkeypatch, date(2026, 10, 5))
        self.chahinez = self.pupil("Chahinez", "Djebbar", self.a)
        move_to(monkeypatch, date(2026, 10, 6))
        payments.record(conn, ctx, self.chahinez, 8000, "transfer")
        move_to(monkeypatch, TODAY)

    def group(self, name, subject, price, teacher):
        subject_id = catalog.create(self.conn, self.ctx, "subject", subject)
        return groups.create(self.conn, self.ctx, GroupInput(
            self.year, self.level, subject_id, name, price, 20, date(2026, 9, 1)), teacher)

    def pupil(self, first, last, group_id) -> int:
        student = students.create(self.conn, self.ctx, StudentInput(first, last))
        registrations.register(self.conn, self.ctx, student, self.level, 1000)
        enrollments.enroll(self.conn, self.ctx, student, group_id, enrolled_on=dates.today())
        return student


@pytest.fixture
def school(conn, director, monkeypatch):
    return School(conn, director, monkeypatch)


# ----- dashboard -----

def test_dashboard_for_the_director(conn, director, school, monkeypatch):
    monkeypatch.setattr(dashboard, "_now_time", lambda: "10:00")
    board = dashboard.load(conn, director)
    assert (board.debt_total, board.debtors) == (7000, 1)
    assert [d.student_id for d in board.top_debtors] == [school.badis]
    assert (board.charged, board.settled, board.collected) == (17000, 13000, 14000)
    assert [(g.title, g.enrolled, g.seats, g.rate_bp) for g in board.groups] == [
        ("A", 2, 20, 1000), ("B", 1, 20, 500)]
    assert (board.enrolled, board.seats) == (3, 40)


def test_the_receptionist_sees_no_money_on_the_dashboard(conn, desk, school):
    board = dashboard.load(conn, desk)
    assert board.charged is None and board.collected is None
    assert board.debt_total == 7000


def test_todays_sessions_left_and_cancelled(conn, director, school, monkeypatch):
    conn.execute("INSERT INTO rooms(name, capacity) VALUES ('Salle 1', 20)")
    for start, end, status in (("09:00", "10:30", "held"), ("17:00", "18:30", "planned"),
                               ("19:00", "20:30", "cancelled")):
        conn.execute(
            "INSERT INTO sessions(group_id, room_id, teacher_id, date, start_time, end_time, "
            "status, source, cancellation_reason) VALUES (?, 1, ?, '2026-10-18', ?, ?, ?, "
            "'manual', ?)", (school.a, school.karim, start, end, status,
                             "Absent" if status == "cancelled" else None))
    monkeypatch.setattr(dashboard, "_now_time", lambda: "12:00")
    board = dashboard.load(conn, director)
    assert [s.start_time for s in board.sessions] == ["09:00", "17:00", "19:00"]
    assert board.sessions_held == 2
    assert [s.start_time for s in board.sessions_left] == ["17:00"]


def test_dashboard_money_by_day(conn, director, school):
    """October to the 18th: 6 000 on the 3rd, 8 000 on the 6th. A day is open when it had a
    session (a cancelled one too) or a payment."""
    conn.execute("INSERT INTO rooms(name, capacity) VALUES ('Salle 1', 20)")
    conn.execute(
        "INSERT INTO sessions(group_id, room_id, teacher_id, date, start_time, end_time, "
        "status, source, cancellation_reason) VALUES (?, 1, ?, '2026-10-12', '17:00', "
        "'18:30', 'cancelled', 'manual', 'Absent')", (school.a, school.karim))
    board = dashboard.load(conn, director)
    assert [d.day for d in board.daily] == [f"2026-10-{d:02d}" for d in range(1, 19)]
    assert sum(d.amount for d in board.daily) == board.collected == 14000
    assert [(d.day[8:], d.amount) for d in board.daily if d.open] == [
        ("03", 6000), ("06", 8000), ("12", 0)]


def test_dashboard_closed_weekdays(conn, director, school):
    assert dashboard.load(conn, director).closed_weekdays == ()  # no timetable yet
    conn.execute("INSERT INTO rooms(name, capacity) VALUES ('Salle 1', 20)")
    for weekday in (1, 3):
        conn.execute(
            "INSERT INTO timetable_slots(group_id, room_id, weekday, start_time, end_time, "
            "valid_from) VALUES (?, 1, ?, '17:00', '18:30', '2026-09-01')", (school.a, weekday))
    conn.execute(
        "INSERT INTO timetable_slots(group_id, room_id, weekday, start_time, end_time, "
        "valid_from, valid_to) VALUES (?, 1, 5, '17:00', '18:30', '2026-09-01', '2026-10-01')",
        (school.b,))  # Fridays ended: the school is closed then now
    assert dashboard.load(conn, director).closed_weekdays == (2, 4, 5, 6, 7)


def test_dashboard_backup_of_the_day(conn, director, school, desk):
    def copy(status: str, day: str = "2026-10-18") -> None:
        conn.execute("INSERT INTO backups(file_path, type, status, created_at) "
                     "VALUES ('x.db', 'auto', ?, ?)", (status, f"{day}T09:00:00"))

    assert dashboard.load(conn, director).backup == "none"
    copy("verified", "2026-10-17")  # yesterday's does not count
    assert dashboard.load(conn, director).backup == "none"
    copy("failed")
    assert dashboard.load(conn, director).backup == "failed"
    copy("verified")
    copy("failed")  # one verified copy today is enough
    assert dashboard.load(conn, director).backup == "verified"
    assert dashboard.load(conn, desk).backup is None


def test_dashboard_for_the_receptionist_has_no_daily_money(conn, desk, school):
    board = dashboard.load(conn, desk)
    assert board.daily is None
    assert [d.student_id for d in board.oldest_debtors] == [school.badis]
    assert (board.opens_at, board.closes_at) == ("08:00", "20:00")


# ----- on the demo seed -----

def test_the_dashboard_agrees_with_the_seed(tmp_path):
    """The demo school: the dashboard runs, and what is late matches the debtors list."""
    import importlib.util
    from pathlib import Path

    from tadris.db.connection import connect

    seed_path = Path(__file__).resolve().parents[1] / "scripts" / "seed_demo.py"
    spec = importlib.util.spec_from_file_location("seed_demo", seed_path)
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    seed.main(tmp_path / "demo.db")
    conn = connect(tmp_path / "demo.db")
    row = conn.execute("SELECT id, username FROM users WHERE role = 'director'").fetchone()
    boss = UserContext(user_id=row[0], username=row[1], role="director")
    board = dashboard.load(conn, boss)
    owing = debt.debtors(conn, boss)
    assert (board.debt_total, board.debtors) == (sum(d.owed_now for d in owing), len(owing))
    assert board.collected == sum(d.amount for d in board.daily)  # nothing paid after today
