-- Phase 3: one open school year at a time, and lookups used by the academic services.
CREATE UNIQUE INDEX uq_school_year_open ON school_years(status) WHERE status = 'open';
CREATE INDEX ix_class_groups_teacher_lookup ON group_teachers(group_id, valid_from);
CREATE INDEX ix_teacher_rates_period        ON teacher_rates(teacher_id, valid_from);
CREATE INDEX ix_slots_weekday               ON timetable_slots(weekday, start_time);
