"""SQL for sessions: one meeting of a group on a date, generated from a timetable slot or
added by hand (makeup). Status planned, held or cancelled.

A *pending* session is a forecast of the timetable: generated, still planned, dated today or
later, with no attendance taken. Pending sessions are discarded and generated again when the
timetable, a teacher or the holidays change; every other session is kept as history.
"""

_PENDING = """
    s.date >= :today AND s.status = 'planned' AND s.source = 'generated'
    AND NOT EXISTS (SELECT 1 FROM attendances a WHERE a.session_id = s.id)
"""


def slots_on(conn, day: str, weekday: int) -> list:
    """Slots meeting on a day: valid then, right weekday, open group, within its year."""
    return conn.execute(
        """
        SELECT ts.id, ts.group_id, ts.room_id, ts.start_time, ts.end_time
          FROM timetable_slots ts
          JOIN class_groups g ON g.id = ts.group_id
          JOIN school_years y ON y.id = g.school_year_id
         WHERE ts.weekday = :weekday AND ts.valid_from <= :day
           AND (ts.valid_to IS NULL OR ts.valid_to > :day)
           AND g.status <> 'closed' AND g.start_date <= :day AND y.end_date >= :day
         ORDER BY ts.start_time, ts.id
        """,
        {"day": day, "weekday": weekday},
    ).fetchall()


def scheduled_teacher(conn, group_id: int, day: str) -> int | None:
    """The group's teacher on that day (half-open teacher periods)."""
    row = conn.execute(
        "SELECT teacher_id FROM group_teachers WHERE group_id = ? AND valid_from <= ? "
        "AND (valid_to IS NULL OR valid_to > ?)",
        (group_id, day, day),
    ).fetchone()
    return None if row is None else row[0]


def exists_for_slot(conn, slot_id: int, day: str) -> bool:
    """Any session of the slot that day, cancelled ones included (unique slot and date)."""
    row = conn.execute("SELECT 1 FROM sessions WHERE slot_id = ? AND date = ?",
                       (slot_id, day)).fetchone()
    return row is not None


def insert_generated(conn, group_id: int, slot_id: int, room_id: int, teacher_id: int,
                     day: str, start_time: str, end_time: str) -> int:
    cur = conn.execute(
        """
        INSERT INTO sessions(group_id, slot_id, room_id, teacher_id, date, start_time,
                             end_time, status, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'planned', 'generated')
        """,
        (group_id, slot_id, room_id, teacher_id, day, start_time, end_time),
    )
    return int(cur.lastrowid)


def discard_pending(conn, today: str, slot_id: int | None = None,
                    group_id: int | None = None, from_date: str | None = None,
                    days: list[str] | None = None, teacher_id: int | None = None) -> int:
    """Delete pending sessions matching every given filter. Returns how many."""
    where, params = [_PENDING], {"today": today}
    for column, name, value in (("s.slot_id", "slot", slot_id),
                                ("s.group_id", "group", group_id),
                                ("s.teacher_id", "teacher", teacher_id)):
        if value is not None:
            where.append(f"{column} = :{name}")
            params[name] = value
    if from_date is not None:
        where.append("s.date >= :from_date")
        params["from_date"] = from_date
    if days is not None:
        if not days:
            return 0
        marks = ", ".join(f":d{i}" for i in range(len(days)))
        where.append(f"s.date IN ({marks})")
        params.update({f"d{i}": day for i, day in enumerate(days)})
    cur = conn.execute(f"DELETE FROM sessions AS s WHERE {' AND '.join(where)}", params)
    return cur.rowcount


def kept_count(conn, slot_id: int, today: str) -> int:
    """The slot's sessions that are history, not a forecast (see the module docstring)."""
    row = conn.execute(
        f"SELECT COUNT(*) FROM sessions s WHERE s.slot_id = :slot AND NOT ({_PENDING})",
        {"slot": slot_id, "today": today},
    ).fetchone()
    return int(row[0])


def between(conn, first: str, last: str) -> list:
    """Sessions in [first, last], for reading back (tests, lists in later tasks)."""
    return conn.execute(
        "SELECT * FROM sessions WHERE date BETWEEN ? AND ? ORDER BY date, start_time, id",
        (first, last),
    ).fetchall()


# ----- reading and changing one session -----

_NOW = "strftime('%Y-%m-%dT%H:%M:%S','now','localtime')"
_COLUMNS = """
    s.id, s.group_id, g.name AS group_name, sb.name AS subject, l.name AS level,
    g.status AS group_status, s.slot_id, s.room_id, r.name AS room, s.teacher_id,
    t.full_name AS teacher,
    (SELECT gt.teacher_id FROM group_teachers gt
      WHERE gt.group_id = s.group_id AND gt.valid_from <= s.date
        AND (gt.valid_to IS NULL OR gt.valid_to > s.date)) AS scheduled_teacher_id,
    s.makeup_of_session_id, s.date, s.start_time, s.end_time, s.status, s.source,
    s.cancellation_reason,
    (SELECT m.id FROM sessions m WHERE m.makeup_of_session_id = s.id
      AND m.status <> 'cancelled' ORDER BY m.id DESC LIMIT 1) AS makeup_id,
    (SELECT m.date FROM sessions m WHERE m.makeup_of_session_id = s.id
      AND m.status <> 'cancelled' ORDER BY m.id DESC LIMIT 1) AS makeup_date,
    (SELECT o.date FROM sessions o WHERE o.id = s.makeup_of_session_id) AS makeup_of_date,
    (SELECT COUNT(*) FROM attendances a WHERE a.session_id = s.id) AS attendance_count,
    (SELECT COUNT(*) FROM enrollments e WHERE e.group_id = s.group_id
        AND e.enrolled_on <= s.date AND (e.left_on IS NULL OR e.left_on >= s.date)) AS expected
"""
_FROM = """
    FROM sessions s
    JOIN class_groups g ON g.id = s.group_id
    JOIN subjects sb ON sb.id = g.subject_id
    JOIN levels l ON l.id = g.level_id
    JOIN rooms r ON r.id = s.room_id
    JOIN teachers t ON t.id = s.teacher_id
"""


def get(conn, session_id: int):
    return conn.execute(f"SELECT {_COLUMNS} {_FROM} WHERE s.id = ?", (session_id,)).fetchone()


def listing(conn, first: str, last: str, group_id: int | None = None,
            teacher_id: int | None = None, room_id: int | None = None) -> list:
    """Sessions in [first, last], by date and time, optionally for one group, teacher, room."""
    where, params = ["s.date BETWEEN :first AND :last"], {"first": first, "last": last}
    for column, name, value in (("s.group_id", "group", group_id),
                                ("s.teacher_id", "teacher", teacher_id),
                                ("s.room_id", "room", room_id)):
        if value is not None:
            where.append(f"{column} = :{name}")
            params[name] = value
    return conn.execute(
        f"SELECT {_COLUMNS} {_FROM} WHERE {' AND '.join(where)} "
        "ORDER BY s.date, s.start_time, r.name",
        params,
    ).fetchall()


def cancel(conn, session_id: int, reason: str) -> None:
    conn.execute(
        f"UPDATE sessions SET status = 'cancelled', cancellation_reason = ?, updated_at = {_NOW} "
        "WHERE id = ?",
        (reason, session_id),
    )


def restore(conn, session_id: int) -> None:
    conn.execute(
        f"UPDATE sessions SET status = 'planned', cancellation_reason = NULL, updated_at = {_NOW} "
        "WHERE id = ?",
        (session_id,),
    )


def set_teacher(conn, session_id: int, teacher_id: int) -> None:
    conn.execute(f"UPDATE sessions SET teacher_id = ?, updated_at = {_NOW} WHERE id = ?",
                 (teacher_id, session_id))


def insert_makeup(conn, of_session_id: int, group_id: int, room_id: int, teacher_id: int,
                  day: str, start_time: str, end_time: str) -> int:
    cur = conn.execute(
        """
        INSERT INTO sessions(group_id, room_id, teacher_id, makeup_of_session_id, date,
                             start_time, end_time, status, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'planned', 'makeup')
        """,
        (group_id, room_id, teacher_id, of_session_id, day, start_time, end_time),
    )
    return int(cur.lastrowid)


# ----- clashes on a date (cancelled sessions free their room, teacher and group) -----

_SAME_TIME = """
    x.date = :day AND x.status <> 'cancelled' AND x.start_time < :end AND x.end_time > :start
    AND x.id IS NOT :exclude
"""
_CLASH_COLUMNS = """
    x.id, x.date, x.start_time, x.end_time, g.name AS "group", r.name AS room,
    t.full_name AS teacher
"""
_CLASH_FROM = """
    FROM sessions x
    JOIN class_groups g ON g.id = x.group_id
    JOIN rooms r ON r.id = x.room_id
    JOIN teachers t ON t.id = x.teacher_id
"""


def _clash(conn, condition: str, params: dict):
    return conn.execute(
        f"SELECT {_CLASH_COLUMNS} {_CLASH_FROM} WHERE {condition} AND {_SAME_TIME} "
        "ORDER BY x.start_time LIMIT 1",
        params,
    ).fetchone()


def room_clash(conn, room_id, day, start, end, exclude_id=None):
    return _clash(conn, "x.room_id = :room", {"room": room_id, "day": day, "start": start,
                                              "end": end, "exclude": exclude_id})


def teacher_clash(conn, teacher_id, day, start, end, exclude_id=None):
    return _clash(conn, "x.teacher_id = :teacher", {"teacher": teacher_id, "day": day,
                                                    "start": start, "end": end,
                                                    "exclude": exclude_id})


def group_clash(conn, group_id, day, start, end, exclude_id=None):
    return _clash(conn, "x.group_id = :group", {"group": group_id, "day": day, "start": start,
                                                "end": end, "exclude": exclude_id})


def students_clash(conn, group_id, day, start, end) -> list:
    """Sessions of other groups at that time where a student of the group (enrolled on that
    day) is also enrolled, with the student's name."""
    return conn.execute(
        f"""
        SELECT {_CLASH_COLUMNS}, mine.student_id,
               st.last_name || ' ' || st.first_name AS student
          {_CLASH_FROM}
          JOIN enrollments other ON other.group_id = x.group_id
          JOIN enrollments mine ON mine.student_id = other.student_id AND mine.group_id = :group
          JOIN students st ON st.id = mine.student_id
         WHERE x.group_id <> :group AND {_SAME_TIME}
           AND mine.enrolled_on <= :day AND (mine.left_on IS NULL OR mine.left_on >= :day)
           AND other.enrolled_on <= :day AND (other.left_on IS NULL OR other.left_on >= :day)
         ORDER BY fold(st.last_name), fold(st.first_name)
        """,
        {"group": group_id, "day": day, "start": start, "end": end, "exclude": None},
    ).fetchall()


def enrolled_on(conn, group_id: int, day: str) -> int:
    """Students in the group on that day (trial or paid)."""
    row = conn.execute(
        "SELECT COUNT(*) FROM enrollments WHERE group_id = ? AND enrolled_on <= ? "
        "AND (left_on IS NULL OR left_on >= ?)",
        (group_id, day, day),
    ).fetchone()
    return int(row[0])


def cancel_future_of_group(conn, group_id: int, today: str, reason: str) -> list[int]:
    """The group closes: its future planned sessions made by hand (makeups) are cancelled.
    Returns their ids."""
    ids = [int(row[0]) for row in conn.execute(
        "SELECT id FROM sessions s WHERE s.group_id = ? AND s.date >= ? AND s.status = 'planned' "
        "AND NOT EXISTS (SELECT 1 FROM attendances a WHERE a.session_id = s.id)",
        (group_id, today))]
    for session_id in ids:
        cancel(conn, session_id, reason)
    return ids
