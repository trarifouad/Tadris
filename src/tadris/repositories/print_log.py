"""SQL for the print log: what was printed, by whom, when."""


def insert(conn, document_type: str, document_id: int, user_id: int) -> int:
    cur = conn.execute(
        "INSERT INTO print_log(document_type, document_id, printed_by) VALUES (?, ?, ?)",
        (document_type, document_id, user_id),
    )
    return int(cur.lastrowid)


def count(conn, document_type: str, document_id: int) -> int:
    """How many times the document was printed (a receipt printed again is a duplicate)."""
    row = conn.execute(
        "SELECT COUNT(*) FROM print_log WHERE document_type = ? AND document_id = ?",
        (document_type, document_id),
    ).fetchone()
    return int(row[0])
