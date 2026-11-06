import sqlite3

import pytest


def alloc(c, payment, charge, amount):
    c.execute("INSERT INTO payment_allocations(payment_id,charge_id,amount) VALUES(?,?,?)",
              (payment, charge, amount))


def test_payment_is_immutable(seeded):
    with pytest.raises(sqlite3.IntegrityError):
        seeded.execute("UPDATE payments SET amount=1 WHERE id=1")
    with pytest.raises(sqlite3.IntegrityError):
        seeded.execute("DELETE FROM payments WHERE id=1")


def test_audit_log_is_immutable(seeded):
    seeded.execute("INSERT INTO audit_log(user_id,action,entity_name) VALUES(1,'x','y')")
    with pytest.raises(sqlite3.IntegrityError):
        seeded.execute("DELETE FROM audit_log")


def test_allocation_cannot_exceed_payment(seeded):
    with pytest.raises(sqlite3.IntegrityError, match="exceed payment"):
        alloc(seeded, 1, 1, 3001)


def test_allocation_cannot_exceed_charge(seeded):
    seeded.execute("INSERT INTO payments(student_id,amount,method,paid_at,received_by) "
                   "VALUES(1,500,'cash','2026-09-03T10:00:00',1)")
    alloc(seeded, 1, 1, 3000)
    with pytest.raises(sqlite3.IntegrityError, match="exceed charge"):
        alloc(seeded, 2, 1, 500)


def test_voided_payment_frees_charge_and_blocks_allocation(seeded):
    alloc(seeded, 1, 1, 3000)
    seeded.execute("INSERT INTO payment_voids(payment_id,reason,voided_by) VALUES(1,'error',1)")
    with pytest.raises(sqlite3.IntegrityError, match="voided"):
        alloc(seeded, 1, 1, 100)


def test_void_after_teacher_payout(seeded):
    """0016: a payout pays the month's full price whether it was paid or not, so it does not
    stop a void (it changes nothing the payout counts)."""
    alloc(seeded, 1, 1, 3000)
    seeded.execute("INSERT INTO teacher_payouts(teacher_id,period_start,period_end,base_amount,amount_due) "
                   "VALUES(1,'2026-09-01','2026-09-30',3000,1800)")
    seeded.execute("INSERT INTO payout_lines(payout_id,group_id,revenue_basis,percentage_bp,amount) "
                   "VALUES(1,1,3000,6000,1800)")
    seeded.execute("INSERT INTO payout_line_charges(payout_line_id,charge_id,amount) VALUES(1,1,3000)")
    seeded.execute("UPDATE teacher_payouts SET status = 'approved' WHERE id = 1")
    seeded.execute("INSERT INTO payment_voids(payment_id,reason,voided_by) VALUES(1,'x',1)")
    assert seeded.execute("SELECT COUNT(*) FROM payment_voids").fetchone()[0] == 1


def test_charge_amount_cannot_change(seeded):
    with pytest.raises(sqlite3.IntegrityError):
        seeded.execute("UPDATE charges SET amount=1 WHERE id=1")


def alloc_with(c, payment, charge, amount, recorded_with):
    c.execute("INSERT INTO payment_allocations(payment_id,charge_id,amount,recorded_with) "
              "VALUES(?,?,?,?)", (payment, charge, amount, recorded_with))


def test_a_payment_pays_a_charge_again_in_a_later_recording(seeded):
    """0018: its own recording, then a later one using its credit; never twice in one."""
    seeded.execute("INSERT INTO payments(student_id,amount,method,paid_at,received_by) "
                   "VALUES(1,100,'cash','2026-09-03T10:00:00',1)")
    alloc_with(seeded, 1, 1, 1000, 1)
    alloc_with(seeded, 1, 1, 1000, 2)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        alloc_with(seeded, 1, 1, 500, 2)
    with pytest.raises(sqlite3.IntegrityError, match="exceed payment"):
        alloc_with(seeded, 1, 1, 1001, None)  # 3 000 at most, whatever the rows


def test_0018_keeps_every_allocation_and_its_id():
    """A version 17 database: the rows, their ids and the next id are kept; the same payment
    can then pay its charge again."""
    from tadris.db.connection import connect
    from tadris.db.migrate import _files, latest_version, migrate

    c = connect(":memory:")
    for version, file in _files():
        if version > 17:
            break
        c.executescript(f"BEGIN IMMEDIATE;\n{file.read_text(encoding='utf-8')}\n"
                        f"PRAGMA user_version = {version};\nCOMMIT;")
    c.executescript("""
    INSERT INTO school_years(label,start_date,end_date) VALUES('2026-2027','2026-09-01','2027-06-30');
    INSERT INTO levels(name) VALUES('3AM');
    INSERT INTO users(username,password_hash,role) VALUES('u','x','director');
    INSERT INTO students(student_number,first_name,last_name) VALUES('2026-0001','A','B');
    INSERT INTO registrations(student_id,school_year_id,level_id,fee_amount) VALUES(1,1,1,2000);
    INSERT INTO charges(registration_id,description,amount,due_date,accrual_date)
      VALUES(1,'Frais',2000,'2026-09-01','2026-09-01');
    INSERT INTO charges(registration_id,description,amount,due_date,accrual_date)
      VALUES(1,'Frais bis',500,'2026-09-01','2026-09-01');
    INSERT INTO payments(student_id,amount,method,paid_at,received_by)
      VALUES(1,3000,'cash','2026-09-02T10:00:00',1);
    INSERT INTO payment_allocations(payment_id,charge_id,amount,recorded_with) VALUES(1,1,500,1);
    INSERT INTO payment_allocations(payment_id,charge_id,amount) VALUES(1,2,500);  -- before 0016
    """)
    before = [tuple(r) for r in c.execute("SELECT * FROM payment_allocations ORDER BY id")]
    assert migrate(c) == latest_version()
    assert [tuple(r) for r in c.execute("SELECT * FROM payment_allocations ORDER BY id")] == before
    c.execute("INSERT INTO payments(student_id,amount,method,paid_at,received_by) "
              "VALUES(1,100,'cash','2026-09-03T10:00:00',1)")
    alloc_with(c, 1, 1, 500, 2)  # refused by the old UNIQUE (payment, charge)
    assert c.execute("SELECT MAX(id) FROM payment_allocations").fetchone()[0] == 3
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        c.execute("DELETE FROM payment_allocations")
