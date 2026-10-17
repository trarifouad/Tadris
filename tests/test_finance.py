import sqlite3
import pytest


@pytest.fixture
def seeded(conn):
    conn.executescript("""
    INSERT INTO school_years(label,start_date,end_date) VALUES('2026-2027','2026-09-01','2027-06-30');
    INSERT INTO levels(name) VALUES('3AM');
    INSERT INTO subjects(name) VALUES('Math');
    INSERT INTO users(username,password_hash,role) VALUES('u','x','director');
    INSERT INTO students(student_number,first_name,last_name) VALUES('2026-0001','A','B');
    INSERT INTO teachers(full_name) VALUES('T');
    INSERT INTO registrations(student_id,school_year_id,level_id,fee_amount) VALUES(1,1,1,2000);
    INSERT INTO class_groups(school_year_id,level_id,subject_id,name,price,capacity,start_date)
      VALUES(1,1,1,'G1',3000,10,'2026-09-01');
    INSERT INTO enrollments(student_id,group_id,registration_id,enrolled_on) VALUES(1,1,1,'2026-09-01');
    INSERT INTO subscriptions(enrollment_id,price,start_date,end_date)
      VALUES(1,3000,'2026-09-01','2026-10-01');
    INSERT INTO charges(subscription_id,description,amount,due_date,accrual_date)
      VALUES(1,'Sept',3000,'2026-09-01','2026-09-01');
    INSERT INTO payments(student_id,amount,method,paid_at,received_by)
      VALUES(1,3000,'cash','2026-09-02T10:00:00',1);
    """)
    return conn


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
                   "VALUES(1,'2026-10-01','2026-10-31',3000,1800)")
    seeded.execute("INSERT INTO payout_lines(payout_id,group_id,revenue_basis,percentage_bp,amount) VALUES(1,1,3000,6000,1800)")
    seeded.execute("INSERT INTO payout_lines(payout_id,group_id,revenue_basis,percentage_bp,amount) VALUES(2,1,3000,6000,1800)")
    seeded.execute("INSERT INTO payout_line_charges(payout_line_id,charge_id,amount) VALUES(1,1,3000)")
    with pytest.raises(sqlite3.IntegrityError):
        seeded.execute("INSERT INTO payout_line_charges(payout_line_id,charge_id,amount) VALUES(2,1,3000)")
