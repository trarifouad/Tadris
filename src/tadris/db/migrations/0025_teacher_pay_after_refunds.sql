-- A teacher is paid on what the school keeps of a month (decided 2026-11-06): its price less
-- what refunds paid out and the archive handed back of it, no longer its full price. A month
-- in a payout counts that amount when the draft is built (a refund paid later on a month in
-- a draft builds the draft's line again; approved and paid payouts never change). migrate()
-- never re-runs 0013, so its rule on the months of a payout is replaced here.

DROP TRIGGER trg_payout_line_charge_rules;

CREATE TRIGGER trg_payout_line_charge_rules BEFORE INSERT ON payout_line_charges
BEGIN
  SELECT RAISE(ABORT, 'payout is not draft')
  WHERE (SELECT p.status FROM payout_lines l JOIN teacher_payouts p ON p.id = l.payout_id
          WHERE l.id = NEW.payout_line_id) <> 'draft';

  SELECT RAISE(ABORT, 'charge is not an open subscription charge')
  WHERE NOT EXISTS (SELECT 1 FROM charges
                     WHERE id = NEW.charge_id AND subscription_id IS NOT NULL AND status = 'open');

  -- the charge amount less what refunds and the archive handed back of it
  SELECT RAISE(ABORT, 'amount must equal the charge amount')
  WHERE NEW.amount <> (SELECT c.amount
                              - COALESCE((SELECT SUM(ra.amount) FROM refund_allocations ra
                                            JOIN payment_allocations pa
                                              ON pa.id = ra.payment_allocation_id
                                           WHERE pa.charge_id = c.id), 0)
                              - COALESCE((SELECT SUM(ra.amount)
                                            FROM archived_refund_allocations ra
                                            JOIN payment_allocations pa
                                              ON pa.id = ra.payment_allocation_id
                                           WHERE pa.charge_id = c.id
                                             AND NOT EXISTS (SELECT 1 FROM payment_voids v
                                                              WHERE v.payment_id = pa.payment_id)),
                                         0)
                         FROM charges c WHERE c.id = NEW.charge_id);

  SELECT RAISE(ABORT, 'accrual date outside payout period')
  WHERE NOT EXISTS (SELECT 1 FROM charges c
                      JOIN payout_lines l ON l.id = NEW.payout_line_id
                      JOIN teacher_payouts p ON p.id = l.payout_id
                     WHERE c.id = NEW.charge_id
                       AND c.accrual_date BETWEEN p.period_start AND p.period_end);

  SELECT RAISE(ABORT, 'charge belongs to another group')
  WHERE (SELECT e.group_id FROM charges c
           JOIN subscriptions s ON s.id = c.subscription_id
           JOIN enrollments e ON e.id = s.enrollment_id
          WHERE c.id = NEW.charge_id)
        <> (SELECT group_id FROM payout_lines WHERE id = NEW.payout_line_id);

  SELECT RAISE(ABORT, 'teacher is not the group teacher on the accrual date')
  WHERE NOT EXISTS (SELECT 1 FROM charges c
                      JOIN subscriptions s ON s.id = c.subscription_id
                      JOIN enrollments e ON e.id = s.enrollment_id
                      JOIN group_teachers gt ON gt.group_id = e.group_id
                      JOIN payout_lines l ON l.id = NEW.payout_line_id
                      JOIN teacher_payouts p ON p.id = l.payout_id
                     WHERE c.id = NEW.charge_id AND gt.teacher_id = p.teacher_id
                       AND gt.valid_from <= c.accrual_date
                       AND (gt.valid_to IS NULL OR gt.valid_to > c.accrual_date));

  SELECT RAISE(ABORT, 'rate differs from the teacher rate on the accrual date')
  WHERE (SELECT l.percentage_bp FROM payout_lines l WHERE l.id = NEW.payout_line_id)
        IS NOT (SELECT tr.percentage_bp FROM charges c
                  JOIN payout_lines l ON l.id = NEW.payout_line_id
                  JOIN teacher_payouts p ON p.id = l.payout_id
                  JOIN teacher_rates tr ON tr.teacher_id = p.teacher_id
                 WHERE c.id = NEW.charge_id
                   AND tr.valid_from <= c.accrual_date
                   AND (tr.valid_to IS NULL OR tr.valid_to > c.accrual_date));
END;
