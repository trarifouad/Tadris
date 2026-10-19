from datetime import datetime

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, NotFound, ValidationError
from tadris.core.money import format_dzd
from tadris.core.permissions import require
from tadris.core.text import clean
from tadris.db.errors import atomic
from tadris.domain.models import Registration
from tadris.i18n.fr import t
from tadris.repositories import registrations as repo
from tadris.repositories import school_years as years_repo
from tadris.repositories import students as students_repo
from tadris.services import audit, catalog, settings

# A registration puts a student in a school year at a level; enrollments in groups hang off
# it. Registrations happen in the open year only. The fee is a snapshot: the default from
# settings or an amount typed at the desk; a fee above 0 creates the registration charge.
# There is one registration per student and year: a cancelled one is made again in place,
# with a new fee charge.


def _to_registration(row) -> Registration:
    return Registration(
        id=row["id"], student_id=row["student_id"], school_year_id=row["school_year_id"],
        year_label=row["year_label"], level_id=row["level_id"], level=row["level"],
        fee_amount=row["fee_amount"], status=row["status"], registered_at=row["registered_at"],
        live_enrollments=row["live_enrollments"], fee_charge_id=row["fee_charge_id"],
        fee_paid=row["fee_paid"], fee_refunded=row["fee_refunded"],
    )


def _require_row(conn, registration_id: int):
    row = repo.get(conn, registration_id)
    if row is None:
        raise NotFound(t["registration.not_found"])
    return row


def default_fee(conn) -> int:
    return settings.get(conn, "defaults.registration_fee", 0)


def get(conn, ctx: UserContext, registration_id: int) -> Registration:
    require(ctx, "student.view")
    return _to_registration(_require_row(conn, registration_id))


def for_student(conn, ctx: UserContext, student_id: int) -> list[Registration]:
    """Every registration of the student, latest year first."""
    require(ctx, "student.view")
    return [_to_registration(row) for row in repo.for_student(conn, student_id)]


def current(conn, ctx: UserContext, student_id: int) -> Registration | None:
    """The student's active registration in the open year, if any."""
    require(ctx, "student.view")
    year = years_repo.open_year(conn)
    if year is None:
        return None
    row = repo.for_student_year(conn, student_id, year["id"])
    if row is None or row["status"] != "active":
        return None
    return _to_registration(row)


def register(conn, ctx: UserContext, student_id: int, level_id: int,
             fee_amount: int | None = None) -> int:
    """Register the student in the open year. fee_amount None takes the default fee."""
    require(ctx, "registration.create")
    with atomic(conn):
        year = years_repo.open_year(conn)
        if year is None:
            raise BusinessRuleError(t["registration.no_open_year"])
        student = students_repo.get(conn, student_id)
        if student is None:
            raise NotFound(t["student.not_found"])
        if student["status"] != "active":
            raise BusinessRuleError(t["registration.student_inactive"])
        catalog.require_active(conn, "level", level_id)
        default = default_fee(conn)
        fee = default if fee_amount is None else fee_amount
        if fee < 0:
            raise ValidationError(t["registration.fee_invalid"])
        existing = repo.for_student_year(conn, student_id, year["id"])
        if existing is not None and existing["status"] == "active":
            raise BusinessRuleError(t["registration.exists"].format(
                label=year["label"], level=existing["level"]))
        # The service's clock, not SQLite's: the day matches the fee charge's due date.
        now = f"{dates.iso(dates.today())}T{datetime.now():%H:%M:%S}"
        if existing is None:
            registration_id = repo.insert(conn, student_id, year["id"], level_id, fee, now)
        else:
            registration_id = existing["id"]
            repo.reactivate(conn, registration_id, level_id, fee, now)
        charge_id = None
        if fee > 0:
            charge_id = repo.insert_fee_charge(
                conn, registration_id,
                t["registration.fee_description"].format(label=year["label"]), fee,
                dates.iso(dates.today()))
        audit.log(conn, ctx, "registration.create", "registrations", registration_id,
                  old=None if existing is None else {"status": "cancelled"},
                  new={"student_id": student_id, "school_year_id": year["id"],
                       "level_id": level_id, "fee_amount": fee, "default_fee": default,
                       "charge_id": charge_id})
        return registration_id


def _require_changeable(conn, registration_id: int):
    """The row of an active registration in the open year, with no live enrollment."""
    row = _require_row(conn, registration_id)
    if row["status"] != "active":
        raise BusinessRuleError(t["registration.already_cancelled"])
    if row["year_status"] != "open":
        raise BusinessRuleError(t["registration.year_closed"].format(label=row["year_label"]))
    if row["live_enrollments"]:
        raise BusinessRuleError(t["registration.has_live_enrollments"].format(
            count=row["live_enrollments"]))
    return row


def change_level(conn, ctx: UserContext, registration_id: int, level_id: int) -> None:
    """Correct the level while the student is in no group of the year."""
    require(ctx, "registration.create")
    with atomic(conn):
        row = _require_changeable(conn, registration_id)
        if row["level_id"] == level_id:
            raise ValidationError(t["registration.same_level"])
        catalog.require_active(conn, "level", level_id)
        repo.set_level(conn, registration_id, level_id)
        audit.log(conn, ctx, "registration.change_level", "registrations", registration_id,
                  old={"level_id": row["level_id"]}, new={"level_id": level_id})


def cancel(conn, ctx: UserContext, registration_id: int, reason: str) -> None:
    """Director only. Refused while the student is in a group of the year or while part of
    the fee paid is kept (refund it first). The open fee charge is cancelled with it."""
    require(ctx, "registration.cancel")
    reason = clean(reason)
    if not reason:
        raise ValidationError(t["registration.reason_required"])
    with atomic(conn):
        row = _require_changeable(conn, registration_id)
        kept = row["fee_paid"] - row["fee_refunded"]
        if kept:
            raise BusinessRuleError(t["registration.fee_paid"].format(amount=format_dzd(kept)))
        charge_id = row["fee_charge_id"]
        if charge_id is not None and row["fee_charge_status"] == "open":
            repo.cancel_charge(conn, charge_id)
        repo.set_status(conn, registration_id, "cancelled")
        audit.log(conn, ctx, "registration.cancel", "registrations", registration_id,
                  old={"status": "active"},
                  new={"status": "cancelled", "reason": reason, "charge_id": charge_id})
