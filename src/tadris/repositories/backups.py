"""SQL for backups: one row per copy of the database, running -> done -> verified, or failed."""

_COLUMNS = ("id, file_path, size_bytes, checksum, type, status, created_at, completed_at, "
            "verified_at")


def get(conn, backup_id: int):
    return conn.execute(f"SELECT {_COLUMNS} FROM backups WHERE id = ?", (backup_id,)).fetchone()


def list_all(conn) -> list:
    return conn.execute(f"SELECT {_COLUMNS} FROM backups ORDER BY id DESC").fetchall()


def verified_auto_on(conn, day: str):
    """The latest verified automatic backup taken on day ('YYYY-MM-DD'), or None."""
    return conn.execute(
        f"SELECT {_COLUMNS} FROM backups WHERE type = 'auto' AND status = 'verified' "
        "AND substr(created_at, 1, 10) = ? ORDER BY id DESC LIMIT 1",
        (day,),
    ).fetchone()


def statuses_on(conn, day: str) -> list[str]:
    """The status of each copy taken on day ('YYYY-MM-DD'), the latest first."""
    rows = conn.execute("SELECT status FROM backups WHERE substr(created_at, 1, 10) = ? "
                        "ORDER BY id DESC", (day,)).fetchall()
    return [row["status"] for row in rows]


def insert(conn, file_path: str, kind: str) -> int:
    cur = conn.execute("INSERT INTO backups(file_path, type) VALUES (?, ?)", (file_path, kind))
    return int(cur.lastrowid)


def mark_done(conn, backup_id: int, size_bytes: int, checksum: str) -> None:
    conn.execute(
        "UPDATE backups SET status = 'done', size_bytes = ?, checksum = ?, "
        "completed_at = strftime('%Y-%m-%dT%H:%M:%S','now','localtime') WHERE id = ?",
        (size_bytes, checksum, backup_id),
    )


def mark_verified(conn, backup_id: int) -> None:
    conn.execute(
        "UPDATE backups SET status = 'verified', "
        "verified_at = strftime('%Y-%m-%dT%H:%M:%S','now','localtime') WHERE id = ?",
        (backup_id,),
    )


def mark_failed(conn, backup_id: int) -> None:
    conn.execute("UPDATE backups SET status = 'failed', verified_at = NULL WHERE id = ?",
                 (backup_id,))


def removable(conn) -> list:
    """Copies retention may look at, latest first: automatic ones never used by a restore."""
    return conn.execute(
        f"SELECT {_COLUMNS} FROM backups b WHERE type = 'auto' "
        "AND NOT EXISTS (SELECT 1 FROM restore_log r WHERE r.backup_id = b.id) "
        "ORDER BY created_at DESC, id DESC"
    ).fetchall()


def delete(conn, backup_id: int) -> None:
    conn.execute("DELETE FROM backups WHERE id = ?", (backup_id,))
