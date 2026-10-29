"""SQL for the WhatsApp group linked to a class group and the parents invited to it."""


def group_code(conn, group_id: int) -> str | None:
    row = conn.execute("SELECT whatsapp_code FROM class_groups WHERE id = ?",
                       (group_id,)).fetchone()
    return row["whatsapp_code"] if row else None


def set_group_code(conn, group_id: int, code: str | None) -> None:
    conn.execute("UPDATE class_groups SET whatsapp_code = ? WHERE id = ?", (code, group_id))


def clear_invites(conn, group_id: int) -> None:
    conn.execute("DELETE FROM whatsapp_invites WHERE group_id = ?", (group_id,))


def add_invite(conn, group_id: int, contact_id: int, on: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO whatsapp_invites(group_id, contact_id, invited_at) "
        "VALUES (?, ?, ?)",
        (group_id, contact_id, on),
    )


def invites(conn, group_id: int) -> dict[int, str]:
    """{contact_id: invited_at} for the group."""
    return {row["contact_id"]: row["invited_at"] for row in conn.execute(
        "SELECT contact_id, invited_at FROM whatsapp_invites WHERE group_id = ?",
        (group_id,))}
