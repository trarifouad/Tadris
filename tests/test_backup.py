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


# ----- second location -----

@pytest.fixture
def usb(tmp_path):
    drive = tmp_path / "usb"
    drive.mkdir()
    return drive


@pytest.fixture
def director(school):
    return auth.login(school, "directeur", "password1")


def test_no_second_location_by_default(school, folder):
    taken = backup.take(school, folder)
    assert backup.second_root(school) is None
    assert backup.mirror(school, taken) is None


def test_each_copy_also_goes_to_the_second_location(school, folder, usb, director):
    backup.set_second_root(school, director, str(usb))
    taken = backup.take(school, folder)

    sub = backup.second_folder(school)
    assert sub.parent == usb and sub.name == f"Tadris-{backup.school_id(school)}"
    copy = sub / Path(taken.file_path).name
    assert copy.is_file() and backup.sha256(copy) == taken.checksum
    assert not list(sub.glob("*.part"))
    with open_ro(copy) as c:
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert c.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 1
    logged = json.loads(audit_rows(school, "backup.mirror")[-1]["new_value"])
    assert logged["file"] == copy.name and logged["folder"] == str(sub)


def test_the_school_id_is_made_once(school):
    first = backup.school_id(school)
    assert len(first) == 12 and backup.school_id(school) == first


def test_a_folder_that_does_not_exist_is_refused(school, director, tmp_path):
    with pytest.raises(backup.ValidationError):
        backup.set_second_root(school, director, str(tmp_path / "nowhere"))
    assert backup.second_root(school) is None
    backup.set_second_root(school, director, "  ")  # off
    assert backup.second_root(school) is None


def test_only_the_director_sets_the_second_location(school, director, usb):
    from tadris.core.errors import PermissionDenied

    auth.create_user(school, director, "accueil", "password1", "receptionist")
    desk = auth.login(school, "accueil", "password1")
    with pytest.raises(PermissionDenied):
        backup.set_second_root(school, desk, str(usb))


def test_a_drive_not_plugged_in_warns_but_the_copy_is_made(school, folder, usb, director):
    backup.set_second_root(school, director, str(usb))
    usb.rmdir()  # unplugged
    with pytest.raises(backup.MirrorFailed) as failed:
        backup.take(school, folder)
    assert "introuvable" in failed.value.message and str(usb) in failed.value.message
    kept = failed.value.backup
    assert kept.status == "verified" and Path(kept.file_path).is_file()
    assert not usb.exists()  # the drive's root is never created
    entry = audit_rows(school, "backup.mirror_failed")[-1]
    assert json.loads(entry["new_value"])["error"] == "missing"
    assert not backup.daily_due(school)  # today's copy counts


def test_a_write_that_fails_leaves_no_half_copy(school, folder, usb, director, monkeypatch):
    backup.set_second_root(school, director, str(usb))

    def full_disk(source, target):
        Path(target).write_bytes(b"half")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(backup.shutil, "copyfile", full_disk)
    with pytest.raises(backup.MirrorFailed) as failed:
        backup.take(school, folder)
    assert "a échoué" in failed.value.message
    assert list(backup.second_folder(school).iterdir()) == []


def test_a_copy_that_differs_is_not_kept(school, folder, usb, director, monkeypatch):
    backup.set_second_root(school, director, str(usb))
    monkeypatch.setattr(backup.shutil, "copyfile",
                        lambda source, target: Path(target).write_bytes(b"not the same"))
    with pytest.raises(backup.MirrorFailed):
        backup.take(school, folder)
    assert list(backup.second_folder(school).iterdir()) == []
    entry = audit_rows(school, "backup.mirror_failed")[-1]
    assert json.loads(entry["new_value"])["error"] == "checksum"


def test_retention_on_the_second_location_by_file_name(tmp_path):
    sub = tmp_path / "Tadris-abc"
    sub.mkdir()
    names = []
    for day in range(1, 31):
        for hour in ("08", "18"):
            name = f"tadris-2020-01-{day:02d}_{hour}0000-auto.db"
            (sub / name).write_bytes(b"x")
            names.append(name)
    (sub / "tadris-2019-01-01_080000-manual.db").write_bytes(b"x")  # a manual copy
    (sub / "notes.txt").write_text("à garder")  # not the app's

    removed = backup.prune_folder(sub)

    left = {p.name for p in sub.iterdir()}
    assert "tadris-2019-01-01_080000-manual.db" in left and "notes.txt" in left
    assert {f"tadris-2020-01-{d:02d}_180000-auto.db" for d in range(17, 31)} <= left
    assert "tadris-2020-01-30_080000-auto.db" in left  # among the 3 latest
    assert len(left) == 14 + 1 + 2
    assert len(removed) == 60 - 15


def test_the_journal_shows_a_failed_copy_to_the_second_location(school, folder, usb,
                                                                director):
    from tadris.repositories import reports as reports_repo

    backup.set_second_root(school, director, str(usb))
    usb.rmdir()
    with pytest.raises(backup.MirrorFailed):
        backup.take(school, folder)
    shown = [row["action"] for row in reports_repo.audit_entries(
        school, "2000-01-01", "2100-01-01", None, None, None, 100)]
    assert "backup.mirror_failed" in shown and "backup.create" not in shown


def test_the_app_warns_about_the_second_location_and_goes_on(monkeypatch):
    shown = []
    monkeypatch.setattr(app.QMessageBox, "warning",
                        lambda parent, title, text: shown.append(text))

    def unplugged():
        raise backup.MirrorFailed("Le second emplacement est introuvable (E:).", None)

    assert app._backup(unplugged) is True  # the copy on this computer is made
    assert "Paramètres → Sauvegardes" in shown[0]
