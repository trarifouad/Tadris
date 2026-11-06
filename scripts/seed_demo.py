"""Fill a database with a demo school the size of an average tutoring school (soutien
scolaire), lived day by day from the first week of September to today, so every page has
realistic rows.

The school: the 2026-2027 year, the 5AP to 3AS levels and « Tous niveaux » (open to every
level, for the workshops), 7 school subjects and 2 workshops (calligraphie, arts
plastiques), 9 rooms, 14 teachers, 38 groups. About 120 families: 210 pupils or so, most in
the exam years (5AP, 4AM, 3AS), each with the age of their level, and a few adults who only
take a workshop. Groups meet twice a week (workshops once, for two hours): weekday
evenings, Friday afternoon and Saturday.

Then, day by day through the services, as the desk would: pupils register and enter their
groups on their own day, most in September, fewer in October (some on trial, a few leave or
switch later); some also take a workshop. Months are renewed around their end (most pupils
stay); each family pays as it usually does: on the day, late, half now and the rest later,
or not at all, so the debtors have every age. Every past session has its attendance (each
pupil with their own habit); today's sessions are marked once started. On the last day of
each month the teachers are paid for the months over by then (a month is paid once it is
done). Then: holidays, a cancelled session with its makeup, a substitute, a voided payment.

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
    "Bensaid", "Guerfi", "Hadjadj", "Larbi", "Mebarki", "Nait", "Abbas", "Aissaoui",
    "Bekkouche", "Benamar", "Bendjelloul", "Benmoussa", "Bouchama", "Boukhari", "Chaouch",
    "Dahmani", "Derradji", "Djellouli", "Fodil", "Ghezal", "Hamadouche", "Kadri", "Kebir",
    "Khaldi", "Laribi", "Madani", "Mammeri", "Messaoudi", "Mokrani", "Moussaoui", "Naceri",
    "Rezki", "Saadi", "Sahraoui", "Tahri", "Taleb",
]
FIRST_NAMES = [
    "Amine", "Yanis", "Lina", "Sara", "Rayan", "Ines", "Adam", "Meriem", "Walid", "Hiba",
    "Islam", "Nour", "Anis", "Aya", "Mehdi", "Ilyes", "Chaïma", "Riad", "Maya", "Sofiane",
    "Yasmine", "Karim", "Dounia", "Nassim", "Amira", "Bilal", "Selma", "Abdelkader", "Asma",
    "Younes", "Rania", "Zakaria", "Imane", "Haroun", "Malak", "Ayoub", "Wissem", "Djihane",
    "Mohamed", "Fatima Zohra", "Abderrahmane", "Kenza", "Oussama", "Lyna",
]
FATHERS = ["Karim", "Mourad", "Farid", "Rachid", "Nabil", "Samir", "Djamel", "Hakim",
           "Khaled", "Mustapha", "Abdelaziz", "Hocine", "Toufik", "Lakhdar"]
MOTHERS = ["Nadia", "Samia", "Fatima", "Amel", "Leila", "Souad", "Karima", "Wafa", "Naima",
           "Houria", "Saliha", "Zohra", "Malika", "Faiza"]


def phone(rng: random.Random) -> str:
    return f"0{rng.choice('567')}{rng.randrange(10**8):08d}"


# ----- the school -----

LEVELS = ["5AP", "1AM", "2AM", "3AM", "4AM", "1AS", "2AS", "3AS"]
OPEN_LEVEL = "Tous niveaux"
# Of 100 pupils, how many in each level: the exam years (5AP, 4AM, 3AS) the most.
LEVEL_SHARE = {"5AP": 10, "1AM": 8, "2AM": 8, "3AM": 9, "4AM": 20, "1AS": 9, "2AS": 12,
               "3AS": 24}
# The year a pupil of the level is born (one in seven repeated a year: born the year before).
BORN = {"5AP": 2015, "1AM": 2014, "2AM": 2013, "3AM": 2012, "4AM": 2011, "1AS": 2010,
        "2AS": 2009, "3AS": 2008}
# How many subjects a pupil of the level takes: more in the exam years.
SUBJECTS_TAKEN = {"5AP": (1, 1, 2), "1AM": (1, 1, 2), "2AM": (1, 1, 2), "3AM": (1, 2),
                  "4AM": (2, 2, 3), "1AS": (1, 1, 2), "2AS": (1, 2), "3AS": (2, 2, 3)}
SUBJECTS = ["Mathématiques", "Physique", "Sciences", "Français", "Anglais", "Arabe",
            "Philosophie"]
WORKSHOPS = ["Calligraphie", "Arts plastiques"]  # subjects of the open level
ROOMS = [("Salle 1", 20), ("Salle 2", 20), ("Salle 3", 18), ("Salle 4", 18), ("Salle 5", 16),
         ("Salle 6", 24), ("Salle 7", 16), ("Labo", 16), ("Atelier", 14)]
TEACHERS = [  # (name, rate in basis points)
    ("Karim Haddad", 6000),      # 0 maths, lycée
    ("Mourad Saidi", 5500),      # 1 maths, CEM
    ("Amina Brahimi", 5000),     # 2 maths, primaire and 1AM-2AM, 1AS
    ("Samia Rahmani", 6000),     # 3 physique, lycée
    ("Nabil Cherif", 5500),      # 4 physique, CEM
    ("Amel Kaci", 5500),         # 5 sciences
    ("Leila Bouzid", 5000),      # 6 français, lycée and 4AM
    ("Hocine Mansouri", 5000),   # 7 français, primaire and CEM
    ("Yasmine Ferhat", 5000),    # 8 anglais, lycée and 4AM
    ("Rachid Lounis", 5000),     # 9 anglais, CEM
    ("Nadia Belkacem", 5000),    # 10 arabe
    ("Djamel Ouali", 5500),      # 11 philosophie
    ("Fatima Zerrouki", 5000),   # 12 calligraphie
    ("Sofiane Toumi", 5000),     # 13 arts plastiques
]
# (subject, level, group name, teacher index, monthly price, capacity)
GROUPS = [
    ("Mathématiques", "5AP", "Maths 5AP", 2, 1800, 16),
    ("Arabe", "5AP", "Arabe 5AP", 10, 1500, 16),
    ("Français", "5AP", "Français 5AP", 7, 1500, 16),
    ("Mathématiques", "1AM", "Maths 1AM", 2, 2000, 16),
    ("Français", "1AM", "Français 1AM", 7, 2000, 16),
    ("Anglais", "1AM", "Anglais 1AM", 9, 2000, 16),
    ("Mathématiques", "2AM", "Maths 2AM", 2, 2000, 16),
    ("Physique", "2AM", "Physique 2AM", 4, 2000, 16),
    ("Français", "2AM", "Français 2AM", 7, 2000, 16),
    ("Mathématiques", "3AM", "Maths 3AM", 1, 2500, 16),
    ("Physique", "3AM", "Physique 3AM", 4, 2500, 16),
    ("Anglais", "3AM", "Anglais 3AM", 9, 2000, 16),
    ("Mathématiques", "4AM", "Maths 4AM G1", 1, 3000, 18),
    ("Mathématiques", "4AM", "Maths 4AM G2", 1, 3000, 18),
    ("Physique", "4AM", "Physique 4AM G1", 4, 2500, 18),
    ("Physique", "4AM", "Physique 4AM G2", 4, 2500, 18),
    ("Sciences", "4AM", "Sciences 4AM", 5, 2500, 18),
    ("Français", "4AM", "Français 4AM", 6, 2500, 18),
    ("Anglais", "4AM", "Anglais 4AM", 8, 2500, 18),
    ("Arabe", "4AM", "Arabe 4AM", 10, 2500, 18),
    ("Mathématiques", "1AS", "Maths 1AS", 2, 3000, 16),
    ("Physique", "1AS", "Physique 1AS", 3, 3000, 16),
    ("Français", "1AS", "Français 1AS", 6, 2500, 16),
    ("Mathématiques", "2AS", "Maths 2AS", 0, 3500, 18),
    ("Physique", "2AS", "Physique 2AS", 3, 3500, 18),
    ("Sciences", "2AS", "Sciences 2AS", 5, 3000, 16),
    ("Anglais", "2AS", "Anglais 2AS", 8, 3000, 16),
    ("Mathématiques", "3AS", "Maths 3AS G1", 0, 4000, 20),
    ("Mathématiques", "3AS", "Maths 3AS G2", 0, 4000, 20),
    ("Physique", "3AS", "Physique 3AS G1", 3, 4000, 20),
    ("Physique", "3AS", "Physique 3AS G2", 3, 4000, 20),
    ("Sciences", "3AS", "Sciences 3AS", 5, 3500, 18),
    ("Philosophie", "3AS", "Philosophie 3AS", 11, 3000, 18),
    ("Anglais", "3AS", "Anglais 3AS", 8, 3000, 18),
    ("Français", "3AS", "Français 3AS", 6, 3000, 18),
    ("Calligraphie", OPEN_LEVEL, "Calligraphie G1", 12, 2000, 14),
    ("Calligraphie", OPEN_LEVEL, "Calligraphie G2", 12, 2000, 14),
    ("Arts plastiques", OPEN_LEVEL, "Arts plastiques", 13, 2000, 14),
]
SLOTS_PER_GROUP = 2  # a school subject: twice a week, 1 h 30
WORKSHOP_SLOTS = 1  # a workshop: once a week, 2 h
# 1 = Monday ... 7 = Sunday. Classes run Sunday to Thursday after school, Friday after the
# prayer and all of Saturday.
STARTS = {5: ["14:00", "15:30", "17:00"], 6: ["08:30", "10:00", "13:30", "15:00", "16:30"]}
EVENING_STARTS = ["16:30", "18:00", "19:30"]
SCHOOL_HOURS = ("08:00", "21:00")
GROUP_START = date(2026, 9, 5)  # the first Saturday of September
SLOT_TRIES = 400  # a group that cannot find a free hour after so many tries keeps fewer


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
    level_ids = {name: catalog.create(conn, director, "level", name)
                 for name in LEVELS + [OPEN_LEVEL]}
    catalog.set_open(conn, director, level_ids[OPEN_LEVEL], True)
    subject_ids = {name: catalog.create(conn, director, "subject", name)
                   for name in SUBJECTS + WORKSHOPS}
    for name in WORKSHOPS:
        catalog.set_workshop(conn, director, subject_ids[name], True)
    room_ids = {name: rooms.create(conn, director, name, capacity) for name, capacity in ROOMS}
    teacher_ids = [
        teachers.create(conn, director, TeacherInput(name, phone(rng), date(2024, 9, 1)), bp,
                        date(2026, 9, 1))
        for name, bp in TEACHERS
    ]
    for subject, level, name, teacher, price, capacity in GROUPS:
        group_id = groups.create(conn, director, GroupInput(
            year, level_ids[level], subject_ids[subject], name, price, capacity,
            GROUP_START), teacher_ids[teacher])
        workshop = subject in WORKSHOPS
        _place_slots(conn, director, rng, group_id,
                     WORKSHOP_SLOTS if workshop else SLOTS_PER_GROUP,
                     120 if workshop else 90,
                     [room_ids["Atelier"]] if workshop else
                     [r for n, r in room_ids.items() if n != "Atelier"])


def _place_slots(conn, director, rng: random.Random, group_id: int, count: int,
                 minutes: int, room_choices: list[int]) -> None:
    """`count` weekly slots on different days; what the services refuse (a room, the
    teacher or the group already busy) is tried again elsewhere."""
    days: set[int] = set()
    for _ in range(SLOT_TRIES):
        if len(days) == count:
            return
        weekday = rng.choice((5, 6, 6, 7, 1, 2, 3, 4))
        if weekday in days:
            continue
        start = rng.choice(STARTS.get(weekday, EVENING_STARTS))
        try:
            timetable.add_slot(conn, director, SlotInput(
                group_id, rng.choice(room_choices), weekday, start, add_minutes(start, minutes),
                GROUP_START))
        except BusinessRuleError:
            continue
        days.add(weekday)


def _child(rng: random.Random, level: str) -> tuple[str, date]:
    """A pupil's level and birthday: the age of the level (or a year older, repeated)."""
    born = BORN[level] - (1 if rng.random() < 1 / 7 else 0)
    return level, date(born, rng.randrange(1, 13), rng.randrange(1, 29))


def seed_students(conn, director, rng: random.Random) -> dict[int, str]:
    """The families and their children; returns {student id: level} (the open level for
    the adults who only take a workshop). Some pupils are inactive (they left last year)."""
    levels = list(LEVEL_SHARE)
    weights = list(LEVEL_SHARE.values())
    made: dict[int, str] = {}
    families = FAMILIES + rng.sample(FAMILIES, k=55)  # two households of a name, often
    for family in families:
        father = ContactInput(f"{rng.choice(FATHERS)} {family}", phone(rng))
        mother = ContactInput(f"{rng.choice(MOTHERS)} {family}", phone(rng))
        father_id = None
        first_names = rng.sample(FIRST_NAMES, k=3)
        for index in range(rng.choice((1, 1, 2, 2, 2, 3))):
            level, born = _child(rng, rng.choices(levels, weights=weights)[0])
            data = StudentInput(first_names[index], family, born)
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
            if rng.random() < 0.05:
                students.deactivate(conn, director, student_id)
            else:
                made[student_id] = level
    for index in range(8):  # adults: a workshop only, their own phone
        family = rng.choice(FAMILIES)
        first = rng.choice(MOTHERS if index % 2 else FATHERS)
        born = date(rng.randrange(1970, 2004), rng.randrange(1, 13), rng.randrange(1, 29))
        student_id = students.create(conn, director, StudentInput(first, family, born),
                                     ContactInput(f"{first} {family}", phone(rng)),
                                     ContactLink("Élève adulte", is_main=True))
        made[student_id] = OPEN_LEVEL
    return made


# ----- the year, day by day -----

REGISTRATION_FEE = 1000
DEBT_WARNING = 10_000
METHODS = ["cash"] * 8 + ["transfer", "cheque"]
# How a family pays: on the day, a few days late, half now and the rest later, or not.
PAYERS = ["on_time"] * 13 + ["late"] * 3 + ["partial"] * 3 + ["never"] * 1
STAYS = 0.85  # a month is renewed (the others show as « non renouvelés »)
WORKSHOP_TOO = 0.1  # a pupil also takes a workshop
ATTENDANCE = {  # a pupil's habit: (present, late, absent, excused) weights
    "keen": (90, 6, 2, 2), "usual": (78, 8, 10, 4), "loose": (55, 10, 30, 5),
}
MARKS = ("present", "late", "absent", "excused")


@dataclass
class Pupil:
    student_id: int
    level_id: int
    # One entry per subject taken: its groups, the preferred first (the others when that
    # one is full or meets at the hour of another of the pupil's groups).
    groups: list[list[int]]
    entry: date
    payer: str
    habit: str
    trial: bool = False
    leaves_on: date | None = None  # leaves the first group that day
    switches_on: date | None = None  # moves the first group to another of the same subject
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
    payouts: int = 0

    def pay_on(self, day: date, student_id: int, how: str) -> None:
        self.to_pay.setdefault(day, []).append((student_id, how))


def _entry_day(rng: random.Random, today: date) -> date:
    """Most enter in the first two weeks, many through September, fewer in October."""
    luck = rng.random()
    if luck < 0.55:
        offset = rng.randrange(0, 14)
    elif luck < 0.85:
        offset = rng.randrange(14, 26)
    else:
        offset = rng.randrange(26, 60)
    return min(GROUP_START + timedelta(days=offset), today)


def plan(conn, director, rng: random.Random, today: date, levels: dict[int, str]) -> Year:
    """Who registers, in which groups, on which day, and how they pay and attend."""
    level_ids = {i.name: i.id for i in catalog.list_items(conn, director, "level")}
    # Per level, its groups by subject (a subject with two groups: one of them).
    by_level: dict[int, dict[int, list[int]]] = {}
    for g in groups.search(conn, director):
        if g.status != "closed":
            by_level.setdefault(g.level_id, {}).setdefault(g.subject_id, []).append(g.id)
    workshops = [ids for ids in by_level.get(level_ids[OPEN_LEVEL], {}).values()]
    year = Year()
    for student_id, level in levels.items():
        if level != OPEN_LEVEL and rng.random() > 0.92:
            continue  # not back this year (yet)
        level_id = level_ids[level]
        subjects = by_level[level_id]
        if level == OPEN_LEVEL:
            wanted = [rng.choice(workshops)]
        else:
            count = min(len(subjects), rng.choice(SUBJECTS_TAKEN[level]))
            wanted = rng.sample(list(subjects.values()), k=count)
            if rng.random() < WORKSHOP_TOO:
                wanted.append(rng.choice(workshops))
        wanted = [rng.sample(ids, k=len(ids)) for ids in wanted]  # which group first
        entry = _entry_day(rng, today)
        pupil = Pupil(student_id, level_id, wanted, entry, rng.choice(PAYERS),
                      rng.choice(("keen", "usual", "usual", "usual", "loose")),
                      trial=rng.random() < 0.1)
        luck = rng.random()
        if luck < 0.05:
            pupil.leaves_on = entry + timedelta(days=rng.randrange(10, 35))
        elif luck < 0.1:
            pupil.switches_on = entry + timedelta(days=rng.randrange(5, 20))
        year.pupils[student_id] = pupil
    return year


def _enter(conn, director, year: Year, pupil: Pupil, day: date, rng: random.Random) -> None:
    if registrations.current(conn, director, pupil.student_id) is None:
        registrations.register(conn, director, pupil.student_id, pupil.level_id)
        year.registered += 1
    trial = pupil.trial
    for choices in pupil.groups:
        for group_id in choices:
            try:
                enrollments.enroll(conn, director, pupil.student_id, group_id, trial=trial,
                                   enrolled_on=day)
            except BusinessRuleError:
                continue  # full, or at the hour of another of their groups: the next one
            year.placed += 1
            if trial and rng.random() < 0.6:  # most confirm after their trial week
                pupil.confirms_on = day + timedelta(days=7)
            trial = False  # the first group placed only
            break
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
    """Months ending within two days are renewed at the desk (most of them)."""
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
            else:  # to the other group of the same subject, when there is one
                group = groups.get(conn, director, live[0].group_id)
                others = [g.id for g in groups.search(conn, director, level_id=group.level_id,
                                                      subject_id=group.subject_id)
                          if g.status != "closed" and g.id != group.id]
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


def _payday(conn, director, year: Year, day: date, today: date) -> None:
    """The last day of the month: every teacher is paid for the months over by then. The
    latest payday before today leaves a few payouts approved, not paid yet."""
    built, _refused = payouts.run(conn, director, day)
    latest = (day + timedelta(days=1)).month == today.month and day < today
    for index, payout_id in enumerate(built):
        payouts.approve(conn, director, payout_id)
        if not latest or index % 3 != 2:
            payouts.mark_paid(conn, director, payout_id, "cash" if index % 4 else "transfer")
    year.payouts += len(built)


def live_the_year(conn, director, desk, rng: random.Random, today: date,
                  levels: dict[int, str], void_on: date) -> Year:
    year = plan(conn, director, rng, today, levels)
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
            if day == void_on:
                seed_void(conn, director, rng)  # before a payday locks its months
            if (day + timedelta(days=1)).month != day.month and day < today:
                _payday(conn, director, year, day, today)
        day += timedelta(days=1)
    return year


# ----- the calendar, today's changes -----

HOLIDAYS = [("1er Novembre", date(2026, 11, 1), None),
            ("Vacances d'hiver", date(2026, 12, 20), date(2027, 1, 3))]


def seed_calendar(conn, director) -> None:
    """Holidays (before any session is generated), the school's details and hours (before
    any slot), the registration fee and the debt warning."""
    if not holidays.list_holidays(conn, director):
        for label, start, end in HOLIDAYS:
            holidays.create(conn, director, label, start, end)
    if not settings.get(conn, "school.address"):
        settings.save_school(conn, director, settings.get(conn, "school.name"),
                             "0550 12 34 56", "12 rue des Oliviers, Oran", *SCHOOL_HOURS,
                             receipt_footer="Merci de votre confiance.")
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
    """The director voids one payment of the day (a payout would lock its months)."""
    ids = [row[0] for row in conn.execute(
        "SELECT id FROM payments WHERE substr(paid_at, 1, 10) = ?", (dates.iso(dates.today()),))]
    rng.shuffle(ids)
    for payment_id in ids:
        try:
            payments.void(conn, director, payment_id, "Démo : erreur de montant")
            return
        except BusinessRuleError:
            continue


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
    seed_calendar(conn, director)
    seed_school(conn, director, rng)
    levels = seed_students(conn, director, rng)
    # A payment voided in the second week of September, before any payday.
    year = live_the_year(conn, director, desk, rng, today, levels,
                         void_on=min(GROUP_START + timedelta(days=10), today))
    seed_changes(conn, director, today)
    conn.close()
    print(f"{len(levels)} students created in {path}: {year.registered} registered for the "
          f"year, {year.placed} placed in groups, {year.renewed} month(s) renewed, "
          f"{year.marked} attendance line(s), {year.paid} payment(s) received, "
          f"{year.payouts} teacher payout(s)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
