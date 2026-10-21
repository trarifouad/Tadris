"""Putting a copy back: checked first, a safety copy before anything is replaced, the copy
written over the open database, brought to this version, and recorded."""

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from tadris.core.errors import BusinessRuleError, PermissionDenied, ValidationError
from tadris.db import migrate as migrations
from tadris.db.connection import connect
from tadris.db.migrate import MigrationFailed, current_version, latest_version, migrate
from tadris.services import auth, backup, restore

# Tables a restore itself writes to: every other one must hold exactly what the copy holds.
BOOKKEEPING = {"backups", "restore_log", "audit_log"}


def new_school(path: Path, name: str = "École Ennour", students: int = 1):
    auth._reset_failures()
    c = connect(path)
    migrate(c)
    auth.bootstrap_director(c, "directeur", "password1", name)
    for n in range(students):
        add_student(c, f"Eleve{n}")
    return c


def add_student(c, last_name: str) -> None:
    number = c.execute("SELECT COUNT(*) + 1 FROM students").fetchone()[0]
    c.execute("INSERT INTO students(student_number, first_name, last_name) VALUES (?, ?, ?)",
              (f"2026-{number:04d}", "Prénom", last_name))


def counts(c) -> dict[str, int]:
    names = [row[0] for row in c.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    return {name: c.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for name in names if name not in BOOKKEEPING}


def names(c) -> list[str]:
    return [row[0] for row in c.execute("SELECT last_name FROM students ORDER BY id")]


@pytest.fixture
def school(tmp_path):
    c = new_school(tmp_path / "tadris.db")
    yield c
    c.close()


@pytest.fixture
def folder(tmp_path):
    return tmp_path / "backups"


@pytest.fixture
def director(school):
    return auth.login(school, "directeur", "password1")


@pytest.fixture
def copy(school, folder):
    """A verified copy holding one student, then a second student added after it."""
    taken = backup.take(school, folder)
    add_student(school, "Apres")
    return taken


# ----- the round trip -----

def test_a_restore_brings_back_every_table_as_the_copy_holds_it(school, folder, director,
                                                                 copy):
    with sqlite3.connect(copy.file_path) as c:
        expected = counts(c)
    assert counts(school) != expected  # the student added since

    restored = restore.restore(school, director, Path(copy.file_path), folder)

    assert counts(school) == expected
    assert names(school) == ["Eleve0"]
    assert restored.copy.students == 1 and restored.copy.school == "École Ennour"
    assert school.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_the_database_works_after_a_restore_and_keeps_it(school, folder, director, copy,
                                                         tmp_path):
    restore.restore(school, director, Path(copy.file_path), folder)
    add_student(school, "Ensuite")
    assert school.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    school.close()
    again = connect(tmp_path / "tadris.db")
    try:
        assert names(again) == ["Eleve0", "Ensuite"]
    finally:
        again.close()


def test_a_safety_copy_holds_the_database_as_it_was(school, folder, director, copy):
    restored = restore.restore(school, director, Path(copy.file_path), folder)

    safety = Path(restored.safety.file_path)
    assert safety.name.endswith("-avant-restauration.db") and safety.parent == folder
    assert restored.safety.type == "manual" and restored.safety.status == "verified"
    with sqlite3.connect(safety) as c:
        assert names(c) == ["Eleve0", "Apres"]  # what the restore replaced
    # A safety copy is never removed by retention.
    assert restored.safety.id not in {row["id"] for row in backup.to_remove(school)}


def test_the_list_of_copies_is_the_one_from_before(school, folder, director, copy):
    later = backup.take(school, folder)  # after the copy: unknown to the copy's own list
    restored = restore.restore(school, director, Path(copy.file_path), folder)

    listed = {b.file_path: b for b in backup.list_backups(school)}
    assert set(listed) == {copy.file_path, later.file_path, restored.safety.file_path}
    assert all(b.status == "verified" for b in listed.values())
    assert set(listed) == {str(p) for p in folder.glob("*.db")}  # the files on disk


def test_a_restore_is_recorded(school, folder, director, copy):
    restore.restore(school, director, Path(copy.file_path), folder)

    log = school.execute("SELECT * FROM restore_log").fetchall()
    assert len(log) == 1 and log[0]["result"] == "success"
    assert log[0]["restored_by"] == director.user_id
    source = backup.get(school, log[0]["backup_id"])
    assert source.file_path == copy.file_path
    assert source.id not in {row["id"] for row in backup.to_remove(school)}  # kept
    entry = school.execute("SELECT * FROM audit_log WHERE action = 'backup.restore'"
                           ).fetchone()
    assert entry["user_id"] == director.user_id
    new = json.loads(entry["new_value"])
    assert new["file"] == Path(copy.file_path).name and new["result"] == "success"
    assert new["safety"].endswith("-avant-restauration.db") and new["by"] == "directeur"


def test_a_registered_copy_is_checked_against_its_checksum(school, folder, director, copy):
    info = restore.inspect_backup(school, director, copy.id)
    assert info.students == 1 and info.schema_version == latest_version()
    with open(copy.file_path, "r+b") as f:
        f.seek(100)
        f.write(b"\x00changed")
    with pytest.raises(ValidationError) as refused:
        restore.inspect_backup(school, director, copy.id)
    assert "abîmée" in refused.value.message


# ----- a copy from elsewhere -----

def test_a_copy_from_another_computer(school, folder, director, tmp_path):
    (tmp_path / "other").mkdir()
    other = new_school(tmp_path / "other" / "tadris.db", "École Ibn Khaldoun", students=3)
    elsewhere = backup.take(other, tmp_path / "other" / "backups")
    other.close()
    usb = tmp_path / "usb"
    usb.mkdir()
    file = Path(shutil.copy(elsewhere.file_path, usb / "copie.db"))

    restored = restore.restore(school, director, file, folder)

    assert restored.copy.school == "École Ibn Khaldoun" and restored.copy.students == 3
    assert school.execute("SELECT value FROM settings WHERE key = 'school.name'"
                          ).fetchone()[0] == "École Ibn Khaldoun"
    log = school.execute("SELECT backup_id FROM restore_log").fetchone()
    source = backup.get(school, log[0])
    assert source.file_path == str(file) and source.type == "manual"
    assert source.checksum == backup.sha256(file)
    backup.prune(school)
    assert file.exists()  # never removed: it is not in the app's folder anyway


def test_the_restorer_is_found_by_username_or_is_the_copys_director(school, folder,
                                                                     director, tmp_path):
    other = new_school(tmp_path / "other.db")
    auth.create_user(other, auth.login(other, "directeur", "password1"), "chef",
                     "password1", "director")
    other.execute("UPDATE users SET status = 'disabled' WHERE username = 'directeur'")
    other.execute("UPDATE users SET username = 'ancien' WHERE username = 'directeur'")
    file = Path(backup.take(other, tmp_path / "other-backups").file_path)
    other.close()

    restore.restore(school, director, file, folder)  # no 'directeur' in the copy
    by = school.execute("SELECT u.username FROM restore_log r JOIN users u "
                        "ON u.id = r.restored_by").fetchone()[0]
    assert by == "chef"
    entry = school.execute("SELECT new_value FROM audit_log WHERE action = 'backup.restore'"
                           ).fetchone()
    assert json.loads(entry[0])["by"] == "directeur"  # who really did it


def test_an_older_copy_is_brought_to_this_version(school, folder, director, tmp_path,
                                                  monkeypatch):
    previous = tmp_path / "previous"
    previous.mkdir()
    for file in sorted(migrations.MIGRATIONS_DIR.glob("*.sql"))[:-1]:
        shutil.copy(file, previous)
    monkeypatch.setattr(migrations, "MIGRATIONS_DIR", previous)
    old = new_school(tmp_path / "old.db", students=2)
    monkeypatch.undo()
    assert current_version(old) == latest_version() - 1
    file = Path(backup.take(old, tmp_path / "old-backups").file_path)
    old.close()

    restored = restore.restore(school, director, file, folder)

    assert restored.copy.schema_version == latest_version() - 1
    assert current_version(school) == latest_version()
    assert names(school) == ["Eleve0", "Eleve1"]


# ----- refused before anything is replaced -----

def refused(school, director, folder, file) -> str:
    before = names(school)
    with pytest.raises(ValidationError) as error:
        restore.restore(school, director, file, folder)
    assert names(school) == before
    assert not folder.exists() or not list(folder.glob("*avant-restauration*"))
    return error.value.message


def test_a_missing_file_is_refused(school, director, folder, tmp_path):
    assert "introuvable" in refused(school, director, folder, tmp_path / "nowhere.db")


def test_a_file_that_is_not_a_database_is_refused(school, director, folder, tmp_path):
    file = tmp_path / "notes.db"
    file.write_text("pas une base " * 500)
    assert refused(school, director, folder, file) == "Ce fichier n'est pas une sauvegarde de Tadris."


def test_another_database_is_refused(school, director, folder, tmp_path):
    file = tmp_path / "other.db"
    with sqlite3.connect(file) as c:
        c.execute("CREATE TABLE things (id INTEGER)")
        c.execute("PRAGMA user_version = 3")
    assert refused(school, director, folder, file) == "Ce fichier n'est pas une sauvegarde de Tadris."


def test_a_damaged_copy_is_refused(school, director, folder, copy):
    file = Path(copy.file_path)
    data = bytearray(file.read_bytes())
    for offset in range(4096, len(data), 4096):  # every page but the header page
        data[offset + 20:offset + 60] = b"\xff" * 40
    file.write_bytes(bytes(data))
    message = refused(school, director, folder, file)
    assert message in (restore.t["restore.damaged"], restore.t["restore.not_a_copy"])


def test_a_copy_from_a_later_version_is_refused(school, director, folder, copy):
    with sqlite3.connect(copy.file_path) as c:
        c.execute(f"PRAGMA user_version = {latest_version() + 1}")
    assert "plus récente" in refused(school, director, folder, Path(copy.file_path))


def test_a_copy_without_a_director_is_refused(school, director, folder, copy):
    with sqlite3.connect(copy.file_path) as c:
        c.execute("UPDATE users SET status = 'disabled'")
    assert "directeur" in refused(school, director, folder, Path(copy.file_path))


def test_only_the_director_restores(school, director, folder, copy):
    auth.create_user(school, director, "accueil", "password1", "receptionist")
    desk = auth.login(school, "accueil", "password1")
    with pytest.raises(PermissionDenied):
        restore.restore(school, desk, Path(copy.file_path), folder)
    with pytest.raises(PermissionDenied):
        restore.inspect_backup(school, desk, copy.id)


def test_without_a_safety_copy_nothing_is_replaced(school, director, copy, tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("a file where the folder should be")
    with pytest.raises(backup.BackupFailed):
        restore.restore(school, director, Path(copy.file_path), blocked / "backups")
    assert names(school) == ["Eleve0", "Apres"]
    assert school.execute("SELECT COUNT(*) FROM restore_log").fetchone()[0] == 0


def test_a_second_location_missing_does_not_stop_a_restore(school, folder, director, copy,
                                                          tmp_path):
    usb = tmp_path / "usb"
    usb.mkdir()
    backup.set_second_root(school, director, str(usb))
    usb.rmdir()
    restored = restore.restore(school, director, Path(copy.file_path), folder)
    assert Path(restored.safety.file_path).is_file()
    assert names(school) == ["Eleve0"]


# ----- a failure half-way puts the database back -----

def test_a_copy_that_cannot_be_brought_to_this_version_is_undone(school, folder, director,
                                                                 copy, monkeypatch):
    def failing(conn):
        raise MigrationFailed(99, "0099_x.sql", sqlite3.OperationalError("disk I/O error"))

    monkeypatch.setattr(restore, "migrate", failing)
    with pytest.raises(BusinessRuleError) as error:
        restore.restore(school, director, Path(copy.file_path), folder)

    assert "revenue à son état d'avant" in error.value.message
    assert "disk I/O error" in error.value.message
    assert names(school) == ["Eleve0", "Apres"]  # as it was
    log = school.execute("SELECT * FROM restore_log").fetchall()
    assert [row["result"] for row in log] == ["failed"]
    entry = school.execute("SELECT new_value FROM audit_log WHERE action = 'backup.restore'"
                           ).fetchone()
    assert json.loads(entry[0])["error"] == "disk I/O error"
    listed = {b.file_path for b in backup.list_backups(school)}
    assert copy.file_path in listed and any("avant-restauration" in p for p in listed)
