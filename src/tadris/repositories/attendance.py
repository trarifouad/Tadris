"""SQL for attendance: one status per student (enrollment) and session.

A session's students are the group's enrollments valid on its date: entered on or before it,
and not left before it (left_on is the last day, included).
"""

_NOW = "strftime('%Y-%m-%dT%H:%M:%S','now','localtime')"


def roster(conn, session_id: int) -> list:
    """The session's students, by name, with their recorded status (or NULL) and whether no
    month covers the date (paid enrollments only)."""
    return conn.execute(
        """
        SELECT e.id AS enrollment_id, e.student_id, st.student_number, st.last_name,
               st.first_name, e.status AS enrollment_status, a.status,
               (e.status <> 'trial' AND NOT EXISTS (
                   SELECT 1 FROM subscriptions sub
                    WHERE sub.enrollment_id = e.id AND sub.status <> 'cancelled'
                      AND sub.start_date <= s.date AND sub.end_date > s.date)) AS not_renewed
          FROM sessions s
          JOIN enrollments e ON e.group_id = s.group_id
                            AND e.enrolled_on <= s.date
                            AND (e.left_on IS NULL OR e.left_on >= s.date)
          JOIN students st ON st.id = e.student_id
          LEFT JOIN attendances a ON a.session_id = s.id AND a.enrollment_id = e.id
         WHERE s.id = ?
         ORDER BY fold(st.last_name), fold(st.first_name)
        """,
        (session_id,),
    ).fetchall()


def statuses(conn, session_id: int) -> dict[int, str]:
    return {row[0]: row[1] for row in conn.execute(
        "SELECT enrollment_id, status FROM attendances WHERE session_id = ?", (session_id,))}


def insert(conn, session_id: int, enrollment_id: int, status: str, user_id: int) -> None:
    conn.execute(
        "INSERT INTO attendances(session_id, enrollment_id, status, entered_by) "
        "VALUES (?, ?, ?, ?)",
        (session_id, enrollment_id, status, user_id),
    )


def update(conn, session_id: int, enrollment_id: int, status: str, user_id: int) -> None:
    conn.execute(
        f"UPDATE attendances SET status = ?, entered_by = ?, updated_at = {_NOW} "
        "WHERE session_id = ? AND enrollment_id = ?",
        (status, user_id, session_id, enrollment_id),
    )


def mark_held(conn, session_id: int) -> None:
    conn.execute(
        f"UPDATE sessions SET status = 'held', updated_at = {_NOW} "
        "WHERE id = ? AND status = 'planned'",
        (session_id,),
    )


def for_student(conn, student_id: int) -> list:
    """The student's recorded attendance, latest first."""
    return conn.execute(
        """
        SELECT a.session_id, s.date, s.start_time, s.end_time, g.name AS group_name,
               sb.name AS subject, l.name AS level, e.group_id, a.status
          FROM attendances a
          JOIN sessions s ON s.id = a.session_id
          JOIN enrollments e ON e.id = a.enrollment_id
          JOIN class_groups g ON g.id = e.group_id
          JOIN subjects sb ON sb.id = g.subject_id
          JOIN levels l ON l.id = g.level_id
         WHERE e.student_id = ?
         ORDER BY s.date DESC, s.start_time DESC
        """,
        (student_id,),
    ).fetchall()
