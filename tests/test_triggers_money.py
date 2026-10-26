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
