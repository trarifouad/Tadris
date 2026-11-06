"""SQL fragments for the money on a charge, written once for every repository (REVIEW_FIXES,
finding 15): what was paid on it, by payments not voided, and what went back from those
payments, by refunds (0021) and the archive (0015). The triggers keep their own copies: SQL
cannot import. `charge` is the SQL of the charge's id where the fragment is used, by
default the alias c."""


def paid_on(charge: str = "c.id") -> str:
    """What payments not voided paid on the charge."""
    return f"""
    COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa
               WHERE pa.charge_id = {charge}
                 AND NOT EXISTS (SELECT 1 FROM payment_voids v
                                  WHERE v.payment_id = pa.payment_id)), 0)
"""


def archived_on(charge: str = "c.id") -> str:
    """What the archive (the phase 8 refunds) handed back from the charge's payments not
    voided: never handed back again."""
    return f"""
    COALESCE((SELECT SUM(ra.amount) FROM archived_refund_allocations ra
                JOIN payment_allocations pa ON pa.id = ra.payment_allocation_id
               WHERE pa.charge_id = {charge}
                 AND NOT EXISTS (SELECT 1 FROM payment_voids v
                                  WHERE v.payment_id = pa.payment_id)), 0)
"""


def handed_back_on(charge: str = "c.id") -> str:
    """What refunds paid out and the archive handed back from the charge's payments (a
    payment with money handed back cannot be voided)."""
    return f"""
    (COALESCE((SELECT SUM(ra.amount) FROM refund_allocations ra
                 JOIN payment_allocations pa ON pa.id = ra.payment_allocation_id
                WHERE pa.charge_id = {charge}), 0)
     + {archived_on(charge)})
"""
