-- A year waiting to be opened stays "à venir" even once its start date has passed (the
-- previous year may still be open at la rentrée). opened_on records the first opening;
-- a closed year with it set, or whose end date has passed, is finished.
ALTER TABLE school_years ADD COLUMN opened_on TEXT;

UPDATE school_years SET opened_on = start_date
 WHERE status = 'open' OR end_date < date('now', 'localtime');
