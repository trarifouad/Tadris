"""Refunds on screen (PLAN « Refunds in V1 »): a student's, in a window from their page, or
what waits (pending, approved) on Paiements, oldest first. The actions follow the request
selected and who looks: the desk asks and withdraws its own pending request; the director
approves, rejects, withdraws any open one and records the money going back, which prints the
receipt. A paid refund's receipt can be printed again (DUPLICATA)."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from tadris.core.context import UserContext
from tadris.core.dates import display_date, short_period
from tadris.core.money import format_dzd
from tadris.core.permissions import allowed
from tadris.domain.models import Refund
from tadris.i18n.fr import t
from tadris.services import printing, refunds
from tadris.ui.refund_dialogs import (
    ApproveRefundDialog,
    CloseRefundDialog,
    PayOutRefundDialog,
    RefundRequestDialog,
)
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets import common
from tadris.ui.widgets.common import ask, primary_button, toast, variant_button
from tadris.ui.widgets.forms import ListSection
from tadris.ui.widgets.tables import CENTER, RIGHT, fit_columns, item


class RefundsSection(QWidget):
    changed = Signal()  # a request asked, decided, withdrawn or paid
    open_student = Signal(int)  # the queue: a row double-clicked

    def __init__(self, conn, ctx: UserContext, student_id: int | None = None):
        """student_id: that student's refunds, every one; None: what waits, everyone's."""
        super().__init__()
        self._conn, self._ctx, self._student_id = conn, ctx, student_id
        self._refunds: dict[int, Refund] = {}
        headers = [t["refunds.col.asked_at"]]
        if student_id is None:
            headers.append(t["refunds.col.student"])
        headers += [t["refunds.col.month"], t["refunds.col.asked"], t["refunds.col.amount"],
                    t["refunds.col.status"], t["refunds.col.number"]]
        empty = t["refunds.empty" if student_id is not None else "refunds.queue_empty"]
        self.list = ListSection(headers, empty)
        self.request = self.list.add_button(primary_button(t["refunds.request"]), end=True)
        self.request.clicked.connect(self._request)
        self.request.setVisible(student_id is not None and allowed(ctx, "refund.request"))
        self.approve = self.list.add_button(QPushButton(t["refunds.approve"]))
        self.approve.clicked.connect(self._approve)
        self.pay = self.list.add_button(QPushButton(t["refunds.pay"]))
        self.pay.clicked.connect(self._pay)
        self.print = self.list.add_button(QPushButton(t["refunds.print"]))
        self.print.clicked.connect(self._print)
        self.reject = self.list.add_button(variant_button(t["refunds.reject"], "danger"))
        self.reject.clicked.connect(lambda: self._close("reject"))
        self.withdraw = self.list.add_button(variant_button(t["refunds.withdraw"], "danger"))
        self.withdraw.clicked.connect(lambda: self._close("withdraw"))
        self.list.selection_changed.connect(self._update_buttons)
        self.list.activated.connect(self._activated)
        fit_columns(self.list.table, stretch=(2 if student_id is None else 1,))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.list)
        if student_id is None:
            self.refresh()  # the queue on Paiements; a student's list waits for its window

    # ----- the list -----

    def refresh(self) -> None:
        found = (refunds.queue(self._conn, self._ctx) if self._student_id is None
                 else refunds.for_student(self._conn, self._ctx, self._student_id))
        self._refunds = {r.id: r for r in found}
        self.list.set_rows([self._cells(r) for r in found])
        self._update_buttons()

    def count(self) -> int:
        return len(self._refunds)

    def _cells(self, r: Refund) -> list:
        cells = [item(display_date(r.requested_at), r.requested_at, item_id=r.id)]
        if self._student_id is None:
            cells.append(item(r.student_name))
        decided = r.amount_approved
        cells += [
            item(f"{r.group_title} · {short_period(r.month_start, r.month_end)}"),
            item(format_dzd(r.amount_requested), align=RIGHT, mono=True),
            item(format_dzd(decided) if decided is not None else "—", align=RIGHT, mono=True),
            item(t[f"refund_status.{r.status}"], kind=kind_for("refund", r.status)),
            item(r.number or "—", align=CENTER, mono=True),
        ]
        return cells

    def selected(self) -> Refund | None:
        refund_id = self.list.selected_id()
        return None if refund_id is None else self._refunds.get(refund_id)

    def _may_withdraw(self, r: Refund) -> bool:
        if allowed(self._ctx, "refund.decide"):
            return r.open
        return r.status == "pending" and r.requested_by_id == self._ctx.user_id

    def _update_buttons(self) -> None:
        r = self.selected()
        decides = allowed(self._ctx, "refund.decide")
        self.approve.setVisible(decides)
        self.reject.setVisible(decides)
        self.pay.setVisible(allowed(self._ctx, "refund.pay"))
        self.print.setVisible(allowed(self._ctx, "print.document"))
        self.withdraw.setVisible(allowed(self._ctx, "refund.request"))
        pending = r is not None and r.status == "pending"
        self.approve.setEnabled(pending)
        self.reject.setEnabled(pending)
        self.pay.setEnabled(r is not None and r.status == "approved")
        self.print.setEnabled(r is not None and r.status == "paid")
        self.withdraw.setEnabled(r is not None and self._may_withdraw(r))

    def _activated(self, refund_id: int) -> None:
        r = self._refunds.get(refund_id)
        if r is None:
            return
        if self._student_id is None:
            self.open_student.emit(r.student_id)
        elif r.status == "paid":
            self._print()

    # ----- the steps -----

    def _done(self, message: str, refund_id: int | None = None) -> None:
        self.list.clear_error()
        self.refresh()
        if refund_id is not None:
            self.list.select_id(refund_id)
        self.changed.emit()
        toast(self, message)

    def _request(self) -> None:
        dialog = RefundRequestDialog(self._conn, self._ctx, self._student_id, parent=self)
        if ask(dialog):
            r = refunds.get(self._conn, self._ctx, dialog.refund_id)
            self._done(t["refunds.requested"].format(amount=format_dzd(r.amount_requested)),
                       r.id)

    def _approve(self) -> None:
        r = self.selected()
        if r is not None and ask(ApproveRefundDialog(self._conn, self._ctx, r, parent=self)):
            r = refunds.get(self._conn, self._ctx, r.id)
            self._done(t["refunds.approved"].format(amount=format_dzd(r.amount),
                                                    name=r.student_name), r.id)

    def _close(self, action: str) -> None:
        r = self.selected()
        if r is not None and ask(CloseRefundDialog(self._conn, self._ctx, r, action,
                                                   parent=self)):
            done = {"reject": "refunds.rejected", "withdraw": "refunds.withdrawn"}[action]
            self._done(t[done].format(name=r.student_name), r.id)

    def _pay(self) -> None:
        r = self.selected()
        if r is None:
            return
        dialog = PayOutRefundDialog(self._conn, self._ctx, r, parent=self)
        if not ask(dialog):
            return
        self._done(t["refunds.paid"].format(number=dialog.number, amount=format_dzd(r.amount),
                                            name=r.student_name), r.id)
        if allowed(self._ctx, "print.document"):
            self._print_refund(r.id)  # the receipt, right away: the family takes it

    def _print(self) -> None:
        r = self.selected()
        if r is not None and r.status == "paid":
            self._print_refund(r.id)

    def _print_refund(self, refund_id: int) -> None:
        if not allowed(self._ctx, "print.document"):
            return
        if not self.list.run(printing.refund_receipt, self._conn, self._ctx, refund_id):
            return
        common.open_document(self.list.last_result)
        toast(self, t["print.done"].format(name=self.list.last_result.name))
