"""SQL for teachers and their rate history. Rate periods are half-open [valid_from, valid_to)."""

_NOW = "strftime('%Y-%m-%dT%H:%M:%S','now','localtime')"

# Groups not closed that the teacher teaches on :today (or on the start date of a group
# that has not started), as the groups list shows them.
_CURRENT_GROUPS = """
    SELECT COUNT(DISTINCT g.id) FROM group_teachers gt JOIN class_groups g ON g.id = gt.group_id
     WHERE gt.teacher_id = t.id AND g.status <> 'closed'
       AND gt.valid_from <= max(:today, g.start_date)
       AND (gt.valid_to IS NULL OR gt.valid_to > max(:today, g.start_date))
"""
_CURRENT_RATE = """
    SELECT percentage_bp FROM teacher_rates r
     WHERE r.teacher_id = t.id AND r.valid_to IS NULL
"""
_CURRENT_RATE_FROM = """
    SELECT valid_from FROM teacher_rates r
     WHERE r.teacher_id = t.id AND r.valid_to IS NULL
"""


def insert(conn, full_name: str, phone: str | None, hire_date: str | None) -> int:
    cur = conn.execute(
        "INSERT INTO teachers(full_name, phone, hire_date) VALUES (?, ?, ?)",
        (full_name, phone, hire_date),
    )
    return int(cur.lastrowid)


def get(conn, teacher_id: int, today: str):
    return conn.execute(
        f"""
        SELECT t.id, t.full_name, t.phone, t.status, t.hire_date,
               ({_CURRENT_RATE}) AS current_rate_bp, ({_CURRENT_RATE_FROM}) AS current_rate_from,
               ({_CURRENT_GROUPS}) AS group_count
          FROM teachers t WHERE t.id = :id
        """,
        {"id": teacher_id, "today": today},
    ).fetchone()


def update(conn, teacher_id: int, full_name: str, phone: str | None,
           hire_date: str | None) -> None:
    conn.execute(
        f"UPDATE teachers SET full_name = ?, phone = ?, hire_date = ?, updated_at = {_NOW} "
        "WHERE id = ?",
        (full_name, phone, hire_date, teacher_id),
    )


def set_status(conn, teacher_id: int, status: str) -> None:
    conn.execute(
        f"UPDATE teachers SET status = ?, updated_at = {_NOW} WHERE id = ?", (status, teacher_id)
    )


def search(conn, folded_terms: list[str], status: str | None, today: str) -> list:
    where, params = [], {"today": today}
    for index, term in enumerate(folded_terms):
        where.append(f"(fold(t.full_name) LIKE :t{index} ESCAPE '\\' "
                     f"OR t.phone LIKE :t{index} ESCAPE '\\')")
        params[f"t{index}"] = term
    if status is not None:
        where.append("t.status = :status")
        params["status"] = status
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    return conn.execute(
        f"""
        SELECT t.id, t.full_name, t.phone, t.status, t.hire_date,
               ({_CURRENT_RATE}) AS current_rate_bp, ({_CURRENT_RATE_FROM}) AS current_rate_from,
               ({_CURRENT_GROUPS}) AS group_count
          FROM teachers t
          {clause}
         ORDER BY fold(t.full_name)
        """,
        params,
    ).fetchall()


def assigned_group_count(conn, teacher_id: int, today: str) -> int:
    """Groups not closed where the teacher teaches now or is planned to take over."""
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT g.id) FROM group_teachers gt
          JOIN class_groups g ON g.id = gt.group_id
         WHERE gt.teacher_id = ? AND g.status <> 'closed'
           AND (gt.valid_to IS NULL OR gt.valid_to > ?)
        """,
        (teacher_id, today),
    ).fetchone()
    return int(row[0])


# ----- rates -----

def rates(conn, teacher_id: int) -> list:
    return conn.execute(
        """
        SELECT id, percentage_bp, valid_from, valid_to FROM teacher_rates
         WHERE teacher_id = ? ORDER BY valid_from DESC
        """,
        (teacher_id,),
    ).fetchall()


def open_rate(conn, teacher_id: int):
    return conn.execute(
        "SELECT id, percentage_bp, valid_from FROM teacher_rates "
        "WHERE teacher_id = ? AND valid_to IS NULL",
        (teacher_id,),
    ).fetchone()


def rate_on(conn, teacher_id: int, on: str) -> int | None:
    row = conn.execute(
        """
        SELECT percentage_bp FROM teacher_rates
         WHERE teacher_id = ? AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)
        """,
        (teacher_id, on, on),
    ).fetchone()
    return None if row is None else int(row[0])


def insert_rate(conn, teacher_id: int, bp: int, valid_from: str) -> int:
    cur = conn.execute(
        "INSERT INTO teacher_rates(teacher_id, percentage_bp, valid_from) VALUES (?, ?, ?)",
        (teacher_id, bp, valid_from),
    )
    return int(cur.lastrowid)


def close_rate(conn, rate_id: int, valid_to: str) -> None:
    conn.execute("UPDATE teacher_rates SET valid_to = ? WHERE id = ?", (valid_to, rate_id))


def correct_rate(conn, rate_id: int, bp: int) -> None:
    conn.execute("UPDATE teacher_rates SET percentage_bp = ? WHERE id = ?", (bp, rate_id))


def first_rate_from(conn, teacher_id: int) -> str | None:
    """The day the teacher's first rate starts (None without any rate)."""
    return conn.execute("SELECT MIN(valid_from) FROM teacher_rates WHERE teacher_id = ?",
                        (teacher_id,)).fetchone()[0]


def move_rate_start(conn, rate_id: int, valid_from: str) -> None:
    conn.execute("UPDATE teacher_rates SET valid_from = ? WHERE id = ?", (valid_from, rate_id))


def has_locked_payout_since(conn, teacher_id: int, since: str) -> bool:
    """An approved or paid payout covering a day on or after `since`."""
    row = conn.execute(
        """
        SELECT 1 FROM teacher_payouts
         WHERE teacher_id = ? AND status <> 'draft' AND period_end >= ?
        """,
        (teacher_id, since),
    ).fetchone()
    return row is not None
