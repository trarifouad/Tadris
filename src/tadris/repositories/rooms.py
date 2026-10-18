"""SQL for rooms."""

# Slots still running or starting later, for groups that are not closed.
_LIVE_SLOTS = """
    SELECT COUNT(*) FROM timetable_slots s JOIN class_groups g ON g.id = s.group_id
     WHERE s.room_id = r.id AND g.status <> 'closed'
       AND (s.valid_to IS NULL OR s.valid_to > ?)
"""


def list_all(conn, today: str) -> list:
    return conn.execute(
        f"""
        SELECT r.id, r.name, r.capacity, r.status, ({_LIVE_SLOTS}) AS slot_count
          FROM rooms r
         ORDER BY r.status, fold(r.name)
        """,
        (today,),
    ).fetchall()


def get(conn, room_id: int):
    return conn.execute(
        "SELECT id, name, capacity, status FROM rooms WHERE id = ?", (room_id,)
    ).fetchone()


def insert(conn, name: str, capacity: int) -> int:
    cur = conn.execute("INSERT INTO rooms(name, capacity) VALUES (?, ?)", (name, capacity))
    return int(cur.lastrowid)


def update(conn, room_id: int, name: str, capacity: int) -> None:
    conn.execute("UPDATE rooms SET name = ?, capacity = ? WHERE id = ?", (name, capacity, room_id))


def set_status(conn, room_id: int, status: str) -> None:
    conn.execute("UPDATE rooms SET status = ? WHERE id = ?", (status, room_id))


def live_slot_count(conn, room_id: int, today: str) -> int:
    row = conn.execute(
        f"SELECT ({_LIVE_SLOTS}) FROM rooms r WHERE r.id = ?", (today, room_id)
    ).fetchone()
    return int(row[0])


def name_taken(conn, name: str, exclude_id: int | None) -> bool:
    row = conn.execute(
        "SELECT 1 FROM rooms WHERE fold(name) = fold(?) AND id IS NOT ?", (name, exclude_id)
    ).fetchone()
    return row is not None
