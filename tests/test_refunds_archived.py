"""V1 has no refunds (migration 0015): the refund tables of an older database are kept as
read-only archives, and a payment some of whose money was handed back still cannot be
voided."""

import re
import sqlite3

import pytest

from tadris.db.connection import connect
from tadris.db.migrate import _files, migrate


def refused(message: str):
    return pytest.raises(sqlite3.IntegrityError, match=re.escape(message))


def test_a_new_database_has_no_refund_tables(conn):
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"refunds", "refund_allocations"}.isdisjoint(names)
    assert {"archived_refunds", "archived_refund_allocations"} <= names
    with refused("archived refunds are read-only"):
        conn.execute("INSERT INTO archived_refunds(charge_id,amount_computed,amount_final,"
                     "reason) VALUES(1,1,1,'x')")


@pytest.fixture
def older():
    """A version 14 database with a month paid 3 000, a refund of 1 000 paid out and one of
    500 still pending."""
    c = connect(":memory:")
    for version, file in _files():
        if version > 14:
            break
        c.executescript(f"BEGIN IMMEDIATE;\n{file.read_text(encoding='utf-8')}\n"
                        f"PRAGMA user_version = {version};\nCOMMIT;")
    c.executescript("""
    INSERT INTO school_years(label,start_date,end_date) VALUES('2026-2027','2026-09-01','2027-06-30');
    INSERT INTO levels(name) VALUES('3AM');
    INSERT INTO subjects(name) VALUES('Math');
    INSERT INTO users(username,password_hash,role) VALUES('u','x','director');
    INSERT INTO students(student_number,first_name,last_name) VALUES('2026-0001','A','B');
    INSERT INTO registrations(student_id,school_year_id,level_id,fee_amount) VALUES(1,1,1,0);
    INSERT INTO class_groups(school_year_id,level_id,subject_id,name,price,capacity,start_date)
      VALUES(1,1,1,'G1',3000,10,'2026-09-01');
    INSERT INTO enrollments(student_id,group_id,registration_id,enrolled_on)
      VALUES(1,1,1,'2026-09-01');
    INSERT INTO subscriptions(enrollment_id,price,start_date,end_date)
      VALUES(1,3000,'2026-09-01','2026-10-01');
    INSERT INTO charges(subscription_id,description,amount,due_date,accrual_date)
      VALUES(1,'Sept',3000,'2026-09-01','2026-09-01');
    INSERT INTO payments(student_id,amount,method,paid_at,received_by)
      VALUES(1,3000,'cash','2026-09-02T10:00:00',1);
    INSERT INTO payment_allocations(payment_id,charge_id,amount) VALUES(1,1,3000);
    INSERT INTO refunds(charge_id,subscription_id,amount_computed,amount_final,reason)
      VALUES(1,1,1000,1000,'Départ');
    INSERT INTO refund_allocations(refund_id,payment_allocation_id,amount) VALUES(1,1,1000);
    UPDATE refunds SET status='approved', approved_by=1 WHERE id=1;
    UPDATE refunds SET status='paid', refunded_amount=1000, number='RB2026-00001',
      method='cash', paid_out_at='2026-09-03T10:00:00' WHERE id=1;
    INSERT INTO refunds(charge_id,subscription_id,amount_computed,amount_final,reason)
      VALUES(1,1,500,500,'Autre');
    """)
    yield c
    c.close()


def test_an_older_database_keeps_its_refunds(older):
    assert migrate(older) >= 15
    rows = [tuple(r) for r in older.execute(
        "SELECT id, status, amount_final, refunded_amount, number FROM archived_refunds "
        "ORDER BY id")]
    assert rows == [(1, "paid", 1000, 1000, "RB2026-00001"), (2, "pending", 500, 0, None)]
    assert [tuple(r) for r in older.execute(
        "SELECT refund_id, payment_allocation_id, amount FROM archived_refund_allocations")
    ] == [(1, 1, 1000)]
    assert older.execute("PRAGMA foreign_key_check").fetchall() == []
    assert older.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_the_archive_is_read_only(older):
    migrate(older)
    for sql in ("UPDATE archived_refunds SET status='rejected' WHERE id=2",
                "DELETE FROM archived_refunds WHERE id=2",
                "UPDATE archived_refund_allocations SET amount=1",
                "DELETE FROM archived_refund_allocations",
                ("INSERT INTO archived_refund_allocations(refund_id,payment_allocation_id,"
                 "amount) VALUES(2,1,100)")):
        with refused("archived refunds are read-only"):
            older.execute(sql)


def test_a_refunded_payment_still_cannot_be_voided(older):
    migrate(older)
    with refused("payment has refunds"):
        older.execute("INSERT INTO payment_voids(payment_id,reason,voided_by) VALUES(1,'x',1)")
