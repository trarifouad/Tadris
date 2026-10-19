"""Phase 6 task 4: attendance (who is expected, save, correct, history), on a copy of the
database. The script moves the date to the session days.

Run from the project root:  .venv/bin/python scripts/manual/try_attendance.py
"""
import json
from datetime import date, timedelta

from _common import Setup, attempt, open_copy

from tadris.core import dates
from tadris.domain.models import SlotInput, StudentInput
from tadris.services import (
    attendance,
    enrollments,
    registrations,
    rooms,
    sessions,
    students,
    subscriptions,
    timetable,
)

conn, director, desk = open_copy("attendance")
school = Setup(conn, director)
real_today = dates.today()
LABELS = {None: "—", "present": "présent", "late": "en retard", "absent": "absent",
          "excused": "excusé"}

room = rooms.create(conn, director, "Salle essai", 20)
g_a = school.group("Essai A", school.lvl1)
timetable.add_slot(conn, director, SlotInput(g_a, room, 6, "09:00", "10:30"))  # Saturdays
start = real_today - timedelta(days=20)


def student(first, trial=False, entered=start):
    sid = students.create(conn, desk, StudentInput(first, "Essai"))
    registrations.register(conn, desk, sid, school.lvl1["id"], 0)
    return enrollments.enroll(conn, desk, sid, g_a, trial=trial, enrolled_on=entered), sid


(amine, amine_sid), (yanis, _) = student("Amine"), student("Yanis", trial=True)
(lina, _) = student("Lina", entered=real_today + timedelta(days=30))  # not yet in the group


def show(session_id):
    s = sessions.get(conn, director, session_id)
    print(f"  Séance du {dates.display_date(s.date)} ({s.status}) :")
    for line in attendance.roster(conn, director, session_id):
        badges = (" [Essai]" if line.trial else "") + (" [Mois non renouvelé]"
                                                       if line.not_renewed else "")
        print(f"    {line.student_name:<14} {LABELS[line.status]:<10}{badges}")


first = conn.execute("SELECT id, date FROM sessions WHERE group_id = ? ORDER BY date",
                     (g_a,)).fetchone()
print("1. Avant le jour de la séance")
show(first["id"])
attempt("Noter les présences maintenant",
        lambda: attendance.save(conn, desk, first["id"], {amine: "present"}))

day = date.fromisoformat(first["date"])
dates.today = lambda: day
print(f"\n2. Le jour de la séance ({dates.display_date(first['date'])})")
attempt("Amine présent, Yanis en retard",
        lambda: attendance.save(conn, desk, first["id"], {amine: "present", yanis: "late"}))
show(first["id"])
attempt("Lina (pas encore dans le groupe)",
        lambda: attendance.save(conn, desk, first["id"], {lina: "present"}))
attempt("Annuler la séance tenue", lambda: sessions.cancel(conn, desk, first["id"], "x"))

dates.today = lambda: day + timedelta(days=10)
print("\n3. Dix jours plus tard : correction (Yanis était absent, excusé)")
attempt("Corriger", lambda: attendance.save(conn, director, first["id"],
                                            {amine: "present", yanis: "excused"}))
show(first["id"])
row = conn.execute("SELECT new_value FROM audit_log WHERE action = 'attendance.save' "
                   "ORDER BY id DESC").fetchone()
print(f"  Journal : {json.loads(row[0])['changes']}")

month = subscriptions.for_enrollment(conn, director, amine)[0]
after = date.fromisoformat(month.end_date) + timedelta(days=1)
dates.today = lambda: after + timedelta(days=7)
sessions.generate(conn, director)
later = conn.execute("SELECT id FROM sessions WHERE group_id = ? AND date >= ? ORDER BY date",
                     (g_a, dates.iso(after))).fetchone()
print(f"\n4. Après la fin du mois d'Amine ({dates.display_date(month.end_date)})")
show(later["id"])
subscriptions.renew(conn, director, month.id)
print("  … renouvelé :")
show(later["id"])

print("\n5. Historique d'Amine")
history = attendance.for_student(conn, director, amine_sid)
for r in history:
    print(f"    {dates.display_date(r.date)}  {r.group_title:<28} {LABELS[r.status]}")
summary = attendance.summarize(r.status for r in history)
print(f"    présent {summary.present} · en retard {summary.late} · absent {summary.absent} · "
      f"excusé {summary.excused}")
conn.close()
