"""SQL for school years. A year's end_date is its last day (inclusive)."""

_COLUMNS = """
    y.id, y.label, y.start_date, y.end_date, y.status, y.opened_on,
    (SELECT COUNT(*) FROM class_groups g WHERE g.school_year_id = y.id) AS group_count
"""


def list_all(conn) -> list:
    return conn.execute(
        f"SELECT {_COLUMNS} FROM school_years y ORDER BY y.start_date DESC"
    ).fetchall()


def get(conn, year_id: int):
    return conn.execute(
        f"SELECT {_COLUMNS} FROM school_years y WHERE y.id = ?", (year_id,)
    ).fetchone()


def open_year(conn):
    return conn.execute(
        f"SELECT {_COLUMNS} FROM school_years y WHERE y.status = 'open'"
    ).fetchone()


def insert(conn, label: str, start_date: str, end_date: str, status: str,
           opened_on: str | None) -> int:
    cur = conn.execute(
        "INSERT INTO school_years(label, start_date, end_date, status, opened_on) "
        "VALUES (?, ?, ?, ?, ?)",
        (label, start_date, end_date, status, opened_on),
    )
    return int(cur.lastrowid)


def update(conn, year_id: int, label: str, start_date: str, end_date: str) -> None:
    conn.execute(
        "UPDATE school_years SET label = ?, start_date = ?, end_date = ? WHERE id = ?",
        (label, start_date, end_date, year_id),
    )


def set_status(conn, year_id: int, status: str) -> None:
    conn.execute("UPDATE school_years SET status = ? WHERE id = ?", (status, year_id))


def mark_opened(conn, year_id: int, on: str) -> None:
    """Record the first opening (a reopening keeps the first date)."""
    conn.execute("UPDATE school_years SET opened_on = COALESCE(opened_on, ?) WHERE id = ?",
                 (on, year_id))


def label_taken(conn, label: str, exclude_id: int | None) -> bool:
    row = conn.execute(
        "SELECT 1 FROM school_years WHERE fold(label) = fold(?) AND id IS NOT ?",
        (label, exclude_id),
    ).fetchone()
    return row is not None


def overlapping(conn, start_date: str, end_date: str, exclude_id: int | None):
    """A year sharing at least one day with [start_date, end_date] (both inclusive)."""
    return conn.execute(
        """
        SELECT id, label FROM school_years
         WHERE start_date <= ? AND end_date >= ? AND id IS NOT ?
         ORDER BY start_date LIMIT 1
        """,
        (end_date, start_date, exclude_id),
    ).fetchone()


def groups_outside(conn, year_id: int, start_date: str, end_date: str) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) FROM class_groups
         WHERE school_year_id = ? AND (start_date < ? OR start_date > ?)
        """,
        (year_id, start_date, end_date),
    ).fetchone()
    return int(row[0])


def close_groups(conn, year_id: int) -> list[int]:
    ids = [
        int(row[0]) for row in conn.execute(
            "SELECT id FROM class_groups WHERE school_year_id = ? AND status <> 'closed'",
            (year_id,),
        )
    ]
    conn.execute(
        """
        UPDATE class_groups
           SET status = 'closed', updated_at = strftime('%Y-%m-%dT%H:%M:%S','now','localtime')
         WHERE school_year_id = ? AND status <> 'closed'
        """,
        (year_id,),
    )
    return ids
