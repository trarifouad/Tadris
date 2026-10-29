# Single source for status colors: domain -> status -> badge kind (see DESIGN.md).
STATUS_STYLE = {
    "student": {"active": "success", "inactive": "neutral"},
    "teacher": {"active": "success", "inactive": "neutral"},
    "room": {"active": "success", "inactive": "neutral"},
    "flag": {"yes": "success", "no": "neutral"},
    "year": {"open": "success", "upcoming": "info", "closed": "neutral"},
    "group": {"active": "success", "upcoming": "info", "closed": "neutral"},
    "registration": {"active": "success", "cancelled": "neutral"},
    "enrollment": {"trial": "info", "active": "success", "left": "neutral", "switched": "neutral"},
    "standing": {"active": "success", "expiring": "warning", "ended": "danger",
                 "none": "danger"},
    "subscription": {
        "upcoming": "info", "active": "success", "expiring": "warning", "ended": "neutral",
        "cancelled": "danger",
    },
    "session": {"planned": "info", "held": "success", "cancelled": "danger"},
    "attendance": {"present": "success", "late": "warning", "absent": "danger", "excused": "info"},
    "payment": {"kept": "success", "voided": "danger"},
    "payout": {"draft": "neutral", "approved": "info", "paid": "success"},
    "message": {"to_send": "info", "opened": "success", "invited": "success",
                "no_mobile": "neutral"},
    "backup": {"verified": "success", "done": "warning", "running": "info", "failed": "danger"},
}


def kind_for(domain: str, status: str) -> str:
    return STATUS_STYLE[domain].get(status, "neutral")
