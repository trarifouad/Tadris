"""Phase 6 tasks 2 and 3: sessions generated from the timetable, then cancel, restore,
makeup and substitute, on a copy of the database.

Run from the project root:  .venv/bin/python scripts/manual/try_sessions.py
"""
from datetime import date, timedelta

from _common import Setup, attempt, open_copy

from tadris.core import dates
from tadris.domain.models import SlotInput, TeacherInput
from tadris.services import groups, holidays, rooms, sessions, teachers, timetable

conn, director, desk = open_copy("sessions")
school = Setup(conn, director)
today = dates.today()
DAYS = ["", "lun", "mar", "mer", "jeu", "ven", "sam", "dim"]


def next_day(weekday: int, after=today):
    return after + timedelta(days=(weekday - after.isoweekday()) % 7)


def show(title, group_ids):
    print(f"  {title}")
    rows = conn.execute(
        "SELECT s.date, s.start_time, s.end_time, s.status, g.name AS grp, r.name AS room, "
        "t.full_name AS teacher FROM sessions s JOIN class_groups g ON g.id = s.group_id "
        "JOIN rooms r ON r.id = s.room_id JOIN teachers t ON t.id = s.teacher_id "
        f"WHERE s.group_id IN ({','.join('?' * len(group_ids))}) ORDER BY s.date, s.start_time",
        group_ids).fetchall()
    for r in rows:
        day = dates.display_date(r["date"])
        weekday = DAYS[dates.weekday_1_to_7(date.fromisoformat(r["date"]))]
        print(f"    {weekday} {day}  {r['start_time']}-{r['end_time']}  {r['grp']:<8} "
              f"{r['room']:<10} {r['teacher']:<14} {r['status']}")
    if not rows:
        print("    (aucune séance)")


room = rooms.create(conn, director, "Salle essai", 20)
other_teacher = teachers.create(conn, director, TeacherInput("Prof remplaçant"), 5000, today)
g_a = school.group("Essai A", school.lvl1)
print(f"Aujourd'hui : {dates.display_date(dates.iso(today))}. Fenêtre : 14 jours.\n")

print("1. Un créneau le lundi 17:00-18:30 pour Essai A")
slot = timetable.add_slot(conn, director, SlotInput(g_a, room, 1, "17:00", "18:30"))
show("Séances créées tout de suite :", [g_a])
print(f"   Régénérer une 2e fois : {sessions.generate(conn, director).created} séance créée")

monday = next_day(1, today + timedelta(days=1))
print(f"\n2. Jour férié le {dates.display_date(dates.iso(monday))}")
holiday = holidays.create(conn, director, "Jour férié (essai)", monday)
show("Après le jour férié :", [g_a])
holidays.remove(conn, director, holiday)
show("Jour férié supprimé, la séance revient :", [g_a])

print("\n3. Le créneau passe au samedi 09:00-10:30")
attempt("Déplacer le créneau",
        lambda: timetable.update_slot(conn, director, slot,
                                      SlotInput(g_a, room, 6, "09:00", "10:30")))
show("Les séances suivent :", [g_a])

saturday = next_day(6, today + timedelta(days=8))
print(f"\n4. Nouvel enseignant à partir du {dates.display_date(dates.iso(saturday))}")
attempt("Changer d'enseignant",
        lambda: groups.change_teacher(conn, director, g_a, other_teacher, saturday))
show("Avant cette date, l'ancien ; après, le nouveau :", [g_a])

first = conn.execute("SELECT id, date FROM sessions WHERE group_id = ? ORDER BY date",
                     (g_a,)).fetchone()
when = dates.display_date(first["date"])
print(f"\n5. Annuler la séance du {when}")
attempt("Annuler sans motif", lambda: sessions.cancel(conn, desk, first["id"], " "))
attempt("Annuler (motif : Enseignant malade)",
        lambda: sessions.cancel(conn, desk, first["id"], "Enseignant malade"))
attempt("Restaurer (annulée par erreur)", lambda: sessions.restore(conn, desk, first["id"]))
attempt("Annuler à nouveau", lambda: sessions.cancel(conn, desk, first["id"], "Grève"))
makeup_day = next_day(5, today + timedelta(days=1))  # a Friday
print(f"\n6. Rattrapage le {dates.display_date(dates.iso(makeup_day))}")
makeup = attempt("Rattrapage 07:00-08:00 (avant l'ouverture)",
                 lambda: sessions.schedule_makeup(conn, desk, first["id"], makeup_day, "7h",
                                                  "8h", room))
makeup = attempt("Rattrapage 10:00-11:30, Salle essai",
                 lambda: sessions.schedule_makeup(conn, desk, first["id"], makeup_day, "10h",
                                                  "11h30", room))
attempt("Un 2e rattrapage pour la même séance",
        lambda: sessions.schedule_makeup(conn, desk, first["id"], makeup_day, "14h", "15h",
                                         room))
attempt("Restaurer la séance rattrapée", lambda: sessions.restore(conn, desk, first["id"]))
second = conn.execute("SELECT id FROM sessions WHERE group_id = ? AND status = 'planned' "
                      "AND source = 'generated' ORDER BY date", (g_a,)).fetchone()
print("\n7. Remplaçant pour une seule séance")
attempt("Prof remplaçant sur la séance suivante",
        lambda: sessions.set_teacher(conn, desk, second["id"], other_teacher))
show("Séances d'Essai A (annulée, rattrapage, remplaçant) :", [g_a])

print("\n8. Clôture du groupe")
groups.close(conn, director, g_a)
show("Les séances prévues disparaissent (l'historique reste) :", [g_a])

print("\n9. Les groupes réels de votre base (régénération complète)")
result = sessions.generate(conn, director)
print(f"   {result.created} séance(s) créée(s), {len(result.conflicts)} conflit(s)")
real = [r[0] for r in conn.execute("SELECT id FROM class_groups WHERE name NOT LIKE 'Essai%'")]
if real:
    show("Séances des 14 prochains jours :", real)
conn.close()
