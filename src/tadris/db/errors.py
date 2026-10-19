import sqlite3
from contextlib import contextmanager

from tadris.core.errors import BusinessRuleError
from tadris.db.connection import transaction
from tadris.i18n.fr import t

_TRIGGER_MESSAGES = (
    ("payments are immutable", "db.payments_immutable"),
    ("payment_allocations are immutable", "db.allocations_immutable"),
    ("receipts are immutable", "db.receipts_immutable"),
    ("payment_voids are immutable", "db.voids_immutable"),
    ("audit_log is immutable", "db.audit_immutable"),
    ("refund is locked", "db.refund_locked"),
    ("refunds cannot be deleted", "db.refund_locked"),
    ("payment is voided", "db.payment_voided"),
    ("charge is cancelled", "db.charge_cancelled"),
    ("payment and charge belong to different students", "db.different_students"),
    ("allocations exceed payment amount", "db.alloc_exceed_payment"),
    ("allocations exceed charge amount", "db.alloc_exceed_charge"),
    ("payment already counted in a teacher payout", "db.void_after_payout"),
    ("payment has refunds", "db.void_has_refunds"),
    ("only charges.status and accrual_date may change", "db.charge_locked"),
    ("charge already counted in a teacher payout", "db.charge_in_payout"),
    ("registration belongs to another student", "db.enrollment_other_student"),
    ("registration is cancelled", "db.registration_cancelled"),
    ("registration school year differs from group", "db.year_mismatch"),
    ("registration level differs from group level", "db.level_mismatch"),
    ("group is closed", "db.group_closed"),
    ("group already started", "db.group_started"),  # dropped in 0009
    ("switched enrollment belongs to another student", "db.switch_other_student"),
    ("left enrollment needs a leaving date", "db.left_needs_date"),
    ("group is full", "db.group_full"),
    ("capacity below current enrollment", "db.capacity_below_enrolled"),
    ("group capacity exceeds room capacity", "db.group_exceeds_room"),
    ("room too small for enrolled students", "db.group_exceeds_room"),
    ("room capacity below a group capacity", "db.room_below_group"),
    ("room capacity below enrolled students", "db.room_below_group"),
    ("room is full", "db.room_full"),
    ("room slot overlap", "db.room_slot_overlap"),
    ("group slot overlap", "db.group_slot_overlap"),
    ("session group differs from slot group", "db.session_group_mismatch"),
    ("session date does not match slot weekday", "db.session_weekday"),
    ("room session overlap", "db.room_session_overlap"),
    ("teacher session overlap", "db.teacher_session_overlap"),
    ("group session overlap", "db.group_session_overlap"),
    ("session is cancelled", "db.session_cancelled"),
    ("enrollment is not in the session group", "db.enrollment_wrong_group"),
    ("enrollment not valid on session date", "db.enrollment_not_valid"),
    ("subscription overlap", "db.subscription_overlap"),
    ("teacher rate period overlap", "db.rate_overlap"),
    ("group teacher period overlap", "db.group_teacher_overlap"),
    ("refund exceeds paid minus already refunded", "db.refund_exceeds_paid"),
    ("refund allocations exceed refund amount", "db.refund_alloc_exceed"),
    ("refund_allocations are immutable", "db.refund_allocations_immutable"),
    ("allocation belongs to another subscription", "db.refund_other_subscription"),
    ("charge is not an open subscription charge", "db.payout_charge_not_open"),
    ("amount must equal the charge amount", "db.payout_amount_mismatch"),
    ("charge belongs to another group", "db.payout_charge_other_group"),
    ("teacher is not the group teacher on the accrual date", "db.payout_wrong_teacher"),
    ("payout_line_charges cannot be updated", "db.payout_locked"),
    ("payout is not draft", "db.payout_not_draft"),
    ("payout is locked", "db.payout_locked"),
    ("accrual date outside payout period", "db.payout_period"),
    ("holiday overlap", "db.holiday_overlap"),
)


def translate(exc: sqlite3.IntegrityError) -> BusinessRuleError:
    raw = str(exc)
    for needle, key in _TRIGGER_MESSAGES:
        if needle in raw:
            return BusinessRuleError(t[key])
    return BusinessRuleError(t["db.integrity"])


@contextmanager
def atomic(conn):
    """BEGIN IMMEDIATE ... COMMIT, with trigger and constraint errors turned into French
    BusinessRuleErrors."""
    try:
        with transaction(conn):
            yield conn
    except sqlite3.IntegrityError as exc:
        raise translate(exc) from exc
