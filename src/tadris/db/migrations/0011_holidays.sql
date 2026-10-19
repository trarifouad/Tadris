-- Phase 6: holidays, days without classes. A period from start_date to end_date, both days
-- included (a single day has start_date = end_date), with a label shown to the desk. No
-- session is generated on those days. Periods never overlap.

CREATE TABLE holidays (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  label      TEXT NOT NULL,
  start_date TEXT NOT NULL,
  end_date   TEXT NOT NULL,                      -- last day off, included
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  CHECK (end_date >= start_date)
);
CREATE INDEX ix_holidays_dates ON holidays(start_date, end_date);

CREATE TRIGGER trg_holidays_overlap_ins BEFORE INSERT ON holidays
WHEN EXISTS (SELECT 1 FROM holidays h
              WHERE h.start_date <= NEW.end_date AND h.end_date >= NEW.start_date)
BEGIN SELECT RAISE(ABORT, 'holiday overlap'); END;

CREATE TRIGGER trg_holidays_overlap_upd BEFORE UPDATE OF start_date, end_date ON holidays
WHEN EXISTS (SELECT 1 FROM holidays h
              WHERE h.id <> NEW.id
                AND h.start_date <= NEW.end_date AND h.end_date >= NEW.start_date)
BEGIN SELECT RAISE(ABORT, 'holiday overlap'); END;
