"""The phase 8 refunds (migration 0015): the refund tables of an older database are kept as
read-only archives, and a payment some of whose money was handed back still cannot be
voided. Refunds came back in V1 with new tables (0021), next to the archive."""

import re
import sqlite3
from datetime import date

import pytest

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError
from tadris.db.connection import connect
from tadris.db.migrate import _files, migrate
from tadris.i18n.fr import t
from tadris.services import refunds


def refused(message: str):
    return pytest.raises(sqlite3.IntegrityError, match=re.escape(message))


def test_a_new_database_has_the_v1_tables_and_the_archive(conn):
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"refunds", "refund_allocations"} <= names  # 0021
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


# ----- what the archive handed back is never handed back again (REVIEW_FIXES, finding 5) -----

def new_request(c, amount, value=3000) -> int:
    return c.execute(
        "INSERT INTO refunds(charge_id,counted_from,sessions_total,sessions_left,"
        "sessions_value,max_amount,amount_requested,reason,requested_by,requested_at) "
        "VALUES(1,'2026-09-02',4,4,?,?,?,'Départ',1,'2026-09-16T10:00:00')",
        (value, value, amount)).lastrowid


def test_new_refund_ids_continue_after_the_archive(older):
    """A new refund never reuses an archived id, so the print log and the Journal never mix
    them (REVIEW_FIXES round 2, finding 4)."""
    migrate(older)
    assert [r[0] for r in older.execute("SELECT id FROM archived_refunds ORDER BY id")] == [1, 2]
    older.execute("INSERT INTO print_log(document_type, document_id, printed_by) "
                  "VALUES('refund', 1, 1)")
    first = new_request(older, 1000)
    assert first == 3
    assert older.execute(
        "SELECT COUNT(*) FROM print_log WHERE document_type = 'refund' AND document_id = 3"
    ).fetchone()[0] == 0


def test_the_archive_caps_a_new_request_and_its_approval(older):
    """3 000 paid, 1 000 handed back by the archive: at most 2 000 more, asked or approved."""
    migrate(older)
    with refused("refund exceeds paid minus already refunded"):
        new_request(older, 2500)
    first = new_request(older, 1500)
    with refused("refund exceeds paid minus already refunded"):
        new_request(older, 600)
    older.execute("UPDATE refunds SET status='approved', amount_approved=1500, decided_by=1, "
                  "decided_at='2026-09-16T11:00:00' WHERE id=?", (first,))
    new_request(older, 500)


def test_the_service_counts_what_the_archive_handed_back(older, monkeypatch):
    """Group G1 meets on Mondays; the student left on 01/09, so September (3 000) has all
    four sessions left. 1 000 went back in the archive: 2 000 at most, and it can be paid
    out (the payment still holds 2 000)."""
    migrate(older)
    older.executescript("""
    INSERT INTO rooms(name,capacity) VALUES('Salle 1',20);
    INSERT INTO timetable_slots(group_id,room_id,weekday,start_time,end_time,valid_from)
      VALUES(1,1,1,'17:00','18:30','2026-09-01');
    UPDATE enrollments SET status='left', left_on='2026-09-01' WHERE id=1;
    """)
    monkeypatch.setattr(dates, "today", lambda: date(2026, 9, 16))
    boss = UserContext(1, "u", "director")
    [month] = refunds.options(older, boss, 1)
    assert (month.sessions.value, month.held, month.max_amount) == (3000, 1000, 2000)
    with pytest.raises(BusinessRuleError,
                       match=re.escape(t["refund.above_max"].format(amount="2 000 DA"))):
        refunds.request(older, boss, 1, 2500, "Départ")
    refund = refunds.request(older, boss, 1, 2000, "Départ")
    refunds.approve(older, boss, refund)
    refunds.pay_out(older, boss, refund, "cash")
    assert refunds.get(older, boss, refund).status == "paid"
