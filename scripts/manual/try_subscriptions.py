"""Phase 5 tasks 1 and 2: subscriptions on a copy of the database. The first month is
automatic (enroll, confirm a trial, switch); then renew, cancel, and the desk's lists.

Run from the project root:  .venv/bin/python scripts/manual/try_subscriptions.py
The script moves the date forward to show the lists.
"""
from datetime import date, timedelta

from _common import Setup, attempt, open_copy

from tadris.core import dates
from tadris.core.money import format_dzd
from tadris.domain.models import GroupInput, StudentInput
from tadris.services import enrollments, groups, registrations, students, subscriptions

conn, director, desk = open_copy("subscriptions")
school = Setup(conn, director)
g_a = school.group("Essai A", school.lvl1)  # 3 000 DA
g_b = school.group("Essai B", school.lvl1)
g = groups.get(conn, director, g_b)
groups.update(conn, director, g_b, GroupInput(g.school_year_id, g.level_id, g.subject_id,
                                              g.name, 2500, g.capacity,
                                              date.fromisoformat(g.start_date)))
real_today = dates.today()


def student(first, trial=False):
    sid = students.create(conn, desk, StudentInput(first, "Essai"))
    registrations.register(conn, desk, sid, school.lvl1["id"], 0)
    return enrollments.enroll(conn, desk, sid, g_a, trial=trial)


STATES = {"upcoming": "à venir", "active": "en cours", "expiring": "se termine",
          "ended": "terminé", "cancelled": "annulé"}


def show(enrollment_id, name):
    listed = subscriptions.for_enrollment(conn, director, enrollment_id)
    if not listed:
        print(f"    {name:<6} aucun abonnement")
    for s in listed:
        print(f"    {name:<6} #{s.id:<3} {s.group_title:<28} du "
              f"{dates.display_date(s.start_date)} au {dates.display_date(s.end_date)}  "
              f"{format_dzd(s.price):>9}  {STATES[s.state]:<10} reste {format_dzd(s.due)}")


print("--- Le premier mois est automatique ---")
amine = attempt("1. Amine inscrit dans Essai A", lambda: student("Amine"))
show(amine, "Amine")
yanis = attempt("2. Yanis en essai dans Essai A", lambda: student("Yanis", trial=True))
show(yanis, "Yanis")
attempt("3. Confirmer l'essai de Yanis", lambda: enrollments.confirm_trial(conn, desk, yanis))
show(yanis, "Yanis")
attempt("4. Un 2e abonnement pour Amine en même temps",
        lambda: subscriptions.start(conn, desk, amine))
first = subscriptions.for_enrollment(conn, director, amine)[0].id

print("\n--- Renouvellement ---")
second = attempt("5. Renouveler le mois 1", lambda: subscriptions.renew(conn, desk, first))
attempt("6. Renouveler encore le mois 1", lambda: subscriptions.renew(conn, desk, first))
attempt("6b. Renouveler le mois 2 avant sa fin",
        lambda: subscriptions.renew(conn, desk, second, real_today))
g = groups.get(conn, director, g_a)
groups.update(conn, director, g_a, GroupInput(g.school_year_id, g.level_id, g.subject_id,
                                              g.name, 3500, g.capacity,
                                              date.fromisoformat(g.start_date)))
print("        (prix du groupe passé à 3 500 DA)")
third = attempt("7. Renouveler le mois 2 (nouveau prix)",
                lambda: subscriptions.renew(conn, desk, second))
show(amine, "Amine")

print("\n--- Annulation ---")
attempt("8. Annulation par l'accueil", lambda: subscriptions.cancel(conn, desk, third, "x"))
attempt("9. Annulation sans motif", lambda: subscriptions.cancel(conn, director, third, " "))
attempt("10. Annulation du mois 3 par le directeur",
        lambda: subscriptions.cancel(conn, director, third, "Erreur"))
show(amine, "Amine")

print("\n--- Changement de groupe en cours de mois ---")
lina = attempt("11. Lina inscrite dans Essai A", lambda: student("Lina"))
lina_b = attempt("12. Lina passe dans Essai B (2 500 DA) aujourd'hui",
                 lambda: enrollments.switch(conn, desk, lina, g_b))
show(lina, "Lina")
show(lina_b, "Lina")

print("\n--- Listes de l'accueil (la date avance) ---")
end = date.fromisoformat(subscriptions.get(conn, director, second).end_date)
for label, on in (("3 jours avant la fin du mois 2", end - timedelta(days=3)),
                  ("2 jours après la fin du mois 2", end + timedelta(days=2))):
    dates.today = lambda on=on: on
    soon = [s.student_name for s in subscriptions.ending_soon(conn, desk)
            if s.group_id == g_a]
    gone = [s.student_name for s in subscriptions.lapsed(conn, desk) if s.group_id == g_a]
    print(f"  Le {dates.display_date(dates.iso(on))} ({label}) :")
    print(f"    se terminent dans 7 jours : {soon or '—'}")
    print(f"    terminés, non renouvelés  : {gone or '—'}")
    print(f"    marqués « terminés » au démarrage : {subscriptions.mark_ended(conn)}")

print("\nCharges d'Amine :")
for row in conn.execute("SELECT c.description, c.amount, c.status FROM charges c "
                        "JOIN subscriptions s ON s.id = c.subscription_id "
                        "WHERE s.enrollment_id = ? AND c.amount > 0 ORDER BY c.id", (amine,)):
    print(f"  {row['description']:<46} {format_dzd(row['amount']):>9}  {row['status']}")
conn.close()
