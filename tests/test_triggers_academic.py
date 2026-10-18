import sqlite3

import pytest


def add_student(c, n, level=1):
    c.execute("INSERT INTO students(student_number,first_name,last_name) VALUES(?,'S','S')",
              (f"2026-{n:04d}",))
    sid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.execute("INSERT INTO registrations(student_id,school_year_id,level_id,fee_amount) "
              "VALUES(?,1,?,0)", (sid, level))
    rid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    return sid, rid


def enroll(c, sid, rid, on="2026-09-01"):
    c.execute("INSERT INTO enrollments(student_id,group_id,registration_id,enrolled_on) "
              "VALUES(?,1,?,?)", (sid, rid, on))


def add_room(c, name="R1", cap=20):
    c.execute("INSERT INTO rooms(name,capacity) VALUES(?,?)", (name, cap))


def add_slot(c, room=1, weekday=1, start="10:00", end="11:00"):
    c.execute("INSERT INTO timetable_slots(group_id,room_id,weekday,start_time,end_time,valid_from) "
              "VALUES(1,?,?,?,?,'2026-09-01')", (room, weekday, start, end))


def add_session(c, room=1, slot=None, date="2026-09-07", start="10:00", end="11:00"):
    c.execute("INSERT INTO sessions(group_id,slot_id,room_id,teacher_id,date,start_time,end_time) "
              "VALUES(1,?,?,1,?,?,?)", (slot, room, date, start, end))


# ----- enrollment -----
def test_enrollment_level_mismatch(seeded):
    seeded.execute("INSERT INTO levels(name) VALUES('4AM')")
    sid, rid = add_student(seeded, 2, level=2)
    with pytest.raises(sqlite3.IntegrityError, match="level"):
        enroll(seeded, sid, rid)


def test_enrollment_level_director_override(seeded):
    seeded.execute("INSERT INTO levels(name) VALUES('4AM')")
    sid, rid = add_student(seeded, 2, level=2)
    seeded.execute("INSERT INTO settings(key,value) VALUES('override:enrollment_level','1')")
    enroll(seeded, sid, rid)


def test_enrollment_after_group_start(seeded):
    sid, rid = add_student(seeded, 2)
    with pytest.raises(sqlite3.IntegrityError, match="already started"):
        enroll(seeded, sid, rid, on="2026-10-05")


def test_group_full(seeded):
    seeded.execute("UPDATE class_groups SET capacity=1 WHERE id=1")
    sid, rid = add_student(seeded, 2)
    with pytest.raises(sqlite3.IntegrityError, match="full"):
        enroll(seeded, sid, rid)


def test_enrollment_update_respects_capacity(seeded):
    seeded.execute("UPDATE class_groups SET capacity=1 WHERE id=1")
    sid, rid = add_student(seeded, 2)
    seeded.execute(
        "INSERT INTO enrollments(student_id,group_id,registration_id,enrolled_on,status) "
        "VALUES(?,1,?,?,'left')",
        (sid, rid, "2026-09-01"),
    )
    with pytest.raises(sqlite3.IntegrityError, match="full"):
        seeded.execute("UPDATE enrollments SET status='active' WHERE student_id=?", (sid,))


def test_enrollment_update_level_mismatch(seeded):
    seeded.execute("INSERT INTO levels(name) VALUES('4AM')")
    seeded.execute(
        "INSERT INTO class_groups(school_year_id,level_id,subject_id,name,price,capacity,start_date) "
        "VALUES(1,2,1,'G2',3000,10,'2026-09-01')"
    )
    with pytest.raises(sqlite3.IntegrityError, match="level"):
        seeded.execute("UPDATE enrollments SET group_id=2 WHERE id=1")


# ----- timetable and sessions -----
def test_slot_room_overlap(seeded):
    add_room(seeded)
    add_slot(seeded)
    with pytest.raises(sqlite3.IntegrityError, match="room"):
        add_slot(seeded, start="10:30", end="11:30")


def test_slot_adjacent_periods_do_not_overlap(seeded):
    add_room(seeded)
    seeded.execute(
        "INSERT INTO timetable_slots(group_id,room_id,weekday,start_time,end_time,valid_from,valid_to) "
        "VALUES(1,1,1,'10:00','11:00','2026-09-01','2026-10-01')"
    )
    seeded.execute(
        "INSERT INTO timetable_slots(group_id,room_id,weekday,start_time,end_time,valid_from,valid_to) "
        "VALUES(1,1,1,'10:00','11:00','2026-10-01','2026-11-01')"
    )


SECOND_STUDENT = """
INSERT INTO students(student_number,first_name,last_name) VALUES('2026-0002','C','D');
INSERT INTO registrations(student_id,school_year_id,level_id,fee_amount) VALUES(2,1,1,0);
"""
ENROLL_SECOND = (
    "INSERT INTO enrollments(student_id,group_id,registration_id,enrolled_on) "
    "VALUES(2,1,2,'2026-09-01')"
)


def test_room_must_fit_enrolled_students_not_group_capacity(seeded):
    # The seeded group has 10 places and 1 student: a 1-seat room is enough...
    add_room(seeded, cap=1)
    add_slot(seeded)
    # ...and while the group meets there, a second student no longer fits.
    seeded.executescript(SECOND_STUDENT)
    with pytest.raises(sqlite3.IntegrityError, match="room is full"):
        seeded.execute(ENROLL_SECOND)


def test_room_cannot_shrink_below_enrolled_students(seeded):
    add_room(seeded, cap=5)
    add_slot(seeded)
    seeded.executescript(SECOND_STUDENT)
    seeded.execute(ENROLL_SECOND)
    seeded.execute("UPDATE rooms SET capacity = 2 WHERE id = 1")  # below the group's 10
    with pytest.raises(sqlite3.IntegrityError, match="room capacity below enrolled students"):
        seeded.execute("UPDATE rooms SET capacity = 1 WHERE id = 1")


def test_room_too_small_for_enrolled_students(seeded):
    seeded.executescript(SECOND_STUDENT)
    seeded.execute(ENROLL_SECOND)
    add_room(seeded, cap=1)
    with pytest.raises(sqlite3.IntegrityError, match="room too small for enrolled students"):
        add_slot(seeded)


def test_session_weekday_matches_slot(seeded):
    add_room(seeded)
    add_slot(seeded, weekday=1)          # Monday
    add_session(seeded, slot=1, date="2026-09-07")   # Monday: ok
    with pytest.raises(sqlite3.IntegrityError, match="weekday"):
        add_session(seeded, slot=1, date="2026-09-08", start="12:00", end="13:00")  # Tuesday


def test_session_teacher_overlap(seeded):
    add_room(seeded, "R1")
    add_room(seeded, "R2")
    add_session(seeded, room=1)
    with pytest.raises(sqlite3.IntegrityError, match="teacher"):
        add_session(seeded, room=2, start="10:30", end="11:30")


# ----- attendance -----
def test_attendance_enrollment_valid_on_date(seeded):
    add_room(seeded)
    add_session(seeded, date="2026-08-31")   # before enrolled_on 2026-09-01
    with pytest.raises(sqlite3.IntegrityError, match="not valid"):
        seeded.execute("INSERT INTO attendances(session_id,enrollment_id,status,entered_by) "
                       "VALUES(1,1,'present',1)")


# ----- periods -----
def test_subscription_overlap(seeded):
    with pytest.raises(sqlite3.IntegrityError, match="overlap"):
        seeded.execute("INSERT INTO subscriptions(enrollment_id,price,start_date,end_date) "
                       "VALUES(1,3000,'2026-09-15','2026-10-15')")


def test_renewal_can_start_on_previous_end(seeded):
    seeded.execute("INSERT INTO subscriptions(enrollment_id,renewal_of_id,price,start_date,end_date) "
                   "VALUES(1,1,3000,'2026-10-01','2026-11-01')")


def test_group_teacher_period_overlap(seeded):
    seeded.execute("INSERT INTO teachers(full_name) VALUES('T2')")
    with pytest.raises(sqlite3.IntegrityError, match="overlap"):
        seeded.execute("INSERT INTO group_teachers(group_id,teacher_id,valid_from,valid_to) "
                       "VALUES(1,2,'2026-08-15','2026-09-15')")


# ----- refunds -----
def test_refund_cannot_exceed_paid(seeded):
    seeded.execute("INSERT INTO payment_allocations(payment_id,charge_id,amount) VALUES(1,1,3000)")
    seeded.execute("INSERT INTO refunds(subscription_id,amount_computed,amount_final,reason) "
                   "VALUES(1,3000,3000,'x')")
    with pytest.raises(sqlite3.IntegrityError, match="exceeds paid"):
        seeded.execute("INSERT INTO refund_allocations(refund_id,payment_allocation_id,amount) "
                       "VALUES(1,1,3001)")


# ----- payouts -----
def test_payout_charge_must_be_in_period(seeded):
    seeded.execute("INSERT INTO teacher_payouts(teacher_id,period_start,period_end,base_amount,amount_due) "
                   "VALUES(1,'2026-10-01','2026-10-31',3000,1800)")
    seeded.execute("INSERT INTO payout_lines(payout_id,group_id,revenue_basis,percentage_bp,amount) "
                   "VALUES(1,1,3000,6000,1800)")
    with pytest.raises(sqlite3.IntegrityError, match="period"):
        seeded.execute("INSERT INTO payout_line_charges(payout_line_id,charge_id,amount) VALUES(1,1,3000)")


def test_payout_not_draft_blocks_new_lines(seeded):
    seeded.execute("INSERT INTO teacher_payouts(teacher_id,period_start,period_end,base_amount,amount_due) "
                   "VALUES(1,'2026-09-01','2026-09-30',3000,1800)")
    seeded.execute("UPDATE teacher_payouts SET status='approved' WHERE id=1")
    with pytest.raises(sqlite3.IntegrityError, match="not draft"):
        seeded.execute("INSERT INTO payout_lines(payout_id,group_id,revenue_basis,percentage_bp,amount) "
                       "VALUES(1,1,3000,6000,1800)")
