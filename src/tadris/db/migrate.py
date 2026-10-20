import re
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_NAME = re.compile(r"^(\d{4})_.+\.sql$")


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


def migrate(conn: sqlite3.Connection) -> int:
    for version, file in _files():
        if version <= current_version(conn):
            continue
        sql = file.read_text(encoding="utf-8")
        try:
            conn.executescript(
                f"BEGIN IMMEDIATE;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;"
            )
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return current_version(conn)