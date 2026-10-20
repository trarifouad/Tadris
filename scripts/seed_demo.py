"""Fill a database with a demo school, lived day by day from the groups' start to today, so
every page and report has realistic rows.

The school: a year, 7 levels, 6 subjects, 6 rooms, 7 teachers, 14 groups with three weekly
slots each, about 30 families (55 to 60 students, some inactive). Then, day by day through
the services, as the desk would: students register and enter their groups on their own day
(some on trial, a few leave or switch later), months are renewed around their end (most
students stay), and each student pays as they usually do: on the day, late, half now and the
rest later, or not at all, so the debtors have every age. Every past session has its
attendance (each student with their own habit); today's sessions are marked once started.
Then: holidays, a cancelled session with its makeup, a substitute, a voided payment, refunds
(paid out, approved, pending) and the teachers paid up to the end of last month (one paid,
the others approved).

Usage: python scripts/seed_demo.py PATH.db
The path is required so the real database is never seeded by accident. Creates the director
account (directeur / password1) and a receptionist (accueil / password2) if the file is new.
A database that already has students is left as it is.
"""

import random
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from tadris.core import dates
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
    payouts,
    refunds,
    registrations,
    rooms,
    school_years,
    sessions,
    settings,
    students,
    subscriptions,
    teachers,
    timetable,
)

FAMILIES = [
    "Benali", "Haddad", "Mansouri", "Bouzid", "Saidi", "Khelifi", "Belkacem", "Meziane",
    "Brahimi", "Cherif", "Amrani", "Ferhat", "Zerrouki", "Boudiaf", "Hamidi", "Rahmani",
    "Djebbar", "Kaci", "Lounis", "Ouali", "Slimani", "Toumi", "Yahiaoui", "Zitouni",
    "Bensaid", "Guerfi", "Hadjadj", "Larbi", "Mebarki", "Nait",
]
FIRST_NAMES = [
    "Amine", "Yanis", "Lina", "Sara", "Rayan", "Ines", "Adam", "Meriem", "Walid", "Hiba",
    "Islam", "Nour", "Anis", "Aya", "Mehdi", "Hélène", "Ilyes", "Chaïma", "Riad", "Maya",
    "Sofiane", "Yasmine", "Karim", "Dounia", "Nassim", "Amira", "Bilal", "Selma",
]
FATHERS = ["Karim", "Mourad", "Farid", "Rachid", "Nabil", "Samir", "Djamel", "Hakim"]
MOTHERS = ["Nadia", "Samia", "Fatima", "Amel", "Leila", "Souad", "Karima", "Wafa"]


def phone(rng: random.Random) -> str:
    return f"0{rng.choice('567')}{rng.randrange(10**8):08d}"


LEVELS = ["1AM", "2AM", "3AM", "4AM", "1AS", "2AS", "3AS"]
SUBJECTS = ["Mathématiques", "Physique", "Sciences", "Français", "Anglais", "Arabe"]
ROOMS = [("Salle A", 20), ("Salle B", 15), ("Salle C", 25), ("Salle D", 18), ("Labo", 12),
         ("Salle E", 16)]
TEACHERS = [("Karim Haddad", 6000), ("Samia Rahmani", 5500), ("Nabil Cherif", 6000),
            ("Leila Bouzid", 5000), ("Mourad Saidi", 6500), ("Amel Kaci", 5500),
            ("Rachid Lounis", 6000)]
# (subject, level, group name, teacher index, price, capacity)
GROUPS = [
    ("Mathématiques", "4AM", "Maths 4AM G1", 0, 3000, 15),
    ("Mathématiques", "4AM", "Maths 4AM G2", 0, 3000, 15),
    ("Physique", "4AM", "Physique 4AM", 1, 2500, 15),
    ("Français", "4AM", "Français 4AM", 3, 2000, 16),
    ("Mathématiques", "3AS", "Maths 3AS", 4, 4000, 20),
    ("Physique", "3AS", "Physique 3AS", 1, 3500, 12),
    ("Sciences", "3AS", "Sciences 3AS", 5, 3500, 12),
    ("Français", "1AM", "Français 1AM", 3, 2000, 20),
    ("Mathématiques", "1AM", "Maths 1AM", 6, 2500, 18),
    ("Anglais", "2AS", "Anglais 2AS", 2, 2500, 15),
    ("Mathématiques", "2AS", "Maths 2AS", 4, 3500, 15),
    ("Sciences", "3AM", "Sciences 3AM", 2, 2500, 12),
    ("Arabe", "2AM", "Arabe 2AM", 5, 2000, 16),
    ("Mathématiques", "1AS", "Maths 1AS", 6, 3000, 16),
]
SLOTS_PER_GROUP = 3
WEEKEND_STARTS = ["08:30", "10:00", "13:30", "15:00"]
EVENING_STARTS = ["16:30", "18:00", "19:30"]
GROUP_START = date(2026, 9, 15)


@contextmanager
def on_day(day: date):
    """The services believe it is `day` (they all read dates.today())."""
    saved = dates.today
    dates.today = lambda: day
    try:
        yield
    finally:
        dates.today = saved


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
        placed, days = 0, set()
        while placed < SLOTS_PER_GROUP:
            # Weekend daytime and weekday evenings, one slot a day; skip what the services
            # refuse (a room, a teacher or the group already busy).
            weekday = rng.choice((5, 6, 6, 7, 1, 2, 3, 4))
            if weekday in days:
                continue
            start = rng.choice(WEEKEND_STARTS if weekday in (5, 6) else EVENING_STARTS)
            end = add_minutes(start, 90)
            try:
                timetable.add_slot(conn, director, SlotInput(
                    group_id, rng.choice(room_ids), weekday, start, end, GROUP_START))
            except BusinessRuleError:
                continue
            placed += 1
            days.add(weekday)


def seed_students(conn, director, rng: random.Random) -> int:
    created = 0
    for family in FAMILIES:
        father = ContactInput(f"{rng.choice(FATHERS)} {family}", phone(rng))
        mother = ContactInput(f"{rng.choice(MOTHERS)} {family}", phone(rng))
        father_id = None
        for _ in range(rng.choice((1, 1, 2, 2, 3))):
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
            if rng.random() < 0.08:
                students.deactivate(conn, director, student_id)
    return created


# ----- the year, day by day -----

REGISTRATION_FEE = 1500
DEBT_WARNING = 10_000
METHODS = ["cash"] * 8 + ["transfer", "cheque"]
# How a family pays: on the day, a few days late, half now and the rest later, or not.
PAYERS = ["on_time"] * 13 + ["late"] * 3 + ["partial"] * 3 + ["never"] * 1
STAYS = 0.8  # a month is renewed (the others show as « non renouvelés »)
ATTENDANCE = {  # a student's habit: (present, late, absent, excused) weights
    "keen": (90, 6, 2, 2), "usual": (78, 8, 10, 4), "loose": (55, 10, 30, 5),
}
MARKS = ("present", "late", "absent", "excused")


@dataclass
class Pupil:
    student_id: int
    level_id: int
    groups: list[int]
    entry: date
    payer: str
    habit: str
    trial: bool = False
    leaves_on: date | None = None  # leaves the first group that day
    switches_on: date | None = None  # moves the first group to another of the level
    confirms_on: date | None = None  # the trial becomes a place (its first month starts)


@dataclass
class Year:
    pupils: dict[int, Pupil] = field(default_factory=dict)
    to_pay: dict[date, list[tuple[int, str]]] = field(default_factory=dict)
    decided: set[int] = field(default_factory=set)  # months whose renewal was decided
    registered: int = 0
    placed: int = 0
    paid: int = 0
    marked: int = 0
    renewed: int = 0

    def pay_on(self, day: date, student_id: int, how: str) -> None:
        self.to_pay.setdefault(day, []).append((student_id, how))


def plan(conn, director, rng: random.Random, today: date) -> Year:
    """Who registers, in which groups, on which day, and how they pay and attend."""
    by_level: dict[int, list[int]] = {}
    for g in groups.search(conn, director):
        if g.status != "closed":
            by_level.setdefault(g.level_id, []).append(g.id)
    year = Year()
    last_entry = max(min(today, GROUP_START + timedelta(days=40)), GROUP_START)
    span = (last_entry - GROUP_START).days
    for row in students.search(conn, director, status="active"):
        if rng.random() > 0.88:
            continue  # not registered this year
        level_id = rng.choice(list(by_level))
        wanted = rng.sample(by_level[level_id], k=min(len(by_level[level_id]),
                                                       rng.choice((1, 1, 2))))
        # Most enter in the first two weeks, the others through October.
        offset = int(rng.triangular(0, span, 0)) if span else 0
        entry = GROUP_START + timedelta(days=offset)
        pupil = Pupil(row.id, level_id, wanted, entry, rng.choice(PAYERS),
                      rng.choice(("keen", "usual", "usual", "usual", "loose")),
                      trial=rng.random() < 0.12)
        luck = rng.random()
        if luck < 0.06:
            pupil.leaves_on = entry + timedelta(days=rng.randrange(10, 30))
        elif luck < 0.14 and len(by_level[level_id]) > len(wanted):
            pupil.switches_on = entry + timedelta(days=rng.randrange(5, 20))
        year.pupils[row.id] = pupil
    return year


def _enter(conn, director, year: Year, pupil: Pupil, day: date, rng: random.Random) -> None:
    if registrations.current(conn, director, pupil.student_id) is None:
        registrations.register(conn, director, pupil.student_id, pupil.level_id)
        year.registered += 1
    for index, group_id in enumerate(pupil.groups):
        trial = pupil.trial and index == 0
        try:
            enrollments.enroll(conn, director, pupil.student_id, group_id, trial=trial,
                               enrolled_on=day)
        except BusinessRuleError:
            continue  # full: the desk offers another day
        year.placed += 1
        if trial and rng.random() < 0.5:  # half confirm after their trial week
            pupil.confirms_on = day + timedelta(days=7)
    _schedule_payment(year, pupil, day, rng)


def _schedule_payment(year: Year, pupil: Pupil, day: date, rng: random.Random) -> None:
    """day: when the new month (or the fee) is due."""
    if pupil.payer == "on_time":
        year.pay_on(day + timedelta(days=rng.choice((0, 0, 0, 1, 2))), pupil.student_id, "all")
    elif pupil.payer == "late":
        year.pay_on(day + timedelta(days=rng.randrange(8, 40)), pupil.student_id, "all")
    elif pupil.payer == "partial":
        year.pay_on(day, pupil.student_id, "half")
        year.pay_on(day + timedelta(days=rng.randrange(15, 45)), pupil.student_id, "all")


def _pay(conn, cashier, student_id: int, how: str, rng: random.Random) -> bool:
    owed = debt.for_student(conn, cashier, student_id).owed_now
    if owed <= 0:
        return False
    amount = owed if how == "all" else max(owed // 2 // 100 * 100, 100)
    main = next((c.contact_id for c in contacts.list_for_student(conn, cashier, student_id)
                 if c.is_main), None)
    payments.record(conn, cashier, student_id, amount, rng.choice(METHODS), main)
    return True


def _renewals(conn, director, year: Year, day: date, rng: random.Random) -> None:
    """Months ending within two days are renewed at the desk (80 % of them)."""
    for month in subscriptions.ending_soon(conn, director, days=2):
        if month.enrollment_status != "active" or month.student_id not in year.pupils:
            continue
        if month.id in year.decided:  # seen on an earlier day: kept as decided then
            continue
        year.decided.add(month.id)
        if rng.random() > STAYS:
            continue
        try:
            subscriptions.renew(conn, director, month.id)
        except BusinessRuleError:
            continue
        year.renewed += 1
        # Paid from the new month's first day (owed_now counts what is due).
        _schedule_payment(year, year.pupils[month.student_id],
                          max(day, date.fromisoformat(month.end_date)), rng)


def _moves(conn, director, year: Year, day: date, rng: random.Random) -> None:
    for pupil in year.pupils.values():
        if day not in (pupil.leaves_on, pupil.switches_on, pupil.confirms_on):
            continue
        live = [e for e in enrollments.for_student(conn, director, pupil.student_id)
                if e.status in ("active", "trial")]
        if not live:
            continue
        try:
            if day == pupil.confirms_on:
                trial = next((e for e in live if e.status == "trial"), None)
                if trial is not None:
                    enrollments.confirm_trial(conn, director, trial.id)
                    _schedule_payment(year, pupil, day, rng)
            elif day == pupil.leaves_on:
                enrollments.leave(conn, director, live[0].id, reason="Démo : départ")
            else:
                others = [g.id for g in groups.search(conn, director, level_id=pupil.level_id)
                          if g.status != "closed" and g.id not in pupil.groups]
                if others:
                    enrollments.switch(conn, director, live[0].id, rng.choice(others))
        except BusinessRuleError:
            pass


def _attendance(conn, director, year: Year, day: date, until: str | None,
                rng: random.Random) -> None:
    """Every session of the day not cancelled; today only those already started."""
    for s in sessions.listing(conn, director, day, day):
        if s.status == "cancelled" or (until is not None and s.start_time > until):
            continue
        lines = attendance.roster(conn, director, s.id)
        marks = {}
        for line in lines:
            pupil = year.pupils.get(line.student_id)
            weights = ATTENDANCE[pupil.habit if pupil else "usual"]
            marks[line.enrollment_id] = rng.choices(MARKS, weights=weights)[0]
        if marks:
            year.marked += attendance.save(conn, director, s.id, marks)


def live_the_year(conn, director, desk, rng: random.Random, today: date) -> Year:
    year = plan(conn, director, rng, today)
    entering: dict[date, list[Pupil]] = {}
    for pupil in year.pupils.values():
        entering.setdefault(pupil.entry, []).append(pupil)
    now = f"{datetime.now():%H:%M}"
    day = min(GROUP_START, today)
    while day <= today:
        with on_day(day):
            subscriptions.mark_ended(conn)
            if (day - GROUP_START).days % 7 == 0 or day == today:
                sessions.generate(conn, director)  # the next 14 days
            for pupil in entering.get(day, []):
                _enter(conn, director, year, pupil, day, rng)
            _renewals(conn, director, year, day, rng)
            _moves(conn, director, year, day, rng)
            for student_id, how in year.to_pay.pop(day, []):
                cashier = desk if rng.random() < 0.8 else director
                year.paid += _pay(conn, cashier, student_id, how, rng)
            _attendance(conn, director, year, day, now if day == today else None, rng)
        day += timedelta(days=1)
    return year


# ----- today -----

HOLIDAYS = [("1er Novembre", date(2026, 11, 1), None),
            ("Vacances d'hiver", date(2026, 12, 20), date(2027, 1, 3))]


def seed_calendar(conn, director) -> None:
    """Holidays (before any session is generated) and the school's address."""
    if not holidays.list_holidays(conn, director):
        for label, start, end in HOLIDAYS:
            holidays.create(conn, director, label, start, end)
    if not settings.get(conn, "school.address"):
        opens_at, closes_at = settings.school_hours(conn)
        settings.save_school(conn, director, settings.get(conn, "school.name"),
                             "0550 12 34 56", "12 rue des Oliviers, Oran", opens_at, closes_at)
    if registrations.default_fee(conn) == 0:
        settings.set_value(conn, director, "defaults.registration_fee", REGISTRATION_FEE)
    if debt.warning_threshold(conn) == 0:
        settings.set_value(conn, director, "defaults.max_debt_warning", DEBT_WARNING)


def seed_changes(conn, director, today: date) -> None:
    """A future session cancelled with its makeup, another taught by a substitute."""
    future = [s for s in sessions.listing(conn, director, today + timedelta(days=1),
                                          today + timedelta(days=13))
              if s.status == "planned"]
    if len(future) < 2:
        return
    cancelled = future[0]
    sessions.cancel(conn, director, cancelled.id, "Enseignant malade")
    for offset in range(1, 6):  # the first free day after, same hours and room
        try:
            sessions.schedule_makeup(conn, director, cancelled.id,
                                     date.fromisoformat(cancelled.date) + timedelta(days=offset),
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


def seed_void(conn, director, rng: random.Random) -> None:
    """The director voids one payment (before the payouts, which would lock its months)."""
    ids = [row[0] for row in conn.execute("SELECT id FROM payments")]
    rng.shuffle(ids)
    for payment_id in ids:
        try:
            payments.void(conn, director, payment_id, "Démo : erreur de montant")
            return
        except BusinessRuleError:
            continue


def seed_refunds(conn, director, desk, rng: random.Random) -> int:
    """Three refunds of 1 000 DA: paid out, approved, pending. Returns how many."""
    asked = 0
    paid = [option for row in students.search(conn, director)
            for option in refunds.options(conn, director, row.id) if option.refundable >= 1000]
    rng.shuffle(paid)
    for step, option in zip(("paid", "approved", "pending"), paid, strict=False):
        refund_id = refunds.request(conn, desk, option.charge_id, 1000, "Démo : départ")
        if step in ("paid", "approved"):
            refunds.approve(conn, director, refund_id)
        if step == "paid":
            refunds.pay_out(conn, desk, refund_id, "cash")
        asked += 1
    return asked


def seed_payouts(conn, director, today: date) -> int:
    """The monthly run up to the end of last month: the first teacher paid in cash, the
    others approved. Returns how many payouts."""
    until = today.replace(day=1) - timedelta(days=1)
    if until < GROUP_START:
        return 0
    built, _refused = payouts.run(conn, director, until)
    for index, payout_id in enumerate(built):
        payouts.approve(conn, director, payout_id)
        if index == 0:
            payouts.mark_paid(conn, director, payout_id, "cash")
    return len(built)


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
    desk = auth.login(conn, "accueil", "password2")
    if conn.execute("SELECT 1 FROM students LIMIT 1").fetchone() is not None:
        conn.close()
        print(f"{path} already has students: nothing added.")
        return

    today = date.today()
    seed_school(conn, director, rng)
    seed_calendar(conn, director)
    created = seed_students(conn, director, rng)
    year = live_the_year(conn, director, desk, rng, today)
    seed_void(conn, director, rng)  # before the payouts lock their months
    seed_changes(conn, director, today)
    asked = seed_refunds(conn, director, desk, rng)
    teachers_paid = seed_payouts(conn, director, today)
    conn.close()
    print(f"{created} students created in {path}: {year.registered} registered for the year, "
          f"{year.placed} placed in groups, {year.renewed} month(s) renewed, "
          f"{year.marked} attendance line(s), {year.paid} payment(s) received, "
          f"{asked} refund(s), {teachers_paid} teacher payout(s)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
