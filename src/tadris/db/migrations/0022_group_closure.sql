-- When a group was closed, and its week as it stood just before (decided 2026-11-06, for
-- refunds: PLAN « Refunds in V1 »; rebuilt after the review, REVIEW_FIXES step 2).
--
-- Closing a group (or its school year) ends its timetable slots that day; a slot that had
-- not started, or started that very day, with no session kept, is removed. The sessions the
-- school no longer gives after the closure are then missing from the timetable, and a
-- refund counted from it would find nothing left. So each closure is a row of its own
-- (group_closures: the group, the day), and keeps the group's slots running that day or
-- planned to start later, with their own dates, before it ends them (group_closure_slots):
-- a refund counts them as going on after the closure. A slot over before the closure is not
-- among them. The group points to its closure (class_groups.closure_id); reopening clears
-- it, and the rows of its closures stay. The place a closure ended (enrollments.closure_id)
-- is added in 0023: 0022 may already have run without it.

CREATE TABLE group_closures (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id   INTEGER NOT NULL REFERENCES class_groups(id) ON DELETE RESTRICT,
  closed_on  TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);
CREATE INDEX ix_group_closures ON group_closures(group_id, closed_on);

CREATE TRIGGER trg_group_closures_no_update BEFORE UPDATE ON group_closures
BEGIN SELECT RAISE(ABORT, 'group_closures are immutable'); END;
CREATE TRIGGER trg_group_closures_no_delete BEFORE DELETE ON group_closures
BEGIN SELECT RAISE(ABORT, 'group_closures are immutable'); END;

-- NULL: never closed, or reopened.
ALTER TABLE class_groups ADD COLUMN closure_id INTEGER REFERENCES group_closures(id);

CREATE TRIGGER trg_class_groups_closure BEFORE UPDATE OF closure_id ON class_groups
WHEN NEW.closure_id IS NOT NULL
BEGIN
  SELECT RAISE(ABORT, 'closure belongs to another group')
  WHERE (SELECT group_id FROM group_closures WHERE id = NEW.closure_id) IS NOT NEW.id;
END;

CREATE TABLE group_closure_slots (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  closure_id INTEGER NOT NULL REFERENCES group_closures(id) ON DELETE RESTRICT,
  weekday    INTEGER NOT NULL CHECK (weekday BETWEEN 1 AND 7),
  start_time TEXT NOT NULL,
  end_time   TEXT NOT NULL,
  valid_from TEXT NOT NULL,  -- the slot's own period as it stood, half-open
  valid_to   TEXT,           -- NULL: no end planned
  slot_id    INTEGER,  -- the slot it was, for the record (no reference: it may be removed)
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  CHECK (valid_to IS NULL OR valid_to > valid_from)
);
CREATE INDEX ix_group_closure_slots ON group_closure_slots(closure_id);

CREATE TRIGGER trg_group_closure_slots_no_update BEFORE UPDATE ON group_closure_slots
BEGIN SELECT RAISE(ABORT, 'group_closure_slots are immutable'); END;
CREATE TRIGGER trg_group_closure_slots_no_delete BEFORE DELETE ON group_closure_slots
BEGIN SELECT RAISE(ABORT, 'group_closure_slots are immutable'); END;

-- ===== groups closed before this migration =====
-- The day comes from the audit log only, written in the closure's own transaction: the
-- latest « group.close » of the group, or « school_year.close » listing it, and only when
-- no « group.reopen » came after it. Otherwise it stays unknown (no closure) and a refund
-- counts the timetable as it stands.
WITH days AS (
  SELECT g.id,
         (SELECT substr(c.at, 1, 10)
            FROM (SELECT MAX(at) AS at FROM (
                     SELECT a.created_at AS at FROM audit_log a
                      WHERE a.action = 'group.close' AND a.entity_name = 'class_groups'
                        AND a.entity_id = g.id
                     UNION ALL
                     SELECT a.created_at FROM audit_log a,
                            json_each(a.new_value, '$.groups_closed') j
                      WHERE a.action = 'school_year.close' AND json_valid(a.new_value)
                        AND j.value = g.id)) c
           WHERE c.at IS NOT NULL
             AND c.at > COALESCE((SELECT MAX(a.created_at) FROM audit_log a
                                   WHERE a.action = 'group.reopen'
                                     AND a.entity_name = 'class_groups'
                                     AND a.entity_id = g.id), '')) AS day
    FROM class_groups g
   WHERE g.status = 'closed'
)
INSERT INTO group_closures(group_id, closed_on)
SELECT id, day FROM days WHERE day IS NOT NULL ORDER BY id;

UPDATE class_groups
   SET closure_id = (SELECT MAX(c.id) FROM group_closures c WHERE c.group_id = class_groups.id)
 WHERE status = 'closed';

-- Their week before the closure: the slots it ended that day (valid_to the closing day, or
-- the day after for a slot started that day with sessions kept), from their own first day
-- and with no end (the closure overwrote it). What these rows cannot tell: a slot changed
-- the same day, before the closure, ends that day too; a slot planned to start later, or
-- started that day with no session, was removed; an end that was planned is lost.
INSERT INTO group_closure_slots(closure_id, weekday, start_time, end_time, valid_from, slot_id)
SELECT c.id, s.weekday, s.start_time, s.end_time, s.valid_from, s.id
  FROM group_closures c
  JOIN timetable_slots s ON s.group_id = c.group_id
 WHERE (s.valid_from < c.closed_on AND s.valid_to = c.closed_on)
    OR (s.valid_from = c.closed_on AND s.valid_to = date(c.closed_on, '+1 day'))
 ORDER BY c.id, s.weekday, s.start_time, s.id;
