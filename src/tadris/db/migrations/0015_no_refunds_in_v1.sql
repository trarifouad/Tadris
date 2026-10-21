-- V1 has no refunds (decided after phase 12): the school has not opened yet, so the refund
-- workflow (request, approval, payout, slip) waits for V2. Money handed back exceptionally
-- is handled outside the app by the director.
--
-- Nothing is deleted: refunds and refund_allocations become read-only archives, so a
-- database that recorded refunds keeps them. A payment some of whose money was handed back
-- still cannot be voided: trg_void_rules (0003) follows the renamed table.

DROP TRIGGER trg_refunds_no_delete;
DROP TRIGGER trg_refunds_limited_update;
DROP TRIGGER trg_refunds_rules;
DROP TRIGGER trg_refunds_paid;
DROP TRIGGER trg_refund_alloc_rules;
DROP TRIGGER trg_refund_alloc_no_update;
DROP TRIGGER trg_refund_alloc_no_delete;

ALTER TABLE refunds RENAME TO archived_refunds;
ALTER TABLE refund_allocations RENAME TO archived_refund_allocations;

CREATE TRIGGER trg_archived_refunds_no_insert BEFORE INSERT ON archived_refunds
BEGIN SELECT RAISE(ABORT, 'archived refunds are read-only'); END;
CREATE TRIGGER trg_archived_refunds_no_update BEFORE UPDATE ON archived_refunds
BEGIN SELECT RAISE(ABORT, 'archived refunds are read-only'); END;
CREATE TRIGGER trg_archived_refunds_no_delete BEFORE DELETE ON archived_refunds
BEGIN SELECT RAISE(ABORT, 'archived refunds are read-only'); END;

CREATE TRIGGER trg_archived_refund_alloc_no_insert BEFORE INSERT ON archived_refund_allocations
BEGIN SELECT RAISE(ABORT, 'archived refunds are read-only'); END;
CREATE TRIGGER trg_archived_refund_alloc_no_update BEFORE UPDATE ON archived_refund_allocations
BEGIN SELECT RAISE(ABORT, 'archived refunds are read-only'); END;
CREATE TRIGGER trg_archived_refund_alloc_no_delete BEFORE DELETE ON archived_refund_allocations
BEGIN SELECT RAISE(ABORT, 'archived refunds are read-only'); END;
