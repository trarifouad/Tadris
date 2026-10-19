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
    "subscription": {
        "upcoming": "info", "active": "success", "expiring": "warning", "ended": "neutral",
        "cancelled": "danger",
    },
    "session": {"planned": "info", "held": "success", "cancelled": "danger"},
    "attendance": {"present": "success", "late": "warning", "absent": "danger", "excused": "info"},
    "refund": {"pending": "warning", "approved": "info", "paid": "success", "rejected": "neutral"},
    "payout": {"draft": "neutral", "approved": "info", "paid": "success"},
    "sms": {"pending": "info", "sent": "success", "failed": "danger"},
}


def kind_for(domain: str, status: str) -> str:
    return STATUS_STYLE[domain].get(status, "neutral")
