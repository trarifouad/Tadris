"""The student's Paiements tab: what is left to pay, line by line, and every payment with its
receipt, latest first."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from tadris.core.context import UserContext
from tadris.core.dates import display_date
from tadris.core.money import format_dzd
from tadris.core.permissions import allowed
from tadris.domain.models import Debt, Payment
from tadris.i18n.fr import t
from tadris.services import debt, payments, printing, students
from tadris.ui.payment_dialogs import PaymentDialog, VoidPaymentDialog
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets import common
from tadris.ui.widgets.common import ask, primary_button, toast, variant_button
from tadris.ui.widgets.forms import ListSection
from tadris.ui.widgets.tables import CENTER, RIGHT, fit_columns, item


def summary_text(d: Debt) -> str:
    if d.balance < 0:
        return t["payments_tab.summary_credit"].format(credit=format_dzd(-d.balance))
    return t["payments_tab.summary"].format(due=format_dzd(d.due),
                                            overdue=format_dzd(d.overdue),
                                            credit=format_dzd(d.credit))


def payment_state(p: Payment) -> str:
    return "voided" if p.voided else "kept"


class PaymentsTab(QWidget):
    changed = Signal()

    def __init__(self, conn, ctx: UserContext, student_id: int):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self._student_id = student_id
        self._payments: dict[int, Payment] = {}

        self.summary = QLabel()
        self.summary.setObjectName("sectionTitle")
        self.dues = ListSection([t["payments_tab.col.item"], t["payments_tab.col.due_date"],
                                 t["payments_tab.col.amount"], t["payments_tab.col.paid"],
                                 t["payments_tab.col.left"]], t["payments_tab.nothing_due"])
        self.dues.toolbar.insertWidget(0, self.summary)
        self.receive = self.dues.add_button(primary_button(t["payments_tab.receive"]), end=True)
        self.receive.setDefault(False)
        self.receive.clicked.connect(self._receive)
        self.receive.setVisible(allowed(ctx, "payment.record"))
        fit_columns(self.dues.table, stretch=(0,))

        history_title = QLabel(t["payments_tab.history"])
        history_title.setObjectName("sectionTitle")
        self.history = ListSection([t["payments_tab.col.date"], t["payments_tab.col.receipt"],
                                    t["payments_tab.col.amount"], t["payments_tab.col.method"],
                                    t["payments_tab.col.cashier"],
                                    t["payments_tab.col.status"]], t["payments_tab.empty"])
        self.history.toolbar.insertWidget(0, history_title)
        self.print = self.history.add_button(QPushButton(t["payments_tab.print"]))
        self.print.clicked.connect(self._print)
        self.print.setVisible(allowed(ctx, "print.document"))
        self.void = self.history.add_button(variant_button(t["payments_tab.void"], "danger"))
        self.void.clicked.connect(self._void)
        self.void.setVisible(allowed(ctx, "payment.void"))
        self.history.selection_changed.connect(self._update_buttons)
        self.history.activated.connect(lambda _id: self._print())
        fit_columns(self.history.table, stretch=(1,))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(self.dues, 1)
        layout.addWidget(self.history, 1)
        self.refresh()

    def refresh(self) -> None:
        current = debt.for_student(self._conn, self._ctx, self._student_id)
        self.summary.setText(summary_text(current))
        self.dues.set_rows([[
            item(c.description, item_id=c.id),
            item(display_date(c.due_date), c.due_date, align=CENTER),
            item(format_dzd(c.amount), align=RIGHT, mono=True),
            item(format_dzd(c.paid), align=RIGHT, mono=True),
            item(format_dzd(c.due), align=RIGHT, mono=True,
                 tone="danger" if c.due_date <= current.as_of else None),
        ] for c in current.charges])
        listed = payments.for_student(self._conn, self._ctx, self._student_id)
        self._payments = {p.id: p for p in listed}
        self.history.set_rows([self._cells(p) for p in listed])

    @staticmethod
    def _cells(p: Payment) -> list:
        state = payment_state(p)
        return [
            item(f"{display_date(p.paid_at)} {p.paid_at[11:16]}", p.paid_at, item_id=p.id),
            item(p.receipt_number or "—", mono=True),
            item(format_dzd(p.amount), align=RIGHT, mono=True),
            item(t[f"payment_method.{p.method}"]),
            item(p.cashier),
            item(t[f"payment_state.{state}"], kind=kind_for("payment", state)),
        ]

    def selected(self) -> Payment | None:
        payment_id = self.history.selected_id()
        return None if payment_id is None else self._payments.get(payment_id)

    def _update_buttons(self) -> None:
        p = self.selected()
        self.print.setEnabled(p is not None and p.receipt_id is not None)
        self.void.setEnabled(p is not None and not p.voided)

    def _done(self, message: str, payment_id: int | None = None) -> None:
        self.history.clear_error()
        self.refresh()
        if payment_id is not None:
            self.history.select_id(payment_id)
        self.changed.emit()
        toast(self, message)

    def _receive(self) -> None:
        student = students.get(self._conn, self._ctx, self._student_id)
        dialog = PaymentDialog(self._conn, self._ctx, student, parent=self)
        if not ask(dialog):
            return
        p = payments.get(self._conn, self._ctx, dialog.payment_id)
        self._done(t["payments_tab.received"].format(amount=format_dzd(p.amount),
                                                     number=p.receipt_number), p.id)
        if allowed(self._ctx, "print.document"):
            self._print()  # the receipt, right away: it is handed over at the desk

    def _print(self) -> None:
        p = self.selected()
        if p is None or p.receipt_id is None or not allowed(self._ctx, "print.document"):
            return
        if not self.history.run(printing.receipt, self._conn, self._ctx, p.receipt_id):
            return
        common.open_document(self.history.last_result)
        toast(self, t["print.done"].format(name=self.history.last_result.name))

    def _void(self) -> None:
        p = self.selected()
        if p is None or p.voided:
            return
        if ask(VoidPaymentDialog(self._conn, self._ctx, p, parent=self)):
            self._done(t["payments_tab.voided"].format(number=p.receipt_number or "—",
                                                       amount=format_dzd(p.amount)), p.id)
