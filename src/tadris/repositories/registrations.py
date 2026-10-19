"""SQL for registrations (a student, a school year, a level) and their fee charge.

One registration per student and year (unique). The fee charge is the registration's charge,
open or cancelled; what was paid on it is derived from allocations of payments not voided.
"""

# The fee charge: the open one of an active registration (none when its fee is 0), the
# latest one of a cancelled registration. A registration made again has one per attempt.
_FEE_CHARGE = """
    SELECT c.id FROM charges c
     WHERE c.registration_id = r.id AND (r.status = 'cancelled' OR c.status = 'open')
     ORDER BY c.id DESC LIMIT 1
"""
_COLUMNS = f"""
    r.id, r.student_id, r.school_year_id, y.label AS year_label, y.status AS year_status,
    r.level_id, l.name AS level, r.fee_amount, r.status, r.registered_at,
    (SELECT COUNT(*) FROM enrollments e
      WHERE e.registration_id = r.id AND e.status IN ('trial', 'active')) AS live_enrollments,
    ({_FEE_CHARGE}) AS fee_charge_id,
    (SELECT c.status FROM charges c WHERE c.id = ({_FEE_CHARGE})) AS fee_charge_status,
    COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa
               WHERE pa.charge_id = ({_FEE_CHARGE})
                 AND NOT EXISTS (SELECT 1 FROM payment_voids v
                                  WHERE v.payment_id = pa.payment_id)), 0) AS fee_paid,
    COALESCE((SELECT SUM(rf.refunded_amount) FROM refunds rf
               WHERE rf.charge_id = ({_FEE_CHARGE}) AND rf.status = 'paid'), 0) AS fee_refunded
"""
_FROM = """
    FROM registrations r
    JOIN school_years y ON y.id = r.school_year_id
    JOIN levels l ON l.id = r.level_id
"""


def get(conn, registration_id: int):
    return conn.execute(f"SELECT {_COLUMNS} {_FROM} WHERE r.id = ?",
                        (registration_id,)).fetchone()


def for_student_year(conn, student_id: int, year_id: int):
    return conn.execute(
        f"SELECT {_COLUMNS} {_FROM} WHERE r.student_id = ? AND r.school_year_id = ?",
        (student_id, year_id),
    ).fetchone()


def for_student(conn, student_id: int) -> list:
    return conn.execute(
        f"SELECT {_COLUMNS} {_FROM} WHERE r.student_id = ? ORDER BY y.start_date DESC",
        (student_id,),
    ).fetchall()


def insert(conn, student_id: int, year_id: int, level_id: int, fee_amount: int,
           registered_at: str) -> int:
    cur = conn.execute(
        "INSERT INTO registrations(student_id, school_year_id, level_id, fee_amount, "
        "registered_at) VALUES (?, ?, ?, ?, ?)",
        (student_id, year_id, level_id, fee_amount, registered_at),
    )
    return int(cur.lastrowid)


def reactivate(conn, registration_id: int, level_id: int, fee_amount: int,
               registered_at: str) -> None:
    """A cancelled registration made again: new level, fee and registration date."""
    conn.execute(
        """
        UPDATE registrations
           SET status = 'active', level_id = ?, fee_amount = ?, registered_at = ?
         WHERE id = ?
        """,
        (level_id, fee_amount, registered_at, registration_id),
    )


def set_level(conn, registration_id: int, level_id: int) -> None:
    conn.execute("UPDATE registrations SET level_id = ? WHERE id = ?",
                 (level_id, registration_id))


def set_status(conn, registration_id: int, status: str) -> None:
    conn.execute("UPDATE registrations SET status = ? WHERE id = ?", (status, registration_id))


def insert_fee_charge(conn, registration_id: int, description: str, amount: int,
                      on: str) -> int:
    cur = conn.execute(
        "INSERT INTO charges(registration_id, description, amount, due_date, accrual_date) "
        "VALUES (?, ?, ?, ?, ?)",
        (registration_id, description, amount, on, on),
    )
    return int(cur.lastrowid)


def cancel_charge(conn, charge_id: int) -> None:
    conn.execute("UPDATE charges SET status = 'cancelled' WHERE id = ?", (charge_id,))
