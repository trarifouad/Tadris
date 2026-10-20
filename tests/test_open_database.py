"""At start the database is brought to this version of the app, or the app stops with a
message: a database from a later version, a migration that fails (nothing changed)."""

import shutil

import pytest

from tadris import __version__, app
from tadris.db import migrate as migrations
from tadris.db.connection import connect
from tadris.db.migrate import MigrationFailed, current_version, latest_version, migrate


@pytest.fixture
def shown(monkeypatch):
    messages = []
    monkeypatch.setattr(app.QMessageBox, "critical",
                        lambda parent, title, text: messages.append((title, text)))
    monkeypatch.setattr(app.QMessageBox, "warning",
                        lambda parent, title, text: messages.append((title, text)))
    return messages


@pytest.fixture
def older(tmp_path):
    """A database one version behind (every migration but the last really run), with a row
    in it."""
    previous = tmp_path / "previous"
    previous.mkdir()
    for file in sorted(migrations.MIGRATIONS_DIR.glob("*.sql"))[:-1]:
        shutil.copy(file, previous)
    saved = migrations.MIGRATIONS_DIR
    migrations.MIGRATIONS_DIR = previous
    c = connect(tmp_path / "tadris.db")
    try:
        migrate(c)
    finally:
        migrations.MIGRATIONS_DIR = saved
    assert current_version(c) == latest_version() - 1
    c.execute("INSERT INTO settings(key, value) VALUES ('school.name', 'École Ennour')")
    yield c
    c.close()


@pytest.fixture
def broken(tmp_path, monkeypatch):
    """The app's migrations plus one more that fails half-way."""
    folder = tmp_path / "migrations"
    shutil.copytree(migrations.MIGRATIONS_DIR, folder)
    nxt = latest_version() + 1
    (folder / f"{nxt:04d}_broken.sql").write_text(
        "CREATE TABLE half_done (id INTEGER);\nINSERT INTO no_such_table VALUES (1);\n",
        encoding="utf-8")
    monkeypatch.setattr(migrations, "MIGRATIONS_DIR", folder)
    return nxt


def test_the_version_matches_the_package():
    import tomllib
    from pathlib import Path

    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert __version__ == project["project"]["version"]


def test_an_older_database_is_copied_then_migrated(older, tmp_path, shown):
    assert app.open_database(older, tmp_path / "backups")
    assert current_version(older) == latest_version()
    assert len(list((tmp_path / "backups").glob("*.db"))) == 1
    assert shown == []


def test_a_database_from_a_later_version_is_not_opened(older, tmp_path, shown):
    older.execute(f"PRAGMA user_version = {latest_version() + 3}")
    assert not app.open_database(older, tmp_path / "backups")
    assert current_version(older) == latest_version() + 3  # untouched
    assert not (tmp_path / "backups").exists()  # no copy either: nothing was changed
    title, text = shown[0]
    assert title == "Mise à jour de la base"
    assert f"version {latest_version() + 3}" in text and "plus récente" in text


def test_a_failed_migration_changes_nothing(older, broken):
    with pytest.raises(MigrationFailed) as failed:  # the real one runs, then the broken one
        migrate(older)
    assert failed.value.version == broken
    assert "no_such_table" in str(failed.value.error)
    assert current_version(older) == broken - 1
    assert older.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'half_done'"
                         ).fetchone()[0] == 0  # rolled back
    assert not older.in_transaction


def test_a_failed_migration_stops_the_app_and_names_the_copy(older, broken, tmp_path,
                                                             shown):
    assert not app.open_database(older, tmp_path / "backups")
    copy = next((tmp_path / "backups").glob("*.db"))
    title, text = shown[0]
    assert title == "Mise à jour de la base"
    assert f"étape {broken}" in text and "no_such_table" in text and str(copy) in text
    assert "n'a pas été modifiée" in text
    assert older.execute("SELECT value FROM settings WHERE key = 'school.name'"
                         ).fetchone()[0] == "École Ennour"


def test_a_new_database_is_created_without_a_copy(tmp_path, shown):
    c = connect(tmp_path / "new.db")
    try:
        assert app.open_database(c, tmp_path / "backups")
        assert current_version(c) == latest_version()
        assert not (tmp_path / "backups").exists()
    finally:
        c.close()
