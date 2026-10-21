"""The « À propos » tab: which version of the app and of the database is running, and where
the data lives."""

from dataclasses import dataclass
from pathlib import Path

from tadris import __version__
from tadris.core.context import UserContext
from tadris.core.permissions import require
from tadris.db.migrate import current_version


@dataclass(frozen=True)
class About:
    app_version: str  # 0.1.0
    schema_version: int  # PRAGMA user_version of the database open
    database: Path | None  # the file open (None for an in-memory database)


def database_file(conn) -> Path | None:
    """The file the connection has open, as SQLite reports it."""
    for row in conn.execute("PRAGMA database_list"):
        if row[1] == "main":
            return Path(row[2]) if row[2] else None
    return None


def info(conn, ctx: UserContext) -> About:
    require(ctx, "settings.view")
    return About(app_version=__version__, schema_version=current_version(conn),
                 database=database_file(conn))
