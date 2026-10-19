from tadris.core.context import UserContext
from tadris.core.errors import PermissionDenied
from tadris.i18n.fr import t

DIRECTOR = "director"
RECEPTIONIST = "receptionist"

BOTH = frozenset({DIRECTOR, RECEPTIONIST})
DIRECTOR_ONLY = frozenset({DIRECTOR})

ACTIONS: dict[str, frozenset[str]] = {
    "dashboard.view": BOTH,
    "student.view": BOTH,
    "student.create": BOTH,
    "student.update": BOTH,
    "student.deactivate": DIRECTOR_ONLY,
    "student.reactivate": DIRECTOR_ONLY,
    "group.view": BOTH,
    "group.manage": DIRECTOR_ONLY,
    "timetable.view": BOTH,
    "timetable.manage": BOTH,
    "registration.create": BOTH,
    "registration.cancel": DIRECTOR_ONLY,
    "enrollment.create": BOTH,
    "enrollment.update": BOTH,
    "enrollment.override": DIRECTOR_ONLY,
    "subscription.manage": BOTH,
    "subscription.cancel": DIRECTOR_ONLY,
    "session.view": BOTH,
    "attendance.save": BOTH,
    "payment.record": BOTH,
    "payment.void": DIRECTOR_ONLY,
    "refund.request": BOTH,
    "refund.approve": DIRECTOR_ONLY,
    "refund.reject": DIRECTOR_ONLY,
    "payout.view": DIRECTOR_ONLY,
    "payout.manage": DIRECTOR_ONLY,
    "academic.view": BOTH,
    "academic.manage": DIRECTOR_ONLY,
    "teacher.view": BOTH,
    "teacher.manage": DIRECTOR_ONLY,
    "report.view": BOTH,
    "sms.view": BOTH,
    "sms.manage": DIRECTOR_ONLY,
    "settings.view": DIRECTOR_ONLY,
    "settings.change": DIRECTOR_ONLY,
    "user.view": DIRECTOR_ONLY,
    "user.create": DIRECTOR_ONLY,
    "user.disable": DIRECTOR_ONLY,
    "audit.view": DIRECTOR_ONLY,
    "print.document": BOTH,
}

NAV_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("dashboard", "nav.dashboard", "dashboard.view"),
    ("students", "nav.students", "student.view"),
    ("groups", "nav.groups", "group.view"),
    ("subscriptions", "nav.subscriptions", "subscription.manage"),
    ("timetable", "nav.timetable", "timetable.view"),
    ("attendance", "nav.attendance", "session.view"),
    ("payments", "nav.payments", "payment.record"),
    ("teachers", "nav.teachers", "teacher.view"),
    ("payouts", "nav.payouts", "payout.view"),
    ("reports", "nav.reports", "report.view"),
    ("sms", "nav.sms", "sms.view"),
    ("settings", "nav.settings", "settings.view"),
)


def allowed(ctx: UserContext, action: str) -> bool:
    # Unknown actions raise KeyError: a typo must fail in tests, not deny everyone.
    return ctx.role in ACTIONS[action]


def require(ctx: UserContext, action: str) -> None:
    if not allowed(ctx, action):
        raise PermissionDenied(t["permission.denied"])


def nav_for(ctx: UserContext) -> list[tuple[str, str]]:
    return [(key, label_key) for key, label_key, action in NAV_ITEMS if allowed(ctx, action)]
