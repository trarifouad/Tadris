"""SQL for holidays: periods without classes, start_date to end_date both included."""


def list_all(conn) -> list:
    return conn.execute(
        "SELECT id, label, start_date, end_date FROM holidays ORDER BY start_date DESC"
    ).fetchall()


def get(conn, holiday_id: int):
    return conn.execute("SELECT id, label, start_date, end_date FROM holidays WHERE id = ?",
                        (holiday_id,)).fetchone()


def overlapping(conn, start_date: str, end_date: str, exclude_id: int | None):
    return conn.execute(
        "SELECT id, label, start_date, end_date FROM holidays "
        "WHERE start_date <= ? AND end_date >= ? AND id IS NOT ? ORDER BY start_date LIMIT 1",
        (end_date, start_date, exclude_id),
    ).fetchone()


def between(conn, first: str, last: str) -> list:
    """Periods sharing at least a day with [first, last] (both included)."""
    return conn.execute(
        "SELECT id, label, start_date, end_date FROM holidays "
        "WHERE start_date <= ? AND end_date >= ? ORDER BY start_date",
        (last, first),
    ).fetchall()


def insert(conn, label: str, start_date: str, end_date: str) -> int:
    cur = conn.execute("INSERT INTO holidays(label, start_date, end_date) VALUES (?, ?, ?)",
                       (label, start_date, end_date))
    return int(cur.lastrowid)


def update(conn, holiday_id: int, label: str, start_date: str, end_date: str) -> None:
    conn.execute("UPDATE holidays SET label = ?, start_date = ?, end_date = ? WHERE id = ?",
                 (label, start_date, end_date, holiday_id))


def delete(conn, holiday_id: int) -> None:
    conn.execute("DELETE FROM holidays WHERE id = ?", (holiday_id,))
