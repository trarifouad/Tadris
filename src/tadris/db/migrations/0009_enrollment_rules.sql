-- Phase 4: enrollment rules for daily use.
-- 1. Joining a group that already started is normal (students join all year long): the
--    'group already started' rule and its override:enrollment_start key are gone.
-- 2. An update re-checks placement only when the placement changes (student, group or
--    registration), and the seats only when an enrollment becomes live (trial or active)
--    again. Leaving, switching or confirming a trial must work even in a closed group or
--    after a level override.
-- 3. A left or switched enrollment carries its leaving date, and a switch points to an
--    enrollment of the same student.

DROP TRIGGER trg_enrollment_rules;
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

  SELECT RAISE(ABORT, 'switched enrollment belongs to another student')
  WHERE NEW.switched_from_id IS NOT NULL
    AND (SELECT student_id FROM enrollments WHERE id = NEW.switched_from_id) <> NEW.student_id;

  SELECT RAISE(ABORT, 'left enrollment needs a leaving date')
  WHERE NEW.status IN ('left','switched') AND NEW.left_on IS NULL;

  SELECT RAISE(ABORT, 'group is full')
  WHERE NEW.status IN ('trial','active')
    AND (SELECT COUNT(*) FROM enrollments
          WHERE group_id = NEW.group_id AND status IN ('trial','active'))
        >= (SELECT capacity FROM class_groups WHERE id = NEW.group_id);
END;

DROP TRIGGER trg_enrollment_rules_upd;
CREATE TRIGGER trg_enrollment_rules_upd
BEFORE UPDATE OF student_id, group_id, registration_id ON enrollments
WHEN NEW.student_id <> OLD.student_id OR NEW.group_id <> OLD.group_id
  OR NEW.registration_id <> OLD.registration_id
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

  SELECT RAISE(ABORT, 'group is full')
  WHERE NEW.status IN ('trial','active')
    AND (SELECT COUNT(*) FROM enrollments
          WHERE group_id = NEW.group_id AND status IN ('trial','active') AND id <> NEW.id)
        >= (SELECT capacity FROM class_groups WHERE id = NEW.group_id);
END;

-- Back to trial or active from left or switched: the group must still take students.
CREATE TRIGGER trg_enrollment_status_upd BEFORE UPDATE OF status, left_on ON enrollments
BEGIN
  SELECT RAISE(ABORT, 'left enrollment needs a leaving date')
  WHERE NEW.status IN ('left','switched') AND NEW.left_on IS NULL;

  SELECT RAISE(ABORT, 'registration is cancelled')
  WHERE NEW.status IN ('trial','active') AND OLD.status NOT IN ('trial','active')
    AND (SELECT status FROM registrations WHERE id = NEW.registration_id) <> 'active';

  SELECT RAISE(ABORT, 'group is closed')
  WHERE NEW.status IN ('trial','active') AND OLD.status NOT IN ('trial','active')
    AND (SELECT status FROM class_groups WHERE id = NEW.group_id) = 'closed';

  SELECT RAISE(ABORT, 'group is full')
  WHERE NEW.status IN ('trial','active') AND OLD.status NOT IN ('trial','active')
    AND (SELECT COUNT(*) FROM enrollments
          WHERE group_id = NEW.group_id AND status IN ('trial','active') AND id <> NEW.id)
        >= (SELECT capacity FROM class_groups WHERE id = NEW.group_id);
END;

-- Seats in the smallest running or future room: checked when a student takes a seat,
-- not when a trial is confirmed (trial to active keeps the same seat).
DROP TRIGGER trg_enrollment_room_full_upd;
CREATE TRIGGER trg_enrollment_room_full_upd BEFORE UPDATE OF status, group_id ON enrollments
WHEN NEW.status IN ('trial','active')
 AND (OLD.status NOT IN ('trial','active') OR NEW.group_id <> OLD.group_id)
 AND (SELECT COUNT(*) FROM enrollments
       WHERE group_id = NEW.group_id AND status IN ('trial','active') AND id <> NEW.id)
     >= COALESCE((SELECT MIN(r.capacity) FROM timetable_slots s JOIN rooms r ON r.id = s.room_id
                   WHERE s.group_id = NEW.group_id
                     AND (s.valid_to IS NULL OR s.valid_to > date('now','localtime'))),
                 2147483647)
BEGIN SELECT RAISE(ABORT, 'room is full'); END;

DELETE FROM settings WHERE key = 'override:enrollment_start';
