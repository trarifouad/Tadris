-- A place left (or closed) before its entry day must not sit on any session: the last day
-- stored is still the entry day (CHECK left_on >= enrolled_on; REVIEW_FIXES decision 4), so
-- the date window alone would keep the student on that day's roster. never_started marks
-- those places. migrate() never re-runs 0004, so the attendance triggers are replaced here.

ALTER TABLE enrollments ADD COLUMN never_started INTEGER NOT NULL DEFAULT 0
  CHECK (never_started IN (0, 1));

CREATE TRIGGER trg_enrollments_never_started_ins BEFORE INSERT ON enrollments
WHEN NEW.never_started = 1
BEGIN
  SELECT RAISE(ABORT, 'never started needs a last day on the entry day')
  WHERE NEW.status NOT IN ('left', 'switched')
     OR NEW.left_on IS NOT NEW.enrolled_on;
END;

CREATE TRIGGER trg_enrollments_never_started_upd BEFORE UPDATE ON enrollments
BEGIN
  SELECT RAISE(ABORT, 'never started is set once')
  WHERE OLD.never_started = 1 AND NEW.never_started = 0;

  SELECT RAISE(ABORT, 'never started needs a last day on the entry day')
  WHERE NEW.never_started = 1
    AND (NEW.status NOT IN ('left', 'switched')
         OR NEW.left_on IS NOT NEW.enrolled_on);
END;

-- The places a closure under 0022 or 0023 already ended before their entry day: their last
-- day is their entry day, after the closing day (REVIEW_FIXES round 3, finding 4).
UPDATE enrollments
   SET never_started = 1
 WHERE status = 'left' AND closure_id IS NOT NULL AND left_on = enrolled_on
   AND enrolled_on > (SELECT c.closed_on FROM group_closures c
                       WHERE c.id = enrollments.closure_id);

DROP TRIGGER IF EXISTS trg_attendance_ins;
CREATE TRIGGER trg_attendance_ins BEFORE INSERT ON attendances
BEGIN
  SELECT RAISE(ABORT, 'session is cancelled')
  WHERE (SELECT status FROM sessions WHERE id = NEW.session_id) = 'cancelled';

  SELECT RAISE(ABORT, 'enrollment is not in the session group')
  WHERE (SELECT group_id FROM enrollments WHERE id = NEW.enrollment_id) <>
        (SELECT group_id FROM sessions WHERE id = NEW.session_id);

  SELECT RAISE(ABORT, 'enrollment not valid on session date')
  WHERE NOT EXISTS (SELECT 1 FROM enrollments e JOIN sessions s ON s.id = NEW.session_id
                     WHERE e.id = NEW.enrollment_id AND e.never_started = 0
                       AND e.enrolled_on <= s.date
                       AND (e.left_on IS NULL OR e.left_on >= s.date));
END;

DROP TRIGGER IF EXISTS trg_attendance_upd;
CREATE TRIGGER trg_attendance_upd BEFORE UPDATE OF session_id, enrollment_id ON attendances
BEGIN
  SELECT RAISE(ABORT, 'enrollment is not in the session group')
  WHERE (SELECT group_id FROM enrollments WHERE id = NEW.enrollment_id) <>
        (SELECT group_id FROM sessions WHERE id = NEW.session_id);

  SELECT RAISE(ABORT, 'enrollment not valid on session date')
  WHERE NOT EXISTS (SELECT 1 FROM enrollments e JOIN sessions s ON s.id = NEW.session_id
                     WHERE e.id = NEW.enrollment_id AND e.never_started = 0
                       AND e.enrolled_on <= s.date
                       AND (e.left_on IS NULL OR e.left_on >= s.date));
END;
