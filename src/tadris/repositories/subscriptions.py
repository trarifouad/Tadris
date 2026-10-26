"""SQL for subscriptions: one month of an enrollment, half-open [start_date, end_date), with its
charge. The price is a snapshot of the group's price. What was paid on the charge is derived
from allocations of payments not voided.
"""

_NOW = "strftime('%Y-%m-%dT%H:%M:%S','now','localtime')"

_PAID = """
    COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa
               WHERE pa.charge_id = c.id
                 AND NOT EXISTS (SELECT 1 FROM payment_voids v
                                  WHERE v.payment_id = pa.payment_id)), 0)
"""
_COLUMNS = f"""
    s.id, s.enrollment_id, e.status AS enrollment_status, e.student_id, st.student_number,
    st.last_name, st.first_name,
    e.group_id, g.name AS group_name, sb.name AS subject, l.name AS level,
    s.renewal_of_id, s.price, s.start_date, s.end_date, s.status,
    c.id AS charge_id, c.status AS charge_status, {_PAID} AS paid,
    EXISTS (SELECT 1 FROM payout_line_charges plc
              JOIN payout_lines pl ON pl.id = plc.payout_line_id
              JOIN teacher_payouts tp ON tp.id = pl.payout_id
             WHERE plc.charge_id = c.id AND tp.status <> 'draft') AS in_payout
"""
_FROM = """
    FROM subscriptions s
    JOIN enrollments e ON e.id = s.enrollment_id
    JOIN students st ON st.id = e.student_id
    JOIN class_groups g ON g.id = e.group_id
    JOIN subjects sb ON sb.id = g.subject_id
    JOIN levels l ON l.id = g.level_id
    LEFT JOIN charges c ON c.subscription_id = s.id
"""


def get(conn, subscription_id: int):
    return conn.execute(f"SELECT {_COLUMNS} {_FROM} WHERE s.id = ?",
                        (subscription_id,)).fetchone()


def for_student(conn, student_id: int) -> list:
    return conn.execute(
        f"SELECT {_COLUMNS} {_FROM} WHERE e.student_id = ? ORDER BY s.start_date DESC, s.id DESC",
        (student_id,),
    ).fetchall()


def for_enrollment(conn, enrollment_id: int) -> list:
    return conn.execute(
        f"SELECT {_COLUMNS} {_FROM} WHERE s.enrollment_id = ? ORDER BY s.start_date, s.id",
        (enrollment_id,),
    ).fetchall()


def latest(conn, enrollment_id: int):
    """The enrollment's latest subscription that is not cancelled."""
    return conn.execute(
        f"SELECT {_COLUMNS} {_FROM} WHERE s.enrollment_id = ? AND s.status <> 'cancelled' "
        "ORDER BY s.end_date DESC LIMIT 1",
        (enrollment_id,),
    ).fetchone()


def starting_after(conn, enrollment_id: int, day: str) -> list:
    """The enrollment's months (not cancelled) that start after `day`, in order."""
    return conn.execute(
        f"SELECT {_COLUMNS} {_FROM} WHERE s.enrollment_id = ? AND s.status <> 'cancelled' "
        "AND s.start_date > ? ORDER BY s.start_date",
        (enrollment_id, day),
    ).fetchall()


def has_renewal(conn, subscription_id: int) -> bool:
    """renewal_of_id is unique, whatever the renewal's status."""
    row = conn.execute("SELECT 1 FROM subscriptions WHERE renewal_of_id = ?",
                       (subscription_id,)).fetchone()
    return row is not None


def insert(conn, enrollment_id: int, renewal_of_id: int | None, price: int, start_date: str,
           end_date: str) -> int:
    cur = conn.execute(
        "INSERT INTO subscriptions(enrollment_id, renewal_of_id, price, start_date, end_date) "
        "VALUES (?, ?, ?, ?, ?)",
        (enrollment_id, renewal_of_id, price, start_date, end_date),
    )
    return int(cur.lastrowid)


def insert_charge(conn, subscription_id: int, description: str, amount: int,
                  on: str) -> int:
    """due_date = accrual_date = the subscription's start (teacher pay follows accrual)."""
    cur = conn.execute(
        "INSERT INTO charges(subscription_id, description, amount, due_date, accrual_date) "
        "VALUES (?, ?, ?, ?, ?)",
        (subscription_id, description, amount, on, on),
    )
    return int(cur.lastrowid)


def set_status(conn, subscription_id: int, status: str) -> None:
    conn.execute(f"UPDATE subscriptions SET status = ?, updated_at = {_NOW} WHERE id = ?",
                 (status, subscription_id))


def cancel_charge(conn, charge_id: int) -> None:
    conn.execute("UPDATE charges SET status = 'cancelled' WHERE id = ?", (charge_id,))


def mark_ended(conn, today: str) -> int:
    """Active subscriptions whose last day has passed become 'ended'. Returns how many."""
    cur = conn.execute(
        f"UPDATE subscriptions SET status = 'ended', updated_at = {_NOW} "
        "WHERE status = 'active' AND end_date <= ?",
        (today,),
    )
    return cur.rowcount


# ----- the desk's lists: live paid enrollments and their latest month -----

_LATEST_PER_ENROLLMENT = f"""
    SELECT {_COLUMNS} {_FROM}
     WHERE e.status = 'active' AND g.status <> 'closed' AND s.status <> 'cancelled'
       AND s.end_date = (SELECT MAX(x.end_date) FROM subscriptions x
                          WHERE x.enrollment_id = s.enrollment_id AND x.status <> 'cancelled')
"""


def ending_between(conn, after: str, until: str, group_id: int | None = None) -> list:
    """Latest months ending in (after, until]: still running, to renew soon."""
    return conn.execute(
        f"{_LATEST_PER_ENROLLMENT} AND s.end_date > :after AND s.end_date <= :until "
        "AND (:group IS NULL OR e.group_id = :group) "
        "ORDER BY s.end_date, fold(st.last_name), fold(st.first_name)",
        {"after": after, "until": until, "group": group_id},
    ).fetchall()


def ended_by(conn, today: str, group_id: int | None = None) -> list:
    """Latest months already over: the student is still in the group but not renewed."""
    return conn.execute(
        f"{_LATEST_PER_ENROLLMENT} AND s.end_date <= :today "
        "AND (:group IS NULL OR e.group_id = :group) "
        "ORDER BY s.end_date, fold(st.last_name), fold(st.first_name)",
        {"today": today, "group": group_id},
    ).fetchall()


def live_months(conn) -> list:
    """Every month (not cancelled) of the live paid enrollments: the Abonnements page."""
    return conn.execute(
        f"SELECT {_COLUMNS} {_FROM} "
        "WHERE e.status = 'active' AND g.status <> 'closed' AND s.status <> 'cancelled' "
        "ORDER BY s.enrollment_id, s.end_date"
    ).fetchall()


def active_without_subscription(conn) -> list:
    """Live paid enrollments with no subscription left (e.g. the only one was cancelled)."""
    return conn.execute(
        """
        SELECT e.id AS enrollment_id, e.student_id, st.student_number, st.last_name,
               st.first_name, e.group_id, g.name AS group_name, sb.name AS subject,
               l.name AS level, e.enrolled_on
          FROM enrollments e
          JOIN students st ON st.id = e.student_id
          JOIN class_groups g ON g.id = e.group_id
          JOIN subjects sb ON sb.id = g.subject_id
          JOIN levels l ON l.id = g.level_id
         WHERE e.status = 'active' AND g.status <> 'closed'
           AND NOT EXISTS (SELECT 1 FROM subscriptions s
                            WHERE s.enrollment_id = e.id AND s.status <> 'cancelled')
         ORDER BY fold(st.last_name), fold(st.first_name)
        """
    ).fetchall()
