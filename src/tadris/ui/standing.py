"""Where a student stands in a group, read the same on the Abonnements page and on the
student's page: En cours, Se termine bientôt, Expiré, Sans abonnement."""

from tadris.core.dates import display_date
from tadris.domain.models import Subscription, standing
from tadris.i18n.fr import t
from tadris.ui.theme.status import kind_for


def standing_badge(month: Subscription | None) -> tuple[str, str, str]:
    """(label, colour, tooltip) from the group's latest month. A month still to come reads
    « En cours » (nothing to do); its tooltip says when it starts."""
    key = standing(month)
    tip = t[f"subscription_line.tip.{key}"]
    if month is not None and month.state == "upcoming":
        tip = t["subscription_line.tip.lined_up"].format(date=display_date(month.start_date))
    return t[f"subscription_line.{key}"], kind_for("standing", key), tip
