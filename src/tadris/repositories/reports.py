"""SQL for the Rapports page: read only.

Money follows the payments repository: what was paid on a charge is what payments not voided
allocated to it; a charge counts in the month of its accrual date (a month on its first day,
the fee on the registration day); cancelled charges are left out. A month's teacher is the
group's teacher on its first day, at their rate that day, as payouts count it.
"""

_PAID = """
    COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa
               WHERE pa.charge_id = c.id
                 AND NOT EXISTS (SELECT 1 FROM payment_voids v
                                  WHERE v.payment_id = pa.payment_id)), 0)
"""


def charges_between(conn, first: str, last: str) -> list:
    """Charges not cancelled with an accrual date in [first, last]: amount, paid, the group
    of a month (NULL for a registration fee), and the teacher and their rate on the month's
    first day (NULL when there is none)."""
    return conn.execute(
        f"""
        SELECT c.id, c.accrual_date, c.amount, {_PAID} AS paid, e.group_id,
               gt.teacher_id, r.percentage_bp
          FROM charges c
          LEFT JOIN subscriptions s ON s.id = c.subscription_id
          LEFT JOIN enrollments e ON e.id = s.enrollment_id
          LEFT JOIN group_teachers gt ON gt.group_id = e.group_id
                                     AND gt.valid_from <= c.accrual_date
                                     AND (gt.valid_to IS NULL OR gt.valid_to > c.accrual_date)
          LEFT JOIN teacher_rates r ON r.teacher_id = gt.teacher_id
                                   AND r.valid_from <= c.accrual_date
                                   AND (r.valid_to IS NULL OR r.valid_to > c.accrual_date)
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


_MARKS = """
    SUM(a.status = 'present') AS present, SUM(a.status = 'late') AS late,
    SUM(a.status = 'absent') AS absent, SUM(a.status = 'excused') AS excused
"""


def attendance_by_group(conn, first: str, last: str, group_id: int | None) -> list:
    """Per group: the sessions with marks, the students marked and the marks of each kind,
    counted in SQL (a year of a big school is a million marks), sessions not cancelled in
    [first, last]."""
    return conn.execute(
        f"""
        SELECT s.group_id, COUNT(DISTINCT a.session_id) AS sessions,
               COUNT(DISTINCT a.enrollment_id) AS students, {_MARKS}
          FROM attendances a
          JOIN sessions s ON s.id = a.session_id
         WHERE s.status <> 'cancelled' AND s.date BETWEEN :first AND :last
           AND (:group IS NULL OR s.group_id = :group)
         GROUP BY s.group_id
        """,
        {"first": first, "last": last, "group": group_id},
    ).fetchall()


def attendance_by_student(conn, first: str, last: str, group_id: int | None) -> list:
    """Per student and group: the marks of each kind, counted in SQL."""
    return conn.execute(
        f"""
        SELECT e.student_id, st.student_number, st.last_name, st.first_name, s.group_id,
               {_MARKS}
          FROM attendances a
          JOIN sessions s ON s.id = a.session_id
          JOIN enrollments e ON e.id = a.enrollment_id
          JOIN students st ON st.id = e.student_id
         WHERE s.status <> 'cancelled' AND s.date BETWEEN :first AND :last
           AND (:group IS NULL OR s.group_id = :group)
         GROUP BY e.student_id, s.group_id
        """,
        {"first": first, "last": last, "group": group_id},
    ).fetchall()


def payouts_by_teacher(conn, first: str, last: str) -> list:
    """Per teacher: paid in [first, last] (by the payout's date), and waiting (draft or
    approved, whatever their dates)."""
    return conn.execute(
        """
        SELECT teacher_id,
               SUM(CASE WHEN status = 'paid' AND substr(paid_at, 1, 10) BETWEEN :first AND :last
                        THEN amount_paid ELSE 0 END) AS paid,
               SUM(CASE WHEN status IN ('draft', 'approved') THEN amount_due ELSE 0 END)
                   AS waiting
          FROM teacher_payouts
         GROUP BY teacher_id
        """,
        {"first": first, "last": last},
    ).fetchall()


def students(conn, status: str | None, year_id: int | None, level_id: int | None,
             group_id: int | None) -> list:
    """Students in name order with their registration in the year (level, date), their groups
    now (trial or active) and their main contact."""
    return conn.execute(
        """
        SELECT st.id, st.student_number, st.last_name, st.first_name, st.status,
               r.level_id, lv.name AS level, r.registered_at,
               (SELECT GROUP_CONCAT(name, ', ') FROM (
                    SELECT g.name || ' · ' || sb.name AS name
                      FROM enrollments e
                      JOIN class_groups g ON g.id = e.group_id
                      JOIN subjects sb ON sb.id = g.subject_id
                     WHERE e.student_id = st.id AND e.status IN ('trial', 'active')
                     ORDER BY g.name)) AS groups,
               ct.full_name AS contact, ct.phone
          FROM students st
          LEFT JOIN registrations r ON r.student_id = st.id AND r.school_year_id = :year
                                   AND r.status = 'active'
          LEFT JOIN levels lv ON lv.id = r.level_id
          LEFT JOIN student_contacts sc ON sc.student_id = st.id AND sc.is_main = 1
          LEFT JOIN contacts ct ON ct.id = sc.contact_id
         WHERE (:status IS NULL OR st.status = :status)
           AND (:level IS NULL OR r.level_id = :level)
           AND (:group IS NULL OR EXISTS (
                   SELECT 1 FROM enrollments e WHERE e.student_id = st.id
                      AND e.group_id = :group AND e.status IN ('trial', 'active')))
         ORDER BY fold(st.last_name), fold(st.first_name), st.student_number
        """,
        {"status": status, "year": year_id, "level": level_id, "group": group_id},
    ).fetchall()


def student_counts(conn, year_id: int | None, today: str) -> dict[str, int]:
    """For the tiles: students active; registered in the year; in a trial now; in a group
    where they pay, the group started, but with no month running today (to renew or
    start)."""
    row = conn.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM students WHERE status = 'active') AS active,
          (SELECT COUNT(*) FROM registrations
            WHERE school_year_id = :year AND status = 'active') AS registered,
          (SELECT COUNT(DISTINCT student_id) FROM enrollments WHERE status = 'trial') AS trial,
          (SELECT COUNT(DISTINCT e.student_id)
             FROM enrollments e
             JOIN class_groups g ON g.id = e.group_id
            WHERE e.status = 'active' AND g.status <> 'closed'
              AND e.enrolled_on <= :today AND g.start_date <= :today
              AND NOT EXISTS (SELECT 1 FROM subscriptions s
                               WHERE s.enrollment_id = e.id AND s.status <> 'cancelled'
                                 AND s.start_date <= :today AND s.end_date > :today))
            AS no_month
        """,
        {"year": year_id, "today": today},
    ).fetchone()
    return dict(row)
