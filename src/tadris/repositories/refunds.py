"""SQL for refunds (migration 0021). No permissions, no transactions, no audit: the service
owns those."""

from tadris.repositories import charge_money


def month(conn, subscription_id: int):
    """A month and what counting its sessions needs: its dates and price, its group (start
    date, the closure it is under and its day, the last day of its school year) and the
    student's place it belongs to."""
    return conn.execute(
        """
        SELECT s.id, s.start_date, s.end_date, s.price, s.enrollment_id, e.group_id,
               g.start_date AS group_start, g.closure_id, gc.closed_on,
               y.end_date AS year_end
          FROM subscriptions s
          JOIN enrollments e ON e.id = s.enrollment_id
          JOIN class_groups g ON g.id = e.group_id
          LEFT JOIN group_closures gc ON gc.id = g.closure_id
          JOIN school_years y ON y.id = g.school_year_id
         WHERE s.id = ?
        """,
        (subscription_id,),
    ).fetchone()


def place_chain(conn, enrollment_id: int) -> list:
    """The month's enrollment and every switch that followed it, oldest first. Each row:
    status, entry and last days, never_started, its group (title), and the closure that
    ended it if one did (a reopening since changes nothing)."""
    return conn.execute(
        """
        WITH RECURSIVE chain(id, depth) AS (
            SELECT ?, 0
            UNION ALL
            SELECT e.id, c.depth + 1
              FROM enrollments e JOIN chain c ON e.switched_from_id = c.id
             WHERE c.depth < 100
        )
        SELECT e.id, e.status, e.enrolled_on, e.left_on, e.never_started, e.group_id,
               e.closure_id, ec.closed_on, g.name AS group_name, sb.name AS subject,
               l.name AS level
          FROM chain c
          JOIN enrollments e ON e.id = c.id
          LEFT JOIN group_closures ec ON ec.id = e.closure_id
          JOIN class_groups g ON g.id = e.group_id
          JOIN subjects sb ON sb.id = g.subject_id
          JOIN levels l ON l.id = g.level_id
         ORDER BY c.depth, e.id
        """,
        (enrollment_id,),
    ).fetchall()


def held_count(conn, group_id: int, day: str) -> int:
    """How many of the group's timetable sessions took place that day: held, or their
    attendance taken (a session the closure cancelled did not). A makeup that day is not one:
    it replaced a session already counted where it was cancelled."""
    return conn.execute(
        """
        SELECT COUNT(*) FROM sessions s
         WHERE s.group_id = ? AND s.date = ? AND s.status <> 'cancelled'
           AND s.source = 'generated'
           AND (s.status = 'held'
                OR EXISTS (SELECT 1 FROM attendances a WHERE a.session_id = s.id))
        """,
        (group_id, day),
    ).fetchone()[0]


def attended_on(conn, group_id: int | None, enrollment_ids: list[int], day: str) -> int:
    """How many timetable sessions of that day (of `group_id` when set) have attendance on
    any of those places; cancelled sessions were not given, and a makeup is not one."""
    if not enrollment_ids:
        return 0
    marks = ",".join("?" * len(enrollment_ids))
    group = "" if group_id is None else " AND s.group_id = ?"
    params: list = list(enrollment_ids)
    if group_id is not None:
        params.append(group_id)
    params.append(day)
    return conn.execute(
        f"""
        SELECT COUNT(*) FROM attendances a JOIN sessions s ON s.id = a.session_id
         WHERE a.enrollment_id IN ({marks}){group} AND s.date = ?
           AND s.status <> 'cancelled' AND s.source = 'generated'
        """,
        params,
    ).fetchone()[0]


def slots(conn, group_id: int, first: str, last: str) -> list:
    """The group's timetable slots valid on at least one day of [first, last] (both
    included; a slot's own period is half-open [valid_from, valid_to))."""
    return conn.execute(
        """
        SELECT weekday, valid_from, valid_to
          FROM timetable_slots
         WHERE group_id = ? AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)
         ORDER BY valid_from, weekday, start_time, id
        """,
        (group_id, last, first),
    ).fetchall()


def closure_slots(conn, closure_id: int) -> list:
    """The slots a closure kept, running that day or planned later, with their own dates."""
    return conn.execute(
        """
        SELECT weekday, valid_from, valid_to FROM group_closure_slots
         WHERE closure_id = ?
         ORDER BY valid_from, weekday, start_time, id
        """,
        (closure_id,),
    ).fetchall()


# What the phase 8 refunds (the archive, 0015) handed back from the payments, not voided, of
# the month c: never handed back again (REVIEW_FIXES, finding 5).
_ARCHIVED = charge_money.archived_on()
_PAID = charge_money.paid_on()
# What refunds hold on the month c: pending ones the amount asked, approved and paid ones the
# amount approved (as the triggers count it, 0021).
_HELD = """
    COALESCE((SELECT SUM(CASE r.status WHEN 'pending' THEN r.amount_requested
                                       ELSE r.amount_approved END)
                FROM refunds r
               WHERE r.charge_id = c.id AND r.status IN ('pending', 'approved', 'paid')), 0)
"""


# ----- requests -----

_COLUMNS = """
    r.id, r.charge_id, c.subscription_id, e.student_id, st.student_number, st.last_name,
    st.first_name, g.name AS group_name, sb.name AS subject, l.name AS level,
    s.start_date AS month_start, s.end_date AS month_end, s.price,
    r.counted_from, r.sessions_total, r.sessions_left, r.sessions_value, r.max_amount,
    r.amount_requested, r.amount_approved, r.reason, r.status,
    r.requested_by AS requested_by_id, ur.username AS requested_by, r.requested_at,
    ud.username AS decided_by, r.decided_at, uc.username AS cancelled_by, r.cancelled_at,
    r.close_reason, r.number, r.method, up.username AS paid_by, r.paid_at
"""
_FROM = """
    FROM refunds r
    JOIN charges c ON c.id = r.charge_id
    JOIN subscriptions s ON s.id = c.subscription_id
    JOIN enrollments e ON e.id = s.enrollment_id
    JOIN students st ON st.id = e.student_id
    JOIN class_groups g ON g.id = e.group_id
    JOIN subjects sb ON sb.id = g.subject_id
    JOIN levels l ON l.id = g.level_id
    JOIN users ur ON ur.id = r.requested_by
    LEFT JOIN users ud ON ud.id = r.decided_by
    LEFT JOIN users uc ON uc.id = r.cancelled_by
    LEFT JOIN users up ON up.id = r.paid_by
"""


def get(conn, refund_id: int):
    return conn.execute(f"SELECT {_COLUMNS} {_FROM} WHERE r.id = ?", (refund_id,)).fetchone()


def for_student(conn, student_id: int) -> list:
    """Latest first."""
    return conn.execute(
        f"SELECT {_COLUMNS} {_FROM} WHERE e.student_id = ? ORDER BY r.requested_at DESC, r.id DESC",
        (student_id,),
    ).fetchall()


def count_for_student(conn, student_id: int) -> int:
    """How many refunds the student has, whatever their status."""
    return conn.execute(
        """
        SELECT COUNT(*) FROM refunds r
          JOIN charges c ON c.id = r.charge_id
          JOIN subscriptions s ON s.id = c.subscription_id
          JOIN enrollments e ON e.id = s.enrollment_id
         WHERE e.student_id = ?
        """,
        (student_id,),
    ).fetchone()[0]


def with_status(conn, statuses: tuple[str, ...]) -> list:
    """Oldest first."""
    marks = ", ".join("?" * len(statuses))
    return conn.execute(
        f"SELECT {_COLUMNS} {_FROM} WHERE r.status IN ({marks}) ORDER BY r.requested_at, r.id",
        statuses,
    ).fetchall()


def paid_on(conn, day: str) -> list:
    """Refunds whose money went back on one day ('YYYY-MM-DD'), in order."""
    return conn.execute(
        f"SELECT {_COLUMNS} {_FROM} WHERE r.status = 'paid' AND substr(r.paid_at, 1, 10) = ? "
        "ORDER BY r.paid_at, r.id",
        (day,),
    ).fetchall()


def held(conn, charge_id: int, exclude_id: int | None = None) -> int:
    """What refunds hold on a month: pending ones the amount asked, approved and paid ones the
    amount approved (as the triggers count it, 0021)."""
    row = conn.execute(
        """
        SELECT COALESCE(SUM(CASE status WHEN 'pending' THEN amount_requested
                                        ELSE amount_approved END), 0)
          FROM refunds
         WHERE charge_id = ? AND status IN ('pending', 'approved', 'paid') AND id IS NOT ?
        """,
        (charge_id, exclude_id),
    ).fetchone()
    return int(row[0])


def paid_months(conn, student_id: int) -> list:
    """The student's months with an open charge paid in full by payments not voided, the
    latest first; archived: what the archive handed back of it; held: what refunds hold on
    it. Each row also has what month() gives, for counting its sessions with no other read."""
    return conn.execute(
        f"""
        SELECT * FROM (
            SELECT s.id AS subscription_id, c.id AS charge_id, c.amount, s.start_date,
                   s.end_date, s.price, s.enrollment_id, e.group_id,
                   g.start_date AS group_start, g.closure_id, gc.closed_on,
                   y.end_date AS year_end, g.name AS group_name, sb.name AS subject,
                   l.name AS level, {_ARCHIVED} AS archived, {_PAID} AS paid, {_HELD} AS held
              FROM subscriptions s
              JOIN charges c ON c.subscription_id = s.id AND c.status = 'open'
              JOIN enrollments e ON e.id = s.enrollment_id
              JOIN class_groups g ON g.id = e.group_id
              LEFT JOIN group_closures gc ON gc.id = g.closure_id
              JOIN school_years y ON y.id = g.school_year_id
              JOIN subjects sb ON sb.id = g.subject_id
              JOIN levels l ON l.id = g.level_id
             WHERE e.student_id = ? AND s.status <> 'cancelled')
         WHERE paid >= amount
         ORDER BY start_date DESC, subscription_id DESC
        """,
        (student_id,),
    ).fetchall()


def open_charge(conn, subscription_id: int):
    """The month's charge if open: id, amount, what payments not voided paid on it, and what
    the archive handed back of it."""
    return conn.execute(
        f"""
        SELECT c.id, c.amount, {_ARCHIVED} AS archived, {_PAID} AS paid
          FROM charges c
          JOIN subscriptions s ON s.id = c.subscription_id
         WHERE c.subscription_id = ? AND c.status = 'open' AND s.status <> 'cancelled'
        """,
        (subscription_id,),
    ).fetchone()


def sources(conn, charge_id: int) -> list:
    """Where money paid on a month can be taken back from: its allocations from payments not
    voided, with what each still holds (less what refunds, and the archive, took from it),
    the latest payment first."""
    return conn.execute(
        """
        SELECT * FROM (
            SELECT pa.id, pa.payment_id, p.paid_at,
                   pa.amount
                   - COALESCE((SELECT SUM(ra.amount) FROM refund_allocations ra
                                WHERE ra.payment_allocation_id = pa.id), 0)
                   - COALESCE((SELECT SUM(ra.amount) FROM archived_refund_allocations ra
                                WHERE ra.payment_allocation_id = pa.id), 0) AS remaining
              FROM payment_allocations pa
              JOIN payments p ON p.id = pa.payment_id
             WHERE pa.charge_id = ?
               AND NOT EXISTS (SELECT 1 FROM payment_voids v WHERE v.payment_id = p.id))
         WHERE remaining > 0
         ORDER BY paid_at DESC, payment_id DESC, id DESC
        """,
        (charge_id,),
    ).fetchall()


def insert(conn, charge_id: int, counted_from: str, total: int, left: int, value: int,
           max_amount: int, amount: int, reason: str, by: int, at: str) -> int:
    cur = conn.execute(
        """
        INSERT INTO refunds(charge_id, counted_from, sessions_total, sessions_left,
                            sessions_value, max_amount, amount_requested, reason,
                            requested_by, requested_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (charge_id, counted_from, total, left, value, max_amount, amount, reason, by, at),
    )
    return int(cur.lastrowid)


def approve(conn, refund_id: int, amount: int, by: int, at: str) -> None:
    conn.execute("UPDATE refunds SET status = 'approved', amount_approved = ?, decided_by = ?, "
                 "decided_at = ? WHERE id = ?", (amount, by, at, refund_id))


def reject(conn, refund_id: int, reason: str, by: int, at: str) -> None:
    conn.execute("UPDATE refunds SET status = 'rejected', close_reason = ?, decided_by = ?, "
                 "decided_at = ? WHERE id = ?", (reason, by, at, refund_id))


def withdraw(conn, refund_id: int, reason: str, by: int, at: str) -> None:
    conn.execute("UPDATE refunds SET status = 'cancelled', close_reason = ?, cancelled_by = ?, "
                 "cancelled_at = ? WHERE id = ?", (reason, by, at, refund_id))


def insert_allocation(conn, refund_id: int, payment_allocation_id: int, amount: int) -> None:
    conn.execute("INSERT INTO refund_allocations(refund_id, payment_allocation_id, amount) "
                 "VALUES (?, ?, ?)", (refund_id, payment_allocation_id, amount))


def mark_paid(conn, refund_id: int, number: str, method: str, by: int, at: str) -> None:
    conn.execute("UPDATE refunds SET status = 'paid', number = ?, method = ?, paid_by = ?, "
                 "paid_at = ? WHERE id = ?", (number, method, by, at, refund_id))


def allocations(conn, refund_id: int) -> list:
    """The money a paid refund took back, payment by payment."""
    return conn.execute(
        """
        SELECT ra.payment_allocation_id, pa.payment_id, ra.amount
          FROM refund_allocations ra
          JOIN payment_allocations pa ON pa.id = ra.payment_allocation_id
         WHERE ra.refund_id = ?
         ORDER BY ra.id
        """,
        (refund_id,),
    ).fetchall()


def taken_from(conn, refund_id: int) -> list:
    """The payments a paid refund took money back from, with their receipt: payment id, its
    receipt number, the day it was received, and how much came back from it; the latest
    payment first (the order it was taken in)."""
    return conn.execute(
        """
        SELECT p.id AS payment_id, rc.number AS receipt_number, p.paid_at,
               SUM(ra.amount) AS amount
          FROM refund_allocations ra
          JOIN payment_allocations pa ON pa.id = ra.payment_allocation_id
          JOIN payments p ON p.id = pa.payment_id
          LEFT JOIN receipts rc ON rc.payment_id = p.id
         WHERE ra.refund_id = ?
         GROUP BY p.id
         ORDER BY p.paid_at DESC, p.id DESC
        """,
        (refund_id,),
    ).fetchall()


# ----- payments -----

def payment_handed_back(conn, payment_id: int) -> bool:
    """Money of the payment was handed back (by a refund, or in the archive)."""
    row = conn.execute(
        """
        SELECT EXISTS (SELECT 1 FROM refund_allocations ra
                         JOIN payment_allocations pa ON pa.id = ra.payment_allocation_id
                        WHERE pa.payment_id = :p)
            OR EXISTS (SELECT 1 FROM archived_refund_allocations ra
                         JOIN payment_allocations pa ON pa.id = ra.payment_allocation_id
                        WHERE pa.payment_id = :p)
        """,
        {"p": payment_id},
    ).fetchone()
    return bool(row[0])


def payment_month_asked(conn, payment_id: int) -> bool:
    """The payment paid a month with a refund request pending or approved."""
    row = conn.execute(
        """
        SELECT EXISTS (SELECT 1 FROM payment_allocations pa
                         JOIN refunds r ON r.charge_id = pa.charge_id
                        WHERE pa.payment_id = ? AND r.status IN ('pending', 'approved'))
        """,
        (payment_id,),
    ).fetchone()
    return bool(row[0])
