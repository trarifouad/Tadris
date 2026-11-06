-- 0021 and 0022 were edited in place before they were committed. migrate() never re-runs a
-- version the database already has (PRAGMA user_version). A file that already applied the
-- first 0021 still lets a pending INSERT carry close_reason, method, decided_at or
-- cancelled_at, which then bricks the row: the update trigger refuses every later step
-- (REVIEW_FIXES round 2, finding 10). A file that already applied the first 0022 has the
-- closures but not enrollments.closure_id. This version adds that column, replaces both
-- refund step triggers with the current rules, and, if needed, starts the new refund ids
-- after the archive.

-- The closure that ended the place (its students leave with it); NULL: left otherwise, or not
-- left. Set once, by the closure of the place's own group.
ALTER TABLE enrollments ADD COLUMN closure_id INTEGER REFERENCES group_closures(id);

DROP TRIGGER IF EXISTS trg_enrollments_closure;
CREATE TRIGGER trg_enrollments_closure BEFORE UPDATE OF closure_id ON enrollments
BEGIN
  SELECT RAISE(ABORT, 'enrollment closure is set once')
  WHERE OLD.closure_id IS NOT NULL AND NEW.closure_id IS NOT OLD.closure_id;

  SELECT RAISE(ABORT, 'closure belongs to another group')
  WHERE NEW.closure_id IS NOT NULL
    AND (SELECT group_id FROM group_closures WHERE id = NEW.closure_id) IS NOT NEW.group_id;
END;

DROP TRIGGER IF EXISTS trg_enrollments_closure_ins;
CREATE TRIGGER trg_enrollments_closure_ins BEFORE INSERT ON enrollments
WHEN NEW.closure_id IS NOT NULL
BEGIN
  SELECT RAISE(ABORT, 'closure belongs to another group')
  WHERE (SELECT group_id FROM group_closures WHERE id = NEW.closure_id) IS NOT NEW.group_id;
END;

-- Only when exactly one closure of the group matches the dates: two closures the same
-- day (close, reopen, close) would otherwise pick an arbitrary id.
UPDATE enrollments
   SET closure_id = (SELECT c.id FROM group_closures c
                      WHERE c.group_id = enrollments.group_id
                        AND max(c.closed_on, enrollments.enrolled_on) = enrollments.left_on)
 WHERE status = 'left'
   AND (SELECT COUNT(*) FROM group_closures c
         WHERE c.group_id = enrollments.group_id
           AND max(c.closed_on, enrollments.enrolled_on) = enrollments.left_on) = 1;

DROP TRIGGER IF EXISTS trg_refund_requests_ins;
CREATE TRIGGER trg_refund_requests_ins BEFORE INSERT ON refunds
BEGIN
  SELECT RAISE(ABORT, 'a new refund is pending')
  WHERE NEW.status <> 'pending' OR NEW.amount_approved IS NOT NULL
     OR NEW.decided_by IS NOT NULL OR NEW.decided_at IS NOT NULL
     OR NEW.cancelled_by IS NOT NULL OR NEW.cancelled_at IS NOT NULL
     OR NEW.number IS NOT NULL OR NEW.method IS NOT NULL
     OR NEW.paid_by IS NOT NULL OR NEW.paid_at IS NOT NULL
     OR trim(COALESCE(NEW.close_reason, '')) <> '';

  SELECT RAISE(ABORT, 'registration fees are not refundable')
  WHERE (SELECT registration_id FROM charges WHERE id = NEW.charge_id) IS NOT NULL;

  SELECT RAISE(ABORT, 'charge is cancelled')
  WHERE (SELECT status FROM charges WHERE id = NEW.charge_id) <> 'open';

  SELECT RAISE(ABORT, 'month is not paid in full')
  WHERE COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa
                   WHERE pa.charge_id = NEW.charge_id
                     AND NOT EXISTS (SELECT 1 FROM payment_voids v
                                      WHERE v.payment_id = pa.payment_id)), 0)
        < (SELECT amount FROM charges WHERE id = NEW.charge_id);

  SELECT RAISE(ABORT, 'refund exceeds the value of the sessions left')
  WHERE COALESCE((SELECT SUM(CASE r.status WHEN 'pending' THEN r.amount_requested
                                           ELSE r.amount_approved END)
                    FROM refunds r
                   WHERE r.charge_id = NEW.charge_id
                     AND r.status IN ('pending','approved','paid')), 0)
        + NEW.amount_requested > NEW.sessions_value;

  SELECT RAISE(ABORT, 'refund exceeds paid minus already refunded')
  WHERE COALESCE((SELECT SUM(CASE r.status WHEN 'pending' THEN r.amount_requested
                                           ELSE r.amount_approved END)
                    FROM refunds r
                   WHERE r.charge_id = NEW.charge_id
                     AND r.status IN ('pending','approved','paid')), 0)
        + NEW.amount_requested
        + COALESCE((SELECT SUM(ra.amount) FROM archived_refund_allocations ra
                    JOIN payment_allocations pa ON pa.id = ra.payment_allocation_id
                   WHERE pa.charge_id = NEW.charge_id
                     AND NOT EXISTS (SELECT 1 FROM payment_voids v
                                      WHERE v.payment_id = pa.payment_id)), 0) >
        COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa
                   WHERE pa.charge_id = NEW.charge_id
                     AND NOT EXISTS (SELECT 1 FROM payment_voids v
                                      WHERE v.payment_id = pa.payment_id)), 0);
END;

DROP TRIGGER IF EXISTS trg_refund_requests_upd;
CREATE TRIGGER trg_refund_requests_upd BEFORE UPDATE ON refunds
BEGIN
  SELECT RAISE(ABORT, 'refund is locked')
  WHERE OLD.status IN ('rejected','cancelled','paid')
     OR NEW.charge_id <> OLD.charge_id
     OR NEW.counted_from <> OLD.counted_from
     OR NEW.sessions_total <> OLD.sessions_total
     OR NEW.sessions_left <> OLD.sessions_left
     OR NEW.sessions_value <> OLD.sessions_value
     OR NEW.max_amount <> OLD.max_amount
     OR NEW.amount_requested <> OLD.amount_requested
     OR NEW.reason <> OLD.reason
     OR NEW.requested_by <> OLD.requested_by
     OR NEW.requested_at <> OLD.requested_at
     OR NEW.created_at <> OLD.created_at
     OR (OLD.decided_by IS NOT NULL AND (NEW.decided_by IS NOT OLD.decided_by
                                         OR NEW.decided_at IS NOT OLD.decided_at))
     OR (NEW.amount_approved IS NOT OLD.amount_approved
         AND NOT (OLD.status = 'pending' AND NEW.status = 'approved'));

  SELECT RAISE(ABORT, 'refund cannot go to that status')
  WHERE NOT ((OLD.status = 'pending' AND NEW.status IN ('approved','rejected','cancelled'))
          OR (OLD.status = 'approved' AND NEW.status IN ('paid','cancelled')));

  SELECT RAISE(ABORT, 'refund has money taken back')
  WHERE NEW.status = 'cancelled'
    AND EXISTS (SELECT 1 FROM refund_allocations WHERE refund_id = NEW.id);

  SELECT RAISE(ABORT, 'refund decision needs who, when and the amount')
  WHERE NEW.status = 'approved'
    AND (NEW.amount_approved IS NULL OR NEW.decided_by IS NULL OR NEW.decided_at IS NULL);

  SELECT RAISE(ABORT, 'closed refund needs who, when and why')
  WHERE (NEW.status = 'rejected'
         AND (NEW.decided_by IS NULL OR NEW.decided_at IS NULL
              OR trim(COALESCE(NEW.close_reason, '')) = ''))
     OR (NEW.status = 'cancelled'
         AND (NEW.cancelled_by IS NULL OR NEW.cancelled_at IS NULL
              OR trim(COALESCE(NEW.close_reason, '')) = ''));

  SELECT RAISE(ABORT, 'refund exceeds the value of the sessions left')
  WHERE NEW.status = 'approved'
    AND COALESCE((SELECT SUM(CASE r.status WHEN 'pending' THEN r.amount_requested
                                           ELSE r.amount_approved END)
                    FROM refunds r
                   WHERE r.charge_id = NEW.charge_id AND r.id <> NEW.id
                     AND r.status IN ('pending','approved','paid')), 0)
        + NEW.amount_approved > NEW.sessions_value;

  SELECT RAISE(ABORT, 'refund exceeds paid minus already refunded')
  WHERE NEW.status = 'approved'
    AND COALESCE((SELECT SUM(CASE r.status WHEN 'pending' THEN r.amount_requested
                                           ELSE r.amount_approved END)
                    FROM refunds r
                   WHERE r.charge_id = NEW.charge_id AND r.id <> NEW.id
                     AND r.status IN ('pending','approved','paid')), 0)
        + NEW.amount_approved
        + COALESCE((SELECT SUM(ra.amount) FROM archived_refund_allocations ra
                    JOIN payment_allocations pa ON pa.id = ra.payment_allocation_id
                   WHERE pa.charge_id = NEW.charge_id
                     AND NOT EXISTS (SELECT 1 FROM payment_voids v
                                      WHERE v.payment_id = pa.payment_id)), 0) >
        COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa
                   WHERE pa.charge_id = NEW.charge_id
                     AND NOT EXISTS (SELECT 1 FROM payment_voids v
                                      WHERE v.payment_id = pa.payment_id)), 0);

  SELECT RAISE(ABORT, 'refund payout needs its number, method, who and when')
  WHERE NEW.status = 'paid'
    AND (NEW.number IS NULL OR NEW.method IS NULL OR NEW.paid_by IS NULL
         OR NEW.paid_at IS NULL);

  SELECT RAISE(ABORT, 'refunded amount must match its allocations')
  WHERE NEW.status = 'paid'
    AND NEW.amount_approved <> COALESCE((SELECT SUM(amount) FROM refund_allocations
                                          WHERE refund_id = NEW.id), 0);

  SELECT RAISE(ABORT, 'refund step fields do not match its status')
  WHERE ((NEW.number IS NOT NULL OR NEW.method IS NOT NULL
          OR NEW.paid_by IS NOT NULL OR NEW.paid_at IS NOT NULL)
         AND NEW.status <> 'paid')
     OR ((NEW.cancelled_by IS NOT NULL OR NEW.cancelled_at IS NOT NULL)
         AND NEW.status <> 'cancelled')
     OR (trim(COALESCE(NEW.close_reason, '')) <> ''
         AND NEW.status NOT IN ('rejected', 'cancelled'));
END;

INSERT INTO sqlite_sequence(name, seq)
SELECT 'refunds', (SELECT MAX(id) FROM archived_refunds)
 WHERE (SELECT MAX(id) FROM archived_refunds) IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name = 'refunds');
UPDATE sqlite_sequence
   SET seq = MAX(seq, COALESCE((SELECT MAX(id) FROM archived_refunds), 0))
 WHERE name = 'refunds';
