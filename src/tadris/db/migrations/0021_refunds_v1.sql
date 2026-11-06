-- Refunds are back in V1 (decided 2026-11-06), rebuilt: the phase 8 tables stay archived and
-- read-only (0015); nothing of theirs is reused but the idea of allocations.
--
-- A refund hands back money paid on one month (a subscription charge) paid in full. The
-- registration fee is never refunded. A refund never changes what is owed nor what a teacher
-- is paid: the month stays open and paid. Once a month is refunded in full, the director may
-- cancel it by hand (then it pays no teacher), unless a teacher payout already holds it.
--
-- The desk asks (pending), once the student has left the group (the service refuses before),
-- for at most the value of the sessions left in the month: the group's timetable minus
-- holidays, counted from the day after the student's last day (from the closing day when the
-- school closed the group and gave no session that day; absences before count as used);
-- price * left / total,
-- rounded down (sessions_value), less what is already refunded or reserved on the month
-- (max_amount: the service's snapshot), and never more than was paid less what the archive
-- handed back of it. The director approves the amount asked or less, or rejects; the desk or the director withdraws it (cancelled). Pending and approved requests
-- reserve their amount, paid ones have handed it back, rejected and cancelled ones hold
-- nothing. The director records the money going out (paid): refund_allocations take it back
-- from the payments that paid the month, each never more than it gave, and the refund gets
-- its number (RB2026-00001).
--
-- Archived refunds (0015) count nowhere, except that what they handed back is never handed
-- back again (an allocation's cap, and the reservations' cap: paid less what they handed
-- back) and still blocks a void (0016).

CREATE TABLE refunds (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  charge_id        INTEGER NOT NULL REFERENCES charges(id) ON DELETE RESTRICT,
  counted_from     TEXT NOT NULL,                       -- the first day not used
  sessions_total   INTEGER NOT NULL CHECK (sessions_total >= 0),  -- 0: worth its price if unused
  sessions_left    INTEGER NOT NULL CHECK (sessions_left BETWEEN 0 AND sessions_total),
  sessions_value   INTEGER NOT NULL CHECK (sessions_value >= 0),
  max_amount       INTEGER NOT NULL CHECK (max_amount BETWEEN 0 AND sessions_value),
  amount_requested INTEGER NOT NULL CHECK (amount_requested BETWEEN 1 AND max_amount),
  amount_approved  INTEGER CHECK (amount_approved IS NULL
                                  OR amount_approved BETWEEN 1 AND amount_requested),
  reason           TEXT NOT NULL CHECK (trim(reason) <> ''),
  status           TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending','approved','rejected','cancelled','paid')),
  requested_by     INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  requested_at     TEXT NOT NULL,
  decided_by       INTEGER REFERENCES users(id) ON DELETE RESTRICT,  -- approved or rejected
  decided_at       TEXT,
  cancelled_by     INTEGER REFERENCES users(id) ON DELETE RESTRICT,
  cancelled_at     TEXT,
  close_reason     TEXT,                                -- why rejected or cancelled
  number           TEXT UNIQUE,                         -- RB2026-00001, once paid
  method           TEXT CHECK (method IS NULL OR method IN ('cash','transfer','cheque','other')),
  paid_by          INTEGER REFERENCES users(id) ON DELETE RESTRICT,
  paid_at          TEXT,
  created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);
-- Their ids go on after the archive's (the phase 8 table took its counter when 0015 renamed
-- it): a refund and an archived one never share an id, so the print log (« refund ») and the
-- audit log (« refunds ») never mix them (REVIEW_FIXES round 2, finding 4).
INSERT INTO sqlite_sequence(name, seq)
SELECT 'refunds', (SELECT MAX(id) FROM archived_refunds)
 WHERE (SELECT MAX(id) FROM archived_refunds) IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name = 'refunds');
-- The archive (0015) kept the phase 8 index names: these are new ones.
CREATE INDEX ix_refund_requests_charge ON refunds(charge_id);
CREATE INDEX ix_refund_requests_status ON refunds(status);
CREATE INDEX ix_refund_requests_paid_at ON refunds(paid_at);

CREATE TABLE refund_allocations (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  refund_id             INTEGER NOT NULL REFERENCES refunds(id) ON DELETE RESTRICT,
  payment_allocation_id INTEGER NOT NULL REFERENCES payment_allocations(id) ON DELETE RESTRICT,
  amount                INTEGER NOT NULL CHECK (amount > 0),
  created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  UNIQUE (refund_id, payment_allocation_id)
);
CREATE INDEX ix_refund_takes_allocation ON refund_allocations(payment_allocation_id);

-- ===== refunds: asked =====
-- What the month holds: paid (payments not voided), what refunds other than this one keep
-- (pending: asked; approved and paid: approved), and what the archive handed back of it.
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

-- ===== refunds: decided, withdrawn, paid out; never deleted =====
CREATE TRIGGER trg_refund_requests_no_delete BEFORE DELETE ON refunds
BEGIN SELECT RAISE(ABORT, 'refunds cannot be deleted'); END;

-- What was asked never changes, a decision stays, a closed refund never changes at all.
-- pending -> approved | rejected | cancelled; approved -> paid | cancelled. Each step says
-- who and when; a rejection or a withdrawal says why. One trigger: its checks run in order.
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

  -- Money is taken back only in the transaction that pays the refund out: a refund
  -- withdrawn with allocations would count money that never went back.
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

  -- Payout fields only when paid, cancel fields only when cancelled, close_reason only
  -- when rejected or cancelled (REVIEW_FIXES round 2, finding 10).
  SELECT RAISE(ABORT, 'refund step fields do not match its status')
  WHERE ((NEW.number IS NOT NULL OR NEW.method IS NOT NULL
          OR NEW.paid_by IS NOT NULL OR NEW.paid_at IS NOT NULL)
         AND NEW.status <> 'paid')
     OR ((NEW.cancelled_by IS NOT NULL OR NEW.cancelled_at IS NOT NULL)
         AND NEW.status <> 'cancelled')
     OR (trim(COALESCE(NEW.close_reason, '')) <> ''
         AND NEW.status NOT IN ('rejected', 'cancelled'));
END;

-- ===== refund_allocations: the money taken back from each payment =====
CREATE TRIGGER trg_refund_takes_no_update BEFORE UPDATE ON refund_allocations
BEGIN SELECT RAISE(ABORT, 'refund_allocations are immutable'); END;
CREATE TRIGGER trg_refund_takes_no_delete BEFORE DELETE ON refund_allocations
BEGIN SELECT RAISE(ABORT, 'refund_allocations are immutable'); END;

CREATE TRIGGER trg_refund_takes_ins BEFORE INSERT ON refund_allocations
BEGIN
  SELECT RAISE(ABORT, 'refund must be approved before it is paid')
  WHERE (SELECT status FROM refunds WHERE id = NEW.refund_id) <> 'approved';

  SELECT RAISE(ABORT, 'payment is voided')
  WHERE EXISTS (SELECT 1 FROM payment_allocations pa
                  JOIN payment_voids v ON v.payment_id = pa.payment_id
                 WHERE pa.id = NEW.payment_allocation_id);

  SELECT RAISE(ABORT, 'allocation belongs to another charge')
  WHERE (SELECT charge_id FROM payment_allocations WHERE id = NEW.payment_allocation_id)
        IS NOT (SELECT charge_id FROM refunds WHERE id = NEW.refund_id);

  SELECT RAISE(ABORT, 'refund exceeds paid minus already refunded')
  WHERE COALESCE((SELECT SUM(amount) FROM refund_allocations
                   WHERE payment_allocation_id = NEW.payment_allocation_id), 0)
        + COALESCE((SELECT SUM(amount) FROM archived_refund_allocations
                     WHERE payment_allocation_id = NEW.payment_allocation_id), 0)
        + NEW.amount >
        (SELECT amount FROM payment_allocations WHERE id = NEW.payment_allocation_id);

  SELECT RAISE(ABORT, 'refund allocations exceed refund amount')
  WHERE COALESCE((SELECT SUM(amount) FROM refund_allocations
                   WHERE refund_id = NEW.refund_id), 0) + NEW.amount >
        (SELECT amount_approved FROM refunds WHERE id = NEW.refund_id);
END;

-- ===== voids: money handed back, or asked back, blocks one =====
-- A payment some of whose money was handed back (now or in the archive, 0016) cannot be
-- voided; nor one that paid a month with a request still pending or approved (withdraw or
-- reject it first): its reservation would be more than what is left paid.
DROP TRIGGER trg_void_rules;
CREATE TRIGGER trg_void_rules BEFORE INSERT ON payment_voids
BEGIN
  SELECT RAISE(ABORT, 'payment has refunds')
  WHERE EXISTS (SELECT 1 FROM archived_refund_allocations ra
                  JOIN payment_allocations pa ON pa.id = ra.payment_allocation_id
                 WHERE pa.payment_id = NEW.payment_id)
     OR EXISTS (SELECT 1 FROM refund_allocations ra
                  JOIN payment_allocations pa ON pa.id = ra.payment_allocation_id
                 WHERE pa.payment_id = NEW.payment_id);

  SELECT RAISE(ABORT, 'payment paid a month with an open refund request')
  WHERE EXISTS (SELECT 1 FROM payment_allocations pa
                  JOIN refunds r ON r.charge_id = pa.charge_id
                 WHERE pa.payment_id = NEW.payment_id
                   AND r.status IN ('pending','approved'));
END;

-- ===== charges: cancelled only once nothing paid is kept =====
-- The services already refuse to cancel a month or a fee with money on it; a month refunded
-- in full may now be cancelled. Money kept: paid by payments not voided, less what refunds
-- (and the archive) handed back from them.
CREATE TRIGGER trg_charges_cancel_money BEFORE UPDATE OF status ON charges
WHEN NEW.status = 'cancelled' AND OLD.status <> 'cancelled'
BEGIN
  SELECT RAISE(ABORT, 'charge has an open refund request')
  WHERE EXISTS (SELECT 1 FROM refunds
                 WHERE charge_id = OLD.id AND status IN ('pending','approved'));

  SELECT RAISE(ABORT, 'charge still holds money paid')
  WHERE COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa
                   WHERE pa.charge_id = OLD.id
                     AND NOT EXISTS (SELECT 1 FROM payment_voids v
                                      WHERE v.payment_id = pa.payment_id)), 0)
        > COALESCE((SELECT SUM(ra.amount) FROM refund_allocations ra
                      JOIN payment_allocations pa ON pa.id = ra.payment_allocation_id
                     WHERE pa.charge_id = OLD.id), 0)
          + COALESCE((SELECT SUM(ra.amount) FROM archived_refund_allocations ra
                        JOIN payment_allocations pa ON pa.id = ra.payment_allocation_id
                       WHERE pa.charge_id = OLD.id), 0);
END;
