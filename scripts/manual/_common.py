"""Shared by the manual check scripts: work on a COPY of the real database.

The copy goes to data/ (ignored by git) and is replaced on each run. The real database is
only read, through SQLite's backup API (safe while the app is open).
"""
import sqlite3
import sys
from datetime import date
from pathlib import Path

from tadris import config
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError
from tadris.db.connection import connect
from tadris.db.migrate import migrate
from tadris.domain.models import GroupInput

DATA = Path(__file__).resolve().parents[2] / "data"


def open_copy(name: str):
    """(conn, director, desk): a migrated copy of the real database, and two contexts with
    the director's user id: one as director, one as receptionist."""
    DATA.mkdir(exist_ok=True)
    copy = DATA / f"manual_{name}.db"
    for leftover in DATA.glob(copy.name + "*"):
        leftover.unlink()
    if not config.db_path().exists():
        sys.exit(f"Base introuvable : {config.db_path()}. Lancez l'application une fois.")
    src = sqlite3.connect(config.db_path())
    dst = sqlite3.connect(copy)
    src.backup(dst)
    dst.close()
    src.close()
    conn = connect(copy)
    migrate(conn)
    user = conn.execute("SELECT id, username FROM users WHERE role = 'director' LIMIT 1"
                        ).fetchone()
    if user is None:
        sys.exit("Aucun compte directeur dans la base.")
    print(f"Copie de travail : {copy}\n")
    director = UserContext(user_id=user["id"], username=user["username"], role="director")
    desk = UserContext(user_id=user["id"], username="accueil", role="receptionist")
    return conn, director, desk


class Setup:
    """The open year, two active levels and a teacher from the real data."""

    def __init__(self, conn, director):
        self.conn, self.director = conn, director
        self.year = conn.execute("SELECT * FROM school_years WHERE status = 'open'").fetchone()
        levels = conn.execute("SELECT id, name FROM levels WHERE is_active = 1 "
                              "ORDER BY order_index LIMIT 2").fetchall()
        self.teacher = conn.execute("SELECT id FROM teachers WHERE status = 'active' LIMIT 1"
                                    ).fetchone()
        if not (self.year and len(levels) == 2 and self.teacher):
            sys.exit("Il faut une année ouverte, deux niveaux et un enseignant actifs.")
        self.lvl1, self.lvl2 = levels

    def group(self, name: str, level, capacity: int = 10, subject_of: int | None = None) -> int:
        """A test group, created in the copy only, with its own test subject (a student may
        take one group per subject), or the subject of the group `subject_of`."""
        from tadris.services import catalog, groups

        if subject_of is None:
            subject_id = catalog.create(self.conn, self.director, "subject", f"Matière {name}")
        else:
            subject_id = groups.get(self.conn, self.director, subject_of).subject_id
        start = date.fromisoformat(self.year["start_date"])
        return groups.create(self.conn, self.director, GroupInput(
            self.year["id"], level["id"], subject_id, name, 3000, capacity, start),
            self.teacher["id"])


def attempt(label: str, action, width: int = 46):
    """Run one step; print OK or the French message of the refusal. Returns the result."""
    try:
        result = action()
        print(f"OK      {label}")
        return result
    except BusinessRuleError as exc:
        print(f"REFUSÉ  {label:<{width}} -> {exc.message}")
        return None
