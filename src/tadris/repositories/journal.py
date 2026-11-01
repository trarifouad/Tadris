"""The audit log, read for the director's Journal (services/journal.py)."""

# The Journal shows what people did. What the app does by itself (backups, sessions prepared,
# months ended) stays in audit_log for a technician, except what the director must know: a
# failed backup or copy to the second location (the data is not being saved), and a computer
# date accepted at start although it looked wrong.
_SHOWN = """
    (a.user_id IS NOT NULL OR a.action IN ('backup.failed', 'backup.mirror_failed',
                                           'clock.behind', 'clock.ahead'))
"""

_FILTERS = f"""
         WHERE a.created_at >= :first AND a.created_at < :after
           AND {_SHOWN}
           AND (:user IS NULL OR a.user_id = :user)
"""


def entries(conn, first: str, after: str, user_id: int | None, limit: int,
            before_id: int | None = None) -> list:
    """Latest first, from `first` (a date) to before `after` (the day after the last one).
    before_id: the next page, the entries older than that one (stable while new ones are
    written, and as fast on the fiftieth page as on the first)."""
    return conn.execute(
        f"""
        SELECT a.id, a.created_at, u.username, a.action, a.entity_name, a.entity_id,
               a.old_value, a.new_value
          FROM audit_log a
          LEFT JOIN users u ON u.id = a.user_id
        {_FILTERS}
           AND (:before IS NULL OR a.id < :before)
         ORDER BY a.id DESC
         LIMIT :limit
        """,
        {"first": first, "after": after, "user": user_id, "limit": limit,
         "before": before_id},
    ).fetchall()


def count(conn, first: str, after: str, user_id: int | None) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM audit_log a {_FILTERS}",
                        {"first": first, "after": after, "user": user_id}).fetchone()[0]


def users(conn) -> list:
    return conn.execute("SELECT id, username FROM users ORDER BY username").fetchall()
