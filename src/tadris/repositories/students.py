"""SQL for students. No permissions, no transactions, no audit: the service owns those."""

from tadris.domain.models import STANDINGS_BY_URGENCY

_NOW = "strftime('%Y-%m-%dT%H:%M:%S','now','localtime')"

_LIST_COLUMNS = """
    s.id, s.student_number, s.first_name, s.last_name, s.birth_date, s.status,
    c.full_name AS main_contact, c.phone AS main_phone
"""
# The list's own columns: the student's groups now (trial or active), « A · Maths, B · Physique »;
# and where they stand on their subscriptions, read as on the Abonnements page from each paid
# group's latest month: the most urgent of ended (over, not renewed), none (no month left),
# expiring (ends by `soon`) and active; NULL with no paid group. Two parameters: today, soon.
# The ranking is models.STANDINGS_BY_URGENCY, the most urgent first, for both the column and
# its order (_URGENCY): written once.
_RANK = {standing: rank for rank, standing in enumerate(STANDINGS_BY_URGENCY, 1)}
_GROUPS_AND_STANDING = f"""
    (SELECT GROUP_CONCAT(name, ', ') FROM (
         SELECT g.name || ' · ' || sb.name AS name
           FROM enrollments e
           JOIN class_groups g ON g.id = e.group_id
           JOIN subjects sb ON sb.id = g.subject_id
          WHERE e.student_id = s.id AND e.status IN ('trial', 'active')
          ORDER BY fold(g.name), fold(sb.name))) AS groups,
    (SELECT CASE MIN(CASE WHEN x.last_end IS NULL THEN {_RANK["none"]}
                          WHEN x.last_end <= ? THEN {_RANK["ended"]}
                          WHEN x.last_end <= ? THEN {_RANK["expiring"]}
                          ELSE {_RANK["active"]} END)
                 {" ".join(f"WHEN {rank} THEN '{name}'" for name, rank in _RANK.items())} END
       FROM (SELECT (SELECT MAX(m.end_date) FROM subscriptions m
                      WHERE m.enrollment_id = e.id AND m.status <> 'cancelled') AS last_end
               FROM enrollments e
               JOIN class_groups g ON g.id = e.group_id
              WHERE e.student_id = s.id AND e.status = 'active' AND g.status <> 'closed') x
    ) AS standing
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


# The most urgent standing first (models.STANDINGS_BY_URGENCY), then no paid group.
_URGENCY = ("CASE standing "
            + " ".join(f"WHEN '{name}' THEN {rank}" for name, rank in _RANK.items())
            + f" ELSE {len(_RANK) + 1} END")
# The orders the students list offers, by column: a whitelist, never text from outside.
# The student number ends each one, so a page boundary never splits two equal rows.
ORDERS = {
    "number": ["s.student_number"],
    "last_name": ["fold(s.last_name)", "fold(s.first_name)", "s.student_number"],
    "first_name": ["fold(s.first_name)", "fold(s.last_name)", "s.student_number"],
    "birth_date": ["COALESCE(s.birth_date, '')", "s.student_number"],
    "groups": ["fold(COALESCE(groups, ''))", "fold(s.last_name)", "fold(s.first_name)",
               "s.student_number"],
    "standing": [_URGENCY, "fold(s.last_name)", "fold(s.first_name)", "s.student_number"],
    "status": ["s.status", "fold(s.last_name)", "fold(s.first_name)", "s.student_number"],
}


def _where(terms: list[tuple[str, str | None]], status: str | None,
           level: tuple[int, int] | None = None,
           group_id: int | None = None) -> tuple[str, list]:
    """Each term is (folded text, digits or None). A student matches when every term matches
    its first name, last name or number, or one of its contacts' phones (digits).
    level: (school year, level): registered at that level that year. group_id: in that
    group now (trial or active)."""
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
    if level is not None:
        where.append("""EXISTS (SELECT 1 FROM registrations r
                                 WHERE r.student_id = s.id AND r.school_year_id = ?
                                   AND r.status = 'active' AND r.level_id = ?)""")
        params += list(level)
    if group_id is not None:
        where.append("""EXISTS (SELECT 1 FROM enrollments e
                                 WHERE e.student_id = s.id AND e.group_id = ?
                                   AND e.status IN ('trial', 'active'))""")
        params.append(group_id)
    return (f"WHERE {' AND '.join(where)}" if where else ""), params


# The orders that read the list's own columns: they need them worked out.
NEEDS_DETAILS = ("groups", "standing")


def search(conn, terms: list[tuple[str, str | None]], status: str | None, today: str,
           soon: str, order: str = "last_name", descending: bool = False,
           limit: int | None = None, offset: int = 0, level: tuple[int, int] | None = None,
           group_id: int | None = None, details: bool = True) -> list:
    """Students matching every term, in `order` (a key of ORDERS); limit/offset: one page.
    today, soon: where each stands on its subscriptions (a month ending by `soon` is
    expiring). details=False: groups and standing are NULL, not worked out (a picker that
    shows neither), unless the order needs them."""
    clause, params = _where(terms, status, level, group_id)
    direction = " DESC" if descending else ""
    order_by = ", ".join(part + direction for part in ORDERS[order])
    page = "" if limit is None else f"LIMIT {int(limit)} OFFSET {int(offset)}"
    if details or order in NEEDS_DETAILS:
        extra, extra_params = _GROUPS_AND_STANDING, [today, soon]
    else:
        extra, extra_params = "NULL AS groups, NULL AS standing", []
    return conn.execute(
        f"""
        SELECT {_LIST_COLUMNS}, {extra}
        {_LIST_FROM}
        {clause}
        ORDER BY {order_by}
        {page}
        """,
        [*extra_params, *params],
    ).fetchall()


def count(conn, terms: list[tuple[str, str | None]], status: str | None,
          level: tuple[int, int] | None = None, group_id: int | None = None) -> int:
    clause, params = _where(terms, status, level, group_id)
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
