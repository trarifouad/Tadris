"""SQL for enrollments: a student in a group, under the registration of the group's year.

Live enrollments are those in status trial or active. One live enrollment per student and
group (unique index); one trial per student, ever (unique index on started_as_trial).
"""

_NOW = "strftime('%Y-%m-%dT%H:%M:%S','now','localtime')"


def on_day(alias: str = "e", day: str = "s.date") -> str:
    """The place is in the group that calendar day: entered on or before it, not left
    before it, and not a place that ended before it ever started."""
    return (f"{alias}.enrolled_on <= {day} AND ({alias}.left_on IS NULL OR {alias}.left_on >= {day})"
            f" AND {alias}.never_started = 0")


_COLUMNS = """
    e.id, e.student_id, st.student_number, st.last_name, st.first_name,
    e.group_id, g.name AS group_name, sb.name AS subject, gl.name AS group_level,
    gl.is_open AS group_level_open,
    g.school_year_id, e.registration_id, rl.name AS registration_level,
    e.status, e.started_as_trial, e.enrolled_on, e.left_on, e.switched_from_id,
    e.never_started
"""
_FROM = """
    FROM enrollments e
    JOIN students st ON st.id = e.student_id
    JOIN class_groups g ON g.id = e.group_id
    JOIN subjects sb ON sb.id = g.subject_id
    JOIN levels gl ON gl.id = g.level_id
    JOIN registrations r ON r.id = e.registration_id
    JOIN levels rl ON rl.id = r.level_id
"""
# Live first, then the latest entry.
_ORDER = "e.status NOT IN ('trial', 'active'), e.enrolled_on DESC, e.id DESC"


def get(conn, enrollment_id: int):
    return conn.execute(f"SELECT {_COLUMNS} {_FROM} WHERE e.id = ?",
                        (enrollment_id,)).fetchone()


def for_student(conn, student_id: int) -> list:
    return conn.execute(f"SELECT {_COLUMNS} {_FROM} WHERE e.student_id = ? ORDER BY {_ORDER}",
                        (student_id,)).fetchall()


def for_group(conn, group_id: int) -> list:
    return conn.execute(
        f"SELECT {_COLUMNS} {_FROM} WHERE e.group_id = ? "
        "ORDER BY e.status NOT IN ('trial', 'active'), fold(st.last_name), fold(st.first_name)",
        (group_id,),
    ).fetchall()


def live_in_group(conn, student_id: int, group_id: int):
    return conn.execute(
        "SELECT id FROM enrollments WHERE student_id = ? AND group_id = ? "
        "AND status IN ('trial', 'active')",
        (student_id, group_id),
    ).fetchone()


def live_in_subject(conn, student_id: int, subject_id: int, level_id: int, group_id: int):
    """Another group of the same subject and level the student is in (trial or active)."""
    return conn.execute(
        """
        SELECT g.id, g.name FROM enrollments e JOIN class_groups g ON g.id = e.group_id
         WHERE e.student_id = ? AND e.status IN ('trial', 'active')
           AND g.subject_id = ? AND g.level_id = ? AND g.id <> ?
         LIMIT 1
        """,
        (student_id, subject_id, level_id, group_id),
    ).fetchone()


def candidates(conn, group_id: int) -> list:
    """The active students registered in the group's year at its level (any level for an open
    level) and not in it now, by name; whether they had their trial, and whether they are in
    another group of its subject and level."""
    return conn.execute(
        """
        SELECT st.id AS student_id, st.student_number, st.last_name, st.first_name,
               rl.name AS level,
               EXISTS (SELECT 1 FROM enrollments t
                        WHERE t.student_id = st.id AND t.started_as_trial = 1) AS had_trial,
               EXISTS (SELECT 1 FROM enrollments o JOIN class_groups og ON og.id = o.group_id
                        WHERE o.student_id = st.id AND o.status IN ('trial', 'active')
                          AND og.subject_id = g.subject_id AND og.level_id = g.level_id
                          AND og.id <> g.id) AS same_subject
          FROM class_groups g
          JOIN levels gl ON gl.id = g.level_id
          JOIN registrations r ON r.school_year_id = g.school_year_id AND r.status = 'active'
                              AND (r.level_id = g.level_id OR gl.is_open = 1)
          JOIN levels rl ON rl.id = r.level_id
          JOIN students st ON st.id = r.student_id AND st.status = 'active'
         WHERE g.id = ?
           AND NOT EXISTS (SELECT 1 FROM enrollments e
                            WHERE e.student_id = st.id AND e.group_id = g.id
                              AND e.status IN ('trial', 'active'))
         ORDER BY fold(st.last_name), fold(st.first_name), st.id
        """,
        (group_id,),
    ).fetchall()


def had_trial(conn, student_id: int) -> bool:
    row = conn.execute("SELECT 1 FROM enrollments WHERE student_id = ? AND started_as_trial = 1",
                       (student_id,)).fetchone()
    return row is not None


def insert(conn, student_id: int, group_id: int, registration_id: int, enrolled_on: str,
           status: str, started_as_trial: bool, switched_from_id: int | None = None) -> int:
    cur = conn.execute(
        """
        INSERT INTO enrollments(student_id, group_id, registration_id, enrolled_on, status,
                                started_as_trial, switched_from_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (student_id, group_id, registration_id, enrolled_on, status, int(started_as_trial),
         switched_from_id),
    )
    return int(cur.lastrowid)


def set_status(conn, enrollment_id: int, status: str) -> None:
    conn.execute(f"UPDATE enrollments SET status = ?, updated_at = {_NOW} WHERE id = ?",
                 (status, enrollment_id))


def end(conn, enrollment_id: int, status: str, left_on: str,
        never_started: bool = False) -> None:
    """status 'left' or 'switched'."""
    conn.execute(
        f"""
        UPDATE enrollments SET status = ?, left_on = ?, never_started = ?,
                               updated_at = {_NOW} WHERE id = ?
        """,
        (status, left_on, int(never_started), enrollment_id),
    )


def end_live_for_group(conn, group_id: int, on: str, closure_id: int) -> list[int]:
    """Every live enrollment of the group leaves on `on`, or on its entry date if later (a
    group closed before it started), ended by that closure. Returns their ids."""
    ids = [int(row[0]) for row in conn.execute(
        "SELECT id FROM enrollments WHERE group_id = ? AND status IN ('trial', 'active')",
        (group_id,))]
    conn.execute(
        f"""
        UPDATE enrollments SET status = 'left', left_on = max(?, enrolled_on), closure_id = ?,
                               never_started = CASE WHEN enrolled_on > ? THEN 1 ELSE 0 END,
                               updated_at = {_NOW}
         WHERE group_id = ? AND status IN ('trial', 'active')
        """,
        (on, closure_id, on, group_id),
    )
    return ids


def last_attendance_date(conn, enrollment_id: int) -> str | None:
    row = conn.execute(
        "SELECT MAX(s.date) FROM attendances a JOIN sessions s ON s.id = a.session_id "
        "WHERE a.enrollment_id = ?",
        (enrollment_id,),
    ).fetchone()
    return row[0]
