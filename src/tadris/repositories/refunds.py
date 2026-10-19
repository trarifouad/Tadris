"""SQL for refunds: money handed back on one charge (a month or the registration fee).

A refund is asked (pending), decided (approved or rejected), then paid out: its
refund_allocations take the money back from the payments that paid the charge, never more
than each one gave (0004, 0012). Paid and rejected refunds never change.
"""

_STUDENT = """
    COALESCE((SELECT rg.student_id FROM registrations rg WHERE rg.id = c.registration_id),
             (SELECT e.student_id FROM subscriptions s JOIN enrollments e ON e.id = s.enrollment_id
               WHERE s.id = c.subscription_id))
"""
_COLUMNS = f"""
    r.id, r.charge_id, r.subscription_id, c.description, c.amount AS charge_amount,
    ({_STUDENT}) AS student_id, r.amount_computed, r.amount_final, r.refunded_amount, r.reason,
    r.status, rq.username AS requested_by, ap.username AS decided_by, r.approved_at,
    r.number, r.method, po.username AS paid_out_by, r.paid_out_at, r.created_at
"""
_FROM = """
    FROM refunds r
    JOIN charges c ON c.id = r.charge_id
    LEFT JOIN users rq ON rq.id = r.requested_by
    LEFT JOIN users ap ON ap.id = r.approved_by
    LEFT JOIN users po ON po.id = r.paid_out_by
"""


def get(conn, refund_id: int):
    return conn.execute(f"SELECT {_COLUMNS} {_FROM} WHERE r.id = ?", (refund_id,)).fetchone()


def for_student(conn, student_id: int) -> list:
    """Latest first."""
    return conn.execute(
        f"SELECT * FROM (SELECT {_COLUMNS} {_FROM}) WHERE student_id = ? "
        "ORDER BY created_at DESC, id DESC",
        (student_id,),
    ).fetchall()


def with_status(conn, statuses: tuple[str, ...]) -> list:
    """Oldest first: the director's queue."""
    marks = ", ".join("?" for _ in statuses)
    return conn.execute(
        f"SELECT {_COLUMNS} {_FROM} WHERE r.status IN ({marks}) ORDER BY r.created_at, r.id",
        statuses,
    ).fetchall()


def paid_on(conn, day: str) -> list:
    """Refunds paid out on one day ('YYYY-MM-DD'), in order."""
    return conn.execute(
        f"SELECT {_COLUMNS} {_FROM} WHERE substr(r.paid_out_at, 1, 10) = ? "
        "ORDER BY r.paid_out_at, r.id",
        (day,),
    ).fetchall()


def money_on_charge(conn, charge_id: int):
    """paid: by payments not voided; refunded: paid out; reserved: asked or approved, not
    paid out yet."""
    return conn.execute(
        """
        SELECT
          COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa
                     WHERE pa.charge_id = :charge
                       AND NOT EXISTS (SELECT 1 FROM payment_voids v
                                        WHERE v.payment_id = pa.payment_id)), 0) AS paid,
          COALESCE((SELECT SUM(refunded_amount) FROM refunds
                     WHERE charge_id = :charge AND status = 'paid'), 0) AS refunded,
          COALESCE((SELECT SUM(amount_final) FROM refunds
                     WHERE charge_id = :charge AND status IN ('pending', 'approved')), 0)
            AS reserved
        """,
        {"charge": charge_id},
    ).fetchone()


def charges_paid(conn, student_id: int) -> list:
    """The student's charges that payments not voided paid something on, open or cancelled,
    oldest due first: what a refund can be asked on."""
    return conn.execute(
        f"""
        SELECT * FROM (
            SELECT c.id, ({_STUDENT}) AS student_id, c.registration_id, c.subscription_id,
                   c.description, c.amount, c.due_date, c.status
              FROM charges c
             WHERE EXISTS (SELECT 1 FROM payment_allocations pa
                            WHERE pa.charge_id = c.id
                              AND NOT EXISTS (SELECT 1 FROM payment_voids v
                                               WHERE v.payment_id = pa.payment_id)))
         WHERE student_id = ? ORDER BY due_date, id
        """,
        (student_id,),
    ).fetchall()


def allocations_left(conn, charge_id: int) -> list:
    """What each payment not voided gave the charge and has not had back yet, newest payment
    first (the latest money goes back first). Rows: id, payment_id, remaining."""
    return conn.execute(
        """
        SELECT * FROM (
            SELECT pa.id, pa.payment_id,
                   pa.amount - COALESCE((SELECT SUM(ra.amount) FROM refund_allocations ra
                                          WHERE ra.payment_allocation_id = pa.id), 0) AS remaining
              FROM payment_allocations pa
             WHERE pa.charge_id = ?
               AND NOT EXISTS (SELECT 1 FROM payment_voids v WHERE v.payment_id = pa.payment_id))
         WHERE remaining > 0
         ORDER BY payment_id DESC, id DESC
        """,
        (charge_id,),
    ).fetchall()


def insert(conn, charge_id: int, subscription_id: int | None, amount_computed: int,
           amount_final: int, reason: str, requested_by: int, created_at: str) -> int:
    cur = conn.execute(
        "INSERT INTO refunds(charge_id, subscription_id, amount_computed, amount_final, reason, "
        "requested_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (charge_id, subscription_id, amount_computed, amount_final, reason, requested_by,
         created_at),
    )
    return int(cur.lastrowid)


def decide(conn, refund_id: int, status: str, decided_by: int, decided_at: str,
           amount_final: int) -> None:
    conn.execute(
        "UPDATE refunds SET status = ?, approved_by = ?, approved_at = ?, amount_final = ? "
        "WHERE id = ?",
        (status, decided_by, decided_at, amount_final, refund_id),
    )


def insert_allocation(conn, refund_id: int, payment_allocation_id: int, amount: int) -> None:
    conn.execute(
        "INSERT INTO refund_allocations(refund_id, payment_allocation_id, amount) VALUES (?, ?, ?)",
        (refund_id, payment_allocation_id, amount),
    )


def mark_paid(conn, refund_id: int, number: str, method: str, paid_out_by: int,
              paid_out_at: str, amount: int) -> None:
    conn.execute(
        "UPDATE refunds SET status = 'paid', refunded_amount = ?, number = ?, method = ?, "
        "paid_out_by = ?, paid_out_at = ? WHERE id = ?",
        (amount, number, method, paid_out_by, paid_out_at, refund_id),
    )
