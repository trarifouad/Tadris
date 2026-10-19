"""Migration 0013: payout lines per group and rate; a payout goes draft -> approved -> paid,
its totals exactly its lines. Raw SQL, as the services refuse these cases first.

The `seeded` fixture: teacher 1 at 60 % from 01/08, group 1 (3 000 DA), charge 1 (a month,
accrued 01/09), all of student 1's (see test_triggers_last_line.py)."""

import re
import sqlite3

import pytest


def refused(message: str):
    return pytest.raises(sqlite3.IntegrityError, match=re.escape(message))


def one(c, sql, params=()) -> int:
    return c.execute(sql, params).lastrowid


def payout(c, base=3000, due=1800, start="2026-09-01", end="2026-09-30") -> int:
    return one(c, "INSERT INTO teacher_payouts(teacher_id,period_start,period_end,base_amount,"
                  "amount_due) VALUES(1,?,?,?,?)", (start, end, base, due))


def line(c, payout_id, revenue=3000, bp=6000, amount=1800) -> int:
    return one(c, "INSERT INTO payout_lines(payout_id,group_id,revenue_basis,percentage_bp,"
                  "amount) VALUES(?,1,?,?,?)", (payout_id, revenue, bp, amount))


def count(c, line_id, charge=1, amount=3000) -> None:
    c.execute("INSERT INTO payout_line_charges(payout_line_id,charge_id,amount) VALUES(?,?,?)",
              (line_id, charge, amount))


def october_month(c) -> int:
    """A second month of student 1, accrued 01/10, and its charge."""
    sub = one(c, "INSERT INTO subscriptions(enrollment_id,renewal_of_id,price,start_date,"
                 "end_date) VALUES(1,1,3000,'2026-10-01','2026-11-01')")
    return one(c, "INSERT INTO charges(subscription_id,description,amount,due_date,"
                  "accrual_date) VALUES(?,'Oct',3000,'2026-10-01','2026-10-01')", (sub,))


def approve(c, payout_id) -> None:
    c.execute("UPDATE teacher_payouts SET status='approved', approved_by=1 WHERE id=?",
              (payout_id,))


def full(c) -> int:
    """A valid September payout: 60 % of 3 000."""
    payout_id = payout(c)
    count(c, line(c, payout_id))
    return payout_id


# ----- the rate -----

def test_a_line_is_at_the_teachers_rate_on_the_first_day(seeded):
    payout_id = payout(seeded)
    with refused("rate differs from the teacher rate on the accrual date"):
        count(seeded, line(seeded, payout_id, bp=5000, amount=1500))


def test_a_teacher_without_a_rate_that_day(seeded):
    seeded.execute("DELETE FROM teacher_rates")
    payout_id = payout(seeded)
    with refused("rate differs from the teacher rate on the accrual date"):
        count(seeded, line(seeded, payout_id))


def test_one_group_at_two_rates_is_two_lines(seeded):
    """60 % until 30/09, 50 % from 01/10: September and October of group 1, one payout."""
    seeded.execute("UPDATE teacher_rates SET valid_to='2026-10-01'")
    seeded.execute("INSERT INTO teacher_rates(teacher_id,percentage_bp,valid_from) "
                   "VALUES(1,5000,'2026-10-01')")
    october = october_month(seeded)
    payout_id = payout(seeded, base=6000, due=3300, end="2026-10-31")
    count(seeded, line(seeded, payout_id, 3000, 6000, 1800))
    count(seeded, line(seeded, payout_id, 3000, 5000, 1500), october)
    with refused("UNIQUE constraint failed"):  # still one line per group and rate
        seeded.execute("INSERT INTO payout_lines(payout_id,group_id,revenue_basis,percentage_bp,"
                       "amount) VALUES(?,1,0,5000,0)", (payout_id,))
    approve(seeded, payout_id)


# ----- draft -> approved -> paid -----

def test_approved_only_when_the_totals_are_the_lines(seeded):
    payout_id = payout(seeded, base=3000, due=1800)
    with refused("payout totals differ from its lines"):  # no line at all
        approve(seeded, payout_id)
    line_id = line(seeded, payout_id)
    with refused("payout totals differ from its lines"):  # a line without its month
        approve(seeded, payout_id)
    count(seeded, line_id)
    seeded.execute("UPDATE teacher_payouts SET amount_due=1801 WHERE id=?", (payout_id,))
    with refused("payout totals differ from its lines"):  # the total is not the lines'
        approve(seeded, payout_id)
    seeded.execute("UPDATE teacher_payouts SET amount_due=1800 WHERE id=?", (payout_id,))
    approve(seeded, payout_id)


def test_a_line_is_its_revenue_at_its_rate_rounded_down(seeded):
    payout_id = payout(seeded, base=3000, due=1801)
    count(seeded, line(seeded, payout_id, amount=1801))
    with refused("payout totals differ from its lines"):
        approve(seeded, payout_id)


def test_never_back_to_draft(seeded):
    payout_id = full(seeded)
    approve(seeded, payout_id)
    with refused("payout cannot go back to draft"):
        seeded.execute("UPDATE teacher_payouts SET status='draft' WHERE id=?", (payout_id,))


def test_paid_only_once_approved_for_the_whole_amount(seeded):
    payout_id = full(seeded)
    with refused("payout must be approved before it is paid"):
        seeded.execute("UPDATE teacher_payouts SET status='paid', amount_paid=1800, "
                       "receipt_number='PE2026-00001' WHERE id=?", (payout_id,))
    approve(seeded, payout_id)
    with refused("payout paid amount must equal amount due"):
        seeded.execute("UPDATE teacher_payouts SET status='paid', amount_paid=1000, "
                       "receipt_number='PE2026-00001' WHERE id=?", (payout_id,))
    with refused("payout paid amount must equal amount due"):  # no number
        seeded.execute("UPDATE teacher_payouts SET status='paid', amount_paid=1800 WHERE id=?",
                       (payout_id,))
    seeded.execute("UPDATE teacher_payouts SET status='paid', amount_paid=1800, "
                   "receipt_number='PE2026-00001', method='cash' WHERE id=?", (payout_id,))
    with refused("payout is locked"):
        seeded.execute("UPDATE teacher_payouts SET method='cheque' WHERE id=?", (payout_id,))


def test_approved_is_approved(seeded):
    payout_id = full(seeded)
    approve(seeded, payout_id)
    seeded.execute("UPDATE teacher_payouts SET status='paid', amount_paid=1800, "
                   "receipt_number='PE2026-00001' WHERE id=?", (payout_id,))
    with refused("payout must be a draft to be approved"):
        seeded.execute("UPDATE teacher_payouts SET status='approved' WHERE id=?", (payout_id,))
