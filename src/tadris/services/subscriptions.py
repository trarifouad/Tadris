from datetime import date, timedelta

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, NotFound, ValidationError
from tadris.core.money import format_dzd
from tadris.core.permissions import require
from tadris.core.text import clean, fold
from tadris.db.errors import atomic
from tadris.domain.models import MissingSubscription, Subscription, SubscriptionLine
from tadris.i18n.fr import t
from tadris.repositories import enrollments as enrollments_repo
from tadris.repositories import groups as groups_repo
from tadris.repositories import subscriptions as repo
from tadris.services import audit, debt, payouts

# A subscription is one month of a paid enrollment: [start, start + 1 month), at a snapshot
# of the group's price, with a charge due (and accrued) on its first day. Absence never
# changes it. Each student has their own cycle: the first month starts on the entry date.
# Renewal is done by the desk: the next month starts when the previous one ends, or later
# after a gap, never earlier. A trial has no subscription. Cancelling (director only) is
# refused once something was paid on the month (V1 has no refunds: only a void of the payment,
# by the director, frees it) or once an approved or paid teacher payout counted it; a draft
# lets it go. A student who leaves a group (or switches, or whose group closes) owes no month
# that starts after their last day: those are cancelled the same way, or kept and listed when
# they cannot be.

EXPIRING_DAYS = 7


def _today() -> str:
    return dates.iso(dates.today())


def state_of(row, today: date | None = None) -> str:
    """Display state: upcoming, active, expiring (7 days or less left), ended, cancelled."""
    if row["status"] == "cancelled":
        return "cancelled"
    on = today or dates.today()
    if row["start_date"] > dates.iso(on):
        return "upcoming"
    if row["end_date"] <= dates.iso(on):
        return "ended"
    if row["end_date"] <= dates.iso(on + timedelta(days=EXPIRING_DAYS)):
        return "expiring"
    return "active"


def _title(row) -> str:
    return f"{row['group_name']} · {row['subject']} {row['level']}"


def _to_subscription(row) -> Subscription:
    return Subscription(
        id=row["id"], enrollment_id=row["enrollment_id"],
        enrollment_status=row["enrollment_status"], student_id=row["student_id"],
        student_number=row["student_number"],
        student_name=f"{row['last_name']} {row['first_name']}", group_id=row["group_id"],
        group_title=_title(row), renewal_of_id=row["renewal_of_id"], price=row["price"],
        start_date=row["start_date"], end_date=row["end_date"], status=row["status"],
        state=state_of(row), charge_id=row["charge_id"], paid=row["paid"],
        in_payout=bool(row["in_payout"]),
    )


def _require_row(conn, subscription_id: int):
    row = repo.get(conn, subscription_id)
    if row is None:
        raise NotFound(t["subscription.not_found"])
    return row


def get(conn, ctx: UserContext, subscription_id: int) -> Subscription:
    require(ctx, "student.view")
    return _to_subscription(_require_row(conn, subscription_id))


def for_student(conn, ctx: UserContext, student_id: int) -> list[Subscription]:
    """Latest first."""
    require(ctx, "student.view")
    return [_to_subscription(row) for row in repo.for_student(conn, student_id)]


def for_enrollment(conn, ctx: UserContext, enrollment_id: int) -> list[Subscription]:
    require(ctx, "student.view")
    return [_to_subscription(row) for row in repo.for_enrollment(conn, enrollment_id)]


# ----- create -----

def create_in(conn, ctx: UserContext, enrollment_id: int, start: str,
              renewal_of_id: int | None = None) -> int:
    """Inside a transaction: one month of the enrollment from `start` ('YYYY-MM-DD'), at the
    group's current price, with its charge when the price is above 0."""
    enrollment = enrollments_repo.get(conn, enrollment_id)
    if enrollment is None:
        raise NotFound(t["enrollment.not_found"])
    if enrollment["status"] == "trial":
        raise BusinessRuleError(t["subscription.trial"])
    if enrollment["status"] != "active":
        raise BusinessRuleError(t["subscription.enrollment_not_live"])
    group = groups_repo.get(conn, enrollment["group_id"], _today())
    if group["status"] == "closed":
        raise BusinessRuleError(t["subscription.group_closed"])
    if start < enrollment["enrolled_on"]:
        raise ValidationError(t["subscription.start_before_entry"].format(
            date=dates.display_date(enrollment["enrolled_on"])))
    if start > group["year_end"]:
        raise ValidationError(t["subscription.start_outside_year"].format(
            end=dates.display_date(group["year_end"])))
    end = dates.iso(dates.add_one_month(date.fromisoformat(start)))
    subscription_id = repo.insert(conn, enrollment_id, renewal_of_id, group["price"], start, end)
    charge_id = None
    if group["price"] > 0:
        charge_id = repo.insert_charge(conn, subscription_id, t["subscription.charge_description"]
                                       .format(group=group["name"],
                                               start=dates.display_date(start),
                                               end=dates.display_date(end)),
                                       group["price"], start)
    audit.log(conn, ctx, "subscription.create", "subscriptions", subscription_id, new={
        "enrollment_id": enrollment_id, "renewal_of_id": renewal_of_id,
        "price": group["price"], "start_date": start, "end_date": end, "charge_id": charge_id,
    })
    return subscription_id


def start(conn, ctx: UserContext, enrollment_id: int, start_date: date | None = None) -> int:
    """A first month for a paid enrollment that has none running or to come (e.g. after a
    cancellation). Defaults to today, or the entry date if later."""
    require(ctx, "subscription.manage")
    with atomic(conn):
        enrollment = enrollments_repo.get(conn, enrollment_id)
        if enrollment is None:
            raise NotFound(t["enrollment.not_found"])
        on = dates.iso(start_date) if start_date else max(_today(), enrollment["enrolled_on"])
        latest = repo.latest(conn, enrollment_id)
        if latest is not None and latest["end_date"] > on:
            raise BusinessRuleError(t["subscription.already_running"].format(
                end=dates.display_date(latest["end_date"])))
        return create_in(conn, ctx, enrollment_id, on)


def renew(conn, ctx: UserContext, subscription_id: int, start_date: date | None = None) -> int:
    """The next month: from the previous end date by default, or later after a gap."""
    require(ctx, "subscription.manage")
    with atomic(conn):
        return _renew(conn, ctx, subscription_id, start_date)


def _renew(conn, ctx: UserContext, subscription_id: int, start_date: date | None) -> int:
    row = _require_row(conn, subscription_id)
    if row["status"] == "cancelled":
        raise BusinessRuleError(t["subscription.cancelled"])
    latest = repo.latest(conn, row["enrollment_id"])
    if latest["id"] != row["id"]:
        raise BusinessRuleError(t["subscription.not_latest"].format(
            end=dates.display_date(latest["end_date"])))
    on = dates.iso(start_date) if start_date else row["end_date"]
    if on < row["end_date"]:
        raise ValidationError(t["subscription.start_before_end"].format(
            end=dates.display_date(row["end_date"])))
    # renewal_of_id is unique even when that renewal was cancelled: the link is then left out.
    link = None if repo.has_renewal(conn, row["id"]) else row["id"]
    return create_in(conn, ctx, row["enrollment_id"], on, link)


def renew_many(conn, ctx: UserContext, subscription_ids: list[int]) -> list[int]:
    """Renew several latest months at once, from their end dates, all or nothing."""
    require(ctx, "subscription.manage")
    with atomic(conn):
        return [_renew(conn, ctx, subscription_id, None) for subscription_id in subscription_ids]


# ----- cancel -----

def cancel(conn, ctx: UserContext, subscription_id: int, reason: str) -> None:
    """Director only. The charge is cancelled with it; the period is free again."""
    require(ctx, "subscription.cancel")
    reason = clean(reason)
    if not reason:
        raise ValidationError(t["subscription.reason_required"])
    with atomic(conn):
        row = _require_row(conn, subscription_id)
        if row["status"] == "cancelled":
            raise BusinessRuleError(t["subscription.already_cancelled"])
        if row["in_payout"]:
            raise BusinessRuleError(t["subscription.in_payout"])
        if row["paid"]:
            raise BusinessRuleError(t["subscription.paid"].format(
                amount=format_dzd(row["paid"])))
        _cancel_in(conn, ctx, row, reason)


def _cancel_in(conn, ctx: UserContext, row, reason: str) -> None:
    """Inside a transaction: a month with nothing paid, in no approved or paid payout, is
    cancelled with its charge; a draft counting it lets it go first."""
    if row["charge_id"] is not None and row["charge_status"] == "open":
        payouts.drop_month(conn, ctx, row["charge_id"])
        repo.cancel_charge(conn, row["charge_id"])
    repo.set_status(conn, row["id"], "cancelled")
    audit.log(conn, ctx, "subscription.cancel", "subscriptions", row["id"],
              old={"status": row["status"]},
              new={"status": "cancelled", "reason": reason, "charge_id": row["charge_id"]})


# ----- leaving a group -----

def after(conn, ctx: UserContext, enrollment_id: int, last_day: date) -> list[Subscription]:
    """The enrollment's months that start after `last_day`: what leaving the group that day
    cancels (can_cancel) or keeps (money paid on it, or a teacher paid for it)."""
    require(ctx, "student.view")
    return [_to_subscription(row)
            for row in repo.starting_after(conn, enrollment_id, dates.iso(last_day))]


def release_after(conn, ctx: UserContext, enrollment_id: int, last_day: str,
                  reason: str) -> tuple[list[int], list[int]]:
    """Inside the transaction that ends the enrollment: its months starting after
    `last_day` are cancelled, those that cannot be are kept. Returns (cancelled, kept)."""
    cancelled, kept = [], []
    for row in repo.starting_after(conn, enrollment_id, last_day):
        if _to_subscription(row).can_cancel:
            _cancel_in(conn, ctx, row, reason)
            cancelled.append(row["id"])
        else:
            kept.append(row["id"])
    return cancelled, kept


# ----- start-up bookkeeping and the desk's lists -----

def mark_ended(conn) -> int:
    """At app start: active subscriptions past their last day become 'ended'."""
    with atomic(conn):
        count = repo.mark_ended(conn, _today())
        if count:
            audit.log_system(conn, "subscription.mark_ended", "subscriptions",
                             new={"count": count, "on": _today()})
        return count


def ending_soon(conn, ctx: UserContext, days: int = EXPIRING_DAYS,
                group_id: int | None = None) -> list[Subscription]:
    """Students still in their group whose latest month ends within `days` days."""
    require(ctx, "student.view")
    until = dates.iso(dates.today() + timedelta(days=days))
    return [_to_subscription(row)
            for row in repo.ending_between(conn, _today(), until, group_id)]


def lapsed(conn, ctx: UserContext, group_id: int | None = None) -> list[Subscription]:
    """Students still in their group whose latest month is over, not renewed."""
    require(ctx, "student.view")
    return [_to_subscription(row) for row in repo.ended_by(conn, _today(), group_id)]


def renewable(conn, ctx: UserContext, group_id: int | None = None) -> list[Subscription]:
    """What the bulk renewal offers: months over, then months ending within 7 days."""
    return lapsed(conn, ctx, group_id) + ending_soon(conn, ctx, group_id=group_id)


def missing(conn, ctx: UserContext) -> list[MissingSubscription]:
    """Students in a group (not on trial) with no subscription at all left."""
    require(ctx, "student.view")
    return [
        MissingSubscription(
            enrollment_id=row["enrollment_id"], student_id=row["student_id"],
            student_number=row["student_number"],
            student_name=f"{row['last_name']} {row['first_name']}", group_id=row["group_id"],
            group_title=_title(row), enrolled_on=row["enrolled_on"])
        for row in repo.active_without_subscription(conn)
    ]


def lines(conn, ctx: UserContext) -> list[SubscriptionLine]:
    """The Abonnements page: each student in each group (not on trial) with the latest month
    and what is left to pay on all of its months (after the student's credit), those with no
    month left too. By name, then group."""
    require(ctx, "student.view")
    months: dict[int, list[Subscription]] = {}
    for row in repo.live_months(conn):
        months.setdefault(row["enrollment_id"], []).append(_to_subscription(row))
    left = debt.left_after_credit(debt.every_debt(conn).values())
    result = []
    today = _today()
    for mine in months.values():
        latest = max(mine, key=lambda m: m.end_date)
        start = min((m.start_date for m in mine if m.end_date > today),
                    default=latest.start_date)
        result.append(SubscriptionLine(
            enrollment_id=latest.enrollment_id, student_id=latest.student_id,
            student_number=latest.student_number, student_name=latest.student_name,
            group_id=latest.group_id, group_title=latest.group_title, month=latest,
            owed=sum(left.get(m.charge_id, 0) for m in mine), period_start=start))
    result += [SubscriptionLine(
        enrollment_id=m.enrollment_id, student_id=m.student_id,
        student_number=m.student_number, student_name=m.student_name, group_id=m.group_id,
        group_title=m.group_title, month=None, owed=0, period_start=None)
        for m in missing(conn, ctx)]
    result.sort(key=lambda line: (fold(line.student_name), fold(line.group_title)))
    return result
