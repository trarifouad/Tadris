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
    order_col = "order_index" if kind == "level" else "0 AS order_index"
    return conn.execute(
        f"""
        SELECT t.id, t.name, t.is_active, {order_col},
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
