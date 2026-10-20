"""SQL for students. No permissions, no transactions, no audit: the service owns those."""

_NOW = "strftime('%Y-%m-%dT%H:%M:%S','now','localtime')"

_LIST_COLUMNS = """
    s.id, s.student_number, s.first_name, s.last_name, s.birth_date, s.status,
    c.full_name AS main_contact, c.phone AS main_phone
"""
_LIST_FROM = """
    FROM students s
    LEFT JOIN student_contacts sc ON sc.student_id = s.id AND sc.is_main = 1
    LEFT JOIN contacts c ON c.id = sc.contact_id
"""


def like_pattern(term: str) -> str:
    """Substring pattern for LIKE ... ESCAPE '\\', so a typed % or _ matches itself."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def insert(conn, student_number: str, first_name: str, last_name: str,
           birth_date: str | None, notes: str | None) -> int:
    cur = conn.execute(
        """
        INSERT INTO students(student_number, first_name, last_name, birth_date, notes)
        VALUES (?, ?, ?, ?, ?)
        """,
        (student_number, first_name, last_name, birth_date, notes),
    )
    return int(cur.lastrowid)


def get(conn, student_id: int):
    return conn.execute(
        """
        SELECT id, student_number, first_name, last_name, birth_date, status, notes, created_at
          FROM students
         WHERE id = ?
        """,
        (student_id,),
    ).fetchone()


def update(conn, student_id: int, first_name: str, last_name: str,
           birth_date: str | None, notes: str | None) -> None:
    conn.execute(
        f"""
        UPDATE students
           SET first_name = ?, last_name = ?, birth_date = ?, notes = ?, updated_at = {_NOW}
         WHERE id = ?
        """,
        (first_name, last_name, birth_date, notes, student_id),
    )


def set_status(conn, student_id: int, status: str) -> None:
    conn.execute(
        f"UPDATE students SET status = ?, updated_at = {_NOW} WHERE id = ?",
        (status, student_id),
    )


# The orders the students list offers, by column: a whitelist, never text from outside.
# The student number ends each one, so a page boundary never splits two equal rows.
ORDERS = {
    "number": ["s.student_number"],
    "last_name": ["fold(s.last_name)", "fold(s.first_name)", "s.student_number"],
    "first_name": ["fold(s.first_name)", "fold(s.last_name)", "s.student_number"],
    "birth_date": ["COALESCE(s.birth_date, '')", "s.student_number"],
    "contact": ["fold(COALESCE(c.full_name, ''))", "s.student_number"],
    "phone": ["COALESCE(c.phone, '')", "s.student_number"],
    "status": ["s.status", "fold(s.last_name)", "fold(s.first_name)", "s.student_number"],
}


def _where(terms: list[tuple[str, str | None]], status: str | None) -> tuple[str, list]:
    """Each term is (folded text, digits or None). A student matches when every term matches
    its first name, last name or number, or one of its contacts' phones (digits)."""
    where: list[str] = []
    params: list = []
    for text, digit_text in terms:
        where.append(
            """
            (fold(s.first_name) LIKE ? ESCAPE '\\'
             OR fold(s.last_name) LIKE ? ESCAPE '\\'
             OR s.student_number LIKE ? ESCAPE '\\'
             OR EXISTS (SELECT 1
                          FROM student_contacts x
                          JOIN contacts p ON p.id = x.contact_id
                         WHERE x.student_id = s.id
                           AND (p.phone LIKE ? OR p.phone_2 LIKE ?)))
            """
        )
        pattern = like_pattern(text)
        phone = None if digit_text is None else f"%{digit_text}%"
        params += [pattern] * 3 + [phone, phone]
    if status is not None:
        where.append("s.status = ?")
        params.append(status)
    return (f"WHERE {' AND '.join(where)}" if where else ""), params


def search(conn, terms: list[tuple[str, str | None]], status: str | None,
           order: str = "last_name", descending: bool = False, limit: int | None = None,
           offset: int = 0) -> list:
    """Students matching every term, in `order` (a key of ORDERS); limit/offset: one page."""
    clause, params = _where(terms, status)
    direction = " DESC" if descending else ""
    order_by = ", ".join(part + direction for part in ORDERS[order])
    page = "" if limit is None else f"LIMIT {int(limit)} OFFSET {int(offset)}"
    return conn.execute(
        f"""
        SELECT {_LIST_COLUMNS}
        {_LIST_FROM}
        {clause}
        ORDER BY {order_by}
        {page}
        """,
        params,
    ).fetchall()


def count(conn, terms: list[tuple[str, str | None]], status: str | None) -> int:
    clause, params = _where(terms, status)
    return conn.execute(f"SELECT COUNT(*) {_LIST_FROM} {clause}", params).fetchone()[0]


def same_name(conn, first_name: str, last_name: str, birth_date: str | None,
              exclude_id: int | None) -> list:
    """Students with the same folded name whose birth date is equal, or unknown on either side."""
    return conn.execute(
        """
        SELECT id, student_number, first_name, last_name
          FROM students
         WHERE fold(first_name) = fold(?)
           AND fold(last_name) = fold(?)
           AND (? IS NULL OR birth_date IS NULL OR birth_date = ?)
           AND id IS NOT ?
         ORDER BY student_number
        """,
        (first_name, last_name, birth_date, birth_date, exclude_id),
    ).fetchall()


def sharing_phone(conn, phones: list[str], exclude_id: int | None) -> list:
    if not phones:
        return []
    marks = ", ".join("?" * len(phones))
    return conn.execute(
        f"""
        SELECT DISTINCT s.id, s.student_number, s.first_name, s.last_name
          FROM students s
          JOIN student_contacts sc ON sc.student_id = s.id
          JOIN contacts c ON c.id = sc.contact_id
         WHERE (c.phone IN ({marks}) OR c.phone_2 IN ({marks}))
           AND s.id IS NOT ?
         ORDER BY s.student_number
        """,
        (*phones, *phones, exclude_id),
    ).fetchall()


def count_live_enrollments(conn, student_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM enrollments WHERE student_id = ? AND status IN ('trial', 'active')",
        (student_id,),
    ).fetchone()
    return int(row[0])
