"""Dialogs of the student's Remboursements tab and the refunds queue: asking for a refund,
approving, rejecting and paying one out."""

from datetime import date

from PySide6.QtWidgets import QComboBox, QLineEdit, QWidget

from tadris.core.context import UserContext
from tadris.core.money import format_dzd
from tadris.domain.models import Refund
from tadris.i18n.fr import t
from tadris.services import refunds
from tadris.ui.payment_dialogs import method_combo
from tadris.ui.widgets.common import labeled
from tadris.ui.widgets.date_edit import DateLineEdit
from tadris.ui.widgets.forms import FormDialog, caption, row
from tadris.ui.widgets.inputs import money_edit, read_money


def nbsp(amount: int) -> str:
    """An amount that never splits across lines."""
    return format_dzd(amount).replace(" ", " ")


class RefundRequestDialog(FormDialog):
    """Ask to hand back money paid on one line, with the suggestion for the days not used."""

    def __init__(self, conn, ctx: UserContext, student_id: int, parent=None):
        super().__init__(t["refund_dialog.title"], t["refund_dialog.submit"], width=640,
                         parent=parent)
        self._conn, self._ctx, self._student_id = conn, ctx, student_id
        self.refund_id: int | None = None
        self.charge = QComboBox()
        self.unused_from = DateLineEdit()
        self.amount = money_edit()
        self.reason = QLineEdit()
        self.reason.setPlaceholderText(t["refund_dialog.reason_placeholder"])
        self.info = caption()
        self.info.setWordWrap(True)
        self.nothing = caption(t["refund_dialog.nothing"])
        self.nothing.setWordWrap(True)
        note = caption(t["refund_dialog.caption"])
        note.setWordWrap(True)

        self.add(note)
        self.add(labeled(t["refund_dialog.charge"], self.charge, required=True))
        self.add(self.info)
        self.add(row(labeled(t["refund_dialog.unused_from"], self.unused_from),
                     labeled(t["refund_dialog.amount"], self.amount, required=True)))
        self.add(labeled(t["refund_dialog.reason"], self.reason, required=True))
        self.add(self.nothing)
        self._options = {}
        self._load(None)
        self.charge.currentIndexChanged.connect(lambda _i: self._picked())
        self.unused_from.textChanged.connect(lambda _text: self._date_changed())
        self._picked()
        self.finish(self.amount)

    def _load(self, on: date | None) -> None:
        """The lines with something to hand back; the suggestions for `on`."""
        options = refunds.options(self._conn, self._ctx, self._student_id, on)
        self._options = {o.charge_id: o for o in options if o.refundable > 0}
        if self.charge.count() == 0:
            for o in self._options.values():
                self.charge.addItem(o.description, o.charge_id)
        has = bool(self._options)
        self.nothing.setVisible(not has)
        self.submit.setEnabled(has)

    def _picked(self) -> None:
        o = self._options.get(self.charge.currentData())
        if o is None:
            self.info.setText("")
            return
        self.info.setText(t["refund_dialog.info"].format(
            paid=nbsp(o.paid), refunded=nbsp(o.refunded), reserved=nbsp(o.reserved),
            refundable=nbsp(o.refundable), suggestion=nbsp(o.suggestion)))
        self.amount.setText(format_dzd(o.suggestion) if o.suggestion else "")

    def _date_changed(self) -> None:
        on = self.unused_from.value()
        if on is not None or not self.unused_from.text().strip():
            self._load(on)
            self._picked()

    def save(self) -> None:
        self.refund_id = refunds.request(self._conn, self._ctx, self.charge.currentData(),
                                         read_money(self.amount), self.reason.text(),
                                         self.unused_from.value())


def _refund_caption(r: Refund, student: str) -> str:
    return t["refund_decision.caption"].format(
        student=student, line=r.description, amount=nbsp(r.amount_final),
        suggestion=nbsp(r.amount_computed), reason=r.reason, by=r.requested_by or "—")


class ApproveRefundDialog(FormDialog):
    """Director only: the amount may be changed before approving."""

    def __init__(self, conn, ctx: UserContext, refund: Refund, student: str, parent=None):
        super().__init__(t["approve_refund.title"], t["approve_refund.submit"], parent=parent)
        self._conn, self._ctx, self._refund = conn, ctx, refund
        self.amount = money_edit(refund.amount_final)
        note = caption(_refund_caption(refund, student))
        note.setWordWrap(True)
        self.add(note)
        self.add(row(labeled(t["approve_refund.amount"], self.amount, required=True), QWidget()))
        self.finish(self.amount)

    def save(self) -> None:
        refunds.approve(self._conn, self._ctx, self._refund.id, read_money(self.amount))


class RejectRefundDialog(FormDialog):
    """Director only, before the money goes out: the reason goes to the audit log."""

    def __init__(self, conn, ctx: UserContext, refund: Refund, student: str, parent=None):
        super().__init__(t["reject_refund.title"], t["reject_refund.submit"], parent=parent)
        self._conn, self._ctx, self._refund = conn, ctx, refund
        self.submit.setProperty("variant", "danger")
        self.reason = QLineEdit()
        self.reason.setPlaceholderText(t["reject_refund.placeholder"])
        note = caption(_refund_caption(refund, student))
        note.setWordWrap(True)
        self.add(note)
        self.add(labeled(t["reject_refund.reason"], self.reason, required=True))
        self.finish(self.reason)

    def save(self) -> None:
        refunds.reject(self._conn, self._ctx, self._refund.id, self.reason.text())


class PayOutDialog(FormDialog):
    """Hand an approved refund over; its slip is printed for the person who takes it."""

    def __init__(self, conn, ctx: UserContext, refund: Refund, student: str, parent=None):
        super().__init__(t["pay_out.title"], t["pay_out.submit"].format(
            amount=format_dzd(refund.amount_final)), parent=parent)
        self._conn, self._ctx, self._refund = conn, ctx, refund
        self.number: str | None = None
        self.method = method_combo()
        note = caption(t["pay_out.caption"].format(
            amount=nbsp(refund.amount_final), student=student, line=refund.description))
        note.setWordWrap(True)
        self.add(note)
        self.add(row(labeled(t["pay_out.method"], self.method, required=True), QWidget()))
        self.finish(self.method)

    def save(self) -> None:
        self.number = refunds.pay_out(self._conn, self._ctx, self._refund.id,
                                      self.method.currentData())
