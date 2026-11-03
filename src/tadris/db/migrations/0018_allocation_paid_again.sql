-- A payment can pay the same charge again through a later recording. Its credit paid a
-- month, a void of another payment made that month owed again, and the next payment's
-- recording uses the credit on it once more: a second (payment, charge) row, recorded with
-- the later payment. UNIQUE (payment_id, charge_id) refused it, and every payment of the
-- student was then refused. One row per payment, charge and recording now (a recording pays
-- a charge from a payment once).
--
-- SQLite cannot change a constraint in place: the table is rebuilt with its rows and ids.
-- archived_refund_allocations (0015) points at it with ON DELETE RESTRICT, so it is rebuilt
-- too, pointing at the new table, before the old one goes; the renames then carry the
-- reference over. Foreign keys stay on: nothing points at a row that is gone. The triggers
-- and indexes of both tables, and trg_void_rules that reads them, are made again as they
-- were (0003, 0002, 0015, 0016).

DROP TRIGGER trg_void_rules;

CREATE TABLE payment_allocations_new (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  payment_id    INTEGER NOT NULL REFERENCES payments(id) ON DELETE RESTRICT,
  charge_id     INTEGER NOT NULL REFERENCES charges(id) ON DELETE RESTRICT,
  amount        INTEGER NOT NULL CHECK (amount > 0),
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  recorded_with INTEGER REFERENCES payments(id),
  UNIQUE (payment_id, charge_id, recorded_with)
);
INSERT INTO payment_allocations_new(id, payment_id, charge_id, amount, created_at, recorded_with)
SELECT id, payment_id, charge_id, amount, created_at, recorded_with FROM payment_allocations;

CREATE TABLE archived_refund_allocations_new (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  refund_id             INTEGER NOT NULL REFERENCES archived_refunds(id) ON DELETE RESTRICT,
  payment_allocation_id INTEGER NOT NULL REFERENCES payment_allocations_new(id)
                        ON DELETE RESTRICT,
  amount                INTEGER NOT NULL CHECK (amount > 0),
  created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  UNIQUE (refund_id, payment_allocation_id)
);
INSERT INTO archived_refund_allocations_new(id, refund_id, payment_allocation_id, amount,
                                            created_at)
SELECT id, refund_id, payment_allocation_id, amount, created_at
  FROM archived_refund_allocations;

-- The next ids follow on from the old tables' (never reused).
UPDATE sqlite_sequence
   SET seq = (SELECT seq FROM sqlite_sequence WHERE name = 'payment_allocations')
 WHERE name = 'payment_allocations_new'
   AND EXISTS (SELECT 1 FROM sqlite_sequence WHERE name = 'payment_allocations');
UPDATE sqlite_sequence
   SET seq = (SELECT seq FROM sqlite_sequence WHERE name = 'archived_refund_allocations')
 WHERE name = 'archived_refund_allocations_new'
   AND EXISTS (SELECT 1 FROM sqlite_sequence WHERE name = 'archived_refund_allocations');

DROP TABLE archived_refund_allocations;
DROP TABLE payment_allocations;
ALTER TABLE payment_allocations_new RENAME TO payment_allocations;
ALTER TABLE archived_refund_allocations_new RENAME TO archived_refund_allocations;

-- ===== payment_allocations: indexes and triggers as before =====
CREATE INDEX ix_allocations_charge ON payment_allocations(charge_id);
CREATE INDEX ix_payment_allocations_recorded_with ON payment_allocations(recorded_with);
-- A row from before 0016 has no recording (NULL, which UNIQUE never compares): those stay
-- one per payment and charge, as they were.
CREATE UNIQUE INDEX uq_allocation_without_recording ON payment_allocations(payment_id, charge_id)
  WHERE recorded_with IS NULL;

CREATE TRIGGER trg_alloc_no_update BEFORE UPDATE ON payment_allocations
BEGIN SELECT RAISE(ABORT, 'payment_allocations are immutable'); END;
CREATE TRIGGER trg_alloc_no_delete BEFORE DELETE ON payment_allocations
BEGIN SELECT RAISE(ABORT, 'payment_allocations are immutable'); END;

CREATE TRIGGER trg_alloc_rules BEFORE INSERT ON payment_allocations
BEGIN
  SELECT RAISE(ABORT, 'payment is voided')
  WHERE EXISTS (SELECT 1 FROM payment_voids WHERE payment_id = NEW.payment_id);

  SELECT RAISE(ABORT, 'charge is cancelled')
  WHERE (SELECT status FROM charges WHERE id = NEW.charge_id) <> 'open';

  SELECT RAISE(ABORT, 'payment and charge belong to different students')
  WHERE (SELECT student_id FROM payments WHERE id = NEW.payment_id) <>
        (SELECT COALESCE(
            (SELECT r.student_id FROM registrations r WHERE r.id = c.registration_id),
            (SELECT e.student_id FROM subscriptions s
               JOIN enrollments e ON e.id = s.enrollment_id
              WHERE s.id = c.subscription_id))
           FROM charges c WHERE c.id = NEW.charge_id);

  SELECT RAISE(ABORT, 'allocations exceed payment amount')
  WHERE COALESCE((SELECT SUM(amount) FROM payment_allocations
                   WHERE payment_id = NEW.payment_id), 0) + NEW.amount >
        (SELECT amount FROM payments WHERE id = NEW.payment_id);

  SELECT RAISE(ABORT, 'allocations exceed charge amount')
  WHERE COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa
                   WHERE pa.charge_id = NEW.charge_id
                     AND NOT EXISTS (SELECT 1 FROM payment_voids v
                                      WHERE v.payment_id = pa.payment_id)), 0)
        + NEW.amount >
        (SELECT amount FROM charges WHERE id = NEW.charge_id);
END;

-- ===== archived_refund_allocations: read-only, as before =====
CREATE INDEX ix_refund_alloc_payment_al ON archived_refund_allocations(payment_allocation_id);

CREATE TRIGGER trg_archived_refund_alloc_no_insert BEFORE INSERT ON archived_refund_allocations
BEGIN SELECT RAISE(ABORT, 'archived refunds are read-only'); END;
CREATE TRIGGER trg_archived_refund_alloc_no_update BEFORE UPDATE ON archived_refund_allocations
BEGIN SELECT RAISE(ABORT, 'archived refunds are read-only'); END;
CREATE TRIGGER trg_archived_refund_alloc_no_delete BEFORE DELETE ON archived_refund_allocations
BEGIN SELECT RAISE(ABORT, 'archived refunds are read-only'); END;

-- ===== voids: money handed back (archived refunds) still blocks one (0016) =====
CREATE TRIGGER trg_void_rules BEFORE INSERT ON payment_voids
BEGIN
  SELECT RAISE(ABORT, 'payment has refunds')
  WHERE EXISTS (SELECT 1 FROM archived_refund_allocations ra
                  JOIN payment_allocations pa ON pa.id = ra.payment_allocation_id
                 WHERE pa.payment_id = NEW.payment_id);
END;
