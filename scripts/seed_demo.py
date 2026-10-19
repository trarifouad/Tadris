"""Fill a database with demo students, contacts and the school structure (year, levels,
subjects, rooms, teachers, groups and a weekly timetable), then register most students for the
year and place them in groups (some on trial, a few switched or gone), add holidays, cancel a
session with its makeup, set a substitute and take today's attendance, then take payments
(most paid, some in part, a few in advance, one voided) and refunds (paid out, approved,
pending), through the services.

Usage: python scripts/seed_demo.py PATH.db
The path is required so the real database is never seeded by accident. Creates the director
account (directeur / password1) and a receptionist (accueil / password2) if the file is new.
"""

import random
import sys
from datetime import date, timedelta
from pathlib import Path

from tadris.core.dates import add_minutes
from tadris.core.errors import BusinessRuleError
from tadris.db.connection import connect
from tadris.db.migrate import migrate
from tadris.domain.models import (
    ContactInput,
    ContactLink,
    GroupInput,
    SlotInput,
    StudentInput,
    TeacherInput,
)
from tadris.services import (
    attendance,
    auth,
    catalog,
    contacts,
    debt,
    enrollments,
    groups,
    holidays,
    payments,
    refunds,
    registrations,
    rooms,
    school_years,
    sessions,
    settings,
    students,
    teachers,
    timetable,
)

FAMILIES = [
    "Benali", "Haddad", "Mansouri", "Bouzid", "Saidi", "Khelifi", "Belkacem", "Meziane",
    "Brahimi", "Cherif", "Amrani", "Ferhat", "Zerrouki", "Boudiaf", "Hamidi", "Rahmani",
]
FIRST_NAMES = [
    "Amine", "Yanis", "Lina", "Sara", "Rayan", "Ines", "Adam", "Meriem", "Walid", "Hiba",
    "Islam", "Nour", "Anis", "Aya", "Mehdi", "Hélène", "Ilyes", "Chaïma", "Riad", "Maya",
]
FATHERS = ["Karim", "Mourad", "Farid", "Rachid", "Nabil", "Samir", "Djamel", "Hakim"]
MOTHERS = ["Nadia", "Samia", "Fatima", "Amel", "Leila", "Souad", "Karima", "Wafa"]


def phone(rng: random.Random) -> str:
    return f"0{rng.choice('567')}{rng.randrange(10**8):08d}"


LEVELS = ["1AM", "2AM", "3AM", "4AM", "1AS", "2AS", "3AS"]
SUBJECTS = ["Mathématiques", "Physique", "Sciences", "Français", "Anglais", "Arabe"]
ROOMS = [("Salle A", 20), ("Salle B", 15), ("Salle C", 25), ("Labo", 12)]
TEACHERS = [("Karim Haddad", 6000), ("Samia Rahmani", 5500), ("Nabil Cherif", 6000),
            ("Leila Bouzid", 5000), ("Mourad Saidi", 6500)]
# (subject, level, group name, teacher index, price, capacity)
GROUPS = [
    ("Mathématiques", "4AM", "Maths 4AM G1", 0, 3000, 15),
    ("Mathématiques", "4AM", "Maths 4AM G2", 0, 3000, 15),
    ("Physique", "4AM", "Physique 4AM", 1, 2500, 15),
    ("Mathématiques", "3AS", "Maths 3AS", 4, 4000, 20),
    ("Physique", "3AS", "Physique 3AS", 1, 3500, 12),
    ("Français", "1AM", "Français 1AM", 3, 2000, 20),
    ("Anglais", "2AS", "Anglais 2AS", 2, 2500, 15),
    ("Sciences", "3AM", "Sciences 3AM", 2, 2500, 12),
]
STARTS = ["09:00", "10:30", "14:00", "15:30", "17:00", "18:30"]
GROUP_START = date(2026, 9, 15)


def seed_school(conn, director, rng: random.Random) -> None:
    if school_years.current(conn, director) is not None:
        return
    year = school_years.create(conn, director, "2026-2027", date(2026, 9, 1), date(2027, 6, 30))
    level_ids = {name: catalog.create(conn, director, "level", name) for name in LEVELS}
    subject_ids = {name: catalog.create(conn, director, "subject", name) for name in SUBJECTS}
    room_ids = [rooms.create(conn, director, name, capacity) for name, capacity in ROOMS]
    teacher_ids = [
        teachers.create(conn, director, TeacherInput(name, phone(rng), date(2024, 9, 1)), bp,
                        date(2026, 9, 1))
        for name, bp in TEACHERS
    ]
    for subject, level, name, teacher, price, capacity in GROUPS:
        group_id = groups.create(conn, director, GroupInput(
            year, level_ids[level], subject_ids[subject], name, price, capacity,
            GROUP_START), teacher_ids[teacher])
        placed = 0
        while placed < 2:
            # Weekend mornings and weekday evenings; skip any clash the services refuse.
            weekday = rng.choice((6, 6, 7, 1, 2, 3, 4, 5))
            start = rng.choice(STARTS[:3] if weekday in (5, 6) else STARTS[4:])
            end = add_minutes(start, 90)
            try:
                timetable.add_slot(conn, director, SlotInput(
                    group_id, rng.choice(room_ids), weekday, start, end, GROUP_START))
                placed += 1
            except BusinessRuleError:
                continue


REGISTRATION_FEE = 1500


def seed_enrollments(conn, director, rng: random.Random) -> tuple[int, int]:
    """Register about 85% of the active students and put each in one or two groups of their
    level. Returns (registrations, enrollments). Full groups are skipped, as at the desk."""
    if registrations.default_fee(conn) == 0:
        settings.set_value(conn, director, "defaults.registration_fee", REGISTRATION_FEE)
    by_level: dict[int, list[int]] = {}
    for g in groups.search(conn, director):
        if g.status != "closed":
            by_level.setdefault(g.level_id, []).append(g.id)
    registered = placed = 0
    for row in students.search(conn, director, status="active"):
        if rng.random() > 0.85 or registrations.current(conn, director, row.id) is not None:
            continue
        level_id = rng.choice(list(by_level))
        registrations.register(conn, director, row.id, level_id)
        registered += 1
        wanted = rng.sample(by_level[level_id], k=min(len(by_level[level_id]), rng.choice((1, 2))))
        for i, group_id in enumerate(wanted):
            trial = i == 0 and rng.random() < 0.15
            try:
                # Entry dates spread from the groups' start to today: some first months are
                # over, some end soon, some run on (the Abonnements lists have rows).
                entered = min(GROUP_START + timedelta(days=rng.randrange(0, 40)), date.today())
                enrollment_id = enrollments.enroll(conn, director, row.id, group_id,
                                                   trial=trial, enrolled_on=entered)
            except BusinessRuleError:
                continue
            placed += 1
            luck = rng.random()
            if trial and luck < 0.5:
                enrollments.confirm_trial(conn, director, enrollment_id)
            elif luck < 0.12:
                enrollments.leave(conn, director, enrollment_id, reason="Démo : départ")
            elif luck < 0.30:
                others = [g for g in by_level[level_id] if g not in wanted]
                if others:
                    try:
                        enrollments.switch(conn, director, enrollment_id, rng.choice(others))
                    except BusinessRuleError:
                        pass
    return registered, placed


HOLIDAYS = [("1er Novembre", date(2026, 11, 1), None),
            ("Vacances d'hiver", date(2026, 12, 20), date(2027, 1, 3))]
MARKS = ["present"] * 17 + ["late", "late", "absent", "absent", "excused"]


def seed_sessions(conn, director, rng: random.Random) -> int:
    """Holidays, a cancelled session and its makeup, a substitute, today's attendance.
    Returns how many attendance lines were taken."""
    if not holidays.list_holidays(conn, director):
        for label, start, end in HOLIDAYS:
            holidays.create(conn, director, label, start, end)
    if not settings.get(conn, "school.address"):
        opens_at, closes_at = settings.school_hours(conn)
        settings.save_school(conn, director, settings.get(conn, "school.name"),
                             "0550 12 34 56", "12 rue des Oliviers, Oran", opens_at, closes_at)
    today = date.today()
    planned = [s for s in sessions.listing(conn, director, today, today + timedelta(days=13))
               if s.status == "planned"]
    future = [s for s in planned if s.date > today.isoformat()]
    if len(future) >= 2:
        cancelled = future[0]
        sessions.cancel(conn, director, cancelled.id, "Enseignant malade")
        for offset in range(1, 6):  # the first free day after, same hours and room
            try:
                sessions.schedule_makeup(conn, director, cancelled.id,
                                         date.fromisoformat(cancelled.date)
                                         + timedelta(days=offset),
                                         cancelled.start_time, cancelled.end_time,
                                         cancelled.room_id)
                break
            except BusinessRuleError:
                continue
        others = [t for t in teachers.search(conn, director) if t.id != future[1].teacher_id]
        for teacher in others:
            try:
                sessions.set_teacher(conn, director, future[1].id, teacher.id)
                break
            except BusinessRuleError:
                continue
    marked = 0
    for s in planned:
        if s.date != today.isoformat():
            continue
        lines = attendance.roster(conn, director, s.id)
        if lines:
            marked += attendance.save(conn, director, s.id,
                                      {line.enrollment_id: rng.choice(MARKS) for line in lines})
    return marked


DEBT_WARNING = 10_000
METHODS = ["cash"] * 8 + ["transfer", "cheque"]


def seed_payments(conn, director, desk, rng: random.Random) -> int:
    """At the desk today: about 55% of the students pay what is late, 20% pay part of it,
    5% pay a month in advance, the rest owe (the debtors list has rows); the director voids
    one payment. Returns how many payments were taken. Skipped once payments exist."""
    if conn.execute("SELECT 1 FROM payments LIMIT 1").fetchone() is not None:
        return 0
    if debt.warning_threshold(conn) == 0:
        settings.set_value(conn, director, "defaults.max_debt_warning", DEBT_WARNING)
    taken = []
    for row in students.search(conn, director):
        owed = debt.for_student(conn, director, row.id).owed_now
        if owed <= 0:
            continue
        luck = rng.random()
        if luck < 0.55:
            amount = owed
        elif luck < 0.75:
            amount = max(owed // 2 // 100 * 100, 100)
        elif luck < 0.80:
            amount = owed + 3000
        else:
            continue
        main = next((c.contact_id for c in contacts.list_for_student(conn, director, row.id)
                     if c.is_main), None)
        cashier = desk if rng.random() < 0.8 else director
        taken.append(payments.record(conn, cashier, row.id, amount, rng.choice(METHODS), main))
    if taken:
        payments.void(conn, director, rng.choice(taken), "Démo : erreur de montant")
    return len(taken)


def seed_refunds(conn, director, desk, rng: random.Random) -> int:
    """Three refunds of 1 000 DA: paid out, approved, pending. Returns how many. Skipped once
    any exists."""
    if conn.execute("SELECT 1 FROM refunds LIMIT 1").fetchone() is not None:
        return 0
    asked = 0
    paid = [option for row in students.search(conn, director)
            for option in refunds.options(conn, director, row.id) if option.refundable >= 1000]
    rng.shuffle(paid)
    for step, option in zip(("paid", "approved", "pending"), paid):
        refund_id = refunds.request(conn, desk, option.charge_id, 1000, "Démo : départ")
        if step in ("paid", "approved"):
            refunds.approve(conn, director, refund_id)
        if step == "paid":
            refunds.pay_out(conn, desk, refund_id, "cash")
        asked += 1
    return asked


def main(path: Path) -> None:
    rng = random.Random(2026)
    path.parent.mkdir(parents=True, exist_ok=True)  # e.g. data/, which git does not keep
    conn = connect(path)
    migrate(conn)
    if auth.user_count(conn) == 0:
        auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")
        director = auth.login(conn, "directeur", "password1")
        auth.create_user(conn, director, "accueil", "password2", "receptionist")
    director = auth.login(conn, "directeur", "password1")
    seed_school(conn, director, rng)

    created = 0
    for family in FAMILIES:
        father = ContactInput(f"{rng.choice(FATHERS)} {family}", phone(rng))
        mother = ContactInput(f"{rng.choice(MOTHERS)} {family}", phone(rng))
        father_id = None
        for _ in range(rng.choice((1, 1, 2, 3))):
            born = date(rng.randrange(2008, 2019), rng.randrange(1, 13), rng.randrange(1, 29))
            data = StudentInput(rng.choice(FIRST_NAMES), family, born)
            if father_id is None:
                student_id = students.create(conn, director, data, father,
                                             ContactLink("Père", is_main=True))
                father_id = contacts.list_for_student(conn, director, student_id)[0].contact_id
                if rng.random() < 0.6:
                    contacts.add(conn, director, student_id, mother,
                                 ContactLink("Mère", can_receive_sms=rng.random() < 0.7))
            else:
                student_id = students.create(conn, director, data)
                contacts.link_existing(conn, director, student_id, father_id, ContactLink("Père"))
            created += 1
            if rng.random() < 0.1:
                students.deactivate(conn, director, student_id)
    registered, placed = seed_enrollments(conn, director, rng)
    marked = seed_sessions(conn, director, rng)
    desk = auth.login(conn, "accueil", "password2")
    paid = seed_payments(conn, director, desk, rng)
    asked = seed_refunds(conn, director, desk, rng)
    conn.close()
    print(f"{created} students created in {path}: {registered} registered for the year, "
          f"{placed} placed in groups, {marked} attendance line(s) taken today, "
          f"{paid} payment(s) received, {asked} refund(s)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
