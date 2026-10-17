import sqlite3
import pytest




def test_charge_needs_exactly_one_parent(seeded):
    with pytest.raises(sqlite3.IntegrityError):
        seeded.execute("INSERT INTO charges(description,amount,due_date,accrual_date) "
                       "VALUES('x',100,'2026-09-01','2026-09-01')")
    with pytest.raises(sqlite3.IntegrityError):
        seeded.execute("INSERT INTO charges(registration_id,subscription_id,description,amount,due_date,accrual_date) "
                       "VALUES(1,1,'x',100,'2026-09-01','2026-09-01')")


def test_allocation_unique_per_payment_charge(seeded):
    seeded.execute("INSERT INTO payment_allocations(payment_id,charge_id,amount) VALUES(1,1,1000)")
    with pytest.raises(sqlite3.IntegrityError):
        seeded.execute("INSERT INTO payment_allocations(payment_id,charge_id,amount) VALUES(1,1,500)")


def test_subscription_renewed_once(seeded):
    seeded.execute("INSERT INTO subscriptions(enrollment_id,renewal_of_id,price,start_date,end_date) "
                   "VALUES(1,1,3000,'2026-10-01','2026-11-01')")
    with pytest.raises(sqlite3.IntegrityError):
        seeded.execute("INSERT INTO subscriptions(enrollment_id,renewal_of_id,price,start_date,end_date) "
                       "VALUES(1,1,3000,'2026-10-01','2026-11-01')")


def test_charge_paid_to_teacher_once(seeded):
    seeded.execute("INSERT INTO teacher_payouts(teacher_id,period_start,period_end,base_amount,amount_due) "
                   "VALUES(1,'2026-09-01','2026-09-30',3000,1800)")
    seeded.execute("INSERT INTO teacher_payouts(teacher_id,period_start,period_end,base_amount,amount_due) "
                   "VALUES(1,'2026-08-31','2026-09-30',3000,1800)")
    seeded.execute("INSERT INTO payout_lines(payout_id,group_id,revenue_basis,percentage_bp,amount) VALUES(1,1,3000,6000,1800)")
    seeded.execute("INSERT INTO payout_lines(payout_id,group_id,revenue_basis,percentage_bp,amount) VALUES(2,1,3000,6000,1800)")
    seeded.execute("INSERT INTO payout_line_charges(payout_line_id,charge_id,amount) VALUES(1,1,3000)")
    with pytest.raises(sqlite3.IntegrityError):
        seeded.execute("INSERT INTO payout_line_charges(payout_line_id,charge_id,amount) VALUES(2,1,3000)")
