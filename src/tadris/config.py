from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "Tadris"

def data_dir() -> Path:
    p = Path(user_data_dir(APP_NAME, appauthor=False))
    p.mkdir(parents=True, exist_ok=True)
    return p

def db_path() -> Path:
    return data_dir() / "tadris.db"

def backup_dir() -> Path:
    p = data_dir() / "backups"
    p.mkdir(exist_ok=True)
    return p