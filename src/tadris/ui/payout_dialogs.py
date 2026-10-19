"""Teacher payout actions shared by the list and the detail view: build again, delete a draft,
approve, pay (the slip opens to be signed) and print. Director only."""

from PySide6.QtWidgets import QWidget

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError
from tadris.core.money import format_dzd
from tadris.domain.models import Payout
from tadris.i18n.fr import t
from tadris.services import payouts, printing
from tadris.ui.payment_dialogs import method_combo
from tadris.ui.widgets import common
from tadris.ui.widgets.common import ask, confirm, labeled, toast
from tadris.ui.widgets.forms import FormDialog, caption, row


def nbsp(amount: int) -> str:
    return format_dzd(amount).replace(" ", " ")


def period_text(p: Payout) -> str:
    return t["payouts.period"].format(start=dates.display_date(p.period_start),
                                      end=dates.display_date(p.period_end))


class PayPayoutDialog(FormDialog):
    """The whole amount to the teacher; the submit button names it."""

    def __init__(self, conn, ctx: UserContext, payout: Payout, parent=None):
        super().__init__(t["pay_payout.title"], t["pay_payout.submit"].format(
            amount=format_dzd(payout.amount_due)), parent=parent)
        self._conn, self._ctx, self._payout = conn, ctx, payout
        self.number: str | None = None
        self.method = method_combo()
        note = caption(t["pay_payout.caption"].format(
            teacher=payout.teacher, amount=nbsp(payout.amount_due), period=period_text(payout)))
        note.setWordWrap(True)
        self.add(note)
        self.add(row(labeled(t["pay_payout.method"], self.method, required=True), QWidget()))
        self.finish(self.method)

    def save(self) -> None:
        self.number = payouts.mark_paid(self._conn, self._ctx, self._payout.id,
                                        self.method.currentData())


class PayoutActions:
    """The actions on one payout from a page; errors go to `show_error`, success to a toast.
    Each returns True when something changed."""

    def __init__(self, conn, ctx: UserContext, page: QWidget, show_error):
        self._conn, self._ctx, self._page, self._show_error = conn, ctx, page, show_error

    def _run(self, action, *args):
        try:
            return action(self._conn, self._ctx, *args)
        except BusinessRuleError as exc:
            self._show_error(exc.message)
            return None

    def rebuild(self, p: Payout) -> int | None:
        """The new draft's id."""
        new_id = self._run(payouts.rebuild, p.id)
        if new_id is not None:
            fresh = payouts.get(self._conn, self._ctx, new_id)
            toast(self._page, t["payouts.rebuilt"].format(teacher=p.teacher,
                                                          amount=format_dzd(fresh.amount_due)))
        return new_id

    def delete(self, p: Payout) -> bool:
        if not confirm(self._page, t["payouts.confirm_delete_title"],
                       t["payouts.confirm_delete"].format(teacher=p.teacher,
                                                          period=period_text(p)),
                       t["payouts.delete"]):
            return False
        try:
            payouts.delete_draft(self._conn, self._ctx, p.id)
        except BusinessRuleError as exc:
            self._show_error(exc.message)
            return False
        toast(self._page, t["payouts.deleted"].format(teacher=p.teacher))
        return True

    def approve(self, p: Payout) -> bool:
        late = payouts.stale(self._conn, self._ctx, p.id)
        text = t["payouts.confirm_approve"].format(teacher=p.teacher, amount=nbsp(p.amount_due),
                                                   period=period_text(p))
        if late:
            text += "\n\n" + t["payouts.stale"].format(count=late)
        if not confirm(self._page, t["payouts.confirm_approve_title"], text,
                       t["payouts.approve"]):
            return False
        try:
            payouts.approve(self._conn, self._ctx, p.id)
        except BusinessRuleError as exc:
            self._show_error(exc.message)
            return False
        toast(self._page, t["payouts.approved"].format(teacher=p.teacher))
        return True

    def pay(self, p: Payout) -> bool:
        dialog = PayPayoutDialog(self._conn, self._ctx, p, parent=self._page)
        if not ask(dialog):
            return False
        toast(self._page, t["payouts.paid"].format(number=dialog.number, teacher=p.teacher,
                                                   amount=format_dzd(p.amount_due)))
        self.print(p.id)  # the slip, right away: the teacher signs it
        return True

    def print(self, payout_id: int) -> None:
        path = self._run(printing.payout_slip, payout_id)
        if path is not None:
            common.open_document(path)
            toast(self._page, t["print.done"].format(name=path.name))
