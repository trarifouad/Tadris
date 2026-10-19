"""Triggers are the last line of defence: the services refuse these cases first, so only
raw SQL reaches them. Each test below makes one trigger fire, with its exact message.

The `seeded` fixture: year 1, level 1, subject 1, user 1, student 1 with registration 1
(fee 2 000), teacher 1, group 1 (3 000 DA, 10 seats, teacher 1 from 01/08), enrollment 1,
subscription 1 (01/09 to 01/10) with charge 1 (3 000, accrued 01/09), payment 1 (3 000).
"""

import re
import sqlite3

import pytest


def refused(message: str):
    return pytest.raises(sqlite3.IntegrityError, match=re.escape(message))


def one(c, sql, params=()) -> int:
    return c.execute(sql, params).lastrowid


def alloc(c, payment, charge, amount) -> int:
    return one(c, "INSERT INTO payment_allocations(payment_id,charge_id,amount) VALUES(?,?,?)",
               (payment, charge, amount))


def pay(c, student, amount) -> int:
    return one(c, "INSERT INTO payments(student_id,amount,method,paid_at,received_by) "
                  "VALUES(?,?,'cash','2026-09-02T10:00:00',1)", (student, amount))


def fee_charge(c) -> int:
    """The registration fee charge of student 1 (2 000)."""
    return one(c, "INSERT INTO charges(registration_id,description,amount,due_date,accrual_date) "
                  "VALUES(1,'Frais',2000,'2026-09-01','2026-09-01')")


def student(c, n) -> tuple[int, int]:
    sid = one(c, "INSERT INTO students(student_number,first_name,last_name) VALUES(?,'S','S')",
              (f"2026-{n:04d}",))
    rid = one(c, "INSERT INTO registrations(student_id,school_year_id,level_id,fee_amount) "
                 "VALUES(?,1,1,0)", (sid,))
    return sid, rid


def group(c, name="G2", year=1) -> int:
    return one(c, "INSERT INTO class_groups(school_year_id,level_id,subject_id,name,price,"
                  "capacity,start_date) VALUES(?,1,1,?,2000,10,'2026-09-01')", (year, name))


def refund(c, amount=1000, charge=1, subscription=1) -> int:
    """A pending refund (0012: refunds target a charge; subscription_id is the month's)."""
    return one(c, "INSERT INTO refunds(charge_id,subscription_id,amount_computed,amount_final,"
                  "reason) VALUES(?,?,?,?,'Départ')", (charge, subscription, amount, amount))


def pay_out(c, refund_id, amount) -> None:
    """Approve, then mark paid: the allocations must already add up to the amount."""
    c.execute("UPDATE refunds SET status='approved', approved_by=1 WHERE id=?", (refund_id,))
    c.execute("UPDATE refunds SET status='paid', refunded_amount=? WHERE id=?",
              (amount, refund_id))


def refund_alloc(c, refund_id, allocation_id, amount) -> int:
    return one(c, "INSERT INTO refund_allocations(refund_id,payment_allocation_id,amount) "
                  "VALUES(?,?,?)", (refund_id, allocation_id, amount))


def payout(c, teacher=1, status="draft") -> tuple[int, int]:
    """A September payout for group 1, and its line."""
    pid = one(c, "INSERT INTO teacher_payouts(teacher_id,period_start,period_end,base_amount,"
                 "amount_due,status) VALUES(?,'2026-09-01','2026-09-30',3000,1800,?)",
              (teacher, status))
    lid = one(c, "INSERT INTO payout_lines(payout_id,group_id,revenue_basis,percentage_bp,"
                 "amount) VALUES(?,1,3000,6000,1800)", (pid,))
    return pid, lid


def count(c, line, charge, amount=3000) -> None:
    c.execute("INSERT INTO payout_line_charges(payout_line_id,charge_id,amount) VALUES(?,?,?)",
              (line, charge, amount))


def room(c, name, capacity=20) -> int:
    return one(c, "INSERT INTO rooms(name,capacity) VALUES(?,?)", (name, capacity))


def teacher(c, name="T2") -> int:
    return one(c, "INSERT INTO teachers(full_name) VALUES(?)", (name,))


def session(c, group_id=1, room_id=None, teacher_id=1, slot=None, date="2026-09-07",
            start="10:00", end="11:00", status="planned") -> int:
    room_id = room_id or room(c, f"S{date}{start}{group_id}")
    reason = "Malade" if status == "cancelled" else None
    return one(c, "INSERT INTO sessions(group_id,slot_id,room_id,teacher_id,date,start_time,"
                  "end_time,status,cancellation_reason) VALUES(?,?,?,?,?,?,?,?,?)",
               (group_id, slot, room_id, teacher_id, date, start, end, status, reason))


def attend(c, session_id, enrollment=1) -> int:
    return one(c, "INSERT INTO attendances(session_id,enrollment_id,status,entered_by) "
                  "VALUES(?,?,'present',1)", (session_id, enrollment))


# ----- allocations -----

def test_allocation_to_a_cancelled_charge(seeded):
    seeded.execute("UPDATE charges SET status='cancelled' WHERE id=1")
    with refused("charge is cancelled"):
        alloc(seeded, 1, 1, 100)


def test_allocation_across_students(seeded):
    other, _rid = student(seeded, 2)
    payment = pay(seeded, other, 500)
    with refused("payment and charge belong to different students"):
        alloc(seeded, payment, 1, 500)


def test_allocations_voids_and_receipts_are_immutable(seeded):
    allocation = alloc(seeded, 1, 1, 3000)
    with refused("payment_allocations are immutable"):
        seeded.execute("UPDATE payment_allocations SET amount=1 WHERE id=?", (allocation,))
    with refused("payment_allocations are immutable"):
        seeded.execute("DELETE FROM payment_allocations WHERE id=?", (allocation,))
    seeded.execute("INSERT INTO receipts(payment_id,number) VALUES(1,'R2026-00001')")
    with refused("receipts are immutable"):
        seeded.execute("UPDATE receipts SET number='R2026-00009'")
    with refused("receipts are immutable"):
        seeded.execute("DELETE FROM receipts")
    seeded.execute("INSERT INTO payment_voids(payment_id,reason,voided_by) VALUES(1,'x',1)")
    with refused("payment_voids are immutable"):
        seeded.execute("UPDATE payment_voids SET reason='y'")
    with refused("payment_voids are immutable"):
        seeded.execute("DELETE FROM payment_voids")


# ----- refunds -----

def test_void_refused_once_refunded(seeded):
    allocation = alloc(seeded, 1, 1, 3000)
    refund_alloc(seeded, refund(seeded), allocation, 1000)
    with refused("payment has refunds"):
        seeded.execute("INSERT INTO payment_voids(payment_id,reason,voided_by) VALUES(1,'x',1)")


def test_refund_closed_takes_no_allocation(seeded):
    allocation = alloc(seeded, 1, 1, 3000)
    rejected = refund(seeded)
    seeded.execute("UPDATE refunds SET status='rejected', approved_by=1 WHERE id=?", (rejected,))
    with refused("refund is locked"):
        refund_alloc(seeded, rejected, allocation, 100)
    paid = refund(seeded, amount=500)
    refund_alloc(seeded, paid, allocation, 500)
    pay_out(seeded, paid, 500)
    with refused("refund is locked"):
        refund_alloc(seeded, paid, allocation, 1)


def test_refund_from_a_voided_payment(seeded):
    allocation = alloc(seeded, 1, 1, 3000)
    seeded.execute("INSERT INTO payment_voids(payment_id,reason,voided_by) VALUES(1,'x',1)")
    with refused("payment is voided"):
        refund_alloc(seeded, refund(seeded), allocation, 100)


def test_refund_of_another_charge(seeded):
    """Money paid on the fee is not money paid on the month."""
    payment = pay(seeded, 1, 2000)
    allocation = alloc(seeded, payment, fee_charge(seeded), 2000)
    with refused("allocation belongs to another charge"):
        refund_alloc(seeded, refund(seeded), allocation, 100)


def test_refund_allocations_stay_within_the_refund(seeded):
    allocation = alloc(seeded, 1, 1, 3000)
    refund_id = refund(seeded, amount=500)
    refund_alloc(seeded, refund_id, allocation, 500)
    with refused("refund allocations exceed refund amount"):
        refund_alloc(seeded, refund_id, allocation, 1)


def test_refunds_and_their_allocations_are_locked(seeded):
    allocation = alloc(seeded, 1, 1, 3000)
    refund_id = refund(seeded)
    line = refund_alloc(seeded, refund_id, allocation, 1000)
    with refused("refund_allocations are immutable"):
        seeded.execute("UPDATE refund_allocations SET amount=1 WHERE id=?", (line,))
    with refused("refund_allocations are immutable"):
        seeded.execute("DELETE FROM refund_allocations WHERE id=?", (line,))
    with refused("refunds cannot be deleted"):
        seeded.execute("DELETE FROM refunds WHERE id=?", (refund_id,))
    with refused("refund is locked"):
        seeded.execute("UPDATE refunds SET reason='autre' WHERE id=?", (refund_id,))
    pay_out(seeded, refund_id, 1000)  # allowed: the approval and payout fields
    with refused("refund is locked"):
        seeded.execute("UPDATE refunds SET method='cash' WHERE id=?", (refund_id,))


# ----- teacher payouts -----

def test_payout_counts_open_subscription_charges_only(seeded):
    _pid, line = payout(seeded)
    with refused("charge is not an open subscription charge"):
        count(seeded, line, fee_charge(seeded), 2000)
    seeded.execute("UPDATE charges SET status='cancelled' WHERE id=1")
    with refused("charge is not an open subscription charge"):
        count(seeded, line, 1)


def test_payout_counts_the_whole_charge(seeded):
    _pid, line = payout(seeded)
    with refused("amount must equal the charge amount"):
        count(seeded, line, 1, 2999)


def test_payout_line_counts_its_own_group(seeded):
    other = group(seeded)
    enrollment = one(seeded, "INSERT INTO enrollments(student_id,group_id,registration_id,"
                             "enrolled_on) VALUES(1,?,1,'2026-09-01')", (other,))
    subscription = one(seeded, "INSERT INTO subscriptions(enrollment_id,price,start_date,"
                               "end_date) VALUES(?,2000,'2026-09-01','2026-10-01')",
                       (enrollment,))
    charge = one(seeded, "INSERT INTO charges(subscription_id,description,amount,due_date,"
                         "accrual_date) VALUES(?,'G2',2000,'2026-09-01','2026-09-01')",
                 (subscription,))
    _pid, line = payout(seeded)  # group 1
    with refused("charge belongs to another group"):
        count(seeded, line, charge, 2000)


def test_payout_goes_to_the_group_teacher(seeded):
    _pid, line = payout(seeded, teacher=teacher(seeded))
    with refused("teacher is not the group teacher on the accrual date"):
        count(seeded, line, 1)


def test_charge_locked_once_counted(seeded):
    _pid, line = payout(seeded)
    count(seeded, line, 1)
    with refused("charge already counted in a teacher payout"):
        seeded.execute("UPDATE charges SET status='cancelled' WHERE id=1")
    with refused("charge already counted in a teacher payout"):
        seeded.execute("UPDATE charges SET accrual_date='2026-09-02' WHERE id=1")
    with refused("payout_line_charges cannot be updated"):
        seeded.execute("UPDATE payout_line_charges SET amount=1")


def test_payout_locked_once_approved(seeded):
    payout_id, line = payout(seeded)
    count(seeded, line, 1)
    seeded.execute("UPDATE teacher_payouts SET status='approved' WHERE id=?", (payout_id,))
    with refused("payout is locked"):
        seeded.execute("UPDATE teacher_payouts SET amount_due=1 WHERE id=?", (payout_id,))
    with refused("payout is locked"):
        seeded.execute("DELETE FROM teacher_payouts WHERE id=?", (payout_id,))
    with refused("payout is locked"):
        seeded.execute("UPDATE payout_lines SET amount=1 WHERE id=?", (line,))
    with refused("payout is locked"):
        seeded.execute("DELETE FROM payout_lines WHERE id=?", (line,))
    with refused("payout is locked"):
        seeded.execute("DELETE FROM payout_line_charges")


def test_a_draft_payout_can_be_redone(seeded):
    payout_id, line = payout(seeded)
    count(seeded, line, 1)
    seeded.execute("DELETE FROM payout_line_charges")
    seeded.execute("DELETE FROM payout_lines WHERE id=?", (line,))
    seeded.execute("DELETE FROM teacher_payouts WHERE id=?", (payout_id,))


# ----- enrollments -----

def test_enrollment_with_another_students_registration(seeded):
    _sid, other_registration = student(seeded, 2)
    other = group(seeded)
    with refused("registration belongs to another student"):
        seeded.execute("INSERT INTO enrollments(student_id,group_id,registration_id,enrolled_on) "
                       "VALUES(1,?,?,'2026-09-01')", (other, other_registration))
    with refused("registration belongs to another student"):
        seeded.execute("UPDATE enrollments SET registration_id=? WHERE id=1",
                       (other_registration,))


def test_enrollment_with_a_cancelled_registration(seeded):
    other = group(seeded)
    seeded.execute("UPDATE registrations SET status='cancelled' WHERE id=1")
    with refused("registration is cancelled"):
        seeded.execute("INSERT INTO enrollments(student_id,group_id,registration_id,enrolled_on) "
                       "VALUES(1,?,1,'2026-09-01')", (other,))
    with refused("registration is cancelled"):
        seeded.execute("UPDATE enrollments SET group_id=? WHERE id=1", (other,))


def test_coming_back_needs_an_active_registration(seeded):
    seeded.execute("UPDATE enrollments SET status='left', left_on='2026-09-20' WHERE id=1")
    seeded.execute("UPDATE registrations SET status='cancelled' WHERE id=1")
    with refused("registration is cancelled"):
        seeded.execute("UPDATE enrollments SET status='active', left_on=NULL WHERE id=1")


def test_enrollment_in_a_group_of_another_year(seeded):
    year = one(seeded, "INSERT INTO school_years(label,start_date,end_date,status) "
                       "VALUES('2027-2028','2027-09-01','2028-06-30','closed')")
    other = group(seeded, "G-next", year)
    with refused("registration school year differs from group"):
        seeded.execute("INSERT INTO enrollments(student_id,group_id,registration_id,enrolled_on) "
                       "VALUES(1,?,1,'2027-09-01')", (other,))
    with refused("registration school year differs from group"):
        seeded.execute("UPDATE enrollments SET group_id=? WHERE id=1", (other,))


# ----- timetable and sessions -----

def test_a_group_has_one_slot_at_a_time(seeded):
    first, second = room(seeded, "R1"), room(seeded, "R2")
    seeded.execute("INSERT INTO timetable_slots(group_id,room_id,weekday,start_time,end_time,"
                   "valid_from) VALUES(1,?,1,'17:00','18:00','2026-09-01')", (first,))
    with refused("group slot overlap"):
        seeded.execute("INSERT INTO timetable_slots(group_id,room_id,weekday,start_time,"
                       "end_time,valid_from) VALUES(1,?,1,'17:30','18:30','2026-09-01')",
                       (second,))


def test_session_of_another_group_on_a_slot(seeded):
    place = room(seeded, "R1")
    slot = one(seeded, "INSERT INTO timetable_slots(group_id,room_id,weekday,start_time,"
                       "end_time,valid_from) VALUES(1,?,1,'10:00','11:00','2026-09-01')",
               (place,))
    with refused("session group differs from slot group"):
        session(seeded, group_id=group(seeded), room_id=place, slot=slot)  # a Monday


def test_a_group_has_one_session_at_a_time(seeded):
    session(seeded)
    with refused("group session overlap"):
        session(seeded, teacher_id=teacher(seeded), start="10:30", end="11:30")
    session(seeded, teacher_id=teacher(seeded, "T3"), start="11:00", end="12:00")  # back to back


def test_no_attendance_for_a_cancelled_session(seeded):
    with refused("session is cancelled"):
        attend(seeded, session(seeded, status="cancelled"))


def test_attendance_belongs_to_the_session_group(seeded):
    other = session(seeded, group_id=group(seeded))
    with refused("enrollment is not in the session group"):
        attend(seeded, other)
    line = attend(seeded, session(seeded, date="2026-09-14"))
    with refused("enrollment is not in the session group"):
        seeded.execute("UPDATE attendances SET session_id=? WHERE id=?", (other, line))
