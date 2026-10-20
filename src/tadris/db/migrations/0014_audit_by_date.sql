-- The Journal reads the audit log by date, a page of 100 at a time, and counts what its
-- filters match: an index on the date keeps both fast as the log grows (it only grows).
CREATE INDEX ix_audit_created ON audit_log(created_at);
