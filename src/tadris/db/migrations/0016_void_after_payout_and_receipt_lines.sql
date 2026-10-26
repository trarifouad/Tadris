-- 1. A payment can be voided after a teacher payout counted its months. A payout pays the
--    full price of each month whether the student paid or not: a void changes nothing it
--    counts (the month is simply owed again). Refused before, a mistyped amount could never
--    be corrected once the month's payout was built. Money handed back (archived refunds,
--    0015) still blocks a void.
DROP TRIGGER trg_void_rules;
CREATE TRIGGER trg_void_rules BEFORE INSERT ON payment_voids
BEGIN
  SELECT RAISE(ABORT, 'payment has refunds')
  WHERE EXISTS (SELECT 1 FROM archived_refund_allocations ra
                  JOIN payment_allocations pa ON pa.id = ra.payment_allocation_id
                 WHERE pa.payment_id = NEW.payment_id);
END;

-- 2. Which recording made each allocation: the payment's own (recorded_with = payment_id), or
--    a later payment whose recording used this payment's credit. A receipt shows what was
--    paid when it was made, the same when printed again. NULL: made before this migration.
ALTER TABLE payment_allocations ADD COLUMN recorded_with INTEGER REFERENCES payments(id);
CREATE INDEX ix_payment_allocations_recorded_with ON payment_allocations(recorded_with);
