"""SQL for class groups and their teacher history (half-open [valid_from, valid_to)).

Queries take :today, the service's date. A group's teacher is the one assigned on today, or
on its start date while it has not started: a change planned for later does not show yet.
"""

_NOW = "strftime('%Y-%m-%dT%H:%M:%S','now','localtime')"
_FOREVER = "9999-12-31"

# Running or future slots: their smallest room limits the group's seats.
_LIVE_ROOMS = """
    FROM timetable_slots ts JOIN rooms r ON r.id = ts.room_id
     WHERE ts.group_id = g.id AND (ts.valid_to IS NULL OR ts.valid_to > :today)
     ORDER BY r.capacity LIMIT 1
"""
_COLUMNS = f"""
    g.id, g.school_year_id, y.label AS year_label, y.status AS year_status,
    y.start_date AS year_start, y.end_date AS year_end,
    g.level_id, l.name AS level, g.subject_id, s.name AS subject,
    g.name, g.price, g.capacity, g.start_date, g.status,
    gt.teacher_id, t.full_name AS teacher,
    (SELECT COUNT(*) FROM enrollments e
      WHERE e.group_id = g.id AND e.status IN ('trial', 'active')) AS enrolled,
    (SELECT r.capacity {_LIVE_ROOMS}) AS room_limit,
    (SELECT r.name {_LIVE_ROOMS}) AS limiting_room
"""
# max(:today, g.start_date): today, or the start date of a group that has not started.
_FROM = """
    FROM class_groups g
    JOIN school_years y ON y.id = g.school_year_id
    JOIN levels l ON l.id = g.level_id
    JOIN subjects s ON s.id = g.subject_id
    LEFT JOIN group_teachers gt ON gt.group_id = g.id
          AND gt.valid_from <= max(:today, g.start_date)
          AND (gt.valid_to IS NULL OR gt.valid_to > max(:today, g.start_date))
    LEFT JOIN teachers t ON t.id = gt.teacher_id
"""


def insert(conn, year_id: int, level_id: int, subject_id: int, name: str, price: int,
           capacity: int, start_date: str) -> int:
    cur = conn.execute(
        """
        INSERT INTO class_groups(school_year_id, level_id, subject_id, name, price, capacity,
                                 start_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (year_id, level_id, subject_id, name, price, capacity, start_date),
    )
    return int(cur.lastrowid)


def get(conn, group_id: int, today: str):
    return conn.execute(f"SELECT {_COLUMNS} {_FROM} WHERE g.id = :id",
                        {"id": group_id, "today": today}).fetchone()


def search(conn, today: str, year_id: int | None, level_id: int | None,
           subject_id: int | None, teacher_id: int | None, status: str | None,
           folded_term: str | None) -> list:
    where, params = [], {"today": today}
    for column, name, value in (("g.school_year_id", "year", year_id),
                                ("g.level_id", "level", level_id),
                                ("g.subject_id", "subject", subject_id),
                                ("gt.teacher_id", "teacher", teacher_id),
                                ("g.status", "status", status)):
        if value is not None:
            where.append(f"{column} = :{name}")
            params[name] = value
    if folded_term:
        where.append(
            "(fold(g.name) LIKE :term ESCAPE '\\' OR fold(s.name) LIKE :term ESCAPE '\\' "
            "OR fold(l.name) LIKE :term ESCAPE '\\' OR fold(t.full_name) LIKE :term ESCAPE '\\')"
        )
        params["term"] = folded_term
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    return conn.execute(
        f"""
        SELECT {_COLUMNS} {_FROM} {clause}
         ORDER BY g.status = 'closed', l.order_index, fold(s.name), fold(g.name)
        """,
        params,
    ).fetchall()


def update(conn, group_id: int, level_id: int, subject_id: int, name: str, price: int,
           capacity: int, start_date: str) -> None:
    conn.execute(
        f"""
        UPDATE class_groups
           SET level_id = ?, subject_id = ?, name = ?, price = ?, capacity = ?, start_date = ?,
               updated_at = {_NOW}
         WHERE id = ?
        """,
        (level_id, subject_id, name, price, capacity, start_date, group_id),
    )


def set_status(conn, group_id: int, status: str) -> None:
    conn.execute(
        f"UPDATE class_groups SET status = ?, updated_at = {_NOW} WHERE id = ?",
        (status, group_id),
    )


def name_taken(conn, year_id: int, name: str, exclude_id: int | None) -> bool:
    row = conn.execute(
        "SELECT 1 FROM class_groups "
        "WHERE school_year_id = ? AND fold(name) = fold(?) AND id IS NOT ?",
        (year_id, name, exclude_id),
    ).fetchone()
    return row is not None


def enrollment_count(conn, group_id: int) -> int:
    """Every enrollment ever made in the group, whatever its status."""
    row = conn.execute("SELECT COUNT(*) FROM enrollments WHERE group_id = ?", (group_id,)).fetchone()
    return int(row[0])


# ----- teacher history -----

def teacher_history(conn, group_id: int) -> list:
    return conn.execute(
        """
        SELECT gt.id, gt.teacher_id, t.full_name AS teacher, gt.valid_from, gt.valid_to
          FROM group_teachers gt JOIN teachers t ON t.id = gt.teacher_id
         WHERE gt.group_id = ? ORDER BY gt.valid_from DESC
        """,
        (group_id,),
    ).fetchall()


def teacher_rows_between(conn, group_id: int, valid_from: str, valid_to: str | None) -> list:
    """The group's teacher periods that share at least a day with [valid_from, valid_to)."""
    return conn.execute(
        f"""
        SELECT id, teacher_id, valid_from, valid_to FROM group_teachers
         WHERE group_id = ? AND valid_from < ? AND COALESCE(valid_to, '{_FOREVER}') > ?
         ORDER BY valid_from
        """,
        (group_id, valid_to or _FOREVER, valid_from),
    ).fetchall()


def first_teacher_row(conn, group_id: int):
    return conn.execute(
        "SELECT id, teacher_id, valid_from, valid_to FROM group_teachers "
        "WHERE group_id = ? ORDER BY valid_from LIMIT 1",
        (group_id,),
    ).fetchone()


def open_teacher_row(conn, group_id: int):
    return conn.execute(
        "SELECT id, teacher_id, valid_from FROM group_teachers "
        "WHERE group_id = ? AND valid_to IS NULL",
        (group_id,),
    ).fetchone()


def insert_teacher_row(conn, group_id: int, teacher_id: int, valid_from: str) -> int:
    cur = conn.execute(
        "INSERT INTO group_teachers(group_id, teacher_id, valid_from) VALUES (?, ?, ?)",
        (group_id, teacher_id, valid_from),
    )
    return int(cur.lastrowid)


def close_teacher_row(conn, row_id: int, valid_to: str) -> None:
    conn.execute("UPDATE group_teachers SET valid_to = ? WHERE id = ?", (valid_to, row_id))


def correct_teacher_row(conn, row_id: int, teacher_id: int) -> None:
    conn.execute("UPDATE group_teachers SET teacher_id = ? WHERE id = ?", (teacher_id, row_id))


def move_teacher_row_start(conn, row_id: int, valid_from: str) -> None:
    conn.execute("UPDATE group_teachers SET valid_from = ? WHERE id = ?", (valid_from, row_id))


def teacher_paid_for_group(conn, group_id: int, teacher_id: int) -> bool:
    """The teacher has payout lines for this group in an approved or paid payout."""
    row = conn.execute(
        """
        SELECT 1 FROM payout_lines l JOIN teacher_payouts p ON p.id = l.payout_id
         WHERE l.group_id = ? AND p.teacher_id = ? AND p.status <> 'draft'
        """,
        (group_id, teacher_id),
    ).fetchone()
    return row is not None
