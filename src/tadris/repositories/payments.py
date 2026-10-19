"""SQL for money received: payments, their allocations to charges, receipts and voids, and the
charges they pay.

A charge belongs to a student through its registration (the fee) or its subscription's
enrollment (a month). What was paid on a charge is the sum of its allocations from payments
not voided; an adjustment (balance_entries, phase 8) linked to a charge lowers it too. Rows
here are never updated or deleted (triggers): a void is a new row.
"""

# The student of a charge, whatever its parent.
_CHARGE_STUDENT = """
    COALESCE((SELECT r.student_id FROM registrations r WHERE r.id = c.registration_id),
             (SELECT e.student_id FROM subscriptions s
                JOIN enrollments e ON e.id = s.enrollment_id
               WHERE s.id = c.subscription_id))
"""
_CHARGE_PAID = """
    COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa
               WHERE pa.charge_id = c.id
                 AND NOT EXISTS (SELECT 1 FROM payment_voids v
                                  WHERE v.payment_id = pa.payment_id)), 0)
"""
_CHARGE_ADJUSTED = """
    COALESCE((SELECT SUM(b.amount) FROM balance_entries b WHERE b.charge_id = c.id), 0)
"""
_CHARGE_COLUMNS = f"""
    c.id, ({_CHARGE_STUDENT}) AS student_id, c.registration_id, c.subscription_id,
    c.description, c.amount, c.due_date, c.status,
    {_CHARGE_PAID} AS paid, {_CHARGE_ADJUSTED} AS adjusted,
    (SELECT e.group_id FROM subscriptions s JOIN enrollments e ON e.id = s.enrollment_id
      WHERE s.id = c.subscription_id) AS group_id
"""


def open_charges(conn, student_id: int | None = None) -> list:
    """Open charges, oldest due first (the order payments pay them in); one student's, or
    everyone's for the debtors list."""
    return conn.execute(
        f"SELECT * FROM (SELECT {_CHARGE_COLUMNS} FROM charges c WHERE c.status = 'open') "
        "WHERE (:student IS NULL OR student_id = :student) ORDER BY due_date, id",
        {"student": student_id},
    ).fetchall()


def charge(conn, charge_id: int):
    return conn.execute(f"SELECT {_CHARGE_COLUMNS} FROM charges c WHERE c.id = ?",
                        (charge_id,)).fetchone()


def unlinked_adjustments(conn, student_id: int | None = None) -> list:
    """Adjustments not tied to a charge, summed per student (rows: student_id, total)."""
    return conn.execute(
        "SELECT student_id, SUM(amount) AS total FROM balance_entries "
        "WHERE charge_id IS NULL AND (:student IS NULL OR student_id = :student) "
        "GROUP BY student_id",
        {"student": student_id},
    ).fetchall()


# ----- payments -----

_PAYMENT_COLUMNS = """
    p.id, p.student_id, st.student_number, st.last_name, st.first_name,
    p.payer_contact_id, ct.full_name AS payer_name, p.amount, p.method, p.paid_at,
    p.received_by, u.username AS cashier, rc.id AS receipt_id, rc.number AS receipt_number,
    COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa
               WHERE pa.payment_id = p.id), 0) AS allocated,
    v.id IS NOT NULL AS voided, v.reason AS void_reason, v.voided_at,
    vu.username AS voided_by
"""
_PAYMENT_FROM = """
    FROM payments p
    JOIN students st ON st.id = p.student_id
    JOIN users u ON u.id = p.received_by
    LEFT JOIN contacts ct ON ct.id = p.payer_contact_id
    LEFT JOIN receipts rc ON rc.payment_id = p.id
    LEFT JOIN payment_voids v ON v.payment_id = p.id
    LEFT JOIN users vu ON vu.id = v.voided_by
"""


def get(conn, payment_id: int):
    return conn.execute(f"SELECT {_PAYMENT_COLUMNS} {_PAYMENT_FROM} WHERE p.id = ?",
                        (payment_id,)).fetchone()


def for_student(conn, student_id: int) -> list:
    """Latest first."""
    return conn.execute(
        f"SELECT {_PAYMENT_COLUMNS} {_PAYMENT_FROM} WHERE p.student_id = ? "
        "ORDER BY p.paid_at DESC, p.id DESC",
        (student_id,),
    ).fetchall()


def on_day(conn, day: str) -> list:
    """Payments received on one day ('YYYY-MM-DD'), voided ones included, in order."""
    return conn.execute(
        f"SELECT {_PAYMENT_COLUMNS} {_PAYMENT_FROM} WHERE substr(p.paid_at, 1, 10) = ? "
        "ORDER BY p.paid_at, p.id",
        (day,),
    ).fetchall()


def with_credit(conn, student_id: int | None = None) -> list:
    """Payments not voided with an amount left to allocate, oldest first (rows: id,
    student_id, amount, allocated)."""
    return conn.execute(
        """
        SELECT * FROM (
            SELECT p.id, p.student_id, p.amount,
                   COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa
                              WHERE pa.payment_id = p.id), 0) AS allocated
              FROM payments p
             WHERE NOT EXISTS (SELECT 1 FROM payment_voids v WHERE v.payment_id = p.id)
               AND (:student IS NULL OR p.student_id = :student))
         WHERE allocated < amount
         ORDER BY id
        """,
        {"student": student_id},
    ).fetchall()


def allocations(conn, payment_id: int) -> list:
    """What a payment paid, in the order of the charges' due dates."""
    return conn.execute(
        """
        SELECT pa.id, pa.charge_id, pa.amount, c.description, c.due_date, c.amount AS charge_amount
          FROM payment_allocations pa
          JOIN charges c ON c.id = pa.charge_id
         WHERE pa.payment_id = ?
         ORDER BY c.due_date, c.id
        """,
        (payment_id,),
    ).fetchall()


def insert(conn, student_id: int, payer_contact_id: int | None, amount: int, method: str,
           paid_at: str, received_by: int) -> int:
    cur = conn.execute(
        "INSERT INTO payments(student_id, payer_contact_id, amount, method, paid_at, received_by) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (student_id, payer_contact_id, amount, method, paid_at, received_by),
    )
    return int(cur.lastrowid)


def insert_allocation(conn, payment_id: int, charge_id: int, amount: int) -> int:
    cur = conn.execute(
        "INSERT INTO payment_allocations(payment_id, charge_id, amount) VALUES (?, ?, ?)",
        (payment_id, charge_id, amount),
    )
    return int(cur.lastrowid)


def insert_receipt(conn, payment_id: int, number: str, issued_at: str) -> int:
    cur = conn.execute(
        "INSERT INTO receipts(payment_id, number, issued_at) VALUES (?, ?, ?)",
        (payment_id, number, issued_at),
    )
    return int(cur.lastrowid)


def insert_void(conn, payment_id: int, reason: str, voided_by: int, voided_at: str) -> int:
    cur = conn.execute(
        "INSERT INTO payment_voids(payment_id, reason, voided_by, voided_at) "
        "VALUES (?, ?, ?, ?)",
        (payment_id, reason, voided_by, voided_at),
    )
    return int(cur.lastrowid)


def receipt(conn, receipt_id: int):
    return conn.execute("SELECT id, payment_id, number, issued_at FROM receipts WHERE id = ?",
                        (receipt_id,)).fetchone()


# ----- the debtors list -----

def live_groups(conn) -> list:
    """(student_id, group_id) for every live enrollment (trial or active)."""
    return conn.execute(
        "SELECT student_id, group_id FROM enrollments WHERE status IN ('trial', 'active')"
    ).fetchall()


def students(conn, student_ids: list[int]) -> list:
    if not student_ids:
        return []
    marks = ", ".join("?" for _ in student_ids)
    return conn.execute(
        f"SELECT id, student_number, last_name, first_name, status FROM students "
        f"WHERE id IN ({marks})",
        student_ids,
    ).fetchall()
