"""Refunds in V1 (migration 0021), at the database: the services refuse these cases first, so
only raw SQL reaches the triggers. Each test makes one rule fire, with its exact message.

The `seeded` fixture: user 1, student 1 with registration 1 (fee 2 000), group 1, enrollment
1, subscription 1 (01/09 to 01/10) with charge 1 (3 000), payment 1 (3 000, not allocated).
"""

import re
import sqlite3

import pytest

from tadris.db.connection import connect
from tadris.db.migrate import _files, latest_version, migrate

NOW = "2026-09-20T10:00:00"


def refused(message: str):
    return pytest.raises(sqlite3.IntegrityError, match=re.escape(message))


def one(c, sql, params=()) -> int:
    return c.execute(sql, params).lastrowid


def alloc(c, payment, charge, amount) -> int:
    return one(c, "INSERT INTO payment_allocations(payment_id,charge_id,amount) VALUES(?,?,?)",
               (payment, charge, amount))


def pay(c, amount) -> int:
    return one(c, "INSERT INTO payments(student_id,amount,method,paid_at,received_by) "
                  "VALUES(1,?,'cash','2026-09-02T10:00:00',1)", (amount,))


def void(c, payment) -> None:
    c.execute("INSERT INTO payment_voids(payment_id,reason,voided_by) VALUES(?,'x',1)",
              (payment,))


def ask(c, amount, value=2000, max_amount=None, charge=1, **columns) -> int:
    """A request on the month: 8 sessions, 6 left from 20/09 (value 2 000 by default)."""
    values = {"charge_id": charge, "counted_from": "2026-09-20", "sessions_total": 8,
              "sessions_left": 6, "sessions_value": value,
              "max_amount": value if max_amount is None else max_amount,
              "amount_requested": amount, "reason": "Départ", "requested_by": 1,
              "requested_at": NOW, **columns}
    names = ",".join(values)
    marks = ",".join("?" * len(values))
    return one(c, f"INSERT INTO refunds({names}) VALUES({marks})", tuple(values.values()))


def approve(c, refund, amount) -> None:
    c.execute("UPDATE refunds SET status='approved', amount_approved=?, decided_by=1, "
              "decided_at=? WHERE id=?", (amount, NOW, refund))


def take(c, refund, allocation, amount) -> int:
    return one(c, "INSERT INTO refund_allocations(refund_id,payment_allocation_id,amount) "
                  "VALUES(?,?,?)", (refund, allocation, amount))


def paid_out(c, refund, number="RB2026-00001") -> None:
    c.execute("UPDATE refunds SET status='paid', number=?, method='cash', paid_by=1, "
              "paid_at=? WHERE id=?", (number, NOW, refund))


def reject(c, refund, reason="Non") -> None:
    c.execute("UPDATE refunds SET status='rejected', decided_by=1, decided_at=?, "
              "close_reason=? WHERE id=?", (NOW, reason, refund))


def withdraw(c, refund, reason="Erreur") -> None:
    c.execute("UPDATE refunds SET status='cancelled', cancelled_by=1, cancelled_at=?, "
              "close_reason=? WHERE id=?", (NOW, reason, refund))


def status(c, refund) -> str:
    return c.execute("SELECT status FROM refunds WHERE id=?", (refund,)).fetchone()[0]


@pytest.fixture
def paid(seeded):
    """The month paid in full by payment 1 (allocation 1)."""
    alloc(seeded, 1, 1, 3000)
    return seeded


# ----- asking -----

def test_a_request_starts_pending(paid):
    with refused("a new refund is pending"):
        ask(paid, 1000, status="approved")
    with refused("a new refund is pending"):
        ask(paid, 1000, number="RB2026-00001")
    with refused("a new refund is pending"):
        ask(paid, 1000, close_reason="x")
    with refused("a new refund is pending"):
        ask(paid, 1000, method="cash")
    with refused("a new refund is pending"):
        ask(paid, 1000, decided_at=NOW)


def test_the_registration_fee_is_not_refundable(seeded):
    fee = one(seeded, "INSERT INTO charges(registration_id,description,amount,due_date,"
                      "accrual_date) VALUES(1,'Frais',2000,'2026-09-01','2026-09-01')")
    alloc(seeded, 1, fee, 2000)
    with refused("registration fees are not refundable"):
        ask(seeded, 1000, charge=fee)


def test_a_cancelled_month_is_not_refundable(seeded):
    seeded.execute("UPDATE charges SET status='cancelled' WHERE id=1")
    with refused("charge is cancelled"):
        ask(seeded, 1000)


def test_only_a_month_paid_in_full(seeded):
    alloc(seeded, 1, 1, 1500)
    with refused("month is not paid in full"):
        ask(seeded, 1000)


def test_a_voided_payment_does_not_pay_the_month(seeded):
    alloc(seeded, 1, 1, 3000)
    void(seeded, 1)
    with refused("month is not paid in full"):
        ask(seeded, 1000)


def test_never_more_than_the_maximum_asked(paid):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        ask(paid, 1500, value=2000, max_amount=1000)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        ask(paid, 1000, value=2000, max_amount=2500)  # the maximum is within the value


def test_pending_and_approved_requests_reserve_their_amount(paid):
    first = ask(paid, 1200)
    with refused("refund exceeds the value of the sessions left"):
        ask(paid, 1000)  # 1 200 kept + 1 000 > 2 000
    approve(paid, first, 1000)
    with refused("refund exceeds the value of the sessions left"):
        ask(paid, 1100)  # the approved amount is kept now: 1 000 + 1 100
    ask(paid, 1000)


def test_rejected_and_cancelled_requests_release_their_amount(paid):
    first = ask(paid, 2000)
    reject(paid, first)
    second = ask(paid, 2000)
    approve(paid, second, 2000)
    withdraw(paid, second)
    ask(paid, 2000)


def test_never_more_than_what_was_paid(paid):
    """The value of the sessions left comes from the service; the money paid is the last
    word."""
    with refused("refund exceeds paid minus already refunded"):
        ask(paid, 3500, value=5000)


# ----- deciding, withdrawing -----

def test_what_was_asked_never_changes(paid):
    refund = ask(paid, 1000)
    for column, value in (("amount_requested", 900), ("reason", "Autre"), ("charge_id", 2),
                          ("counted_from", "2026-09-25"), ("sessions_total", 9),
                          ("sessions_left", 2), ("sessions_value", 3000),
                          ("max_amount", 1500), ("requested_by", 2)):
        with refused("refund is locked"):
            paid.execute(f"UPDATE refunds SET {column}=? WHERE id=?", (value, refund))


def test_the_count_behind_the_maximum_is_kept_as_asked(paid):
    """The database never reads the timetable or the holidays: a change to them after the
    request changes nothing kept with it."""
    refund = ask(paid, 1500, value=1500)
    approve(paid, refund, 1500)
    row = paid.execute("SELECT counted_from, sessions_total, sessions_left, sessions_value, "
                       "max_amount FROM refunds WHERE id=?", (refund,)).fetchone()
    assert tuple(row) == ("2026-09-20", 8, 6, 1500, 1500)


def test_the_steps_go_one_way(paid):
    refund = ask(paid, 1000)
    with refused("refund cannot go to that status"):
        paid_out(paid, refund)  # not approved yet
    with refused("refund cannot go to that status"):
        paid.execute("UPDATE refunds SET requested_at=requested_at WHERE id=?", (refund,))
    approve(paid, refund, 1000)
    with refused("refund cannot go to that status"):
        paid.execute("UPDATE refunds SET status='pending' WHERE id=?", (refund,))
    with refused("refund cannot go to that status"):
        reject(paid, refund)  # approved: withdrawn, never rejected


def test_an_approval_says_who_when_and_how_much(paid):
    refund = ask(paid, 1000)
    with refused("refund decision needs who, when and the amount"):
        paid.execute("UPDATE refunds SET status='approved', amount_approved=1000 WHERE id=?",
                     (refund,))
    with refused("refund decision needs who, when and the amount"):
        paid.execute("UPDATE refunds SET status='approved', decided_by=1, decided_at=? "
                     "WHERE id=?", (NOW, refund))


def test_the_director_approves_the_amount_asked_or_less(paid):
    """Never more than asked, even within the maximum (REVIEW_FIXES, decision 3)."""
    refund = ask(paid, 1000, value=2000, max_amount=1500)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        approve(paid, refund, 1001)
    approve(paid, refund, 800)
    assert status(paid, refund) == "approved"


def test_an_approval_respects_what_others_keep(paid):
    ask(paid, 1000)
    second = ask(paid, 1000)
    with refused("refund exceeds the value of the sessions left"):
        approve(paid, second, 1500)  # 1 000 kept by the first


def test_an_approval_never_exceeds_what_was_paid(paid):
    refund = ask(paid, 2000, value=5000)
    with refused("refund exceeds paid minus already refunded"):
        approve(paid, refund, 3500)


def test_a_rejection_or_a_withdrawal_says_why(paid):
    refund = ask(paid, 1000)
    with refused("closed refund needs who, when and why"):
        reject(paid, refund, reason="  ")
    with refused("closed refund needs who, when and why"):
        paid.execute("UPDATE refunds SET status='cancelled', close_reason='x' WHERE id=?",
                     (refund,))


def test_a_decision_stays(paid):
    refund = ask(paid, 1000)
    approve(paid, refund, 1000)
    with refused("refund is locked"):
        paid.execute("UPDATE refunds SET decided_by=NULL WHERE id=?", (refund,))
    with refused("refund is locked"):
        paid.execute("UPDATE refunds SET amount_approved=900 WHERE id=?", (refund,))


def test_a_refund_with_money_taken_back_cannot_be_withdrawn(paid):
    refund = ask(paid, 1000)
    approve(paid, refund, 1000)
    take(paid, refund, 1, 1000)
    with refused("refund has money taken back"):
        withdraw(paid, refund)


def test_a_paid_refund_keeps_its_money(paid):
    """Paying a refund out never frees its amount: the same money cannot go back twice."""
    refund = ask(paid, 2000)
    approve(paid, refund, 2000)
    take(paid, refund, 1, 2000)
    paid_out(paid, refund)
    with refused("refund exceeds the value of the sessions left"):
        ask(paid, 1)
    with refused("refund exceeds paid minus already refunded"):
        ask(paid, 1001, value=5000)  # 2 000 handed back + 1 001 > 3 000 paid


def test_a_closed_refund_never_changes(paid):
    rejected = ask(paid, 500)
    reject(paid, rejected)
    with refused("refund is locked"):
        paid.execute("UPDATE refunds SET close_reason='autre' WHERE id=?", (rejected,))
    with refused("refunds cannot be deleted"):
        paid.execute("DELETE FROM refunds WHERE id=?", (rejected,))


# ----- paying out -----

def test_a_full_refund_paid_out(paid):
    refund = ask(paid, 2000)
    approve(paid, refund, 2000)
    take(paid, refund, 1, 2000)
    paid_out(paid, refund)
    assert status(paid, refund) == "paid"
    with refused("refund is locked"):
        paid.execute("UPDATE refunds SET method='transfer' WHERE id=?", (refund,))


def test_a_step_cannot_set_another_step_s_fields(paid):
    """An approval cannot carry a payout number, a method or a cancel author
    (REVIEW_FIXES round 2, finding 10)."""
    refund = ask(paid, 1000)
    with refused("refund step fields do not match its status"):
        paid.execute("UPDATE refunds SET status='approved', amount_approved=1000, decided_by=1, "
                     "decided_at=?, number='RB2026-00001' WHERE id=?", (NOW, refund))
    with refused("refund step fields do not match its status"):
        paid.execute("UPDATE refunds SET status='approved', amount_approved=1000, decided_by=1, "
                     "decided_at=?, method='cash' WHERE id=?", (NOW, refund))
    with refused("refund step fields do not match its status"):
        paid.execute("UPDATE refunds SET status='approved', amount_approved=1000, decided_by=1, "
                     "decided_at=?, cancelled_by=1 WHERE id=?", (NOW, refund))
    with refused("refund step fields do not match its status"):
        paid.execute("UPDATE refunds SET status='approved', amount_approved=1000, decided_by=1, "
                     "decided_at=?, close_reason='x' WHERE id=?", (NOW, refund))
    approve(paid, refund, 1000)
    with refused("refund step fields do not match its status"):
        paid.execute("UPDATE refunds SET status='cancelled', cancelled_by=1, cancelled_at=?, "
                     "close_reason='x', number='RB2026-00001' WHERE id=?", (NOW, refund))


def test_a_payout_says_its_number_method_who_and_when(paid):
    refund = ask(paid, 1000)
    approve(paid, refund, 1000)
    take(paid, refund, 1, 1000)
    with refused("refund payout needs its number, method, who and when"):
        paid.execute("UPDATE refunds SET status='paid', method='cash', paid_by=1, paid_at=? "
                     "WHERE id=?", (NOW, refund))


def test_a_payout_hands_back_exactly_what_was_approved(paid):
    refund = ask(paid, 1000)
    approve(paid, refund, 1000)
    take(paid, refund, 1, 600)
    with refused("refunded amount must match its allocations"):
        paid_out(paid, refund)


def test_numbers_are_unique(paid):
    first, second = ask(paid, 1000), ask(paid, 1000)
    for refund in (first, second):
        approve(paid, refund, 1000)
        take(paid, refund, 1, 1000)
    paid_out(paid, first)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        paid_out(paid, second)


# ----- refund_allocations -----

def test_money_goes_out_once_approved(paid):
    refund = ask(paid, 1000)
    with refused("refund must be approved before it is paid"):
        take(paid, refund, 1, 1000)


def test_money_comes_from_the_month_refunded(paid):
    fee = one(paid, "INSERT INTO charges(registration_id,description,amount,due_date,"
                    "accrual_date) VALUES(1,'Frais',2000,'2026-09-01','2026-09-01')")
    other = alloc(paid, pay(paid, 2000), fee, 2000)
    refund = ask(paid, 1000)
    approve(paid, refund, 1000)
    with refused("allocation belongs to another charge"):
        take(paid, refund, other, 1000)


def test_never_from_a_voided_payment(seeded):
    early = alloc(seeded, pay(seeded, 1000), 1, 1000)
    void(seeded, 2)
    alloc(seeded, 1, 1, 3000)
    refund = ask(seeded, 1000)
    approve(seeded, refund, 1000)
    with refused("payment is voided"):
        take(seeded, refund, early, 1000)


def test_each_payment_gives_back_at_most_what_it_gave(seeded):
    first = alloc(seeded, 1, 1, 1500)
    second = alloc(seeded, pay(seeded, 1500), 1, 1500)
    refund = ask(seeded, 2000)
    approve(seeded, refund, 2000)
    with refused("refund exceeds paid minus already refunded"):
        take(seeded, refund, second, 1600)
    take(seeded, refund, second, 1500)  # the latest payment first
    take(seeded, refund, first, 500)
    paid_out(seeded, refund)


def test_never_more_than_the_refund(seeded):
    first = alloc(seeded, 1, 1, 1500)
    second = alloc(seeded, pay(seeded, 1500), 1, 1500)
    refund = ask(seeded, 1000)
    approve(seeded, refund, 1000)
    take(seeded, refund, second, 700)
    with refused("refund allocations exceed refund amount"):
        take(seeded, refund, first, 400)


def test_refund_allocations_are_immutable(paid):
    refund = ask(paid, 1000)
    approve(paid, refund, 1000)
    take(paid, refund, 1, 1000)
    with refused("refund_allocations are immutable"):
        paid.execute("UPDATE refund_allocations SET amount=1")
    with refused("refund_allocations are immutable"):
        paid.execute("DELETE FROM refund_allocations")


# ----- voids -----

def test_a_payment_with_money_handed_back_cannot_be_voided(paid):
    refund = ask(paid, 1000)
    approve(paid, refund, 1000)
    take(paid, refund, 1, 1000)
    paid_out(paid, refund)
    with refused("payment has refunds"):
        void(paid, 1)


def test_no_void_while_a_request_is_open_on_the_month(paid):
    refund = ask(paid, 1000)
    with refused("payment paid a month with an open refund request"):
        void(paid, 1)
    approve(paid, refund, 1000)
    with refused("payment paid a month with an open refund request"):
        void(paid, 1)
    withdraw(paid, refund)
    void(paid, 1)  # nothing reserved any more


# ----- cancelling the month -----

def test_no_cancel_while_a_request_is_open(paid):
    ask(paid, 1000)
    with refused("charge has an open refund request"):
        paid.execute("UPDATE charges SET status='cancelled' WHERE id=1")


def test_no_cancel_while_money_paid_is_kept(paid):
    with refused("charge still holds money paid"):
        paid.execute("UPDATE charges SET status='cancelled' WHERE id=1")
    refund = ask(paid, 2000, value=3000)
    approve(paid, refund, 2000)
    take(paid, refund, 1, 2000)
    paid_out(paid, refund)
    with refused("charge still holds money paid"):  # 1 000 kept
        paid.execute("UPDATE charges SET status='cancelled' WHERE id=1")


def test_a_month_refunded_in_full_can_be_cancelled_and_pays_no_teacher(paid):
    """A month not started: every session left, refunded in full, then cancelled by hand. A
    payout no longer takes it (0013)."""
    refund = ask(paid, 3000, value=3000, counted_from="2026-09-01", sessions_left=8)
    approve(paid, refund, 3000)
    take(paid, refund, 1, 3000)
    paid_out(paid, refund)
    paid.execute("UPDATE charges SET status='cancelled' WHERE id=1")
    payout = one(paid, "INSERT INTO teacher_payouts(teacher_id,period_start,period_end,"
                       "base_amount,amount_due) VALUES(1,'2026-09-01','2026-09-30',3000,1800)")
    line = one(paid, "INSERT INTO payout_lines(payout_id,group_id,revenue_basis,"
                     "percentage_bp,amount) VALUES(?,1,3000,6000,1800)", (payout,))
    with refused("charge is not an open subscription charge"):
        paid.execute("INSERT INTO payout_line_charges(payout_line_id,charge_id,amount) "
                     "VALUES(?,1,3000)", (line,))


def test_a_month_paid_only_by_voided_payments_can_be_cancelled(seeded):
    alloc(seeded, 1, 1, 3000)
    void(seeded, 1)
    seeded.execute("UPDATE charges SET status='cancelled' WHERE id=1")


# ----- upgrade -----

def test_a_version_20_database_upgrades_and_keeps_its_money():
    c = connect(":memory:")
    for version, file in _files():
        if version > 20:
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
    INSERT INTO payments(student_id,amount,method,paid_at,received_by)
      VALUES(1,2000,'cash','2026-09-02T10:00:00',1);
    INSERT INTO payment_allocations(payment_id,charge_id,amount,recorded_with) VALUES(1,1,2000,1);
    """)
    before = [tuple(r) for r in c.execute("SELECT * FROM payment_allocations")]
    assert migrate(c) == latest_version() >= 21
    assert [tuple(r) for r in c.execute("SELECT * FROM payment_allocations")] == before
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with refused("charge still holds money paid"):
        c.execute("UPDATE charges SET status='cancelled' WHERE id=1")


def test_a_database_already_at_22_gains_enrollment_closure_and_insert_rules():
    """A first 0022 never added enrollments.closure_id; migrate() will not re-run it."""
    c = connect(":memory:")
    for version, file in _files():
        if version > 22:
            break
        c.executescript(f"BEGIN IMMEDIATE;\n{file.read_text(encoding='utf-8')}\n"
                        f"PRAGMA user_version = {version};\nCOMMIT;")
    cols = {row[1] for row in c.execute("PRAGMA table_info(enrollments)")}
    assert "closure_id" not in cols
    assert migrate(c) == latest_version() >= 24
    cols = {row[1] for row in c.execute("PRAGMA table_info(enrollments)")}
    assert "closure_id" in cols and "never_started" in cols
    ins = c.execute("SELECT sql FROM sqlite_master WHERE name='trg_refund_requests_ins'"
                    ).fetchone()[0]
    assert "close_reason" in ins
    att = c.execute("SELECT sql FROM sqlite_master WHERE name='trg_attendance_ins'").fetchone()[0]
    assert "never_started" in att
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []


def test_a_database_already_at_23_gains_never_started():
    """0024 is the only version that adds never_started; migrate() will not re-run 0004."""
    c = connect(":memory:")
    for version, file in _files():
        if version > 23:
            break
        c.executescript(f"BEGIN IMMEDIATE;\n{file.read_text(encoding='utf-8')}\n"
                        f"PRAGMA user_version = {version};\nCOMMIT;")
    cols = {row[1] for row in c.execute("PRAGMA table_info(enrollments)")}
    assert "never_started" not in cols
    assert migrate(c) == 24
    cols = {row[1] for row in c.execute("PRAGMA table_info(enrollments)")}
    assert "never_started" in cols
    att = c.execute("SELECT sql FROM sqlite_master WHERE name='trg_attendance_ins'").fetchone()[0]
    assert "never_started" in att
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []


def test_two_closures_the_same_day_are_not_guessed_on_upgrade():
    """0023 must not pick an arbitrary closure_id when two closures share the leave day."""
    c = connect(":memory:")
    for version, file in _files():
        if version > 22:
            break
        c.executescript(f"BEGIN IMMEDIATE;\n{file.read_text(encoding='utf-8')}\n"
                        f"PRAGMA user_version = {version};\nCOMMIT;")
    c.executescript("""
    INSERT INTO school_years(label,start_date,end_date) VALUES('2026-2027','2026-09-01','2027-06-30');
    INSERT INTO levels(name) VALUES('4AM');
    INSERT INTO subjects(name) VALUES('Maths');
    INSERT INTO users(username,password_hash,role) VALUES('u','x','director');
    INSERT INTO class_groups(school_year_id,level_id,subject_id,name,price,capacity,start_date)
      VALUES(1,1,1,'A',6000,30,'2026-09-01');
    INSERT INTO students(student_number,first_name,last_name) VALUES('2026-0001','A','B');
    INSERT INTO registrations(student_id,school_year_id,level_id,fee_amount) VALUES(1,1,1,0);
    INSERT INTO enrollments(student_id,group_id,registration_id,enrolled_on,status,left_on)
      VALUES(1,1,1,'2026-09-01','left','2026-11-06');
    INSERT INTO group_closures(group_id, closed_on) VALUES(1,'2026-11-06'),(1,'2026-11-06');
    """)
    migrate(c)
    assert c.execute("SELECT closure_id FROM enrollments WHERE id=1").fetchone()[0] is None
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []


def test_places_a_closure_ended_before_their_entry_are_marked_never_started():
    """A version 23 database: group A closed on 20/09; one place ended with it before its
    entry day (01/10), one that had started. 0024 marks the first only (round 3,
    finding 4)."""
    c = connect(":memory:")
    for version, file in _files():
        if version > 23:
            break
        c.executescript(f"BEGIN IMMEDIATE;\n{file.read_text(encoding='utf-8')}\n"
                        f"PRAGMA user_version = {version};\nCOMMIT;")
    c.executescript("""
    INSERT INTO school_years(label,start_date,end_date) VALUES('2026-2027','2026-09-01','2027-06-30');
    INSERT INTO levels(name) VALUES('4AM');
    INSERT INTO subjects(name) VALUES('Maths');
    INSERT INTO users(username,password_hash,role) VALUES('u','x','director');
    INSERT INTO class_groups(school_year_id,level_id,subject_id,name,price,capacity,start_date)
      VALUES(1,1,1,'A',6000,30,'2026-09-01');
    INSERT INTO students(student_number,first_name,last_name)
      VALUES('2026-0001','A','B'), ('2026-0002','C','D');
    INSERT INTO registrations(student_id,school_year_id,level_id,fee_amount)
      VALUES(1,1,1,0), (2,1,1,0);
    INSERT INTO group_closures(group_id, closed_on) VALUES(1,'2026-09-20');
    INSERT INTO enrollments(student_id,group_id,registration_id,enrolled_on,status,left_on,
                            closure_id)
      VALUES(1,1,1,'2026-10-01','left','2026-10-01',1),
            (2,1,2,'2026-09-01','left','2026-09-20',1);
    """)
    assert migrate(c) == 24
    assert [tuple(r) for r in c.execute(
        "SELECT student_id, never_started FROM enrollments ORDER BY id")] == [(1, 1), (2, 0)]


def test_no_migration_needs_a_recent_sqlite_for_having():
    """HAVING without GROUP BY needs SQLite 3.39 (2022): a school's older system SQLite
    would stop the migration, and the app (round 3, finding 3)."""
    for version, file in _files():
        for statement in file.read_text(encoding="utf-8").split(";"):
            upper = statement.upper()
            if "HAVING" in upper:
                assert "GROUP BY" in upper, f"{file.name}: HAVING without GROUP BY"
