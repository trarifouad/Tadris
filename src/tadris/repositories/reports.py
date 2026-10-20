"""SQL for the dashboard and the reports: read only.

Money follows the payments repository: what was paid on a charge is what payments not voided
allocated to it; a charge counts in the month of its accrual date (a month on its first day,
the fee on the registration day); cancelled charges are left out.
"""

_GROUP_TITLE = "g.name || ' · ' || sb.name || ' ' || l.name"

_PAID = """
    COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa
               WHERE pa.charge_id = c.id
                 AND NOT EXISTS (SELECT 1 FROM payment_voids v
                                  WHERE v.payment_id = pa.payment_id)), 0)
"""
_REFUNDED = """
    COALESCE((SELECT SUM(rf.refunded_amount) FROM refunds rf
               WHERE rf.charge_id = c.id AND rf.status = 'paid'), 0)
"""


def charges_between(conn, first: str, last: str) -> list:
    """Charges not cancelled with an accrual date in [first, last]: amount, paid, refunded,
    and the group for a month (NULL for the registration fee)."""
    return conn.execute(
        f"""
        SELECT c.id, c.accrual_date, c.amount, {_PAID} AS paid, {_REFUNDED} AS refunded,
               e.group_id, {_GROUP_TITLE} AS group_title
          FROM charges c
          LEFT JOIN subscriptions s ON s.id = c.subscription_id
          LEFT JOIN enrollments e ON e.id = s.enrollment_id
          LEFT JOIN class_groups g ON g.id = e.group_id
          LEFT JOIN subjects sb ON sb.id = g.subject_id
          LEFT JOIN levels l ON l.id = g.level_id
         WHERE c.status = 'open' AND c.accrual_date BETWEEN ? AND ?
         ORDER BY c.accrual_date, c.id
        """,
        (first, last),
    ).fetchall()


def collected_by_month(conn, first: str, last: str) -> dict[str, int]:
    """{'YYYY-MM': amount} of payments not voided received in [first, last]."""
    rows = conn.execute(
        """
        SELECT substr(p.paid_at, 1, 7) AS month, SUM(p.amount) AS amount
          FROM payments p
         WHERE substr(p.paid_at, 1, 10) BETWEEN ? AND ?
           AND NOT EXISTS (SELECT 1 FROM payment_voids v WHERE v.payment_id = p.id)
         GROUP BY month
        """,
        (first, last),
    ).fetchall()
    return {row["month"]: row["amount"] for row in rows}


def refunded_by_month(conn, first: str, last: str) -> dict[str, int]:
    """{'YYYY-MM': amount} handed back (refunds paid out) in [first, last]."""
    rows = conn.execute(
        """
        SELECT substr(paid_out_at, 1, 7) AS month, SUM(refunded_amount) AS amount
          FROM refunds
         WHERE status = 'paid' AND substr(paid_out_at, 1, 10) BETWEEN ? AND ?
         GROUP BY month
        """,
        (first, last),
    ).fetchall()
    return {row["month"]: row["amount"] for row in rows}


_MARKS = """
    SUM(a.status = 'present') AS present, SUM(a.status = 'late') AS late,
    SUM(a.status = 'absent') AS absent, SUM(a.status = 'excused') AS excused
"""
_ATTENDANCE_FROM = """
      FROM attendances a
      JOIN sessions s ON s.id = a.session_id
      JOIN class_groups g ON g.id = s.group_id
      JOIN subjects sb ON sb.id = g.subject_id
      JOIN levels l ON l.id = g.level_id
"""


def attendance_by_group(conn, first: str, last: str) -> list:
    """Per group: sessions with marks and the marks of each kind, counted in SQL (a year
    of a big school is a million marks), sessions not cancelled in [first, last]."""
    return conn.execute(
        f"""
        SELECT s.group_id, {_GROUP_TITLE} AS group_title,
               COUNT(DISTINCT a.session_id) AS sessions, {_MARKS}
        {_ATTENDANCE_FROM}
         WHERE s.status <> 'cancelled' AND s.date BETWEEN :first AND :last
         GROUP BY s.group_id
        """,
        {"first": first, "last": last},
    ).fetchall()


def attendance_by_student(conn, first: str, last: str, group_id: int | None) -> list:
    """Per student and group: the marks of each kind, counted in SQL."""
    return conn.execute(
        f"""
        SELECT e.student_id, st.student_number, st.last_name, st.first_name, s.group_id,
               {_GROUP_TITLE} AS group_title, {_MARKS}
        {_ATTENDANCE_FROM}
          JOIN enrollments e ON e.id = a.enrollment_id
          JOIN students st ON st.id = e.student_id
         WHERE s.status <> 'cancelled' AND s.date BETWEEN :first AND :last
           AND (:group IS NULL OR s.group_id = :group)
         GROUP BY e.student_id, s.group_id
        """,
        {"first": first, "last": last, "group": group_id},
    ).fetchall()


def payouts_by_teacher(conn, first: str, last: str) -> list:
    """Per teacher: paid in [first, last] (by payment date), and waiting (draft or approved,
    whatever their dates)."""
    return conn.execute(
        """
        SELECT teacher_id,
               SUM(CASE WHEN status = 'paid' AND substr(paid_at, 1, 10) BETWEEN :first AND :last
                        THEN amount_paid ELSE 0 END) AS paid,
               SUM(CASE WHEN status = 'draft' THEN amount_due ELSE 0 END) AS drafted,
               SUM(CASE WHEN status = 'approved' THEN amount_due ELSE 0 END) AS approved
          FROM teacher_payouts
         GROUP BY teacher_id
        """,
        {"first": first, "last": last},
    ).fetchall()


_STUDENT_FILTER = """
         WHERE (:status IS NULL OR st.status = :status)
           AND (:group IS NULL OR EXISTS (
                   SELECT 1 FROM enrollments e WHERE e.student_id = st.id
                      AND e.group_id = :group AND e.status IN ('trial', 'active')))
"""


def student_ids(conn, status: str | None, group_id: int | None) -> list[int]:
    """Every student the list's filters match (ids only: the count and the total owed)."""
    return [row[0] for row in conn.execute(
        f"SELECT st.id FROM students st {_STUDENT_FILTER}",
        {"status": status, "group": group_id})]


def student_list(conn, status: str | None, year_id: int | None, group_id: int | None,
                 limit: int | None = None, offset: int = 0) -> list:
    """Students with their level in the year, their groups now (trial or active) and their
    main contact; limit/offset: one page of them, in name order."""
    return conn.execute(
        f"""
        SELECT st.id, st.student_number, st.last_name, st.first_name, st.birth_date, st.status,
               (SELECT lv.name FROM registrations r JOIN levels lv ON lv.id = r.level_id
                 WHERE r.student_id = st.id AND r.status = 'active'
                   AND r.school_year_id = :year) AS level,
               (SELECT GROUP_CONCAT(title, ', ') FROM (
                    SELECT {_GROUP_TITLE} AS title
                      FROM enrollments e
                      JOIN class_groups g ON g.id = e.group_id
                      JOIN subjects sb ON sb.id = g.subject_id
                      JOIN levels l ON l.id = g.level_id
                     WHERE e.student_id = st.id AND e.status IN ('trial', 'active')
                     ORDER BY g.name)) AS groups,
               (SELECT ct.full_name FROM student_contacts sc
                  JOIN contacts ct ON ct.id = sc.contact_id
                 WHERE sc.student_id = st.id AND sc.is_main = 1) AS contact,
               (SELECT ct.phone FROM student_contacts sc
                  JOIN contacts ct ON ct.id = sc.contact_id
                 WHERE sc.student_id = st.id AND sc.is_main = 1) AS phone
          FROM students st
        {_STUDENT_FILTER}
         ORDER BY fold(st.last_name), fold(st.first_name), st.student_number
         LIMIT :limit OFFSET :offset
        """,
        {"status": status, "year": year_id, "group": group_id,
         "limit": -1 if limit is None else limit, "offset": offset},
    ).fetchall()


# ----- audit log -----

# The Journal shows what people did. What the app does by itself (backups, sessions prepared,
# months ended) stays in audit_log for a technician, except a failed backup: the director
# must know the data is not being saved.
_SHOWN = """
    (a.user_id IS NOT NULL OR a.action IN ('backup.failed'))
"""


_FILTERS = f"""
         WHERE a.created_at >= :first AND a.created_at < :after
           AND {_SHOWN}
           AND (:user IS NULL OR a.user_id = :user)
           AND (:prefix IS NULL OR a.action = :prefix OR a.action LIKE :prefix || '.%')
           AND (:entity IS NULL OR a.entity_id = :entity)
"""


def _params(first: str, after: str, user_id, action_prefix, entity_id) -> dict:
    return {"first": first, "after": after, "user": user_id, "prefix": action_prefix,
            "entity": entity_id}


def audit_entries(conn, first: str, after: str, user_id: int | None,
                  action_prefix: str | None, entity_id: int | None, limit: int,
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
        {**_params(first, after, user_id, action_prefix, entity_id), "limit": limit,
         "before": before_id},
    ).fetchall()


def audit_count(conn, first: str, after: str, user_id: int | None,
                action_prefix: str | None, entity_id: int | None) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM audit_log a {_FILTERS}",
                        _params(first, after, user_id, action_prefix, entity_id)).fetchone()[0]


def audit_families(conn) -> list[str]:
    """The first part of every action the Journal shows ('payment' for 'payment.record')."""
    return [row[0] for row in conn.execute(
        "SELECT DISTINCT CASE WHEN instr(action, '.') > 0 "
        "THEN substr(action, 1, instr(action, '.') - 1) ELSE action END AS family "
        f"FROM audit_log a WHERE {_SHOWN} ORDER BY family")]


def users(conn) -> list:
    return conn.execute("SELECT id, username FROM users ORDER BY username").fetchall()
