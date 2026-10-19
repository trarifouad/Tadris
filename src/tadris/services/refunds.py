from datetime import date, datetime, timedelta

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, NotFound, ValidationError
from tadris.core.money import format_dzd
from tadris.core.permissions import require
from tadris.core.text import clean
from tadris.db.errors import atomic
from tadris.domain.models import PAYMENT_METHODS, Refund, RefundableCharge
from tadris.i18n.fr import t
from tadris.repositories import enrollments as enrollments_repo
from tadris.repositories import payments as payments_repo
from tadris.repositories import refunds as repo
from tadris.repositories import subscriptions as subscriptions_repo
from tadris.services import audit, counters

# A refund hands back money paid on one charge (a month or the registration fee). It does not
# change what is owed: a month refunded in full stays paid, and the director may then cancel
# it (cancelling looks at what was paid and not refunded).
#
# The desk asks (pending), with a suggestion: for a month, what was paid beyond the value of
# the days used (until the student left, or until today), at the month's price; for
# the fee, everything kept. The director approves (the amount may change) or rejects. The
# desk pays out an approved refund: in one transaction, the money is taken back from the
# payments that paid the charge (latest first, never more than each one gave: trigger), a
# number 'RB2026-00001' comes from the year's counter, and the refund is locked.
# Not covered: credit (money paid and allocated to no charge) cannot be refunded.


def _now() -> str:
    return f"{dates.iso(dates.today())}T{datetime.now():%H:%M:%S}"


def _to_refund(row) -> Refund:
    return Refund(
        id=row["id"], charge_id=row["charge_id"], subscription_id=row["subscription_id"],
        student_id=row["student_id"], description=row["description"],
        amount_computed=row["amount_computed"], amount_final=row["amount_final"],
        refunded_amount=row["refunded_amount"], reason=row["reason"], status=row["status"],
        requested_by=row["requested_by"], decided_by=row["decided_by"],
        decided_at=row["approved_at"], number=row["number"], method=row["method"],
        paid_out_by=row["paid_out_by"], paid_out_at=row["paid_out_at"],
        created_at=row["created_at"],
    )


def _require_row(conn, refund_id: int):
    row = repo.get(conn, refund_id)
    if row is None:
        raise NotFound(t["refund.not_found"])
    return row


# ----- reading -----

def get(conn, ctx: UserContext, refund_id: int) -> Refund:
    require(ctx, "student.view")
    return _to_refund(_require_row(conn, refund_id))


def for_student(conn, ctx: UserContext, student_id: int) -> list[Refund]:
    """Latest first."""
    require(ctx, "student.view")
    return [_to_refund(row) for row in repo.for_student(conn, student_id)]


def queue(conn, ctx: UserContext) -> list[Refund]:
    """Waiting for the director (pending) or for the money to go out (approved), oldest
    first."""
    require(ctx, "refund.request")
    return [_to_refund(row) for row in repo.with_status(conn, ("pending", "approved"))]


def paid_on(conn, ctx: UserContext, day: date) -> list[Refund]:
    require(ctx, "report.view")
    return [_to_refund(row) for row in repo.paid_on(conn, dates.iso(day))]


# ----- what can be refunded, and the suggestion -----

def _first_unused_day(conn, subscription, on: date | None) -> date:
    """The first day the month was not used: the day after the student left the group, or
    `on` (today by default)."""
    if on is not None:
        return on
    enrollment = enrollments_repo.get(conn, subscription["enrollment_id"])
    if enrollment["status"] in ("left", "switched") and enrollment["left_on"]:
        return date.fromisoformat(enrollment["left_on"]) + timedelta(days=1)
    return dates.today()


def suggestion(conn, charge_row, money, on: date | None = None) -> int:
    """What was paid and kept beyond the value of the days used, never more than what can
    still be refunded."""
    available = max(money["paid"] - money["refunded"] - money["reserved"], 0)
    if charge_row["subscription_id"] is None:
        return available  # the fee: the director decides
    month = subscriptions_repo.get(conn, charge_row["subscription_id"])
    start, end = date.fromisoformat(month["start_date"]), date.fromisoformat(month["end_date"])
    total = (end - start).days
    unused_from = min(max(_first_unused_day(conn, month, on), start), end)
    used = (unused_from - start).days
    used_value = -(-charge_row["amount"] * used // total)  # rounded up: whole dinars kept
    kept = money["paid"] - money["refunded"]
    return min(max(kept - used_value, 0), available)


def options(conn, ctx: UserContext, student_id: int,
            on: date | None = None) -> list[RefundableCharge]:
    """The student's charges with money paid and not handed back, oldest due first."""
    require(ctx, "refund.request")
    result = []
    for row in repo.charges_paid(conn, student_id):
        charge = payments_repo.charge(conn, row["id"])
        money = repo.money_on_charge(conn, row["id"])
        if money["paid"] - money["refunded"] <= 0:
            continue
        result.append(RefundableCharge(
            charge_id=row["id"], subscription_id=row["subscription_id"],
            description=row["description"], amount=row["amount"], status=row["status"],
            paid=money["paid"], refunded=money["refunded"], reserved=money["reserved"],
            suggestion=suggestion(conn, charge, money, on)))
    return result


# ----- asking, deciding, paying out -----

def _check_amount(amount) -> int:
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ValidationError(t["refund.amount_invalid"])
    return amount


def request(conn, ctx: UserContext, charge_id: int, amount: int, reason: str,
            on: date | None = None) -> int:
    """Ask to hand back `amount` DA paid on the charge. on: the first day not used (default:
    the day after the student left, or today), for the suggestion kept with the request."""
    require(ctx, "refund.request")
    _check_amount(amount)
    reason = clean(reason)
    if not reason:
        raise ValidationError(t["refund.reason_required"])
    with atomic(conn):
        charge = payments_repo.charge(conn, charge_id)
        if charge is None:
            raise NotFound(t["refund.charge_not_found"])
        money = repo.money_on_charge(conn, charge_id)
        available = money["paid"] - money["refunded"] - money["reserved"]
        if amount > available:
            raise BusinessRuleError(t["refund.exceeds"].format(
                amount=format_dzd(max(available, 0))))
        computed = suggestion(conn, charge, money, on)
        refund_id = repo.insert(conn, charge_id, charge["subscription_id"], computed, amount,
                                reason, ctx.user_id, _now())
        audit.log(conn, ctx, "refund.request", "refunds", refund_id, new={
            "student_id": charge["student_id"], "charge_id": charge_id, "amount": amount,
            "suggestion": computed, "reason": reason})
        return refund_id


def approve(conn, ctx: UserContext, refund_id: int, amount: int | None = None) -> None:
    """Director only. amount: a different final amount (default: the one asked)."""
    require(ctx, "refund.approve")
    with atomic(conn):
        row = _require_row(conn, refund_id)
        if row["status"] != "pending":
            raise BusinessRuleError(t["refund.not_pending"])
        final = row["amount_final"] if amount is None else _check_amount(amount)
        money = repo.money_on_charge(conn, row["charge_id"])
        available = money["paid"] - money["refunded"] - (money["reserved"] - row["amount_final"])
        if final > available:
            raise BusinessRuleError(t["refund.exceeds"].format(
                amount=format_dzd(max(available, 0))))
        repo.decide(conn, refund_id, "approved", ctx.user_id, _now(), final)
        audit.log(conn, ctx, "refund.approve", "refunds", refund_id,
                  old={"status": "pending", "amount_final": row["amount_final"]},
                  new={"status": "approved", "amount_final": final})


def reject(conn, ctx: UserContext, refund_id: int, reason: str) -> None:
    """Director only, before the money goes out. The reason goes to the audit log."""
    require(ctx, "refund.reject")
    reason = clean(reason)
    if not reason:
        raise ValidationError(t["refund.reason_required"])
    with atomic(conn):
        row = _require_row(conn, refund_id)
        if row["status"] not in ("pending", "approved"):
            raise BusinessRuleError(t["refund.closed"])
        repo.decide(conn, refund_id, "rejected", ctx.user_id, _now(), row["amount_final"])
        audit.log(conn, ctx, "refund.reject", "refunds", refund_id,
                  old={"status": row["status"]}, new={"status": "rejected", "reason": reason})


def refund_number(conn) -> str:
    """Next 'RB2026-00001'. Call inside the transaction that pays the refund out."""
    year = dates.today().year
    return f"RB{year}-{counters.next_value(conn, f'refund:{year}'):05d}"


def pay_out(conn, ctx: UserContext, refund_id: int, method: str) -> str:
    """Hand an approved refund over; returns its number."""
    require(ctx, "refund.pay")
    if method not in PAYMENT_METHODS:
        raise ValidationError(t["payment.method_invalid"])
    with atomic(conn):
        row = _require_row(conn, refund_id)
        if row["status"] != "approved":
            raise BusinessRuleError(t["refund.not_approved"])
        amount = row["amount_final"]
        sources = repo.allocations_left(conn, row["charge_id"])
        available = sum(source["remaining"] for source in sources)
        if available < amount:  # a payment was voided since the approval
            raise BusinessRuleError(t["refund.money_gone"].format(
                amount=format_dzd(available)))
        taken, left = [], amount
        for source in sources:
            if left <= 0:
                break
            part = min(left, source["remaining"])
            repo.insert_allocation(conn, refund_id, source["id"], part)
            taken.append({"payment_id": source["payment_id"], "allocation_id": source["id"],
                          "amount": part})
            left -= part
        number = refund_number(conn)
        repo.mark_paid(conn, refund_id, number, method, ctx.user_id, _now(), amount)
        audit.log(conn, ctx, "refund.pay", "refunds", refund_id,
                  old={"status": "approved"},
                  new={"status": "paid", "number": number, "amount": amount,
                       "method": method, "from": taken})
        return number
