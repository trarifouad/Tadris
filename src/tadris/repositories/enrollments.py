"""SQL for enrollments: a student in a group, under the registration of the group's year.

Live enrollments are those in status trial or active. One live enrollment per student and
group (unique index); one trial per student, ever (unique index on started_as_trial).
"""

_NOW = "strftime('%Y-%m-%dT%H:%M:%S','now','localtime')"

_COLUMNS = """
    e.id, e.student_id, st.student_number, st.last_name, st.first_name,
    e.group_id, g.name AS group_name, sb.name AS subject, gl.name AS group_level,
    g.school_year_id, e.registration_id, rl.name AS registration_level,
    e.status, e.started_as_trial, e.enrolled_on, e.left_on, e.switched_from_id
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


def end(conn, enrollment_id: int, status: str, left_on: str) -> None:
    """status 'left' or 'switched'."""
    conn.execute(
        f"UPDATE enrollments SET status = ?, left_on = ?, updated_at = {_NOW} WHERE id = ?",
        (status, left_on, enrollment_id),
    )


def end_live_for_group(conn, group_id: int, on: str) -> list[int]:
    """Every live enrollment of the group leaves on `on`, or on its entry date if later (a
    group closed before it started). Returns their ids."""
    ids = [int(row[0]) for row in conn.execute(
        "SELECT id FROM enrollments WHERE group_id = ? AND status IN ('trial', 'active')",
        (group_id,))]
    conn.execute(
        f"""
        UPDATE enrollments SET status = 'left', left_on = max(?, enrolled_on), updated_at = {_NOW}
         WHERE group_id = ? AND status IN ('trial', 'active')
        """,
        (on, group_id),
    )
    return ids


def last_attendance_date(conn, enrollment_id: int) -> str | None:
    row = conn.execute(
        "SELECT MAX(s.date) FROM attendances a JOIN sessions s ON s.id = a.session_id "
        "WHERE a.enrollment_id = ?",
        (enrollment_id,),
    ).fetchone()
    return row[0]
