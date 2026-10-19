-- Phase 8: refunds.
--
-- Refunds target one charge: a month or the registration fee (0001 allowed months only, so
-- the fee paid before cancelling a registration could not be given back). Nothing wrote
-- refunds before this phase: the table is rebuilt with charge_id, an optional subscription_id
-- (the month's), who asked, the refund number, how and by whom it was paid out.
--
-- A refund is money handed back for what was paid; it does not change what is owed.
--
-- The school gives no remises (discounts) nor corrections: a student owes the full price of
-- each month and fee. balance_entries (0001), never written, is dropped.

-- ===== refunds: rebuilt =====
-- The rule on refund_allocations reads refunds: drop it before the table goes.
DROP TRIGGER trg_refund_alloc_rules;

CREATE TABLE refunds_new (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  charge_id       INTEGER NOT NULL REFERENCES charges(id) ON DELETE RESTRICT,
  subscription_id INTEGER REFERENCES subscriptions(id) ON DELETE RESTRICT, -- NULL for the fee
  amount_computed INTEGER NOT NULL CHECK (amount_computed >= 0),           -- the suggestion
  amount_final    INTEGER NOT NULL CHECK (amount_final >= 0),
  refunded_amount INTEGER NOT NULL DEFAULT 0 CHECK (refunded_amount >= 0),
  reason          TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','approved','paid','rejected')),
  requested_by    INTEGER REFERENCES users(id) ON DELETE RESTRICT,
  approved_by     INTEGER REFERENCES users(id) ON DELETE RESTRICT,         -- who decided
  approved_at     TEXT,
  number          TEXT UNIQUE,                                             -- RB2026-00001
  method          TEXT CHECK (method IS NULL OR method IN ('cash','transfer','cheque','other')),
  paid_out_by     INTEGER REFERENCES users(id) ON DELETE RESTRICT,
  paid_out_at     TEXT,
  created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

INSERT INTO refunds_new(id, charge_id, subscription_id, amount_computed, amount_final,
                        refunded_amount, reason, status, approved_by, approved_at, paid_out_at,
                        created_at)
SELECT r.id,
       (SELECT c.id FROM charges c WHERE c.subscription_id = r.subscription_id
         ORDER BY c.id DESC LIMIT 1),
       r.subscription_id, r.amount_computed, r.amount_final, r.refunded_amount, r.reason,
       r.status, r.approved_by, r.approved_at, r.paid_out_at, r.created_at
  FROM refunds r;

DROP TABLE refunds;
ALTER TABLE refunds_new RENAME TO refunds;

CREATE INDEX ix_refunds_charge ON refunds(charge_id);
CREATE INDEX ix_refunds_status ON refunds(status);

CREATE TRIGGER trg_refunds_no_delete BEFORE DELETE ON refunds
BEGIN SELECT RAISE(ABORT, 'refunds cannot be deleted'); END;

-- What was asked never changes; a paid or rejected refund never changes at all.
CREATE TRIGGER trg_refunds_limited_update BEFORE UPDATE ON refunds
WHEN OLD.status IN ('paid','rejected')
  OR NEW.charge_id <> OLD.charge_id
  OR NEW.subscription_id IS NOT OLD.subscription_id
  OR NEW.amount_computed <> OLD.amount_computed
  OR NEW.reason <> OLD.reason
  OR NEW.requested_by IS NOT OLD.requested_by
  OR NEW.created_at <> OLD.created_at
BEGIN SELECT RAISE(ABORT, 'refund is locked'); END;

CREATE TRIGGER trg_refunds_rules BEFORE INSERT ON refunds
BEGIN
  SELECT RAISE(ABORT, 'a new refund is pending')
  WHERE NEW.status <> 'pending' OR NEW.refunded_amount <> 0;

  SELECT RAISE(ABORT, 'refund subscription differs from its charge')
  WHERE NEW.subscription_id IS NOT (SELECT subscription_id FROM charges WHERE id = NEW.charge_id);
END;

-- Paid out: approved first, and the money given back is exactly what its allocations say.
CREATE TRIGGER trg_refunds_paid BEFORE UPDATE OF status ON refunds
WHEN NEW.status = 'paid' AND OLD.status <> 'paid'
BEGIN
  SELECT RAISE(ABORT, 'refund must be approved before it is paid')
  WHERE OLD.status <> 'approved';

  SELECT RAISE(ABORT, 'refunded amount must match its allocations')
  WHERE NEW.refunded_amount <> NEW.amount_final
     OR NEW.refunded_amount <> COALESCE((SELECT SUM(amount) FROM refund_allocations
                                          WHERE refund_id = NEW.id), 0);
END;

-- Money given back comes from what payments not voided allocated to the refunded charge,
-- never more than each allocation, never more than the refund.
CREATE TRIGGER trg_refund_alloc_rules BEFORE INSERT ON refund_allocations
BEGIN
  SELECT RAISE(ABORT, 'refund is locked')
  WHERE (SELECT status FROM refunds WHERE id = NEW.refund_id) NOT IN ('pending','approved');

  SELECT RAISE(ABORT, 'payment is voided')
  WHERE EXISTS (SELECT 1 FROM payment_allocations pa
                  JOIN payment_voids v ON v.payment_id = pa.payment_id
                 WHERE pa.id = NEW.payment_allocation_id);

  SELECT RAISE(ABORT, 'allocation belongs to another charge')
  WHERE (SELECT charge_id FROM payment_allocations WHERE id = NEW.payment_allocation_id)
        IS NOT (SELECT charge_id FROM refunds WHERE id = NEW.refund_id);

  SELECT RAISE(ABORT, 'refund exceeds paid minus already refunded')
  WHERE COALESCE((SELECT SUM(amount) FROM refund_allocations
                   WHERE payment_allocation_id = NEW.payment_allocation_id), 0) + NEW.amount >
        (SELECT amount FROM payment_allocations WHERE id = NEW.payment_allocation_id);

  SELECT RAISE(ABORT, 'refund allocations exceed refund amount')
  WHERE COALESCE((SELECT SUM(amount) FROM refund_allocations
                   WHERE refund_id = NEW.refund_id), 0) + NEW.amount >
        (SELECT amount_final FROM refunds WHERE id = NEW.refund_id);
END;

-- ===== no adjustments =====
DROP TABLE balance_entries;
