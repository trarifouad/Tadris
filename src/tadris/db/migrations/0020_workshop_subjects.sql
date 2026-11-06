-- A subject may be a workshop (calligraphie, arts, …): the group dialog offers the workshops
-- for the groups of an open level (0019) and the other subjects for the other levels. The
-- director marks a subject in Paramètres → Matières.
-- A subject so far taught only in groups of an open level is a workshop already.

ALTER TABLE subjects ADD COLUMN is_workshop INTEGER NOT NULL DEFAULT 0
  CHECK (is_workshop IN (0,1));

UPDATE subjects SET is_workshop = 1
 WHERE id IN (SELECT g.subject_id FROM class_groups g JOIN levels l ON l.id = g.level_id
               WHERE l.is_open = 1)
   AND id NOT IN (SELECT g.subject_id FROM class_groups g JOIN levels l ON l.id = g.level_id
                   WHERE l.is_open = 0);
