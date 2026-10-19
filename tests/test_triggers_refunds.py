"""Migration 0012: refunds target a charge; there are no adjustments. Raw SQL, as the
services refuse these cases first (see test_triggers_last_line.py for the `seeded`
fixture's content)."""

import re
import sqlite3

import pytest


def refused(message: str):
    return pytest.raises(sqlite3.IntegrityError, match=re.escape(message))


def one(c, sql, params=()) -> int:
    return c.execute(sql, params).lastrowid


def alloc(c, payment, charge, amount) -> int:
    return one(c, "INSERT INTO payment_allocations(payment_id,charge_id,amount) VALUES(?,?,?)",
               (payment, charge, amount))


def fee_charge(c) -> int:
    return one(c, "INSERT INTO charges(registration_id,description,amount,due_date,accrual_date) "
                  "VALUES(1,'Frais',2000,'2026-09-01','2026-09-01')")


def refund(c, amount=1000, charge=1, subscription=1, **extra) -> int:
    columns = ["charge_id", "subscription_id", "amount_computed", "amount_final", "reason"]
    values = [charge, subscription, amount, amount, "Départ"]
    for key, value in extra.items():
        columns.append(key)
        values.append(value)
    marks = ",".join("?" for _ in values)
    return one(c, f"INSERT INTO refunds({','.join(columns)}) VALUES({marks})", values)


def refund_alloc(c, refund_id, allocation_id, amount) -> int:
    return one(c, "INSERT INTO refund_allocations(refund_id,payment_allocation_id,amount) "
                  "VALUES(?,?,?)", (refund_id, allocation_id, amount))


# ----- refunds -----

def test_the_rebuilt_table_keeps_its_links(seeded):
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        refund(seeded, charge=999, subscription=None)
    links = {row["table"] for row in seeded.execute("PRAGMA foreign_key_list(refund_allocations)")}
    assert links == {"refunds", "payment_allocations"}
    with pytest.raises(sqlite3.IntegrityError):  # its rule refuses before the key is checked
        refund_alloc(seeded, 999, alloc(seeded, 1, 1, 3000), 100)


def test_a_new_refund_is_pending_with_nothing_paid(seeded):
    with refused("a new refund is pending"):
        refund(seeded, status="approved")
    with refused("a new refund is pending"):
        refund(seeded, refunded_amount=500)


def test_a_refund_matches_its_charge(seeded):
    fee = fee_charge(seeded)
    with refused("refund subscription differs from its charge"):
        refund(seeded, charge=1, subscription=None)
    with refused("refund subscription differs from its charge"):
        refund(seeded, charge=fee, subscription=1)
    refund(seeded, charge=fee, subscription=None)  # the fee: no subscription


def test_paid_only_once_approved(seeded):
    allocation = alloc(seeded, 1, 1, 3000)
    refund_id = refund(seeded)
    refund_alloc(seeded, refund_id, allocation, 1000)
    with refused("refund must be approved before it is paid"):
        seeded.execute("UPDATE refunds SET status='paid', refunded_amount=1000 WHERE id=?",
                       (refund_id,))


def test_paid_amount_matches_its_allocations(seeded):
    seeded.execute("INSERT INTO payments(student_id,amount,method,paid_at,received_by) "
                   "VALUES(1,400,'cash','2026-09-03T10:00:00',1)")
    allocation, other = alloc(seeded, 1, 1, 2600), alloc(seeded, 2, 1, 400)
    refund_id = refund(seeded)
    seeded.execute("UPDATE refunds SET status='approved', approved_by=1 WHERE id=?",
                   (refund_id,))
    with refused("refunded amount must match its allocations"):  # nothing allocated
        seeded.execute("UPDATE refunds SET status='paid', refunded_amount=1000 WHERE id=?",
                       (refund_id,))
    refund_alloc(seeded, refund_id, allocation, 600)
    with refused("refunded amount must match its allocations"):  # 600 of 1 000
        seeded.execute("UPDATE refunds SET status='paid', refunded_amount=1000 WHERE id=?",
                       (refund_id,))
    with refused("refunded amount must match its allocations"):  # not the final amount
        seeded.execute("UPDATE refunds SET status='paid', refunded_amount=600 WHERE id=?",
                       (refund_id,))
    refund_alloc(seeded, refund_id, other, 400)  # one line per payment allocation
    seeded.execute("UPDATE refunds SET status='paid', refunded_amount=1000 WHERE id=?",
                   (refund_id,))


def test_a_refund_spreads_over_several_payments(seeded):
    """Cap per payment: 1 800 + 1 200 paid, 2 000 refunded = 1 800 + 200."""
    seeded.execute("INSERT INTO payments(student_id,amount,method,paid_at,received_by) "
                   "VALUES(1,1200,'cash','2026-09-03T10:00:00',1)")
    first, second = alloc(seeded, 1, 1, 1800), alloc(seeded, 2, 1, 1200)
    refund_id = refund(seeded, amount=2000)
    with refused("refund exceeds paid minus already refunded"):
        refund_alloc(seeded, refund_id, first, 1801)
    refund_alloc(seeded, refund_id, first, 1800)
    refund_alloc(seeded, refund_id, second, 200)
    with refused("refund allocations exceed refund amount"):
        refund_alloc(seeded, refund_id, second, 1)


# ----- no adjustments -----

def test_the_adjustments_table_is_gone(seeded):
    """The school gives no remises nor corrections: what is owed is the full price."""
    assert seeded.execute("SELECT 1 FROM sqlite_master WHERE name = 'balance_entries'"
                          ).fetchone() is None


