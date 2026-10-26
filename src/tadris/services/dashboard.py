import calendar
from datetime import date, datetime, timedelta

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.permissions import allowed, require
from tadris.domain.models import Dashboard, DashboardSession, DayCash, GroupFill
from tadris.repositories import backups as backups_repo
from tadris.repositories import dashboard as repo
from tadris.services import debt, groups, sessions, settings, subscriptions

# The dashboard (« Aujourd'hui ») only reads: the day's sessions, who is late, the months to
# renew, the groups' seats and, for the director, the month's money and today's backup.
#
# The month's money: « Facturé » is the months and fees starting in the month (accrual date),
# cancelled ones left out; « Réglé » is what payments not voided paid on them, whenever it was
# paid; « Encaissé » is the money received in the month (payments not voided), whatever it
# paid. V1 has no refunds (archived since 0015).

TOP_DEBTORS = 20  # the dashboard shows as many as fit


def _now_time() -> str:
    return f"{datetime.now():%H:%M}"


def month_bounds(day: date) -> tuple[date, date]:
    first = day.replace(day=1)
    return first, day.replace(day=calendar.monthrange(day.year, day.month)[1])


def load(conn, ctx: UserContext) -> Dashboard:
    require(ctx, "dashboard.view")
    today = dates.today()
    day_sessions = tuple(
        DashboardSession(id=s.id, start_time=s.start_time, end_time=s.end_time,
                         group_title=s.group_name, room=s.room, teacher=s.teacher,
                         status=s.status)
        for s in sorted(sessions.listing(conn, ctx, today, today),
                        key=lambda s: (s.start_time, s.group_name.casefold())))
    owing = debt.debtors(conn, ctx)
    running = [g for g in groups.search(conn, ctx, status="active") if g.state == "active"]
    fills = sorted((GroupFill(group_id=g.id, title=g.name, enrolled=g.enrolled, seats=g.seats)
                    for g in running), key=lambda f: (-f.rate_bp, f.title.casefold()))
    money = {}
    first, last = month_bounds(today)
    if allowed(ctx, "report.finance"):
        charged, settled = repo.charged_between(conn, dates.iso(first), dates.iso(last))
        received = repo.collected_by_day(conn, dates.iso(first), dates.iso(last))
        money = {"charged": charged, "settled": settled, "collected": sum(received.values()),
                 "daily": daily_cash(conn, first, today)}
    extra = {}
    if allowed(ctx, "backup.create"):
        extra["backup"] = backup_status(conn, today)
    opens_at, closes_at = settings.school_hours(conn)
    weekdays = repo.slot_weekdays(conn, dates.iso(today))
    return Dashboard(
        today=dates.iso(today), now=_now_time(), sessions=day_sessions,
        ending=tuple(subscriptions.ending_soon(conn, ctx)),
        lapsed=len(subscriptions.lapsed(conn, ctx)),
        debt_total=sum(d.owed_now for d in owing), debtors=len(owing),
        top_debtors=tuple(owing[:TOP_DEBTORS]), groups=tuple(fills),
        oldest_debtors=tuple(sorted(owing, key=lambda d: (-d.days_overdue, -d.owed_now))
                             [:TOP_DEBTORS]),
        opens_at=opens_at, closes_at=closes_at,
        closed_weekdays=tuple(d for d in range(1, 8) if weekdays and d not in weekdays),
        **money, **extra)


def daily_cash(conn, first: date, last: date) -> tuple[DayCash, ...]:
    """Each day from first to last: what was received, and whether the school was open (a
    session, even cancelled, or a payment)."""
    received = repo.collected_by_day(conn, dates.iso(first), dates.iso(last))
    held = repo.session_days(conn, dates.iso(first), dates.iso(last))
    days = []
    day = first
    while day <= last:
        key = dates.iso(day)
        amount = received.get(key, 0)
        days.append(DayCash(day=key, amount=amount, open=key in held or amount > 0))
        day += timedelta(days=1)
    return tuple(days)


def backup_status(conn, day: date) -> str:
    """'verified' once a copy of the day is checked, 'failed' when the latest failed, else
    'none'."""
    statuses = backups_repo.statuses_on(conn, dates.iso(day))
    if "verified" in statuses:
        return "verified"
    return "failed" if statuses and statuses[0] == "failed" else "none"
