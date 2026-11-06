-- A level may be open to every level (« Tous niveaux »: calligraphie, arts, …). Its groups
-- take students of any registration level, next to the groups of their own level: a 3AS
-- student follows maths 3AS and calligraphie « Tous niveaux » under the same registration.
-- A student may also be registered at the open level itself (an adult who only takes a
-- workshop): they then follow the open groups only.
-- 1. levels.is_open, 0 for every existing level: nothing changes until the director opens one.
-- 2. The enrollment triggers (0010) skip the level check when the group's level is open.
-- 3. An open level goes back to its own students only while none of another level is live
--    in its groups.

ALTER TABLE levels ADD COLUMN is_open INTEGER NOT NULL DEFAULT 0 CHECK (is_open IN (0,1));

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
    AND NOT (SELECT l.is_open FROM class_groups g JOIN levels l ON l.id = g.level_id
              WHERE g.id = NEW.group_id);

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
    AND NOT (SELECT l.is_open FROM class_groups g JOIN levels l ON l.id = g.level_id
              WHERE g.id = NEW.group_id);

  SELECT RAISE(ABORT, 'group is closed')
  WHERE (SELECT status FROM class_groups WHERE id = NEW.group_id) = 'closed';

  SELECT RAISE(ABORT, 'group is full')
  WHERE NEW.status IN ('trial','active')
    AND (SELECT COUNT(*) FROM enrollments
          WHERE group_id = NEW.group_id AND status IN ('trial','active') AND id <> NEW.id)
        >= (SELECT capacity FROM class_groups WHERE id = NEW.group_id);
END;

CREATE TRIGGER trg_level_open_upd BEFORE UPDATE OF is_open ON levels
WHEN OLD.is_open = 1 AND NEW.is_open = 0
BEGIN
  SELECT RAISE(ABORT, 'open level has students of other levels')
  WHERE EXISTS (SELECT 1 FROM enrollments e
                  JOIN class_groups g ON g.id = e.group_id
                  JOIN registrations r ON r.id = e.registration_id
                 WHERE g.level_id = NEW.id AND r.level_id <> NEW.id
                   AND e.status IN ('trial','active'));
END;
