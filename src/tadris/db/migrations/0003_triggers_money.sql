-- ===== Immutability: corrections are new rows =====
CREATE TRIGGER trg_payments_no_update BEFORE UPDATE ON payments
BEGIN SELECT RAISE(ABORT, 'payments are immutable'); END;
CREATE TRIGGER trg_payments_no_delete BEFORE DELETE ON payments
BEGIN SELECT RAISE(ABORT, 'payments are immutable'); END;

CREATE TRIGGER trg_alloc_no_update BEFORE UPDATE ON payment_allocations
BEGIN SELECT RAISE(ABORT, 'payment_allocations are immutable'); END;
CREATE TRIGGER trg_alloc_no_delete BEFORE DELETE ON payment_allocations
BEGIN SELECT RAISE(ABORT, 'payment_allocations are immutable'); END;

CREATE TRIGGER trg_receipts_no_update BEFORE UPDATE ON receipts
BEGIN SELECT RAISE(ABORT, 'receipts are immutable'); END;
CREATE TRIGGER trg_receipts_no_delete BEFORE DELETE ON receipts
BEGIN SELECT RAISE(ABORT, 'receipts are immutable'); END;

CREATE TRIGGER trg_voids_no_update BEFORE UPDATE ON payment_voids
BEGIN SELECT RAISE(ABORT, 'payment_voids are immutable'); END;
CREATE TRIGGER trg_voids_no_delete BEFORE DELETE ON payment_voids
BEGIN SELECT RAISE(ABORT, 'payment_voids are immutable'); END;

CREATE TRIGGER trg_audit_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is immutable'); END;
CREATE TRIGGER trg_audit_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is immutable'); END;

CREATE TRIGGER trg_refund_alloc_no_update BEFORE UPDATE ON refund_allocations
BEGIN SELECT RAISE(ABORT, 'refund_allocations are immutable'); END;
CREATE TRIGGER trg_refund_alloc_no_delete BEFORE DELETE ON refund_allocations
BEGIN SELECT RAISE(ABORT, 'refund_allocations are immutable'); END;

CREATE TRIGGER trg_refunds_no_delete BEFORE DELETE ON refunds
BEGIN SELECT RAISE(ABORT, 'refunds cannot be deleted'); END;
-- refunds: only approval/payout fields may change, and only before they are paid/rejected
CREATE TRIGGER trg_refunds_limited_update BEFORE UPDATE ON refunds
WHEN OLD.status IN ('paid','rejected')
  OR NEW.subscription_id <> OLD.subscription_id
  OR NEW.amount_computed <> OLD.amount_computed
  OR NEW.reason <> OLD.reason
  OR NEW.created_at <> OLD.created_at
BEGIN SELECT RAISE(ABORT, 'refund is locked'); END;

-- ===== Allocation rules =====
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

-- ===== Void rule: blocked once the money was used downstream =====
CREATE TRIGGER trg_void_rules BEFORE INSERT ON payment_voids
BEGIN
  SELECT RAISE(ABORT, 'payment already counted in a teacher payout')
  WHERE EXISTS (SELECT 1 FROM payment_allocations pa
                  JOIN payout_line_charges plc ON plc.charge_id = pa.charge_id
                 WHERE pa.payment_id = NEW.payment_id);

  SELECT RAISE(ABORT, 'payment has refunds')
  WHERE EXISTS (SELECT 1 FROM refund_allocations ra
                  JOIN payment_allocations pa ON pa.id = ra.payment_allocation_id
                 WHERE pa.payment_id = NEW.payment_id);
END;

-- ===== Charges: allowed audited updates only; cancel blocked after payout =====
CREATE TRIGGER trg_charges_limited_update BEFORE UPDATE ON charges
WHEN NEW.amount <> OLD.amount
  OR NEW.registration_id IS NOT OLD.registration_id
  OR NEW.subscription_id IS NOT OLD.subscription_id
  OR NEW.description <> OLD.description
  OR NEW.due_date <> OLD.due_date
BEGIN SELECT RAISE(ABORT, 'only charges.status and accrual_date may change'); END;

CREATE TRIGGER trg_charges_lock_after_payout BEFORE UPDATE ON charges
WHEN (NEW.status <> OLD.status OR NEW.accrual_date <> OLD.accrual_date)
 AND EXISTS (SELECT 1 FROM payout_line_charges WHERE charge_id = OLD.id)
BEGIN SELECT RAISE(ABORT, 'charge already counted in a teacher payout'); END;
