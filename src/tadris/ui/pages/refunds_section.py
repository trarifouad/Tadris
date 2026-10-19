"""A list of refunds with their actions: the student's (Remboursements tab) or the queue
waiting for a decision or a payout (Paiements page). Approve and reject are the director's;
paying out an approved refund prints its slip, signed by whoever takes the money."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPushButton

from tadris.core.context import UserContext
from tadris.core.dates import display_date
from tadris.core.money import format_dzd
from tadris.core.permissions import allowed
from tadris.domain.models import Refund
from tadris.i18n.fr import t
from tadris.services import printing, students
from tadris.ui.refund_dialogs import ApproveRefundDialog, PayOutDialog, RejectRefundDialog
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets import common
from tadris.ui.widgets.common import ask, toast, variant_button
from tadris.ui.widgets.forms import ListSection
from tadris.ui.widgets.tables import RIGHT, fit_columns, item


class RefundsSection(ListSection):
    changed = Signal()
    open_student = Signal(int)

    def __init__(self, conn, ctx: UserContext, load, show_student: bool, empty_text: str):
        """load() returns the refunds to list."""
        headers = [t["refunds.col.date"]]
        if show_student:
            headers.append(t["refunds.col.student"])
        headers += [t["refunds.col.line"], t["refunds.col.amount"], t["refunds.col.status"],
                    t["refunds.col.number"]]
        super().__init__(headers, empty_text)
        self._conn, self._ctx, self._load = conn, ctx, load
        self._show_student = show_student
        self._refunds: dict[int, Refund] = {}
        self._names: dict[int, str] = {}
        self.approve = self.add_button(QPushButton(t["refunds.approve"]))
        self.approve.clicked.connect(self._approve)
        self.approve.setVisible(allowed(ctx, "refund.approve"))
        self.reject = self.add_button(variant_button(t["refunds.reject"], "danger"))
        self.reject.clicked.connect(self._reject)
        self.reject.setVisible(allowed(ctx, "refund.reject"))
        self.pay = self.add_button(QPushButton(t["refunds.pay"]))
        self.pay.clicked.connect(self._pay)
        self.pay.setVisible(allowed(ctx, "refund.pay"))
        self.print = self.add_button(QPushButton(t["refunds.print"]))
        self.print.clicked.connect(self._print)
        self.print.setVisible(allowed(ctx, "print.document"))
        self.selection_changed.connect(self._update_buttons)
        if show_student:
            self.activated.connect(self._open)
        fit_columns(self.table, stretch=(2 if show_student else 1,))

    def refresh(self) -> None:
        listed = self._load()
        self._refunds = {r.id: r for r in listed}
        for r in listed:
            if r.student_id not in self._names:
                self._names[r.student_id] = students.get(self._conn, self._ctx,
                                                         r.student_id).full_name
        self.set_rows([self._cells(r) for r in listed])

    def _cells(self, r: Refund) -> list:
        cells = [item(display_date(r.created_at), r.created_at, item_id=r.id)]
        if self._show_student:
            cells.append(item(self._names[r.student_id]))
        amount = r.refunded_amount if r.status == "paid" else r.amount_final
        cells += [
            item(r.description),
            item(format_dzd(amount), align=RIGHT, mono=True),
            item(t[f"refund_status.{r.status}"], kind=kind_for("refund", r.status)),
            item(r.number or "—", mono=True),
        ]
        return cells

    def selected(self) -> Refund | None:
        refund_id = self.selected_id()
        return None if refund_id is None else self._refunds.get(refund_id)

    def _update_buttons(self) -> None:
        r = self.selected()
        self.approve.setEnabled(r is not None and r.status == "pending")
        self.reject.setEnabled(r is not None and r.open)
        self.pay.setEnabled(r is not None and r.status == "approved")
        self.print.setEnabled(r is not None and r.status == "paid")

    def _done(self, message: str, refund_id: int) -> None:
        self.clear_error()
        self.refresh()
        self.select_id(refund_id)
        self.changed.emit()
        toast(self, message)

    def _name(self, r: Refund) -> str:
        return self._names.get(r.student_id) or students.get(self._conn, self._ctx,
                                                             r.student_id).full_name

    def _approve(self) -> None:
        r = self.selected()
        if r is not None and ask(ApproveRefundDialog(self._conn, self._ctx, r, self._name(r),
                                                     parent=self)):
            self._done(t["refunds.approved"].format(line=r.description), r.id)

    def _reject(self) -> None:
        r = self.selected()
        if r is not None and ask(RejectRefundDialog(self._conn, self._ctx, r, self._name(r),
                                                    parent=self)):
            self._done(t["refunds.rejected"].format(line=r.description), r.id)

    def _pay(self) -> None:
        r = self.selected()
        if r is None:
            return
        dialog = PayOutDialog(self._conn, self._ctx, r, self._name(r), parent=self)
        if ask(dialog):
            self._done(t["refunds.paid"].format(number=dialog.number,
                                                amount=format_dzd(r.amount_final)), r.id)
            # The slip, right away: it is signed at the desk. By id: a paid refund leaves
            # the queue, so it is no longer the selected row there.
            self._print_slip(r.id)

    def _print(self) -> None:
        r = self.selected()
        if r is not None and r.status == "paid":
            self._print_slip(r.id)

    def _print_slip(self, refund_id: int) -> None:
        if not allowed(self._ctx, "print.document"):
            return
        if not self.run(printing.refund_slip, self._conn, self._ctx, refund_id):
            return
        common.open_document(self.last_result)
        toast(self, t["print.done"].format(name=self.last_result.name))

    def _open(self, refund_id: int) -> None:
        r = self._refunds.get(refund_id)
        if r is not None:
            self.open_student.emit(r.student_id)
