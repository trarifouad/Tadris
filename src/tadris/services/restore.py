"""Putting a copy of the database back (Paramètres → Sauvegardes), director only.

A copy is looked at first (inspect): it must open, pass PRAGMA integrity_check, be a Tadris
database with a director, and not come from a later version of the app; a copy the app
recorded must also still match its checksum. Nothing is replaced before that.

Then, in order:
1. a safety copy of the database as it is now (« avant-restauration », never removed by
   retention): without it, nothing is replaced;
2. the copy is written over the open database with SQLite's online backup API (the database
   stays in WAL mode and the file is never swapped under the app);
3. an older copy is brought to this version (migrations); if that fails, the safety copy
   is put back and the attempt is written to restore_log as failed;
4. the list of copies on disk is the one from before (the copy's own list is out of date),
   and restore_log and the audit log record who restored what.

The user is then sent back to the login screen: the accounts are the copy's.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, ValidationError
from tadris.core.permissions import require
from tadris.db.connection import transaction
from tadris.db.migrate import MigrationFailed, latest_version, migrate
from tadris.domain.models import Backup
from tadris.i18n.fr import t
from tadris.services import audit, backup

REQUIRED_TABLES = {"users", "settings", "students", "backups", "restore_log", "audit_log"}
SAFETY_LABEL = "avant-restauration"


@dataclass(frozen=True)
class CopyInfo:
    """What a copy holds, shown before it is restored."""

    path: Path
    schema_version: int
    school: str
    students: int
    last_activity: str | None  # the latest audit entry ('YYYY-MM-DDTHH:MM:SS')


@dataclass(frozen=True)
class Restored:
    copy: CopyInfo
    safety: Backup  # the database as it was just before


def _open_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def inspect(path: Path) -> CopyInfo:
    """Check a file can be restored and say what it holds. Raises ValidationError."""
    path = Path(path)
    if not path.is_file():
        raise ValidationError(t["restore.missing"].format(path=path))
    try:
        copy = _open_ro(path)
    except sqlite3.Error as exc:
        raise ValidationError(t["restore.not_a_copy"]) from exc
    try:
        return _read(copy, path)
    except sqlite3.DatabaseError as exc:  # not a database at all, or damaged
        raise ValidationError(t["restore.not_a_copy"]) from exc
    finally:
        copy.close()


def _read(copy: sqlite3.Connection, path: Path) -> CopyInfo:
    if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValidationError(t["restore.damaged"])
    version = copy.execute("PRAGMA user_version").fetchone()[0]
    tables = {row[0] for row in copy.execute("SELECT name FROM sqlite_master WHERE "
                                             "type = 'table'")}
    if version < 1 or not REQUIRED_TABLES <= tables:
        raise ValidationError(t["restore.not_a_copy"])
    if version > latest_version():
        raise ValidationError(t["restore.newer"].format(version=version,
                                                        latest=latest_version()))
    if copy.execute("SELECT 1 FROM users WHERE role = 'director' AND status = 'active'"
                    ).fetchone() is None:
        raise ValidationError(t["restore.no_director"])
    school = copy.execute("SELECT value FROM settings WHERE key = 'school.name'").fetchone()
    return CopyInfo(
        path=path, schema_version=version, school=school[0] if school else "",
        students=copy.execute("SELECT COUNT(*) FROM students").fetchone()[0],
        last_activity=copy.execute("SELECT MAX(created_at) FROM audit_log").fetchone()[0])


def inspect_backup(conn, ctx: UserContext, backup_id: int) -> CopyInfo:
    """A copy the app recorded: still the file it wrote (checksum), then inspect()."""
    require(ctx, "backup.restore")
    if not backup.verify(conn, backup_id):
        raise ValidationError(t["restore.damaged"])
    return inspect(Path(backup.get(conn, backup_id).file_path))


def restore(conn, ctx: UserContext, path: Path, folder: Path) -> Restored:
    """Put the copy at `path` in place of the open database (see the module docstring).
    folder: where the safety copy goes. Raises ValidationError (the copy cannot be used),
    BackupFailed (no safety copy: nothing replaced) or BusinessRuleError (the copy could
    not be brought to this version: the database is back as it was)."""
    require(ctx, "backup.restore")
    info = inspect(path)
    try:
        safety = backup.take(conn, folder, "manual", label=SAFETY_LABEL)
    except backup.MirrorFailed as exc:  # the safety copy is made: only the second is missing
        safety = exc.backup
    carried = [dict(row) for row in conn.execute("SELECT * FROM backups ORDER BY id")]

    try:
        _write_over(conn, info.path)
        migrate(conn)
    except (MigrationFailed, sqlite3.Error) as exc:
        error = getattr(exc, "error", exc)
        try:
            _write_over(conn, Path(safety.file_path))  # as it was: the copy just taken
        except sqlite3.Error as again:
            raise BusinessRuleError(t["restore.failed_badly"].format(
                error=error, safety=safety.file_path)) from again
        with transaction(conn):
            _carry_backups(conn, carried)
            _log(conn, ctx, info, safety, "failed", str(error))
        raise BusinessRuleError(t["restore.failed"].format(error=error)) from exc

    with transaction(conn):
        _carry_backups(conn, carried)
        _log(conn, ctx, info, safety, "success")
    return Restored(copy=info, safety=safety)


def _write_over(conn, source: Path) -> None:
    copy = _open_ro(source)
    try:
        copy.backup(conn)
    finally:
        copy.close()


def _carry_backups(conn, carried: list[dict]) -> None:
    """The copies on disk are the ones listed before the restore (the copy's list stopped
    when it was taken). Rows a restore_log entry points to stay; the others are replaced."""
    conn.execute("DELETE FROM backups WHERE id NOT IN (SELECT backup_id FROM restore_log)")
    kept = {row[0] for row in conn.execute("SELECT file_path FROM backups")}
    for row in carried:
        if row["file_path"] in kept:
            continue
        conn.execute(
            "INSERT INTO backups(file_path, size_bytes, checksum, type, status, created_at, "
            "completed_at, verified_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (row["file_path"], row["size_bytes"], row["checksum"], row["type"],
             row["status"], row["created_at"], row["completed_at"], row["verified_at"]))


def _source_row(conn, path: Path) -> int:
    """The backups row of the copy restored; a file from elsewhere (another computer) gets
    one, as a manual copy, so retention never removes it."""
    row = conn.execute("SELECT id FROM backups WHERE file_path = ? ORDER BY id DESC LIMIT 1",
                       (str(path),)).fetchone()
    if row is not None:
        return row[0]
    cur = conn.execute(
        "INSERT INTO backups(file_path, size_bytes, checksum, type, status, completed_at, "
        "verified_at) VALUES (?, ?, ?, 'manual', 'verified', "
        "strftime('%Y-%m-%dT%H:%M:%S','now','localtime'), "
        "strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))",
        (str(path), path.stat().st_size, backup.sha256(path)))
    return int(cur.lastrowid)


def _restorer(conn, ctx: UserContext) -> UserContext:
    """Who restored, in the database now open: the same username, else its first active
    director (the copy may come from before this account existed)."""
    row = conn.execute("SELECT id, username, role FROM users WHERE username = ?",
                       (ctx.username,)).fetchone()
    if row is None:
        row = conn.execute("SELECT id, username, role FROM users WHERE role = 'director' "
                           "AND status = 'active' ORDER BY id LIMIT 1").fetchone()
    return UserContext(user_id=row["id"], username=row["username"], role=row["role"])


def _log(conn, ctx: UserContext, info: CopyInfo, safety: Backup, result: str,
         error: str | None = None) -> None:
    source_id = _source_row(conn, info.path)
    by = _restorer(conn, ctx)
    conn.execute("INSERT INTO restore_log(backup_id, restored_by, result) VALUES (?, ?, ?)",
                 (source_id, by.user_id, result))
    new = {"file": info.path.name, "folder": str(info.path.parent),
           "safety": Path(safety.file_path).name, "by": ctx.username, "result": result}
    if error:
        new["error"] = error
    audit.log(conn, by, "backup.restore", "backups", source_id, new=new)
