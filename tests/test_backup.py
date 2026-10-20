import json
import os
import sqlite3
from pathlib import Path

import pytest

from tadris import app, config
from tadris.db.connection import connect
from tadris.db.migrate import has_pending, latest_version, migrate
from tadris.services import auth, backup


@pytest.fixture
def school(tmp_path):
    """A database on disk, in WAL mode like the real one, with a director and a student."""
    auth._reset_failures()
    c = connect(tmp_path / "tadris.db")
    migrate(c)
    auth.bootstrap_director(c, "directeur", "password1", "École Ennour")
    c.execute("INSERT INTO students(student_number, first_name, last_name) "
              "VALUES ('2026-0001', 'Amine', 'Benali')")
    yield c
    c.close()


@pytest.fixture
def folder(tmp_path):
    return tmp_path / "backups"


def tables(c) -> list[str]:
    return [row[0] for row in c.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name")]


def counts(c) -> dict[str, int]:
    return {name: c.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0] for name in tables(c)}


def audit_rows(c, action) -> list:
    return c.execute("SELECT * FROM audit_log WHERE action = ? ORDER BY id", (action,)).fetchall()


def open_ro(path):
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


# ----- take and verify -----

def test_a_backup_is_a_verified_copy_of_every_table(school, folder):
    before = counts(school)
    taken = backup.take(school, folder)

    path = Path(taken.file_path)
    assert path.parent == folder
    assert taken.status == "verified" and taken.type == "auto"
    assert taken.completed_at and taken.verified_at
    assert taken.size_bytes == path.stat().st_size
    assert taken.checksum == backup.sha256(path)
    assert [p.name for p in folder.iterdir()] == [path.name]  # no .part, no -wal, no -shm

    copy = open_ro(path)  # one self-contained file
    try:
        assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert copy.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert copy.execute("PRAGMA user_version").fetchone()[0] == latest_version()
        copied = {name: copy.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
                  for name in tables(copy)}
    finally:
        copy.close()
    # Same rows everywhere; the copy only has its own backups row, still 'running'.
    assert copied == {**before, "backups": before["backups"] + 1}

    entry = audit_rows(school, "backup.create")[-1]
    assert entry["user_id"] is None
    assert json.loads(entry["new_value"]) == {"id": taken.id, "file": path.name, "type": "auto"}


def test_the_copy_holds_writes_still_in_the_wal(school, folder):
    school.execute("INSERT INTO students(student_number, first_name, last_name) "
                   "VALUES ('2026-0002', 'Sara', 'Kaci')")
    assert (school.execute("PRAGMA journal_mode").fetchone()[0]) == "wal"
    copy = open_ro(Path(backup.take(school, folder, "manual").file_path))
    try:
        names = [row[0] for row in copy.execute("SELECT first_name FROM students ORDER BY id")]
    finally:
        copy.close()
    assert names == ["Amine", "Sara"]


def test_an_in_memory_database_backs_up_too(conn, folder):
    taken = backup.take(conn, folder)
    assert taken.status == "verified"


def test_two_backups_in_the_same_second_get_their_own_file(school, folder):
    first = backup.take(school, folder)
    second = backup.take(school, folder)
    assert first.file_path != second.file_path
    assert len(list(folder.iterdir())) == 2
    assert [b.id for b in backup.list_backups(school)] == [second.id, first.id]


def test_a_corrupted_backup_fails_verification(school, folder):
    taken = backup.take(school, folder)
    with open(taken.file_path, "r+b") as f:
        f.seek(200)
        f.write(b"\xff" * 64)

    assert backup.verify(school, taken.id) is False
    after = backup.get(school, taken.id)
    assert after.status == "failed" and after.verified_at is None
    entry = audit_rows(school, "backup.failed")[-1]
    assert json.loads(entry["new_value"])["error"] == "verification"


def test_a_missing_backup_fails_verification(school, folder):
    taken = backup.take(school, folder)
    os.remove(taken.file_path)
    assert backup.verify(school, taken.id) is False
    assert backup.get(school, taken.id).status == "failed"


def test_a_sound_backup_verifies_again(school, folder):
    taken = backup.take(school, folder)
    assert backup.verify(school, taken.id) is True
    assert backup.get(school, taken.id).status == "verified"


def test_a_folder_that_cannot_be_created_fails(school, tmp_path):
    taken = tmp_path / "backups"
    taken.write_text("x")  # the folder name is taken by a file
    with pytest.raises(backup.BackupFailed) as raised:
        backup.take(school, taken)
    assert raised.value.message.startswith("La sauvegarde de la base a échoué")
    assert backup.list_backups(school) == []


def test_a_failed_copy_marks_its_row_failed(school, folder, monkeypatch):
    def broken(conn, path):
        path.with_name(path.name + ".part").write_bytes(b"half")
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(backup, "_copy", broken)
    with pytest.raises(backup.BackupFailed):
        backup.take(school, folder)

    (failed,) = backup.list_backups(school)
    assert failed.status == "failed" and failed.checksum is None
    assert list(folder.iterdir()) == []  # the half-written file is gone
    assert json.loads(audit_rows(school, "backup.failed")[-1]["new_value"])["error"] == (
        "disk I/O error")


def test_an_unknown_backup(school):
    with pytest.raises(backup.NotFound):
        backup.verify(school, 999)


# ----- once a day -----

def test_the_daily_backup_runs_once_a_day(school, folder):
    first = backup.daily(school, folder)
    assert first is not None
    assert backup.daily(school, folder) is None

    # The rows are stamped by SQLite's clock: move the recorded day back instead of the clock.
    school.execute("UPDATE backups SET created_at = '2020-01-01T08:00:00'")
    assert backup.daily(school, folder) is not None


def test_a_failed_or_manual_backup_does_not_count_for_the_day(school, folder):
    manual = backup.take(school, folder, "manual")
    assert backup.daily_due(school)
    auto = backup.take(school, folder)
    assert not backup.daily_due(school)
    os.remove(auto.file_path)
    backup.verify(school, auto.id)
    assert backup.daily_due(school)
    assert manual.type == "manual"


# ----- before a migration -----

def test_pending_migration_only_for_an_existing_older_database(tmp_path):
    fresh = connect(tmp_path / "new.db")
    try:
        assert not has_pending(fresh)  # a new database has nothing to save
        migrate(fresh)
        assert not has_pending(fresh)
        fresh.execute(f"PRAGMA user_version = {latest_version() - 1}")
        assert has_pending(fresh)
    finally:
        fresh.close()


# ----- folder and warnings -----

def test_backups_sit_next_to_the_database_in_use(tmp_path, monkeypatch):
    monkeypatch.setenv(config.DB_ENV, str(tmp_path / "copy" / "manual.db"))
    assert config.backup_dir() == tmp_path / "copy" / "backups"
    assert config.backup_dir().is_dir()


def test_a_failure_warns_and_never_raises(monkeypatch):
    shown = []
    monkeypatch.setattr(app.QMessageBox, "warning",
                        lambda parent, title, text: shown.append((title, text)))

    def failing():
        raise backup.BackupFailed("La sauvegarde de la base a échoué (x).")

    assert app._backup(failing) is False
    assert shown[0][0] == "Sauvegarde"
    assert shown[0][1].startswith("La sauvegarde de la base a échoué (x).")
    assert "L'application continue" in shown[0][1]

    assert app._backup(failing, warning="backup.before_migration") is False
    assert "mettre à jour la base" in shown[1][1]
    assert app._backup(lambda: None) is True


# ----- retention -----

def old_copy(c, folder, created_at, status="verified", kind="auto"):
    """A copy row with its file, as if taken at created_at."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"tadris-{created_at.replace(':', '')}-{status}.db"
    path.write_bytes(b"copy")
    cur = c.execute("INSERT INTO backups(file_path, type, status, created_at) "
                    "VALUES (?, ?, ?, ?)", (str(path), kind, status, created_at))
    return cur.lastrowid, path


def kept_ids(c) -> set[int]:
    return {row[0] for row in c.execute("SELECT id FROM backups")}


def test_retention_keeps_one_copy_a_day_for_14_days_and_one_a_month_for_12(school, folder):
    days = {}
    for n in range(40):  # two copies a day (start and close), every day for 40 days
        day = f"2020-03-{n + 1:02d}" if n < 31 else f"2020-04-{n - 30:02d}"
        days[day] = [old_copy(school, folder, f"{day}T08:00:00")[0],
                     old_copy(school, folder, f"{day}T18:00:00")[0]]
    months = [old_copy(school, folder, f"2019-{m:02d}-15T18:00:00")[0] for m in range(1, 13)]

    removed = backup.prune(school)

    kept = kept_ids(school)
    last_days = sorted(days)[-14:]
    assert {days[d][1] for d in last_days} <= kept  # each day's close copy
    assert days[last_days[-1]][0] in kept  # among the 3 latest copies
    assert days["2020-03-31"][1] in kept  # March's latest copy (one of the 14 days too)
    assert days["2020-03-15"][0] not in kept and days["2020-03-15"][1] not in kept
    assert set(months[-10:]) <= kept  # with March and April: 12 months
    assert months[0] not in kept and months[1] not in kept
    assert len(kept) == 14 + 1 + 10  # 14 days, 1 more of the 3 latest, 10 older months
    for name in removed:
        assert not (folder / name).exists()
    assert len(list(folder.iterdir())) == len(kept)
    logged = audit_rows(school, "backup.prune")
    assert json.loads(logged[-1]["new_value"])["count"] == len(removed) == 80 + 12 - len(kept)


def test_a_long_break_never_empties_the_folder(school, folder):
    ids = [old_copy(school, folder, f"2019-07-{d:02d}T18:00:00")[0] for d in range(1, 6)]
    assert backup.prune(school) == []  # summer: the last copies are months old, still kept
    assert set(ids) <= kept_ids(school)


def test_manual_copies_and_copies_a_restore_used_are_kept(school, folder):
    manual, _ = old_copy(school, folder, "2018-01-01T08:00:00", kind="manual")
    used, _ = old_copy(school, folder, "2018-01-02T08:00:00")
    school.execute("INSERT INTO restore_log(backup_id, restored_by, result) VALUES (?, 1, "
                   "'success')", (used,))
    for d in range(1, 31):
        old_copy(school, folder, f"2020-01-{d:02d}T08:00:00")
        old_copy(school, folder, f"2020-02-{d if d < 30 else 29:02d}T0{d % 10}:00:00")
    backup.prune(school)
    assert {manual, used} <= kept_ids(school)


def test_failed_copies_go_after_14_days(school, folder):
    old, old_path = old_copy(school, folder, "2020-01-01T08:00:00", status="failed")
    stuck, _ = old_copy(school, folder, "2020-01-02T08:00:00", status="running")
    recent, _ = old_copy(school, folder, backup.dates.iso(backup.dates.today()) + "T08:00:00",
                         status="failed")
    backup.prune(school)
    assert old not in kept_ids(school) and stuck not in kept_ids(school)
    assert not old_path.exists()
    assert recent in kept_ids(school)


def test_a_file_that_cannot_be_removed_keeps_its_row(school, folder, monkeypatch):
    for d in range(1, 6):
        old_copy(school, folder, f"2020-01-{d:02d}T08:00:00")
        old_copy(school, folder, f"2020-01-{d:02d}T09:00:00")
    monkeypatch.setattr(Path, "unlink", lambda self, missing_ok=False: (_ for _ in ()).throw(
        PermissionError("locked")))
    assert backup.prune(school) == []
    assert len(kept_ids(school)) == 10
    assert audit_rows(school, "backup.prune") == []


def test_each_new_copy_prunes_the_old_ones(school, folder):
    for d in range(1, 21):
        old_copy(school, folder, f"2020-01-{d:02d}T08:00:00")
    taken = backup.take(school, folder)
    kept = kept_ids(school)
    assert taken.id in kept
    assert len(kept) == 14  # today and the last 13 days of January (its latest among them)
    assert len(list(folder.iterdir())) == 14
