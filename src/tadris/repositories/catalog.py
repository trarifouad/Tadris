"""SQL for the named reference lists: levels (ordered) and subjects.

Both tables have the same shape, so one module serves them. The table name always comes
from TABLES, never from user input.
"""

TABLES = {"level": "levels", "subject": "subjects"}
_GROUP_COLUMN = {"level": "level_id", "subject": "subject_id"}


def _table(kind: str) -> str:
    return TABLES[kind]


def list_all(conn, kind: str) -> list:
    order = "order_index, name" if kind == "level" else "name"
    level_cols = ("order_index, is_open, 0 AS is_workshop" if kind == "level"
                  else "0 AS order_index, 0 AS is_open, is_workshop")
    return conn.execute(
        f"""
        SELECT t.id, t.name, t.is_active, {level_cols},
               (SELECT COUNT(*) FROM class_groups g
                 WHERE g.{_GROUP_COLUMN[kind]} = t.id AND g.status <> 'closed') AS group_count
          FROM {_table(kind)} t
         ORDER BY {order}
        """
    ).fetchall()


def get(conn, kind: str, item_id: int):
    return conn.execute(f"SELECT * FROM {_table(kind)} WHERE id = ?", (item_id,)).fetchone()


def insert(conn, kind: str, name: str) -> int:
    if kind == "level":
        cur = conn.execute(
            "INSERT INTO levels(name, order_index) "
            "VALUES (?, (SELECT COALESCE(MAX(order_index), 0) + 1 FROM levels))",
            (name,),
        )
    else:
        cur = conn.execute("INSERT INTO subjects(name) VALUES (?)", (name,))
    return int(cur.lastrowid)


def rename(conn, kind: str, item_id: int, name: str) -> None:
    conn.execute(f"UPDATE {_table(kind)} SET name = ? WHERE id = ?", (name, item_id))


def set_active(conn, kind: str, item_id: int, active: bool) -> None:
    conn.execute(f"UPDATE {_table(kind)} SET is_active = ? WHERE id = ?", (int(active), item_id))


def set_open(conn, level_id: int, is_open: bool) -> None:
    """Levels only: open the level's groups to students of every level, or not."""
    conn.execute("UPDATE levels SET is_open = ? WHERE id = ?", (int(is_open), level_id))


def set_workshop(conn, subject_id: int, is_workshop: bool) -> None:
    """Subjects only: a workshop is offered for the groups of an open level."""
    conn.execute("UPDATE subjects SET is_workshop = ? WHERE id = ?",
                 (int(is_workshop), subject_id))


def other_level_students(conn, level_id: int) -> int:
    """Levels only: students of another level live in the level's groups (an open level)."""
    return conn.execute(
        """
        SELECT COUNT(DISTINCT e.student_id) FROM enrollments e
          JOIN class_groups g ON g.id = e.group_id
          JOIN registrations r ON r.id = e.registration_id
         WHERE g.level_id = ? AND r.level_id <> g.level_id AND e.status IN ('trial', 'active')
        """,
        (level_id,),
    ).fetchone()[0]


def set_order(conn, ordered_ids: list[int]) -> None:
    """Levels only: rewrite order_index as 1..n following ordered_ids."""
    conn.executemany(
        "UPDATE levels SET order_index = ? WHERE id = ?",
        [(position, level_id) for position, level_id in enumerate(ordered_ids, start=1)],
    )


def name_taken(conn, kind: str, name: str, exclude_id: int | None) -> bool:
    row = conn.execute(
        f"SELECT 1 FROM {_table(kind)} WHERE fold(name) = fold(?) AND id IS NOT ?",
        (name, exclude_id),
    ).fetchone()
    return row is not None
