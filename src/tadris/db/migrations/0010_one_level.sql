-- A student follows the groups of one level: the level of their registration for the year.
-- No override any more, not even for the director: the override:enrollment_level key is gone
-- and the triggers no longer read it. To change level, the student leaves their groups and
-- the registration's level is changed (allowed while the student is in no group).

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
        (SELECT level_id FROM class_groups WHERE id = NEW.group_id);

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
        (SELECT level_id FROM class_groups WHERE id = NEW.group_id);

  SELECT RAISE(ABORT, 'group is closed')
  WHERE (SELECT status FROM class_groups WHERE id = NEW.group_id) = 'closed';

  SELECT RAISE(ABORT, 'group is full')
  WHERE NEW.status IN ('trial','active')
    AND (SELECT COUNT(*) FROM enrollments
          WHERE group_id = NEW.group_id AND status IN ('trial','active') AND id <> NEW.id)
        >= (SELECT capacity FROM class_groups WHERE id = NEW.group_id);
END;

DELETE FROM settings WHERE key = 'override:enrollment_level';
