"""The computer's clock, checked at start against the database. The computer is offline:
nothing corrects its date. A date earlier than the last operation saved (a flat CMOS
battery) or long after it (the wrong year typed) would date receipts wrongly and end months
on the wrong day."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from tadris.db.errors import atomic
from tadris.services import audit

BEHIND_MARGIN = timedelta(minutes=10)  # a clock set back a little (a manual fix) is fine
AHEAD_DAYS = 120  # longer than the summer break; a year typed wrong is 365


@dataclass(frozen=True)
class ClockCheck:
    state: str  # 'ok', 'behind' or 'ahead'
    now: datetime
    last: datetime | None  # the latest audit entry; None in a new database


def check(conn, now: datetime) -> ClockCheck:
    value = conn.execute("SELECT MAX(created_at) FROM audit_log").fetchone()[0]
    if value is None:
        return ClockCheck("ok", now, None)  # nothing to compare with
    last = datetime.fromisoformat(value)
    if now < last - BEHIND_MARGIN:
        state = "behind"
    elif now - last > timedelta(days=AHEAD_DAYS):
        state = "ahead"
    else:
        state = "ok"
    return ClockCheck(state, now, last)


def went_on(conn, result: ClockCheck) -> None:
    """« Continuer quand même »: the app goes on with this date, written to the audit log
    (by the app: nobody is logged in yet)."""
    with atomic(conn):
        audit.log_system(conn, f"clock.{result.state}", "app", new={
            "now": result.now.isoformat(timespec="seconds"),
            "last": result.last.isoformat(timespec="seconds") if result.last else None,
        })
