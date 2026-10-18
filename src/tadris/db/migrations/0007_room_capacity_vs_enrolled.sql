-- A room must fit the students actually enrolled in a group, not the group's maximum.
-- A group planned for 16 can meet in a 5-seat room while it has 5 students or fewer; while
-- it meets there, the smallest room among its running or future slots caps its enrollments.
-- "Enrolled" means enrollments in status trial or active.

DROP TRIGGER trg_group_capacity_vs_room;   -- group capacity may now exceed its rooms

DROP TRIGGER trg_room_capacity_update;
CREATE TRIGGER trg_room_capacity_update BEFORE UPDATE OF capacity ON rooms
WHEN EXISTS (SELECT 1 FROM timetable_slots s JOIN class_groups g ON g.id = s.group_id
              WHERE s.room_id = NEW.id AND g.status <> 'closed'
                AND (s.valid_to IS NULL OR s.valid_to > date('now','localtime'))
                AND (SELECT COUNT(*) FROM enrollments e
                      WHERE e.group_id = g.id AND e.status IN ('trial','active')) > NEW.capacity)
BEGIN SELECT RAISE(ABORT, 'room capacity below enrolled students'); END;

DROP TRIGGER trg_slots_ins;
CREATE TRIGGER trg_slots_ins BEFORE INSERT ON timetable_slots
BEGIN
  SELECT RAISE(ABORT, 'room too small for enrolled students')
  WHERE (SELECT COUNT(*) FROM enrollments
          WHERE group_id = NEW.group_id AND status IN ('trial','active')) >
        (SELECT capacity FROM rooms WHERE id = NEW.room_id);
  SELECT RAISE(ABORT, 'room slot overlap')
  WHERE EXISTS (SELECT 1 FROM timetable_slots s
                 WHERE s.room_id = NEW.room_id AND s.weekday = NEW.weekday
                   AND s.start_time < NEW.end_time AND s.end_time > NEW.start_time
                   AND s.valid_from < COALESCE(NEW.valid_to, '9999-12-31')
                   AND COALESCE(s.valid_to, '9999-12-31') > NEW.valid_from);
  SELECT RAISE(ABORT, 'group slot overlap')
  WHERE EXISTS (SELECT 1 FROM timetable_slots s
                 WHERE s.group_id = NEW.group_id AND s.weekday = NEW.weekday
                   AND s.start_time < NEW.end_time AND s.end_time > NEW.start_time
                   AND s.valid_from < COALESCE(NEW.valid_to, '9999-12-31')
                   AND COALESCE(s.valid_to, '9999-12-31') > NEW.valid_from);
END;

DROP TRIGGER trg_slots_upd;
CREATE TRIGGER trg_slots_upd BEFORE UPDATE ON timetable_slots
BEGIN
  SELECT RAISE(ABORT, 'room too small for enrolled students')
  WHERE (SELECT COUNT(*) FROM enrollments
          WHERE group_id = NEW.group_id AND status IN ('trial','active')) >
        (SELECT capacity FROM rooms WHERE id = NEW.room_id);
  SELECT RAISE(ABORT, 'room slot overlap')
  WHERE EXISTS (SELECT 1 FROM timetable_slots s
                 WHERE s.id <> NEW.id AND s.room_id = NEW.room_id AND s.weekday = NEW.weekday
                   AND s.start_time < NEW.end_time AND s.end_time > NEW.start_time
                   AND s.valid_from < COALESCE(NEW.valid_to, '9999-12-31')
                   AND COALESCE(s.valid_to, '9999-12-31') > NEW.valid_from);
  SELECT RAISE(ABORT, 'group slot overlap')
  WHERE EXISTS (SELECT 1 FROM timetable_slots s
                 WHERE s.id <> NEW.id AND s.group_id = NEW.group_id AND s.weekday = NEW.weekday
                   AND s.start_time < NEW.end_time AND s.end_time > NEW.start_time
                   AND s.valid_from < COALESCE(NEW.valid_to, '9999-12-31')
                   AND COALESCE(s.valid_to, '9999-12-31') > NEW.valid_from);
END;

-- Enrolling: the group's smallest running or future room caps its live enrollments.
CREATE TRIGGER trg_enrollment_room_full BEFORE INSERT ON enrollments
WHEN NEW.status IN ('trial','active')
 AND (SELECT COUNT(*) FROM enrollments
       WHERE group_id = NEW.group_id AND status IN ('trial','active'))
     >= COALESCE((SELECT MIN(r.capacity) FROM timetable_slots s JOIN rooms r ON r.id = s.room_id
                   WHERE s.group_id = NEW.group_id
                     AND (s.valid_to IS NULL OR s.valid_to > date('now','localtime'))),
                 2147483647)
BEGIN SELECT RAISE(ABORT, 'room is full'); END;

CREATE TRIGGER trg_enrollment_room_full_upd BEFORE UPDATE OF status, group_id ON enrollments
WHEN NEW.status IN ('trial','active')
 AND (SELECT COUNT(*) FROM enrollments
       WHERE group_id = NEW.group_id AND status IN ('trial','active') AND id <> NEW.id)
     >= COALESCE((SELECT MIN(r.capacity) FROM timetable_slots s JOIN rooms r ON r.id = s.room_id
                   WHERE s.group_id = NEW.group_id
                     AND (s.valid_to IS NULL OR s.valid_to > date('now','localtime'))),
                 2147483647)
BEGIN SELECT RAISE(ABORT, 'room is full'); END;
