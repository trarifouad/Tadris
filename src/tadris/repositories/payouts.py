"""SQL for teacher payouts: a payout (teacher, period, totals, status), its lines (one per
group and rate) and the months (subscription charges) each line counts.

A month is owed to the teacher of its group on its first day (accrual date), at the full
price, whether the student paid or not; it is counted in one payout only (unique index).
Approved and paid payouts never change (triggers).
"""

# A month owed to a teacher: an open subscription charge, in no payout yet, of a group the
# teacher taught on the month's first day.
_OWED = """
    SELECT c.id AS charge_id, c.amount, c.accrual_date, c.description,
           e.group_id, g.name AS group_name, sb.name AS subject, l.name AS level,
           e.student_id, st.student_number, st.last_name, st.first_name, gt.teacher_id
      FROM charges c
      JOIN subscriptions s ON s.id = c.subscription_id
      JOIN enrollments e ON e.id = s.enrollment_id
      JOIN students st ON st.id = e.student_id
      JOIN class_groups g ON g.id = e.group_id
      JOIN subjects sb ON sb.id = g.subject_id
      JOIN levels l ON l.id = g.level_id
      JOIN group_teachers gt ON gt.group_id = e.group_id
                            AND gt.valid_from <= c.accrual_date
                            AND (gt.valid_to IS NULL OR gt.valid_to > c.accrual_date)
     WHERE c.status = 'open'
       AND NOT EXISTS (SELECT 1 FROM payout_line_charges plc WHERE plc.charge_id = c.id)
       AND c.accrual_date <= :until
"""


def owed(conn, teacher_id: int, until: str) -> list:
    """The teacher's months not paid yet with a first day on or before `until`, oldest
    first."""
    return conn.execute(
        f"{_OWED} AND gt.teacher_id = :teacher ORDER BY c.accrual_date, c.id",
        {"until": until, "teacher": teacher_id},
    ).fetchall()


def owed_teachers(conn, until: str) -> list:
    """Per teacher with months not paid yet up to `until`: teacher_id, months, revenue."""
    return conn.execute(
        f"SELECT teacher_id, COUNT(*) AS months, SUM(amount) AS revenue FROM ({_OWED}) "
        "GROUP BY teacher_id",
        {"until": until},
    ).fetchall()


# ----- payouts -----

_COLUMNS = """
    p.id, p.teacher_id, t.full_name AS teacher, p.period_start, p.period_end, p.base_amount,
    p.amount_due, p.amount_paid, p.receipt_number, p.status, ap.username AS approved_by,
    p.approved_at, p.method, pb.username AS paid_by, p.paid_at, p.created_at,
    (SELECT COUNT(*) FROM payout_line_charges plc JOIN payout_lines l ON l.id = plc.payout_line_id
      WHERE l.payout_id = p.id) AS months
"""
_FROM = """
    FROM teacher_payouts p
    JOIN teachers t ON t.id = p.teacher_id
    LEFT JOIN users ap ON ap.id = p.approved_by
    LEFT JOIN users pb ON pb.id = p.paid_by
"""


def get(conn, payout_id: int):
    return conn.execute(f"SELECT {_COLUMNS} {_FROM} WHERE p.id = ?", (payout_id,)).fetchone()


def listing(conn, statuses: tuple[str, ...], teacher_id: int | None = None) -> list:
    """Latest period first, then by teacher."""
    marks = ", ".join("?" for _ in statuses)
    return conn.execute(
        f"SELECT {_COLUMNS} {_FROM} WHERE p.status IN ({marks}) "
        "AND (? IS NULL OR p.teacher_id = ?) ORDER BY p.period_end DESC, t.full_name, p.id",
        (*statuses, teacher_id, teacher_id),
    ).fetchall()


def draft_of(conn, teacher_id: int):
    return conn.execute(f"SELECT {_COLUMNS} {_FROM} WHERE p.teacher_id = ? "
                        "AND p.status = 'draft'", (teacher_id,)).fetchone()


def same_period(conn, teacher_id: int, start: str, end: str):
    return conn.execute(
        "SELECT id, status FROM teacher_payouts WHERE teacher_id = ? AND period_start = ? "
        "AND period_end = ?",
        (teacher_id, start, end),
    ).fetchone()


def paid_on(conn, day: str) -> list:
    """Payouts paid on one day ('YYYY-MM-DD'), in order."""
    return conn.execute(
        f"SELECT {_COLUMNS} {_FROM} WHERE substr(p.paid_at, 1, 10) = ? ORDER BY p.paid_at, p.id",
        (day,),
    ).fetchall()


def lines(conn, payout_id: int) -> list:
    """One per group and rate, with the months and distinct students it counts."""
    return conn.execute(
        """
        SELECT l.id, l.group_id, g.name AS group_name, sb.name AS subject, lv.name AS level,
               l.revenue_basis, l.percentage_bp, l.amount,
               (SELECT COUNT(*) FROM payout_line_charges plc
                 WHERE plc.payout_line_id = l.id) AS months,
               (SELECT COUNT(DISTINCT e.student_id) FROM payout_line_charges plc
                  JOIN charges c ON c.id = plc.charge_id
                  JOIN subscriptions s ON s.id = c.subscription_id
                  JOIN enrollments e ON e.id = s.enrollment_id
                 WHERE plc.payout_line_id = l.id) AS students
          FROM payout_lines l
          JOIN class_groups g ON g.id = l.group_id
          JOIN subjects sb ON sb.id = g.subject_id
          JOIN levels lv ON lv.id = g.level_id
         WHERE l.payout_id = ?
         ORDER BY g.name, l.percentage_bp DESC
        """,
        (payout_id,),
    ).fetchall()


def months(conn, payout_id: int) -> list:
    """Every month the payout counts, by group then student."""
    return conn.execute(
        """
        SELECT plc.charge_id, plc.amount, l.percentage_bp, c.accrual_date, c.description,
               g.name AS group_name, sb.name AS subject, lv.name AS level,
               st.student_number, st.last_name, st.first_name
          FROM payout_line_charges plc
          JOIN payout_lines l ON l.id = plc.payout_line_id
          JOIN charges c ON c.id = plc.charge_id
          JOIN subscriptions s ON s.id = c.subscription_id
          JOIN enrollments e ON e.id = s.enrollment_id
          JOIN students st ON st.id = e.student_id
          JOIN class_groups g ON g.id = l.group_id
          JOIN subjects sb ON sb.id = g.subject_id
          JOIN levels lv ON lv.id = g.level_id
         WHERE l.payout_id = ?
         ORDER BY g.name, st.last_name, st.first_name, c.accrual_date
        """,
        (payout_id,),
    ).fetchall()


def insert(conn, teacher_id: int, start: str, end: str, base: int, due: int,
           created_at: str) -> int:
    cur = conn.execute(
        "INSERT INTO teacher_payouts(teacher_id, period_start, period_end, base_amount, "
        "amount_due, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (teacher_id, start, end, base, due, created_at),
    )
    return int(cur.lastrowid)


def insert_line(conn, payout_id: int, group_id: int, revenue: int, bp: int,
                amount: int) -> int:
    cur = conn.execute(
        "INSERT INTO payout_lines(payout_id, group_id, revenue_basis, percentage_bp, amount) "
        "VALUES (?, ?, ?, ?, ?)",
        (payout_id, group_id, revenue, bp, amount),
    )
    return int(cur.lastrowid)


def insert_month(conn, line_id: int, charge_id: int, amount: int) -> None:
    conn.execute(
        "INSERT INTO payout_line_charges(payout_line_id, charge_id, amount) VALUES (?, ?, ?)",
        (line_id, charge_id, amount),
    )


def delete_draft(conn, payout_id: int) -> None:
    """A draft with its lines and months (the triggers refuse it once approved)."""
    conn.execute(
        "DELETE FROM payout_line_charges WHERE payout_line_id IN "
        "(SELECT id FROM payout_lines WHERE payout_id = ?)",
        (payout_id,),
    )
    conn.execute("DELETE FROM payout_lines WHERE payout_id = ?", (payout_id,))
    conn.execute("DELETE FROM teacher_payouts WHERE id = ?", (payout_id,))


def approve(conn, payout_id: int, by: int, at: str) -> None:
    conn.execute(
        "UPDATE teacher_payouts SET status = 'approved', approved_by = ?, approved_at = ? "
        "WHERE id = ?",
        (by, at, payout_id),
    )


def mark_paid(conn, payout_id: int, amount: int, number: str, method: str, by: int,
              at: str) -> None:
    conn.execute(
        "UPDATE teacher_payouts SET status = 'paid', amount_paid = ?, receipt_number = ?, "
        "method = ?, paid_by = ?, paid_at = ? WHERE id = ?",
        (amount, number, method, by, at, payout_id),
    )
