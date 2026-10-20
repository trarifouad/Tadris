import re
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_NAME = re.compile(r"^(\d{4})_.+\.sql$")


class MigrationFailed(Exception):
    """A migration could not run; the database was left as it was (its transaction rolled
    back). version: the one that failed."""

    def __init__(self, version: int, file: str, error: Exception):
        super().__init__(f"{file}: {error}")
        self.version = version
        self.file = file
        self.error = error


def current_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _files() -> list[tuple[int, Path]]:
    return sorted(
        (int(m.group(1)), f)
        for f in MIGRATIONS_DIR.glob("*.sql")
        if (m := _NAME.match(f.name))
    )


def latest_version() -> int:
    return max((version for version, _ in _files()), default=0)


def has_pending(conn: sqlite3.Connection) -> bool:
    """An existing database (version 1 or more) that a migration is about to change."""
    return 0 < current_version(conn) < latest_version()


def is_newer(conn: sqlite3.Connection) -> bool:
    """A database written by a later version of the app: this one must not open it."""
    return current_version(conn) > latest_version()


def migrate(conn: sqlite3.Connection) -> int:
    """Run every migration the database lacks, each in its own transaction. Raises
    MigrationFailed (the failed one changed nothing)."""
    for version, file in _files():
        if version <= current_version(conn):
            continue
        sql = file.read_text(encoding="utf-8")
        try:
            conn.executescript(
                f"BEGIN IMMEDIATE;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;"
            )
        except Exception as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise MigrationFailed(version, file.name, exc) from exc
    return current_version(conn)