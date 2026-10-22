"""The student's Paiements tab: what is left to pay, line by line, and every payment with its
receipt, latest first, a page at a time."""

from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from tadris.core.context import UserContext
from tadris.core.dates import display_date
from tadris.core.money import format_dzd
from tadris.core.permissions import allowed
from tadris.domain.models import Payment
from tadris.i18n.fr import t
from tadris.services import debt, payments, printing, students
from tadris.ui.pages.dues_view import DuesView, StatBlocks, buckets, tabular
from tadris.ui.payment_dialogs import PaymentDialog, VoidPaymentDialog
from tadris.ui.widgets import common
from tadris.ui.widgets.common import ask, primary_button, toast, variant_button
from tadris.ui.widgets.forms import ListSection
from tadris.ui.widgets.tables import (
    PAGE_SIZE,
    RIGHT,
    MoreOnScroll,
    fit_columns,
    frozen_columns,
    item,
)


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

        # What is owed, by urgency, then the lines (see dues_view).
        self.stats = StatBlocks()
        self.receive = primary_button(t["payments_tab.receive"])
        self.receive.setDefault(False)
        self.receive.clicked.connect(lambda: self._receive())
        self.receive.setVisible(allowed(ctx, "payment.record"))
        self.head = QHBoxLayout()
        self.head.setSpacing(12)
        self.head.addWidget(self.stats, 1)
        self.head.addWidget(self.receive, 0, Qt.AlignmentFlag.AlignTop)
        self.dues = DuesView(allowed(ctx, "payment.record"))
        self.dues.pay.connect(self._receive)

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
        self._total = 0
        self.pager = MoreOnScroll(self.history.table, self._load_more)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(16)
        layout.addLayout(self.head)
        layout.addWidget(self.dues)
        layout.addWidget(self.history, 1)
        self.refresh()

    def refresh(self) -> None:
        current = debt.for_student(self._conn, self._ctx, self._student_id)
        today = date.fromisoformat(current.as_of)
        self.stats.set_buckets(buckets(current, today))
        self.dues.set_debt(current, today)
        # The latest page, or as many as were shown: a payment voided far down stays in view.
        self._total = payments.count_for_student(self._conn, self._ctx, self._student_id)
        listed = payments.for_student(self._conn, self._ctx, self._student_id,
                                      limit=max(PAGE_SIZE, len(self._payments)))
        self._payments = {p.id: p for p in listed}
        self.history.set_rows([self._cells(p) for p in listed])
        self.pager.reset(len(listed) < self._total)

    def _load_more(self) -> bool:
        page = payments.for_student(self._conn, self._ctx, self._student_id,
                                    limit=PAGE_SIZE, offset=len(self._payments))
        table = self.history.table
        start = table.rowCount()
        with frozen_columns(table):
            table.setRowCount(start + len(page))
            for r, p in enumerate(page, start):
                for c, cell in enumerate(self._cells(p)):
                    table.setItem(r, c, cell)
        self._payments.update((p.id, p) for p in page)
        return bool(page) and len(self._payments) < self._total

    @staticmethod
    def _cells(p: Payment) -> list:
        state = payment_state(p)
        amount = item(format_dzd(p.amount), align=RIGHT)
        amount.setFont(tabular())
        # Green is kept for the student's and the groups' status: a payment kept is grey.
        return [
            item(f"{display_date(p.paid_at)} {p.paid_at[11:16]}", p.paid_at, item_id=p.id),
            item(p.receipt_number or "—", mono=True),
            amount,
            item(t[f"payment_method.{p.method}"]),
            item(p.cashier),
            item(t[f"payment_state.{state}"],
                 kind="danger" if state == "voided" else "neutral"),
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

    def _receive(self, charge_ids: list[int] | None = None) -> None:
        """charge_ids: the lines to pay (a row's « Encaisser », the ticked ones); by default
        what is late or due soon."""
        student = students.get(self._conn, self._ctx, self._student_id)
        dialog = PaymentDialog(self._conn, self._ctx, student,
                               preselect=self.dues.urgent_ids() if charge_ids is None
                               else charge_ids, parent=self)
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
