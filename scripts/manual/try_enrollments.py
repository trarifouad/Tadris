"""Phase 4 task 3: enrolling in groups, on a copy of the real database.

Run from the project root:  .venv/bin/python scripts/manual/try_enrollments.py
"""
from datetime import date

from _common import Setup, attempt, open_copy

from tadris.domain.models import StudentInput
from tadris.services import enrollments, groups, registrations, students

conn, director, desk = open_copy("enrollments")
school = Setup(conn, director)
g_a = school.group("Essai A", school.lvl1)
g_b = school.group("Essai B", school.lvl1)
g_small = school.group("Essai petit", school.lvl1, 1)
g_other = school.group("Essai autre niveau", school.lvl2)
title = {gid: groups.get(conn, director, gid).title for gid in (g_a, g_b, g_small, g_other)}

amine = students.create(conn, desk, StudentInput("Amine", "Essai"))
yanis = students.create(conn, desk, StudentInput("Yanis", "Essai"))
lina = students.create(conn, desk, StudentInput("Lina", "Essai"))  # never registered
for student in (amine, yanis):
    registrations.register(conn, desk, student, school.lvl1["id"], 0)
print(f"Amine et Yanis inscrits en {school.lvl1['name']}, Lina sans inscription annuelle.\n")
start = date.fromisoformat(school.year["start_date"])

attempt(f"1. Amine dans {title[g_a]}", lambda: enrollments.enroll(conn, desk, amine, g_a))
attempt(f"2. Amine dans {title[g_b]} (2e groupe)",
        lambda: enrollments.enroll(conn, desk, amine, g_b))
attempt("3. Amine encore dans Essai A", lambda: enrollments.enroll(conn, desk, amine, g_a))
attempt("4. Lina (pas d'inscription annuelle)", lambda: enrollments.enroll(conn, desk, lina, g_a))
attempt("5. Yanis en essai gratuit", lambda: enrollments.enroll(conn, desk, yanis, g_a, True))
attempt("6. Yanis : 2e essai gratuit", lambda: enrollments.enroll(conn, desk, yanis, g_b, True))
attempt("7. Amine dans Essai petit (1 place)",
        lambda: enrollments.enroll(conn, desk, amine, g_small))
attempt("8. Yanis dans Essai petit (complet)",
        lambda: enrollments.enroll(conn, desk, yanis, g_small))
attempt("9. Accueil : groupe d'un autre niveau",
        lambda: enrollments.enroll(conn, desk, amine, g_other))
attempt("10. Directeur : autre niveau sans motif",
        lambda: enrollments.enroll(conn, director, amine, g_other))
attempt("11. Directeur : autre niveau avec motif",
        lambda: enrollments.enroll(conn, director, amine, g_other,
                                   override_reason="Rattrapage"))
attempt("12. Date d'entrée avant le début du groupe",
        lambda: enrollments.enroll(conn, desk, yanis, g_b, enrolled_on=date(start.year, 1, 1)))

left = conn.execute("SELECT COUNT(*) FROM settings WHERE key LIKE 'override:%'").fetchone()[0]
print(f"\nClés de dérogation restées dans settings : {left} (attendu : 0)")

print("\nGroupes proposés à Yanis (dialogue « Inscrire dans un groupe ») :")
for o in enrollments.options(conn, desk, yanis):
    state = "déjà dedans" if o.already_in else ("complet" if o.free == 0 else "disponible")
    level = "" if o.same_level else "  [autre niveau : directeur]"
    print(f"  {o.group.title:<36} {o.free:>2} place(s) libre(s)  {state}{level}")

print("\nÉlèves de Essai A :")
for e in enrollments.for_group(conn, director, g_a):
    print(f"  {e.student_name:<20} {e.status}")

print("\nJournal d'audit (dérogation) :")
for row in conn.execute("SELECT new_value FROM audit_log WHERE action = 'enrollment.create' "
                        "AND new_value LIKE '%override%'"):
    print(f"  {row['new_value']}")
conn.close()
