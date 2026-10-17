-- ===== Enrollment rules =====
CREATE TRIGGER trg_enrollment_rules BEFORE INSERT ON enrollments
BEGIN
  SELECT RAISE(ABORT, 'registration belongs to another student')
  WHERE (SELECT student_id FROM registrations WHERE id = NEW.registration_id) <> NEW.student_id;

  SELECT RAISE(ABORT, 'registration is cancelled')
  WHERE (SELECT status FROM registrations WHERE id = NEW.registration_id) <> 'active';

  SELECT RAISE(ABORT, 'registration school year differs from group')
  WHERE (SELECT school_year_id FROM registrations WHERE id = NEW.registration_id) <>
        (SELECT school_year_id FROM class_groups WHERE id = NEW.group_id);

  SELECT RAISE(ABORT, 'registration level differs from group level')
  WHERE (SELECT level_id FROM registrations WHERE id = NEW.registration_id) <>
        (SELECT level_id FROM class_groups WHERE id = NEW.group_id)
    AND NOT EXISTS (SELECT 1 FROM settings
                     WHERE key = 'override:enrollment_level' AND value = '1');

  SELECT RAISE(ABORT, 'group is closed')
  WHERE (SELECT status FROM class_groups WHERE id = NEW.group_id) = 'closed';

  SELECT RAISE(ABORT, 'group already started')
  WHERE NEW.enrolled_on > (SELECT start_date FROM class_groups WHERE id = NEW.group_id)
    AND NOT EXISTS (SELECT 1 FROM settings
                     WHERE key = 'override:enrollment_start' AND value = '1');

  SELECT RAISE(ABORT, 'group is full')
  WHERE NEW.status IN ('trial','active')
    AND (SELECT COUNT(*) FROM enrollments
          WHERE group_id = NEW.group_id AND status IN ('trial','active'))
        >= (SELECT capacity FROM class_groups WHERE id = NEW.group_id);
END;

-- ===== Capacity: group <= smallest room used by its current/future slots =====
CREATE TRIGGER trg_group_capacity_not_below_enrolled BEFORE UPDATE OF capacity ON class_groups
WHEN NEW.capacity < (SELECT COUNT(*) FROM enrollments
                      WHERE group_id = NEW.id AND status IN ('trial','active'))
BEGIN SELECT RAISE(ABORT, 'capacity below current enrollment'); END;

CREATE TRIGGER trg_group_capacity_vs_room BEFORE UPDATE OF capacity ON class_groups
WHEN NEW.capacity > COALESCE(
       (SELECT MIN(r.capacity) FROM timetable_slots s JOIN rooms r ON r.id = s.room_id
         WHERE s.group_id = NEW.id
           AND (s.valid_to IS NULL OR s.valid_to >= date('now','localtime'))), 2147483647)
BEGIN SELECT RAISE(ABORT, 'group capacity exceeds room capacity'); END;

CREATE TRIGGER trg_room_capacity_update BEFORE UPDATE OF capacity ON rooms
WHEN EXISTS (SELECT 1 FROM timetable_slots s JOIN class_groups g ON g.id = s.group_id
              WHERE s.room_id = NEW.id AND g.status <> 'closed'
                AND (s.valid_to IS NULL OR s.valid_to >= date('now','localtime'))
                AND g.capacity > NEW.capacity)
BEGIN SELECT RAISE(ABORT, 'room capacity below a group capacity'); END;

-- ===== Timetable slots: room capacity + overlaps (valid_to inclusive here) =====
CREATE TRIGGER trg_slots_ins BEFORE INSERT ON timetable_slots
BEGIN
  SELECT RAISE(ABORT, 'group capacity exceeds room capacity')
  WHERE (SELECT capacity FROM class_groups WHERE id = NEW.group_id) >
        (SELECT capacity FROM rooms WHERE id = NEW.room_id);

  SELECT RAISE(ABORT, 'room slot overlap')
  WHERE EXISTS (SELECT 1 FROM timetable_slots s
                 WHERE s.room_id = NEW.room_id AND s.weekday = NEW.weekday
                   AND s.start_time < NEW.end_time AND s.end_time > NEW.start_time
                   AND s.valid_from <= COALESCE(NEW.valid_to, '9999-12-31')
                   AND COALESCE(s.valid_to, '9999-12-31') >= NEW.valid_from);

  SELECT RAISE(ABORT, 'group slot overlap')
  WHERE EXISTS (SELECT 1 FROM timetable_slots s
                 WHERE s.group_id = NEW.group_id AND s.weekday = NEW.weekday
                   AND s.start_time < NEW.end_time AND s.end_time > NEW.start_time
                   AND s.valid_from <= COALESCE(NEW.valid_to, '9999-12-31')
                   AND COALESCE(s.valid_to, '9999-12-31') >= NEW.valid_from);
END;

CREATE TRIGGER trg_slots_upd BEFORE UPDATE ON timetable_slots
BEGIN
  SELECT RAISE(ABORT, 'group capacity exceeds room capacity')
  WHERE (SELECT capacity FROM class_groups WHERE id = NEW.group_id) >
        (SELECT capacity FROM rooms WHERE id = NEW.room_id);

  SELECT RAISE(ABORT, 'room slot overlap')
  WHERE EXISTS (SELECT 1 FROM timetable_slots s
                 WHERE s.id <> NEW.id AND s.room_id = NEW.room_id AND s.weekday = NEW.weekday
                   AND s.start_time < NEW.end_time AND s.end_time > NEW.start_time
                   AND s.valid_from <= COALESCE(NEW.valid_to, '9999-12-31')
                   AND COALESCE(s.valid_to, '9999-12-31') >= NEW.valid_from);

  SELECT RAISE(ABORT, 'group slot overlap')
  WHERE EXISTS (SELECT 1 FROM timetable_slots s
                 WHERE s.id <> NEW.id AND s.group_id = NEW.group_id AND s.weekday = NEW.weekday
                   AND s.start_time < NEW.end_time AND s.end_time > NEW.start_time
                   AND s.valid_from <= COALESCE(NEW.valid_to, '9999-12-31')
                   AND COALESCE(s.valid_to, '9999-12-31') >= NEW.valid_from);
END;

-- ===== Sessions: weekday match + no room/teacher/group overlap (cancelled ignored) =====
CREATE TRIGGER trg_sessions_ins BEFORE INSERT ON sessions
BEGIN
  SELECT RAISE(ABORT, 'session group differs from slot group')
  WHERE NEW.slot_id IS NOT NULL
    AND (SELECT group_id FROM timetable_slots WHERE id = NEW.slot_id) <> NEW.group_id;

  SELECT RAISE(ABORT, 'session date does not match slot weekday')
  WHERE NEW.slot_id IS NOT NULL
    AND ((CAST(strftime('%w', NEW.date) AS INTEGER) + 6) % 7 + 1) <>
        (SELECT weekday FROM timetable_slots WHERE id = NEW.slot_id);

  SELECT RAISE(ABORT, 'room session overlap')
  WHERE NEW.status <> 'cancelled' AND EXISTS (
    SELECT 1 FROM sessions x WHERE x.room_id = NEW.room_id AND x.date = NEW.date
       AND x.status <> 'cancelled' AND x.start_time < NEW.end_time AND x.end_time > NEW.start_time);

  SELECT RAISE(ABORT, 'teacher session overlap')
  WHERE NEW.status <> 'cancelled' AND EXISTS (
    SELECT 1 FROM sessions x WHERE x.teacher_id = NEW.teacher_id AND x.date = NEW.date
       AND x.status <> 'cancelled' AND x.start_time < NEW.end_time AND x.end_time > NEW.start_time);

  SELECT RAISE(ABORT, 'group session overlap')
  WHERE NEW.status <> 'cancelled' AND EXISTS (
    SELECT 1 FROM sessions x WHERE x.group_id = NEW.group_id AND x.date = NEW.date
       AND x.status <> 'cancelled' AND x.start_time < NEW.end_time AND x.end_time > NEW.start_time);
END;

CREATE TRIGGER trg_sessions_upd
BEFORE UPDATE OF group_id, slot_id, room_id, teacher_id, date, start_time, end_time, status
ON sessions
BEGIN
  SELECT RAISE(ABORT, 'session group differs from slot group')
  WHERE NEW.slot_id IS NOT NULL
    AND (SELECT group_id FROM timetable_slots WHERE id = NEW.slot_id) <> NEW.group_id;

  SELECT RAISE(ABORT, 'session date does not match slot weekday')
  WHERE NEW.slot_id IS NOT NULL
    AND ((CAST(strftime('%w', NEW.date) AS INTEGER) + 6) % 7 + 1) <>
        (SELECT weekday FROM timetable_slots WHERE id = NEW.slot_id);

  SELECT RAISE(ABORT, 'room session overlap')
  WHERE NEW.status <> 'cancelled' AND EXISTS (
    SELECT 1 FROM sessions x WHERE x.id <> NEW.id AND x.room_id = NEW.room_id AND x.date = NEW.date
       AND x.status <> 'cancelled' AND x.start_time < NEW.end_time AND x.end_time > NEW.start_time);

  SELECT RAISE(ABORT, 'teacher session overlap')
  WHERE NEW.status <> 'cancelled' AND EXISTS (
    SELECT 1 FROM sessions x WHERE x.id <> NEW.id AND x.teacher_id = NEW.teacher_id AND x.date = NEW.date
       AND x.status <> 'cancelled' AND x.start_time < NEW.end_time AND x.end_time > NEW.start_time);

  SELECT RAISE(ABORT, 'group session overlap')
  WHERE NEW.status <> 'cancelled' AND EXISTS (
    SELECT 1 FROM sessions x WHERE x.id <> NEW.id AND x.group_id = NEW.group_id AND x.date = NEW.date
       AND x.status <> 'cancelled' AND x.start_time < NEW.end_time AND x.end_time > NEW.start_time);
END;

-- ===== Attendance: enrollment belongs to the session group and is valid on its date =====
CREATE TRIGGER trg_attendance_ins BEFORE INSERT ON attendances
BEGIN
  SELECT RAISE(ABORT, 'session is cancelled')
  WHERE (SELECT status FROM sessions WHERE id = NEW.session_id) = 'cancelled';

  SELECT RAISE(ABORT, 'enrollment is not in the session group')
  WHERE (SELECT group_id FROM enrollments WHERE id = NEW.enrollment_id) <>
        (SELECT group_id FROM sessions WHERE id = NEW.session_id);

  SELECT RAISE(ABORT, 'enrollment not valid on session date')
  WHERE NOT EXISTS (SELECT 1 FROM enrollments e JOIN sessions s ON s.id = NEW.session_id
                     WHERE e.id = NEW.enrollment_id AND e.enrolled_on <= s.date
                       AND (e.left_on IS NULL OR e.left_on >= s.date));
END;

CREATE TRIGGER trg_attendance_upd BEFORE UPDATE OF session_id, enrollment_id ON attendances
BEGIN
  SELECT RAISE(ABORT, 'enrollment is not in the session group')
  WHERE (SELECT group_id FROM enrollments WHERE id = NEW.enrollment_id) <>
        (SELECT group_id FROM sessions WHERE id = NEW.session_id);

  SELECT RAISE(ABORT, 'enrollment not valid on session date')
  WHERE NOT EXISTS (SELECT 1 FROM enrollments e JOIN sessions s ON s.id = NEW.session_id
                     WHERE e.id = NEW.enrollment_id AND e.enrolled_on <= s.date
                       AND (e.left_on IS NULL OR e.left_on >= s.date));
END;

-- ===== Subscriptions: no overlap per enrollment, half-open [start, end) =====
CREATE TRIGGER trg_subscription_overlap_ins BEFORE INSERT ON subscriptions
WHEN NEW.status <> 'cancelled' AND EXISTS (
  SELECT 1 FROM subscriptions x
   WHERE x.enrollment_id = NEW.enrollment_id AND x.status <> 'cancelled'
     AND x.start_date < NEW.end_date AND x.end_date > NEW.start_date)
BEGIN SELECT RAISE(ABORT, 'subscription overlap'); END;

CREATE TRIGGER trg_subscription_overlap_upd
BEFORE UPDATE OF start_date, end_date, status ON subscriptions
WHEN NEW.status <> 'cancelled' AND EXISTS (
  SELECT 1 FROM subscriptions x
   WHERE x.id <> NEW.id AND x.enrollment_id = NEW.enrollment_id AND x.status <> 'cancelled'
     AND x.start_date < NEW.end_date AND x.end_date > NEW.start_date)
BEGIN SELECT RAISE(ABORT, 'subscription overlap'); END;

-- ===== Rate periods and group-teacher periods: no overlap, half-open =====
CREATE TRIGGER trg_rates_overlap_ins BEFORE INSERT ON teacher_rates
WHEN EXISTS (SELECT 1 FROM teacher_rates x
              WHERE x.teacher_id = NEW.teacher_id
                AND x.valid_from < COALESCE(NEW.valid_to, '9999-12-31')
                AND COALESCE(x.valid_to, '9999-12-31') > NEW.valid_from)
BEGIN SELECT RAISE(ABORT, 'teacher rate period overlap'); END;

CREATE TRIGGER trg_rates_overlap_upd BEFORE UPDATE OF valid_from, valid_to ON teacher_rates
WHEN EXISTS (SELECT 1 FROM teacher_rates x
              WHERE x.id <> NEW.id AND x.teacher_id = NEW.teacher_id
                AND x.valid_from < COALESCE(NEW.valid_to, '9999-12-31')
                AND COALESCE(x.valid_to, '9999-12-31') > NEW.valid_from)
BEGIN SELECT RAISE(ABORT, 'teacher rate period overlap'); END;

CREATE TRIGGER trg_group_teachers_overlap_ins BEFORE INSERT ON group_teachers
WHEN EXISTS (SELECT 1 FROM group_teachers x
              WHERE x.group_id = NEW.group_id
                AND x.valid_from < COALESCE(NEW.valid_to, '9999-12-31')
                AND COALESCE(x.valid_to, '9999-12-31') > NEW.valid_from)
BEGIN SELECT RAISE(ABORT, 'group teacher period overlap'); END;

CREATE TRIGGER trg_group_teachers_overlap_upd BEFORE UPDATE OF valid_from, valid_to ON group_teachers
WHEN EXISTS (SELECT 1 FROM group_teachers x
              WHERE x.id <> NEW.id AND x.group_id = NEW.group_id
                AND x.valid_from < COALESCE(NEW.valid_to, '9999-12-31')
                AND COALESCE(x.valid_to, '9999-12-31') > NEW.valid_from)
BEGIN SELECT RAISE(ABORT, 'group teacher period overlap'); END;

-- ===== Refund cap =====
CREATE TRIGGER trg_refund_alloc_rules BEFORE INSERT ON refund_allocations
BEGIN
  SELECT RAISE(ABORT, 'refund is locked')
  WHERE (SELECT status FROM refunds WHERE id = NEW.refund_id) NOT IN ('pending','approved');

  SELECT RAISE(ABORT, 'payment is voided')
  WHERE EXISTS (SELECT 1 FROM payment_allocations pa
                  JOIN payment_voids v ON v.payment_id = pa.payment_id
                 WHERE pa.id = NEW.payment_allocation_id);

  SELECT RAISE(ABORT, 'allocation belongs to another subscription')
  WHERE (SELECT c.subscription_id FROM payment_allocations pa
           JOIN charges c ON c.id = pa.charge_id WHERE pa.id = NEW.payment_allocation_id)
        IS NOT (SELECT subscription_id FROM refunds WHERE id = NEW.refund_id);

  SELECT RAISE(ABORT, 'refund exceeds paid minus already refunded')
  WHERE COALESCE((SELECT SUM(amount) FROM refund_allocations
                   WHERE payment_allocation_id = NEW.payment_allocation_id), 0) + NEW.amount >
        (SELECT amount FROM payment_allocations WHERE id = NEW.payment_allocation_id);

  SELECT RAISE(ABORT, 'refund allocations exceed refund amount')
  WHERE COALESCE((SELECT SUM(amount) FROM refund_allocations
                   WHERE refund_id = NEW.refund_id), 0) + NEW.amount >
        (SELECT amount_final FROM refunds WHERE id = NEW.refund_id);
END;

-- ===== Teacher payouts: eligibility and locking =====
CREATE TRIGGER trg_payout_line_ins BEFORE INSERT ON payout_lines
WHEN (SELECT status FROM teacher_payouts WHERE id = NEW.payout_id) <> 'draft'
BEGIN SELECT RAISE(ABORT, 'payout is not draft'); END;

CREATE TRIGGER trg_payout_line_charge_rules BEFORE INSERT ON payout_line_charges
BEGIN
  SELECT RAISE(ABORT, 'payout is not draft')
  WHERE (SELECT p.status FROM payout_lines l JOIN teacher_payouts p ON p.id = l.payout_id
          WHERE l.id = NEW.payout_line_id) <> 'draft';

  SELECT RAISE(ABORT, 'charge is not an open subscription charge')
  WHERE NOT EXISTS (SELECT 1 FROM charges
                     WHERE id = NEW.charge_id AND subscription_id IS NOT NULL AND status = 'open');

  SELECT RAISE(ABORT, 'amount must equal the charge amount')
  WHERE NEW.amount <> (SELECT amount FROM charges WHERE id = NEW.charge_id);

  SELECT RAISE(ABORT, 'accrual date outside payout period')
  WHERE NOT EXISTS (SELECT 1 FROM charges c
                      JOIN payout_lines l ON l.id = NEW.payout_line_id
                      JOIN teacher_payouts p ON p.id = l.payout_id
                     WHERE c.id = NEW.charge_id
                       AND c.accrual_date BETWEEN p.period_start AND p.period_end);

  SELECT RAISE(ABORT, 'charge belongs to another group')
  WHERE (SELECT e.group_id FROM charges c
           JOIN subscriptions s ON s.id = c.subscription_id
           JOIN enrollments e ON e.id = s.enrollment_id
          WHERE c.id = NEW.charge_id)
        <> (SELECT group_id FROM payout_lines WHERE id = NEW.payout_line_id);

  SELECT RAISE(ABORT, 'teacher is not the group teacher on the accrual date')
  WHERE NOT EXISTS (SELECT 1 FROM charges c
                      JOIN subscriptions s ON s.id = c.subscription_id
                      JOIN enrollments e ON e.id = s.enrollment_id
                      JOIN group_teachers gt ON gt.group_id = e.group_id
                      JOIN payout_lines l ON l.id = NEW.payout_line_id
                      JOIN teacher_payouts p ON p.id = l.payout_id
                     WHERE c.id = NEW.charge_id AND gt.teacher_id = p.teacher_id
                       AND gt.valid_from <= c.accrual_date
                       AND (gt.valid_to IS NULL OR gt.valid_to > c.accrual_date));
END;

CREATE TRIGGER trg_payouts_lock BEFORE UPDATE ON teacher_payouts
WHEN OLD.status <> 'draft' AND (
     OLD.status = 'paid'
  OR NEW.teacher_id <> OLD.teacher_id OR NEW.period_start <> OLD.period_start
  OR NEW.period_end <> OLD.period_end OR NEW.base_amount <> OLD.base_amount
  OR NEW.amount_due <> OLD.amount_due)
BEGIN SELECT RAISE(ABORT, 'payout is locked'); END;

CREATE TRIGGER trg_payouts_no_delete BEFORE DELETE ON teacher_payouts
WHEN OLD.status <> 'draft'
BEGIN SELECT RAISE(ABORT, 'payout is locked'); END;

CREATE TRIGGER trg_payout_lines_lock_upd BEFORE UPDATE ON payout_lines
WHEN (SELECT status FROM teacher_payouts WHERE id = OLD.payout_id) <> 'draft'
BEGIN SELECT RAISE(ABORT, 'payout is locked'); END;

CREATE TRIGGER trg_payout_lines_lock_del BEFORE DELETE ON payout_lines
WHEN (SELECT status FROM teacher_payouts WHERE id = OLD.payout_id) <> 'draft'
BEGIN SELECT RAISE(ABORT, 'payout is locked'); END;

CREATE TRIGGER trg_plc_no_update BEFORE UPDATE ON payout_line_charges
BEGIN SELECT RAISE(ABORT, 'payout_line_charges cannot be updated'); END;

CREATE TRIGGER trg_plc_lock_del BEFORE DELETE ON payout_line_charges
WHEN (SELECT p.status FROM payout_lines l JOIN teacher_payouts p ON p.id = l.payout_id
       WHERE l.id = OLD.payout_line_id) <> 'draft'
BEGIN SELECT RAISE(ABORT, 'payout is locked'); END;
