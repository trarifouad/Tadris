"""Fill a database with demo students and contacts, through the services.

Usage: python scripts/seed_demo.py PATH.db
The path is required so the real database is never seeded by accident. Creates the director
account (directeur / password1) and a receptionist (accueil / password2) if the file is new.
"""

import random
import sys
from datetime import date
from pathlib import Path

from tadris.db.connection import connect
from tadris.db.migrate import migrate
from tadris.domain.models import ContactInput, ContactLink, StudentInput
from tadris.services import auth, contacts, students

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


def main(path: Path) -> None:
    rng = random.Random(2026)
    conn = connect(path)
    migrate(conn)
    if auth.user_count(conn) == 0:
        auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")
        director = auth.login(conn, "directeur", "password1")
        auth.create_user(conn, director, "accueil", "password2", "receptionist")
    director = auth.login(conn, "directeur", "password1")

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
    conn.close()
    print(f"{created} students created in {path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
