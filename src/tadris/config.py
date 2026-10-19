import os
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "Tadris"

def data_dir() -> Path:
    p = Path(user_data_dir(APP_NAME, appauthor=False))
    p.mkdir(parents=True, exist_ok=True)
    return p

# Manual testing: TADRIS_DB=data/manual_enrollments.db opens another database (a copy).
DB_ENV = "TADRIS_DB"


def db_override() -> Path | None:
    value = os.environ.get(DB_ENV, "").strip()
    return Path(value).expanduser().resolve() if value else None


def db_path() -> Path:
    return db_override() or data_dir() / "tadris.db"

def documents_dir() -> Path:
    """Printed documents (attendance sheets, receipts), next to the database in use."""
    p = db_path().parent / "documents"
    p.mkdir(parents=True, exist_ok=True)
    return p


def backup_dir() -> Path:
    p = data_dir() / "backups"
    p.mkdir(exist_ok=True)
    return p