"""SQL for weekly timetable slots. Validity is half-open [valid_from, valid_to).

Each slot row shows the group's teacher on :on, or on the slot's first day if it starts
later: a teacher change planned for later does not show before its date.
"""

_FOREVER = "9999-12-31"

_COLUMNS = """
    s.id, s.group_id, g.name AS "group", l.name AS level, sj.name AS subject,
    s.room_id, r.name AS room, gt.teacher_id, t.full_name AS teacher,
    s.weekday, s.start_time, s.end_time, s.valid_from, s.valid_to
"""
_GROUP_ROOM = """
    FROM timetable_slots s
    JOIN class_groups g ON g.id = s.group_id
    JOIN levels l ON l.id = g.level_id
    JOIN subjects sj ON sj.id = g.subject_id
    JOIN rooms r ON r.id = s.room_id
"""
_FROM = _GROUP_ROOM + """
    LEFT JOIN group_teachers gt ON gt.group_id = g.id
          AND gt.valid_from <= max(:on, s.valid_from)
          AND (gt.valid_to IS NULL OR gt.valid_to > max(:on, s.valid_from))
    LEFT JOIN teachers t ON t.id = gt.teacher_id
"""
# Same weekday, overlapping times and overlapping validity with [:from, :to).
_CLASH = f"""
    s.weekday = :weekday AND s.start_time < :end AND s.end_time > :start
    AND s.valid_from < :to AND COALESCE(s.valid_to, '{_FOREVER}') > :from
    AND s.id IS NOT :exclude
"""


def insert(conn, group_id: int, room_id: int, weekday: int, start_time: str, end_time: str,
           valid_from: str) -> int:
    cur = conn.execute(
        """
        INSERT INTO timetable_slots(group_id, room_id, weekday, start_time, end_time, valid_from)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (group_id, room_id, weekday, start_time, end_time, valid_from),
    )
    return int(cur.lastrowid)


def get(conn, slot_id: int, today: str):
    return conn.execute(f"SELECT {_COLUMNS} {_FROM} WHERE s.id = :id",
                        {"id": slot_id, "on": today}).fetchone()


def update(conn, slot_id: int, room_id: int, weekday: int, start_time: str,
           end_time: str) -> None:
    conn.execute(
        """
        UPDATE timetable_slots SET room_id = ?, weekday = ?, start_time = ?, end_time = ?
         WHERE id = ?
        """,
        (room_id, weekday, start_time, end_time, slot_id),
    )


def end(conn, slot_id: int, valid_to: str) -> None:
    conn.execute("UPDATE timetable_slots SET valid_to = ? WHERE id = ?", (valid_to, slot_id))


def set_valid_from(conn, slot_id: int, valid_from: str) -> None:
    conn.execute("UPDATE timetable_slots SET valid_from = ? WHERE id = ?", (valid_from, slot_id))


def delete(conn, slot_id: int) -> None:
    conn.execute("DELETE FROM timetable_slots WHERE id = ?", (slot_id,))


def valid_on(conn, on: str, room_id: int | None = None, group_id: int | None = None,
             teacher_id: int | None = None) -> list:
    """Slots valid on a date, optionally for one room, group or teacher (on that date).
    A closed group's slots ended when it closed, so past weeks still show them."""
    where = ["s.valid_from <= :on", "(s.valid_to IS NULL OR s.valid_to > :on)"]
    params: dict = {"on": on}
    for column, value in (("s.room_id", room_id), ("s.group_id", group_id),
                          ("gt.teacher_id", teacher_id)):
        if value is not None:
            name = column.split(".")[1]
            where.append(f"{column} = :{name}")
            params[name] = value
    return conn.execute(
        f"""
        SELECT {_COLUMNS} {_FROM}
         WHERE {' AND '.join(where)}
         ORDER BY s.weekday, s.start_time
        """,
        params,
    ).fetchall()


def for_group(conn, group_id: int, today: str) -> list:
    """The group's slots that are running or start later."""
    return conn.execute(
        f"""
        SELECT {_COLUMNS} {_FROM}
         WHERE s.group_id = :group AND (s.valid_to IS NULL OR s.valid_to > :on)
         ORDER BY s.weekday, s.start_time
        """,
        {"group": group_id, "on": today},
    ).fetchall()


def starting_before(conn, group_id: int, start_date: str) -> list:
    """The group's slots that start before a date (its start date moved later)."""
    return conn.execute(
        "SELECT id, valid_from, valid_to FROM timetable_slots "
        "WHERE group_id = ? AND valid_from < ?",
        (group_id, start_date),
    ).fetchall()


def _window(weekday, start_time, end_time, valid_from, valid_to, exclude_id) -> dict:
    return {"weekday": weekday, "start": start_time, "end": end_time, "from": valid_from,
            "to": valid_to or _FOREVER, "exclude": exclude_id}


def room_clash(conn, room_id, weekday, start_time, end_time, valid_from, valid_to, exclude_id,
               today: str):
    return conn.execute(
        f"SELECT {_COLUMNS} {_FROM} WHERE s.room_id = :room AND {_CLASH} LIMIT 1",
        {"room": room_id, "on": today,
         **_window(weekday, start_time, end_time, valid_from, valid_to, exclude_id)},
    ).fetchone()


def group_clash(conn, group_id, weekday, start_time, end_time, valid_from, valid_to,
                exclude_id, today: str):
    return conn.execute(
        f"SELECT {_COLUMNS} {_FROM} WHERE s.group_id = :group AND {_CLASH} LIMIT 1",
        {"group": group_id, "on": today,
         **_window(weekday, start_time, end_time, valid_from, valid_to, exclude_id)},
    ).fetchone()


# ----- students: one student cannot attend two groups at the same time -----

_LIVE = "('trial', 'active')"


def student_busy(conn, student_id, group_id, weekday, start_time, end_time, valid_from,
                 valid_to, today: str):
    """A slot of another group the student is in (trial or active), at the same time."""
    return conn.execute(
        f"""
        SELECT {_COLUMNS} {_FROM}
          JOIN enrollments e ON e.group_id = s.group_id AND e.student_id = :student
                            AND e.status IN {_LIVE}
         WHERE s.group_id <> :group AND {_CLASH} LIMIT 1
        """,
        {"student": student_id, "group": group_id, "on": today,
         **_window(weekday, start_time, end_time, valid_from, valid_to, None)},
    ).fetchone()


def students_busy(conn, group_id, weekday, start_time, end_time, valid_from, valid_to,
                  today: str) -> list:
    """For a slot of the group: the slots of other groups where one of its students (trial or
    active) is also enrolled at the same time, with that student's name."""
    return conn.execute(
        f"""
        SELECT {_COLUMNS}, mine.student_id, st.last_name || ' ' || st.first_name AS student
          {_FROM}
          JOIN enrollments other ON other.group_id = s.group_id AND other.status IN {_LIVE}
          JOIN enrollments mine ON mine.student_id = other.student_id AND mine.group_id = :group
                               AND mine.status IN {_LIVE}
          JOIN students st ON st.id = mine.student_id
         WHERE s.group_id <> :group AND {_CLASH}
         ORDER BY fold(st.last_name), fold(st.first_name)
        """,
        {"group": group_id, "on": today,
         **_window(weekday, start_time, end_time, valid_from, valid_to, None)},
    ).fetchall()


def teacher_clash(conn, teacher_id, group_id, weekday, start_time, end_time, valid_from,
                  valid_to, exclude_id):
    """A slot of another open group that the teacher teaches at the same time, on a day of
    [valid_from, valid_to). The slot, the teacher's period in that group and the window
    overlap pairwise, so (intervals on a line) they share a day."""
    return conn.execute(
        f"""
        SELECT s.id, s.group_id, g.name AS "group", l.name AS level, sj.name AS subject,
               s.room_id, r.name AS room, a.teacher_id, t.full_name AS teacher,
               s.weekday, s.start_time, s.end_time, s.valid_from, s.valid_to
          {_GROUP_ROOM}
          JOIN group_teachers a ON a.group_id = s.group_id AND a.teacher_id = :teacher
          JOIN teachers t ON t.id = a.teacher_id
         WHERE s.group_id <> :group AND g.status <> 'closed' AND {_CLASH}
           AND a.valid_from < :to AND COALESCE(a.valid_to, '{_FOREVER}') > :from
           AND a.valid_from < COALESCE(s.valid_to, '{_FOREVER}')
           AND COALESCE(a.valid_to, '{_FOREVER}') > s.valid_from
         LIMIT 1
        """,
        {"teacher": teacher_id, "group": group_id,
         **_window(weekday, start_time, end_time, valid_from, valid_to, exclude_id)},
    ).fetchone()


def outside_hours(conn, opens_at: str, closes_at: str, today: str) -> list:
    """Running or future slots of open groups that start before opening or end after
    closing."""
    return conn.execute(
        f"""
        SELECT {_COLUMNS} {_FROM}
         WHERE g.status <> 'closed' AND (s.valid_to IS NULL OR s.valid_to > :on)
           AND (s.start_time < :opens OR s.end_time > :closes)
         ORDER BY s.weekday, s.start_time
        """,
        {"on": today, "opens": opens_at, "closes": closes_at},
    ).fetchall()
