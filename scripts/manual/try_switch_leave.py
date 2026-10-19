"""Phase 4 task 4: confirm a trial, leave, switch, close a group, on a copy of the database.

Run from the project root:  .venv/bin/python scripts/manual/try_switch_leave.py
"""
from datetime import timedelta

from _common import Setup, attempt, open_copy

from tadris.core import dates
from tadris.domain.models import StudentInput
from tadris.services import enrollments, groups, registrations, students

conn, director, desk = open_copy("switch_leave")
school = Setup(conn, director)
g_a = school.group("Essai A", school.lvl1)
g_b = school.group("Essai B", school.lvl1)
g_full = school.group("Essai complet", school.lvl1, 1)
g_other = school.group("Essai autre niveau", school.lvl2)
today = dates.today()


def student(first):
    sid = students.create(conn, desk, StudentInput(first, "Essai"))
    registrations.register(conn, desk, sid, school.lvl1["id"], 0)
    return sid


amine, yanis, lina, sami = student("Amine"), student("Yanis"), student("Lina"), student("Sami")
enrollments.enroll(conn, desk, sami, g_full)  # fills the 1-seat group


def show(sid, name):
    for e in enrollments.for_student(conn, director, sid):
        link = f", vient de #{e.switched_from_id}" if e.switched_from_id else ""
        left = f", sortie le {e.left_on}" if e.left_on else ""
        print(f"    #{e.id:<3} {name:<6} {e.group_title:<34} {e.status:<9} "
              f"entrée le {e.enrolled_on}{left}{link}")


print("--- Essai puis confirmation ---")
y_trial = enrollments.enroll(conn, desk, yanis, g_a, trial=True)
attempt("1. Confirmer l'essai de Yanis", lambda: enrollments.confirm_trial(conn, desk, y_trial))
attempt("2. Confirmer une 2e fois", lambda: enrollments.confirm_trial(conn, desk, y_trial))
show(yanis, "Yanis")

print("\n--- Sortie d'un groupe ---")
a_enr = enrollments.enroll(conn, desk, amine, g_a)
attempt("3. Sortie demain (futur)",
        lambda: enrollments.leave(conn, desk, a_enr, today + timedelta(days=1)))
attempt("4. Sortie avant la date d'entrée",
        lambda: enrollments.leave(conn, desk, a_enr, today - timedelta(days=1)))
attempt("5. Amine sort aujourd'hui (motif : Déménagement)",
        lambda: enrollments.leave(conn, desk, a_enr, reason="Déménagement"))
attempt("6. Amine sort une 2e fois", lambda: enrollments.leave(conn, desk, a_enr))
show(amine, "Amine")

print("\n--- Changement de groupe ---")
l_enr = enrollments.enroll(conn, desk, lina, g_a, trial=True)
attempt("7. Lina vers le même groupe", lambda: enrollments.switch(conn, desk, l_enr, g_a))
attempt("8. Lina vers Essai complet", lambda: enrollments.switch(conn, desk, l_enr, g_full))
attempt("9. Directeur : Lina vers un autre niveau",
        lambda: enrollments.switch(conn, director, l_enr, g_other, override_reason="x"))
attempt("10. Lina vers Essai B (reste en essai)",
        lambda: enrollments.switch(conn, desk, l_enr, g_b))
show(lina, "Lina")

print("\n--- Clôture de Essai A ---")
print(f"  Avant : {groups.get(conn, director, g_a).enrolled} élève(s) dans le groupe")
groups.close(conn, director, g_a)
print(f"  Après : {groups.get(conn, director, g_a).enrolled} élève(s) dans le groupe")
show(yanis, "Yanis")
groups.reopen(conn, director, g_a)
print(f"  Après réouverture : {groups.get(conn, director, g_a).enrolled} élève(s) "
      "(les élèves ne reviennent pas)")

print("\nJournal d'audit :")
for row in conn.execute("SELECT action, new_value FROM audit_log "
                        "WHERE action IN ('enrollment.confirm_trial', 'enrollment.leave', "
                        "'enrollment.switch', 'group.close') ORDER BY id"):
    print(f"  {row['action']:<26} {row['new_value']}")
conn.close()
