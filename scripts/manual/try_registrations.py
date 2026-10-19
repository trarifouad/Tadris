"""Phase 4 task 2: registrations, on a copy of the real database.

Run from the project root:  .venv/bin/python scripts/manual/try_registrations.py
"""
from _common import Setup, attempt, open_copy

from tadris.core.money import format_dzd
from tadris.domain.models import StudentInput
from tadris.services import enrollments, groups, registrations, settings, students

conn, director, desk = open_copy("registrations")
school = Setup(conn, director)
student = students.create(conn, desk, StudentInput("Amine", "Essai"))
print(f"Élève de test : Essai Amine, niveaux {school.lvl1['name']} et {school.lvl2['name']}\n")


def show():
    reg = registrations.current(conn, director, student)
    if reg is None:
        print("        -> aucune inscription annuelle active")
    else:
        print(f"        -> {reg.year_label} {reg.level}, frais {format_dzd(reg.fee_amount)}, "
              f"reste à payer {format_dzd(reg.fee_due)}")


settings.set_value(conn, director, "defaults.registration_fee", 2000)
attempt("1. Inscription annuelle (frais par défaut 2 000)",
        lambda: registrations.register(conn, desk, student, school.lvl1["id"]))
show()
attempt("2. Inscription annuelle en double",
        lambda: registrations.register(conn, desk, student, school.lvl2["id"]))
reg_id = registrations.current(conn, director, student).id
attempt(f"3. Changer le niveau -> {school.lvl2['name']}",
        lambda: registrations.change_level(conn, desk, reg_id, school.lvl2["id"]))
show()
attempt("4. Annulation par l'accueil", lambda: registrations.cancel(conn, desk, reg_id, "test"))
attempt("5. Annulation sans motif", lambda: registrations.cancel(conn, director, reg_id, "  "))
attempt("6. Annulation par le directeur",
        lambda: registrations.cancel(conn, director, reg_id, "Erreur de saisie"))
show()
attempt("7. Réinscription à 1 500",
        lambda: registrations.register(conn, desk, student, school.lvl1["id"], 1500))
show()

print("\nPlusieurs groupes avec une seule inscription annuelle :")
g_a = school.group("Essai A", school.lvl1)
g_b = school.group("Essai B", school.lvl1)
for group_id in (g_a, g_b):
    enrollments.enroll(conn, desk, student, group_id)
    print(f"  dans {groups.get(conn, director, group_id).title}")
reg = registrations.get(conn, director, reg_id)
print(f"  -> {reg.live_enrollments} groupe(s), toujours 1 inscription annuelle, "
      f"frais {format_dzd(reg.fee_amount)} comptés une seule fois")

print("\nCharges de frais d'inscription :")
for row in conn.execute("SELECT description, amount, status FROM charges "
                        "WHERE registration_id = ? ORDER BY id", (reg_id,)):
    print(f"  {row['description']:<30} {format_dzd(row['amount']):>10}  {row['status']}")
print("\nJournal d'audit :")
for row in conn.execute("SELECT action, new_value FROM audit_log "
                        "WHERE action LIKE 'registration.%' ORDER BY id"):
    print(f"  {row['action']:<28} {row['new_value']}")
conn.close()
