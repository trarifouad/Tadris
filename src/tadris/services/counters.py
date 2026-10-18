def next_value(conn, name: str) -> int:
    """Increment a named counter inside the caller's transaction."""
    conn.execute(
        "INSERT INTO counters(name, last_value) VALUES (?, 0) ON CONFLICT(name) DO NOTHING",
        (name,),
    )
    conn.execute(
        """
        UPDATE counters
           SET last_value = last_value + 1,
               updated_at = strftime('%Y-%m-%dT%H:%M:%S','now','localtime')
         WHERE name = ?
        """,
        (name,),
    )
    row = conn.execute("SELECT last_value FROM counters WHERE name = ?", (name,)).fetchone()
    return int(row[0])
