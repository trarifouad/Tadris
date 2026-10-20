import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

from tadris.core import dates
from tadris.core.errors import BusinessRuleError, NotFound
from tadris.db.connection import transaction
from tadris.domain.models import Backup
from tadris.i18n.fr import t
from tadris.repositories import backups as repo
from tadris.services import audit

# Copies of the database, taken by the app itself: at start once a day (and again by a timer
# if the app stays open past midnight), when the app closes, and before a migration. A copy is
# made with SQLite's online backup API, never a raw file copy (the database runs in WAL mode),
# written under a temporary name and renamed once complete, so a half-written file never looks
# like a backup. Each copy is then verified: opened read-only, PRAGMA integrity_check, sha256
# compared with the one recorded. A failure never stops the app; the caller warns the user.
# Retention, a second location and restore come in phase 12.

_HASH_CHUNK = 1 << 20


class BackupFailed(BusinessRuleError):
    pass


def _to_backup(row) -> Backup:
    return Backup(id=row["id"], file_path=row["file_path"], size_bytes=row["size_bytes"],
                  checksum=row["checksum"], type=row["type"], status=row["status"],
                  created_at=row["created_at"], completed_at=row["completed_at"],
                  verified_at=row["verified_at"])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _target(folder: Path, kind: str) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = folder / f"tadris-{stamp}-{kind}.db"
    n = 2
    while path.exists():
        path = folder / f"tadris-{stamp}-{kind}-{n}.db"
        n += 1
    return path


def _copy(conn, path: Path) -> None:
    part = path.with_name(path.name + ".part")
    part.unlink(missing_ok=True)
    dest = sqlite3.connect(part)
    try:
        conn.backup(dest)
        # One self-contained file: the copy can be opened read-only without a -wal or -shm.
        dest.execute("PRAGMA journal_mode = DELETE")
    finally:
        dest.close()
    part.replace(path)


def _check(path: Path, checksum: str | None) -> bool:
    if not path.is_file() or checksum is None or sha256(path) != checksum:
        return False
    try:
        copy = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            return copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            copy.close()
    except sqlite3.DatabaseError:
        return False


def take(conn, folder: Path, kind: str = "auto") -> Backup:
    """Copy the database into folder and verify the copy. Raises BackupFailed (the row stays,
    marked failed, and the failure is in the audit log)."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackupFailed(t["backup.failed"].format(path=folder)) from exc
    path = _target(folder, kind)
    with transaction(conn):
        backup_id = repo.insert(conn, str(path), kind)
    try:
        _copy(conn, path)
        checksum = sha256(path)
        with transaction(conn):
            repo.mark_done(conn, backup_id, path.stat().st_size, checksum)
    except (OSError, sqlite3.Error) as exc:
        path.with_name(path.name + ".part").unlink(missing_ok=True)
        _fail(conn, backup_id, str(path), exc)
    if not verify(conn, backup_id):
        raise BackupFailed(t["backup.failed"].format(path=path))
    with transaction(conn):
        audit.log_system(conn, "backup.create", "backups",
                         new={"id": backup_id, "file": path.name, "type": kind})
    return get(conn, backup_id)


def _fail(conn, backup_id: int, path: str, exc: Exception) -> None:
    with transaction(conn):
        repo.mark_failed(conn, backup_id)
        audit.log_system(conn, "backup.failed", "backups",
                         new={"id": backup_id, "file": path, "error": str(exc)})
    raise BackupFailed(t["backup.failed"].format(path=path)) from exc


def verify(conn, backup_id: int) -> bool:
    """Check the file is still the one written and a sound database. Sets verified or failed."""
    row = repo.get(conn, backup_id)
    if row is None:
        raise NotFound(t["backup.not_found"])
    ok = _check(Path(row["file_path"]), row["checksum"])
    with transaction(conn):
        if ok:
            repo.mark_verified(conn, backup_id)
        else:
            repo.mark_failed(conn, backup_id)
            audit.log_system(conn, "backup.failed", "backups",
                             new={"id": backup_id, "file": row["file_path"],
                                  "error": "verification"})
    return ok


def get(conn, backup_id: int) -> Backup:
    row = repo.get(conn, backup_id)
    if row is None:
        raise NotFound(t["backup.not_found"])
    return _to_backup(row)


def list_backups(conn) -> list[Backup]:
    """Latest first."""
    return [_to_backup(row) for row in repo.list_all(conn)]


def daily_due(conn) -> bool:
    return repo.verified_auto_on(conn, dates.iso(dates.today())) is None


def daily(conn, folder: Path) -> Backup | None:
    """Today's automatic copy, unless one was already taken and verified today."""
    return take(conn, folder) if daily_due(conn) else None
