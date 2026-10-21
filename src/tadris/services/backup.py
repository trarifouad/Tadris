import hashlib
import re
import shutil
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, NotFound, ValidationError
from tadris.core.permissions import require
from tadris.db.connection import transaction
from tadris.domain.models import Backup
from tadris.i18n.fr import t
from tadris.repositories import backups as repo
from tadris.services import audit, settings

# Copies of the database, taken by the app itself: at start once a day (and again by a timer
# if the app stays open past midnight), when the app closes, and before a migration. A copy is
# made with SQLite's online backup API, never a raw file copy (the database runs in WAL mode),
# written under a temporary name and renamed once complete, so a half-written file never looks
# like a backup. Each copy is then verified: opened read-only, PRAGMA integrity_check, sha256
# compared with the one recorded. A failure never stops the app; the caller warns the user.
#
# Retention: after each new verified copy, older ones are removed (file and row) so the folder
# does not grow for ever. Kept: the RECENT_KEPT latest copies, the latest copy of each of the
# last DAILY_KEPT days that have one, and of each of the last MONTHLY_KEPT months; days and
# months without a copy (holidays) do not count, so a long break never empties the folder.
# Manual copies and copies a restore used are never removed. A failed copy (or one cut short
# by a crash) goes once it is older than DAILY_KEPT days. A second location and restore come in phase 12.

_HASH_CHUNK = 1 << 20
RECENT_KEPT = 3
DAILY_KEPT = 14
MONTHLY_KEPT = 12


class BackupFailed(BusinessRuleError):
    pass


class MirrorFailed(BackupFailed):
    """The copy is made and verified, but could not be written to the second location."""

    def __init__(self, message: str, backup: Backup):
        super().__init__(message)
        self.backup = backup


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


def _target(folder: Path, label: str) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = folder / f"tadris-{stamp}-{label}.db"
    n = 2
    while path.exists():
        path = folder / f"tadris-{stamp}-{label}-{n}.db"
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


def take(conn, folder: Path, kind: str = "auto", label: str | None = None) -> Backup:
    """Copy the database into folder and verify the copy. Raises BackupFailed (the row stays,
    marked failed, and the failure is in the audit log). label: the file name's last part
    (the kind by default, e.g. 'avant-restauration' for the copy a restore takes first)."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackupFailed(t["backup.failed"].format(path=folder)) from exc
    path = _target(folder, label or kind)
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
    prune(conn)
    taken = get(conn, backup_id)
    mirror(conn, taken)
    return taken


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


def take_now(conn, ctx: UserContext, folder: Path) -> Backup:
    """« Sauvegarder maintenant »: a manual copy (never removed by retention). Raises
    BackupFailed, or MirrorFailed when only the second location is missing."""
    require(ctx, "backup.create")
    try:
        taken = take(conn, folder, "manual")
    except MirrorFailed as exc:
        _log_manual(conn, ctx, exc.backup)
        raise
    _log_manual(conn, ctx, taken)
    return taken


def _log_manual(conn, ctx: UserContext, taken: Backup) -> None:
    with transaction(conn):
        audit.log(conn, ctx, "backup.manual", "backups", taken.id,
                  new={"file": Path(taken.file_path).name})


def daily_due(conn) -> bool:
    return repo.verified_auto_on(conn, dates.iso(dates.today())) is None


def daily(conn, folder: Path) -> Backup | None:
    """Today's automatic copy, unless one was already taken and verified today."""
    return take(conn, folder) if daily_due(conn) else None


# ----- retention -----

def _kept(stamped: list[tuple[str, object]]) -> set:
    """Of (created_at, key) pairs, latest first: the keys retention keeps (the RECENT_KEPT
    latest, the latest of each of the last DAILY_KEPT days and MONTHLY_KEPT months)."""
    kept = {key for _stamp, key in stamped[:RECENT_KEPT]}
    for length, count in ((10, DAILY_KEPT), (7, MONTHLY_KEPT)):  # 'YYYY-MM-DD', 'YYYY-MM'
        latest: dict[str, object] = {}
        for stamp, key in stamped:
            period = stamp[:length]
            if period not in latest:
                if len(latest) == count:
                    break
                latest[period] = key
        kept |= set(latest.values())
    return kept


def to_remove(conn) -> list:
    """The copies retention lets go (rows, latest first)."""
    rows = repo.removable(conn)
    kept = _kept([(row["created_at"], row["id"]) for row in rows
                  if row["status"] == "verified"])
    cutoff = dates.iso(dates.today() - timedelta(days=DAILY_KEPT))
    return [row for row in rows if row["id"] not in kept
            and (row["status"] == "verified" or row["created_at"][:10] < cutoff)]


def prune(conn) -> list[str]:
    """Remove the copies retention lets go; returns their file names. A file that cannot be
    removed (locked) keeps its row and is tried again after the next copy."""
    removed = []
    for row in to_remove(conn):
        path = Path(row["file_path"])
        try:
            path.unlink(missing_ok=True)
            path.with_name(path.name + ".part").unlink(missing_ok=True)
        except OSError:
            continue
        with transaction(conn):
            repo.delete(conn, row["id"])
        removed.append(path.name)
    if removed:
        with transaction(conn):
            audit.log_system(conn, "backup.prune", "backups",
                             new={"count": len(removed), "files": removed})
    return removed


# ----- second location -----

SECOND_KEY = "backup.second_dir"
SCHOOL_KEY = "backup.school_id"
# tadris-2026-10-21_183005-auto.db, or ...-auto-2.db for a second copy in the same second.
_FILE = re.compile(r"^tadris-(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})(\d{2})-auto(?:-\d+)?\.db$")


def school_id(conn) -> str:
    """A random id given to the school's database once, naming its subfolder on the second
    location. A copy of the database (a restore on another computer) keeps it."""
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (SCHOOL_KEY,)).fetchone()
    if row is not None:
        return row[0]
    with transaction(conn):
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                     (SCHOOL_KEY, uuid.uuid4().hex[:12]))
    return conn.execute("SELECT value FROM settings WHERE key = ?",
                        (SCHOOL_KEY,)).fetchone()[0]


def second_root(conn) -> Path | None:
    """The second location the director chose, or None."""
    value = settings.get(conn, SECOND_KEY, "")
    return Path(value) if value else None


def second_folder(conn) -> Path | None:
    """This school's subfolder on the second location, or None when there is none."""
    root = second_root(conn)
    return None if root is None else root / f"Tadris-{school_id(conn)}"


def set_second_root(conn, ctx: UserContext, folder: str) -> None:
    """Set the second location ('' turns it off). The folder must exist now (the drive
    plugged in), so a typo is caught when it is chosen."""
    require(ctx, "settings.change")
    folder = folder.strip()
    if folder and not Path(folder).is_dir():
        raise ValidationError(t["backup.second_not_found"].format(path=folder))
    settings.set_value(conn, ctx, SECOND_KEY, folder)


def mirror(conn, backup: Backup) -> Path | None:
    """Write a verified copy to the second location; None when there is none. Raises
    MirrorFailed (the copy itself is fine) when the drive is missing or the write fails."""
    root = second_root(conn)
    if root is None:
        return None
    if not root.is_dir():  # never create a drive's root: it is not plugged in
        _mirror_failed(conn, backup, root, "missing", t["backup.second_missing"])
    folder = second_folder(conn)
    source = Path(backup.file_path)
    target = folder / source.name
    part = target.with_name(target.name + ".part")
    try:
        folder.mkdir(exist_ok=True)
        shutil.copyfile(source, part)
        if sha256(part) != backup.checksum:
            raise OSError("checksum")
        part.replace(target)
    except OSError as exc:
        try:
            part.unlink(missing_ok=True)  # never leave half a copy on the drive
        except OSError:
            pass
        _mirror_failed(conn, backup, folder, str(exc), t["backup.second_failed"])
    with transaction(conn):
        audit.log_system(conn, "backup.mirror", "backups",
                         new={"id": backup.id, "file": target.name, "folder": str(folder)})
    prune_folder(folder)
    return target


def _mirror_failed(conn, backup: Backup, folder: Path, error: str, message: str) -> None:
    with transaction(conn):
        audit.log_system(conn, "backup.mirror_failed", "backups",
                         new={"id": backup.id, "folder": str(folder), "error": error})
    raise MirrorFailed(message.format(path=folder), backup)


def prune_folder(folder: Path) -> list[str]:
    """Retention on the second location, by file name: only automatic copies named by the
    app are looked at (manual ones and any other file stay). Returns the names removed."""
    stamped = []
    for path in folder.iterdir():
        match = _FILE.match(path.name)
        if match and path.is_file():
            day, hh, mm, ss = match.groups()
            stamped.append((f"{day}T{hh}:{mm}:{ss}", path.name))
    stamped.sort(reverse=True)
    kept = _kept(stamped)
    removed = []
    for _stamp, name in stamped:
        if name in kept:
            continue
        try:
            (folder / name).unlink()
        except OSError:
            continue
        removed.append(name)
    return removed
