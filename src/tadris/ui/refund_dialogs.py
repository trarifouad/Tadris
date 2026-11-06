"""Dialogs of the refunds (PLAN « Refunds in V1 »): ask for one, approve it, reject or withdraw
it, and record the money going back. Each says what it does in one line; the service checks
everything again (a refusal shows in the dialog's banner)."""

from PySide6.QtWidgets import QComboBox, QLineEdit

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.money import dzd_inline, format_dzd
from tadris.domain.models import Refund, RefundableMonth
from tadris.i18n.fr import t
from tadris.services import refunds
from tadris.ui.payment_dialogs import method_combo
from tadris.ui.widgets.common import labeled
from tadris.ui.widgets.forms import FormDialog, caption
from tadris.ui.widgets.inputs import money_edit, read_money


def count_text(left: int, total: int, counted_from: str, value: int) -> str:
    """« 2 séance(s) sur 4 à partir du 16/09/2026 : 3 000 DA »; a month with no session,
    none of it used, is worth its price."""
    if total == 0:
        return t["refund_dialog.count_none"].format(value=dzd_inline(value))
    return t["refund_dialog.count"].format(left=left, total=total,
                                           date=dates.display_date(counted_from),
                                           value=dzd_inline(value))


class RefundRequestDialog(FormDialog):
    """The desk (or the director) asks: a month paid in full, an amount up to its maximum
    (the value of its sessions left, less what refunds already hold on it), a reason."""

    def __init__(self, conn, ctx: UserContext, student_id: int, parent=None):
        super().__init__(t["refund_dialog.title"], t["refund_dialog.submit"], width=540,
                         parent=parent)
        self._conn, self._ctx = conn, ctx
        self.refund_id: int | None = None
        found = refunds.options(conn, ctx, student_id)
        self._months: list[RefundableMonth] = [m for m in found if m.max_amount > 0]
        # The months the student still follows wait for the leave: say so, offered or not.
        still_in = sorted({m.still_in for m in found if m.still_in is not None})
        self.still = caption(t["refund_dialog.still_enrolled"].format(
            groups=", ".join(still_in)) if still_in else "")
        self.still.setWordWrap(True)
        self.still.setVisible(bool(still_in))
        self.month = QComboBox()
        for m in self._months:
            self.month.addItem(t["refund_dialog.month"].format(
                group=m.group_title, period=dates.short_period(m.start_date, m.end_date),
                most=format_dzd(m.max_amount)), m.subscription_id)
        self.count = caption()
        self.count.setWordWrap(True)
        self.amount = money_edit()
        self.reason = QLineEdit()
        self.reason.setPlaceholderText(t["refund_dialog.reason_placeholder"])
        self.none = caption(t["refund_dialog.none"])
        self.none.setWordWrap(True)
        if self._months:
            self.add(labeled(t["refund_dialog.month_label"], self.month, required=True))
            self.add(self.count)
            self.add(labeled(t["refund_dialog.amount"], self.amount, required=True))
            self.add(labeled(t["refund_dialog.reason"], self.reason, required=True))
            self.month.currentIndexChanged.connect(lambda _i: self._show_month())
            self._show_month()
            if still_in:
                self.add(self.still)
        else:
            self.add(self.still if still_in else self.none)
            self.submit.setEnabled(False)
        self.finish(self.amount if self._months else None)

    def chosen(self) -> RefundableMonth | None:
        index = self.month.currentIndex()
        return self._months[index] if 0 <= index < len(self._months) else None

    def _show_month(self) -> None:
        m = self.chosen()
        if m is None:
            return
        text = count_text(m.sessions.left, m.sessions.total, m.sessions.counted_from,
                          m.sessions.value)
        if m.held:
            text += " " + t["refund_dialog.held"].format(held=dzd_inline(m.held))
        text += " " + t["refund_dialog.most"].format(most=dzd_inline(m.max_amount))
        self.count.setText(text)
        self.amount.setText(format_dzd(m.max_amount))

    def save(self) -> None:
        m = self.chosen()
        self.refund_id = refunds.request(self._conn, self._ctx, m.subscription_id,
                                         read_money(self.amount), self.reason.text())


def _summary(r: Refund) -> str:
    """Three lines: who and which month; asked, the maximum and its count; the reason."""
    return t["refund_dialog.summary"].format(
        student=r.student_name, group=r.group_title,
        period=dates.short_period(r.month_start, r.month_end), asked=dzd_inline(r.amount_requested),
        most=dzd_inline(r.max_amount),
        count=count_text(r.sessions_left, r.sessions_total, r.counted_from, r.sessions_value),
        reason=r.reason)


class ApproveRefundDialog(FormDialog):
    """Director only: the amount asked, or less (never more: REVIEW_FIXES, decision 3)."""

    def __init__(self, conn, ctx: UserContext, refund: Refund, parent=None):
        super().__init__(t["approve_refund_dialog.title"], t["approve_refund_dialog.submit"],
                         width=540, parent=parent)
        self._conn, self._ctx, self._refund = conn, ctx, refund
        note = caption(_summary(refund))
        note.setWordWrap(True)
        self.amount = money_edit(refund.amount_requested)
        self.most = caption(t["approve_refund_dialog.most"].format(
            asked=dzd_inline(refund.amount_requested)))
        self.add(note)
        self.add(labeled(t["approve_refund_dialog.amount"], self.amount, required=True))
        self.add(self.most)
        self.finish(self.amount)

    def save(self) -> None:
        refunds.approve(self._conn, self._ctx, self._refund.id, read_money(self.amount))


class CloseRefundDialog(FormDialog):
    """Reject (the director, a pending request) or withdraw (whoever asked it while pending;
    the director any open one): the reason goes with it; its amount is freed."""

    def __init__(self, conn, ctx: UserContext, refund: Refund, action: str, parent=None):
        super().__init__(t[f"{action}_refund_dialog.title"], t[f"{action}_refund_dialog.submit"],
                         width=540, parent=parent)
        self._conn, self._ctx, self._refund, self._action = conn, ctx, refund, action
        self.submit.setProperty("variant", "danger")
        note = caption(_summary(refund))
        note.setWordWrap(True)
        self.reason = QLineEdit()
        self.add(note)
        self.add(labeled(t["refund_dialog.close_reason"], self.reason, required=True))
        self.finish(self.reason)

    def save(self) -> None:
        step = refunds.reject if self._action == "reject" else refunds.withdraw
        step(self._conn, self._ctx, self._refund.id, self.reason.text())


class PayOutRefundDialog(FormDialog):
    """Director only, once the money has gone back to the family: how it went back. The money
    is taken back from the month's payments and the refund gets its number (its receipt is
    printed next)."""

    def __init__(self, conn, ctx: UserContext, refund: Refund, parent=None):
        super().__init__(t["pay_refund_dialog.title"], t["pay_refund_dialog.submit"],
                         width=540, parent=parent)
        self._conn, self._ctx, self._refund = conn, ctx, refund
        self.number: str | None = None
        note = caption(t["pay_refund_dialog.caption"].format(
            amount=dzd_inline(refund.amount), student=refund.student_name,
            group=refund.group_title))
        note.setWordWrap(True)
        self.method = method_combo()
        self.add(note)
        self.add(labeled(t["pay_refund_dialog.method"], self.method, required=True))
        self.finish(self.method)

    def save(self) -> None:
        self.number = refunds.pay_out(self._conn, self._ctx, self._refund.id,
                                      self.method.currentData())
