-- Phase 9: teacher payouts.
--
-- A payout pays a teacher a percentage of the full price of each month (subscription
-- charge) of the groups they taught on the month's first day (accrual date), whether the
-- student paid or not. A payout takes every month not paid to a teacher yet up to a date:
-- a month renewed late (starting in a period already paid) is never left behind.
--
-- One line per group and rate: months of one group at two rates (a rate change, or a late
-- month from before it) are two lines, each at the teacher's rate on the months' first day.
-- Nothing wrote payout_lines before this phase: the table is rebuilt with that key.
-- teacher_payouts gains who approved and when, and how and by whom it was paid out.

-- ===== payout_lines: rebuilt, one line per group and rate =====
-- Triggers on payout_line_charges read payout_lines: drop them before the table goes.
DROP TRIGGER trg_payout_line_charge_rules;
DROP TRIGGER trg_plc_lock_del;

CREATE TABLE payout_lines_new (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  payout_id     INTEGER NOT NULL REFERENCES teacher_payouts(id) ON DELETE RESTRICT,
  group_id      INTEGER NOT NULL REFERENCES class_groups(id) ON DELETE RESTRICT,
  revenue_basis INTEGER NOT NULL CHECK (revenue_basis >= 0),
  percentage_bp INTEGER NOT NULL CHECK (percentage_bp BETWEEN 0 AND 10000),  -- snapshot
  amount        INTEGER NOT NULL CHECK (amount >= 0),
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  UNIQUE (payout_id, group_id, percentage_bp)
);
INSERT INTO payout_lines_new(id, payout_id, group_id, revenue_basis, percentage_bp, amount,
                             created_at)
SELECT id, payout_id, group_id, revenue_basis, percentage_bp, amount, created_at
  FROM payout_lines;
DROP TABLE payout_lines;
ALTER TABLE payout_lines_new RENAME TO payout_lines;
CREATE INDEX ix_payout_lines_payout ON payout_lines(payout_id);

CREATE TRIGGER trg_payout_line_ins BEFORE INSERT ON payout_lines
WHEN (SELECT status FROM teacher_payouts WHERE id = NEW.payout_id) <> 'draft'
BEGIN SELECT RAISE(ABORT, 'payout is not draft'); END;

CREATE TRIGGER trg_payout_lines_lock_upd BEFORE UPDATE ON payout_lines
WHEN (SELECT status FROM teacher_payouts WHERE id = OLD.payout_id) <> 'draft'
BEGIN SELECT RAISE(ABORT, 'payout is locked'); END;

CREATE TRIGGER trg_payout_lines_lock_del BEFORE DELETE ON payout_lines
WHEN (SELECT status FROM teacher_payouts WHERE id = OLD.payout_id) <> 'draft'
BEGIN SELECT RAISE(ABORT, 'payout is locked'); END;

-- 0004's rules, and the rate: the line's rate is the teacher's rate on the month's first day.
CREATE TRIGGER trg_payout_line_charge_rules BEFORE INSERT ON payout_line_charges
BEGIN
  SELECT RAISE(ABORT, 'payout is not draft')
  WHERE (SELECT p.status FROM payout_lines l JOIN teacher_payouts p ON p.id = l.payout_id
          WHERE l.id = NEW.payout_line_id) <> 'draft';

  SELECT RAISE(ABORT, 'charge is not an open subscription charge')
  WHERE NOT EXISTS (SELECT 1 FROM charges
                     WHERE id = NEW.charge_id AND subscription_id IS NOT NULL AND status = 'open');

  SELECT RAISE(ABORT, 'amount must equal the charge amount')
  WHERE NEW.amount <> (SELECT amount FROM charges WHERE id = NEW.charge_id);

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

CREATE TRIGGER trg_plc_lock_del BEFORE DELETE ON payout_line_charges
WHEN (SELECT p.status FROM payout_lines l JOIN teacher_payouts p ON p.id = l.payout_id
       WHERE l.id = OLD.payout_line_id) <> 'draft'
BEGIN SELECT RAISE(ABORT, 'payout is locked'); END;

-- ===== teacher_payouts: decision and payout =====
ALTER TABLE teacher_payouts ADD COLUMN approved_by INTEGER REFERENCES users(id);
ALTER TABLE teacher_payouts ADD COLUMN approved_at TEXT;
ALTER TABLE teacher_payouts ADD COLUMN method TEXT
  CHECK (method IS NULL OR method IN ('cash','transfer','cheque','other'));
ALTER TABLE teacher_payouts ADD COLUMN paid_by INTEGER REFERENCES users(id);

-- draft -> approved -> paid, never back. Approved: the totals are exactly its lines, each
-- line exactly its months at its rate (rounded down). Paid: the whole amount, numbered.
CREATE TRIGGER trg_payouts_status BEFORE UPDATE OF status ON teacher_payouts
WHEN NEW.status <> OLD.status
BEGIN
  SELECT RAISE(ABORT, 'payout cannot go back to draft')
  WHERE NEW.status = 'draft';

  SELECT RAISE(ABORT, 'payout must be a draft to be approved')
  WHERE NEW.status = 'approved' AND OLD.status <> 'draft';

  SELECT RAISE(ABORT, 'payout totals differ from its lines')
  WHERE NEW.status = 'approved' AND (
        NEW.base_amount <> COALESCE((SELECT SUM(revenue_basis) FROM payout_lines
                                      WHERE payout_id = NEW.id), 0)
     OR NEW.amount_due <> COALESCE((SELECT SUM(amount) FROM payout_lines
                                     WHERE payout_id = NEW.id), 0)
     OR EXISTS (SELECT 1 FROM payout_lines l
                 WHERE l.payout_id = NEW.id
                   AND (l.revenue_basis <> COALESCE((SELECT SUM(amount) FROM payout_line_charges
                                                      WHERE payout_line_id = l.id), 0)
                        OR l.amount <> l.revenue_basis * l.percentage_bp / 10000)));

  SELECT RAISE(ABORT, 'payout must be approved before it is paid')
  WHERE NEW.status = 'paid' AND OLD.status <> 'approved';

  SELECT RAISE(ABORT, 'payout paid amount must equal amount due')
  WHERE NEW.status = 'paid' AND (NEW.amount_paid <> NEW.amount_due
                                  OR NEW.receipt_number IS NULL);
END;
