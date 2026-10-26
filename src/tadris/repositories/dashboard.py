"""SQL for the dashboard: read only.

Money follows the payments repository: what was paid on a charge is what payments not voided
allocated to it; a charge counts in the month of its accrual date (a month on its first day,
the fee on the registration day); cancelled charges are left out.
"""

_PAID = """
    COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa
               WHERE pa.charge_id = c.id
                 AND NOT EXISTS (SELECT 1 FROM payment_voids v
                                  WHERE v.payment_id = pa.payment_id)), 0)
"""


def charged_between(conn, first: str, last: str) -> tuple[int, int]:
    """(charged, settled): the charges not cancelled with an accrual date in [first, last],
    and what payments not voided paid on them."""
    row = conn.execute(
        f"""
        SELECT COALESCE(SUM(c.amount), 0), COALESCE(SUM({_PAID}), 0)
          FROM charges c
         WHERE c.status = 'open' AND c.accrual_date BETWEEN ? AND ?
        """,
        (first, last),
    ).fetchone()
    return row[0], row[1]


def collected_by_day(conn, first: str, last: str) -> dict[str, int]:
    """{'YYYY-MM-DD': amount} of payments not voided received in [first, last]."""
    rows = conn.execute(
        """
        SELECT substr(p.paid_at, 1, 10) AS day, SUM(p.amount) AS amount
          FROM payments p
         WHERE substr(p.paid_at, 1, 10) BETWEEN ? AND ?
           AND NOT EXISTS (SELECT 1 FROM payment_voids v WHERE v.payment_id = p.id)
         GROUP BY day
        """,
        (first, last),
    ).fetchall()
    return {row["day"]: row["amount"] for row in rows}


def session_days(conn, first: str, last: str) -> set[str]:
    """The days in [first, last] with a session, cancelled ones included."""
    rows = conn.execute("SELECT DISTINCT date FROM sessions WHERE date BETWEEN ? AND ?",
                        (first, last)).fetchall()
    return {row["date"] for row in rows}


def slot_weekdays(conn, day: str) -> set[int]:
    """The weekdays (1 = Monday) of the slots of groups not closed, running on day or
    later."""
    rows = conn.execute(
        """
        SELECT DISTINCT ts.weekday
          FROM timetable_slots ts
          JOIN class_groups g ON g.id = ts.group_id
         WHERE g.status <> 'closed' AND (ts.valid_to IS NULL OR ts.valid_to > ?)
        """,
        (day,),
    ).fetchall()
    return {row["weekday"] for row in rows}
