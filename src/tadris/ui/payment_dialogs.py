"""Dialogs of the student's Paiements tab: receive a payment, void one. Also the debt warning
shown by the enrollment and renewal dialogs."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError
from tadris.core.money import format_dzd
from tadris.domain.models import PAYMENT_METHODS, Payment, Student
from tadris.i18n.fr import t
from tadris.services import contacts, debt, payments
from tadris.services.payments import PaymentPlan
from tadris.ui.widgets.common import WarningBanner, labeled
from tadris.ui.widgets.forms import FormDialog, caption, row
from tadris.ui.widgets.inputs import money_edit, read_money, select_data
from tadris.ui.widgets.tables import (
    CENTER,
    ID_ROLE,
    ROW_HEIGHT,
    fill,
    fit_columns,
    item,
    ruled_table,
)

VISIBLE_ROWS = 6


def debt_banner(conn, ctx: UserContext, student_id: int) -> WarningBanner | None:
    """An amber banner when the student's late debt reaches the threshold (Paramètres)."""
    message = debt.warning(conn, ctx, student_id)
    if message is None:
        return None
    banner = WarningBanner()
    banner.setText(message)
    banner.show()
    return banner


def owing(plan: PaymentPlan) -> list:
    """The lines with something left once the credit paid its part, as every screen shows
    them. A line the credit pays whole is not shown: it is paid all the same when the
    payment is recorded (the receipt lists it, with the credit used)."""
    return [line for line in plan.lines if line.charge.due > line.from_credit]


def method_combo(selected: str = "cash") -> QComboBox:
    combo = QComboBox()
    for method in PAYMENT_METHODS:
        combo.addItem(t[f"payment_method.{method}"], method)
    select_data(combo, selected)
    return combo


class PaymentDialog(FormDialog):
    """The student's debt, the amount and how it is paid, and what it will pay: the credit
    first, then the oldest lines, unless the desk ticks the lines to pay. Only what is left
    after the credit is listed. The submit button names the amount ("Encaisser 2 500 DA")."""

    def __init__(self, conn, ctx: UserContext, student: Student,
                 preselect: list[int] | None = None, parent=None):
        """preselect: charge ids ticked from the start (the student page's selection, or
        what is late and due soon); the amount is what is left on them."""
        super().__init__(t["payment_dialog.title"], t["payment_dialog.submit"], width=880,
                         parent=parent)
        self._conn, self._ctx, self._student = conn, ctx, student
        self.payment_id: int | None = None
        self._checked: set[int] = set()
        current = debt.for_student(conn, ctx, student.id)
        self._base = payments.preview(conn, ctx, student.id, 0)  # the credit's part per line

        net = current.after_credit()
        text = t["payment_dialog.summary"].format(
            name=student.full_name, due=format_dzd(net.due), overdue=format_dzd(net.overdue))
        if current.credit > net.credit:
            text += " " + t["payment_dialog.credit_deducted"].format(
                amount=format_dzd(current.credit - net.credit))
        if net.credit:
            text += " " + t["payment_dialog.credit_left"].format(amount=format_dzd(net.credit))
        self.summary = caption(text)
        self.summary.setWordWrap(True)
        suggested = current.owed_now or max(current.balance, 0)
        self.amount = money_edit(suggested or None)
        self.method = method_combo()
        self.payer = QComboBox()
        self.payer.addItem(t["payment_dialog.no_payer"], None)
        main = None
        for c in contacts.list_for_student(conn, ctx, student.id):
            self.payer.addItem(f"{c.full_name} ({c.relation})" if c.relation else c.full_name,
                               c.contact_id)
            if c.is_main:
                main = c.contact_id
        select_data(self.payer, main)
        self.choose = QCheckBox(t["payment_dialog.choose"])
        self.table = ruled_table([t["payment_dialog.col.item"], t["payment_dialog.col.due_date"],
                                  t["payment_dialog.col.left"], t["payment_dialog.col.this"],
                                  t["payment_dialog.col.after"]])
        fit_columns(self.table, stretch=(0,))
        rows = max(min(len(owing(self._base)), VISIBLE_ROWS), 1)
        header = self.table.horizontalHeader().height() or ROW_HEIGHT
        self.table.setFixedHeight(header + 2 + ROW_HEIGHT * rows)
        self.nothing = caption(t["payment_dialog.nothing_due"])
        self.outcome = caption()
        self.outcome.setWordWrap(True)

        banner = debt_banner(conn, ctx, student.id)
        if banner is not None:
            self.add(banner)
        self.add(self.summary)
        self.add(row(labeled(t["payment_dialog.amount"], self.amount, required=True),
                     labeled(t["payment_dialog.method"], self.method, required=True),
                     labeled(t["payment_dialog.payer"], self.payer)))
        self.add(self.choose)
        self.add(self.table)
        self.add(self.nothing)
        self.add(self.outcome)
        has_lines = bool(owing(self._base))
        self.table.setVisible(has_lines)
        self.choose.setVisible(has_lines)
        self.nothing.setVisible(not has_lines)

        if preselect:
            self._checked = set(preselect) & {line.charge.id for line in owing(self._base)}
            if self._checked:
                self.choose.setChecked(True)
                left = sum(line.left for line in owing(self._base)
                           if line.charge.id in self._checked)
                if left:
                    self.amount.setText(format_dzd(left))
        self.amount.textChanged.connect(lambda _text: self._update())
        self.choose.toggled.connect(lambda _on: self._update())
        self.table.itemChanged.connect(self._ticked)
        self._update()
        self.finish(self.amount)
        self.amount.selectAll()

    # ----- the preview -----

    def _read_amount(self) -> int | None:
        try:
            amount = read_money(self.amount)
        except BusinessRuleError:
            return None
        return amount if amount > 0 else None

    def chosen(self, amount: int) -> list[tuple[int, int]] | None:
        """With "choose" on: the amount spread over the ticked lines, oldest first, after
        the credit's part. None: the oldest-first order, also while no line is ticked (the
        whole amount would otherwise go to credit)."""
        if not self.choose.isChecked() or not self._checked:
            return None
        chosen, left = [], amount
        for line in owing(self._base):
            if line.charge.id in self._checked and left > 0:
                take = min(left, line.left)
                if take > 0:
                    chosen.append((line.charge.id, take))
                    left -= take
        return chosen

    def _update(self) -> None:
        amount = self._read_amount()
        self.submit.setEnabled(amount is not None)
        self.submit.setText(t["payment_dialog.submit_amount"].format(amount=format_dzd(amount))
                            if amount else t["payment_dialog.submit"])
        try:
            plan = payments.preview(self._conn, self._ctx, self._student.id, amount or 0,
                                    self.chosen(amount or 0))
        except BusinessRuleError as exc:
            self.outcome.setText(exc.message)
            return
        self._fill(plan)
        self.outcome.setText(self._result_text(plan, amount))

    def _fill(self, plan: PaymentPlan) -> None:
        """Rows are made once; later updates change the cells in place. A tick fires
        itemChanged from the ticked cell, which must not be deleted while it does."""
        lines = owing(plan)
        ids = [line.charge.id for line in lines]
        self.table.blockSignals(True)
        try:
            if ids != self._row_ids():
                fill(self.table, [self._cells(line) for line in lines])
            for r, line in enumerate(lines):
                self._set_amounts(r, line)
                self._set_checkable(self.table.item(r, 0), line.charge.id)
        finally:
            self.table.blockSignals(False)

    def _row_ids(self) -> list[int]:
        return [self.table.item(r, 0).data(ID_ROLE) for r in range(self.table.rowCount())]

    @staticmethod
    def _cells(line) -> list:
        """« Reste dû »: what is left once the credit paid its part."""
        c = line.charge
        return [
            item(c.description, item_id=c.id),
            item(dates.display_date(c.due_date), align=CENTER),
            item(format_dzd(c.due - line.from_credit), align=CENTER, mono=True),
            item("", align=CENTER, mono=True),
            item("", align=CENTER, mono=True),
        ]

    def _set_amounts(self, r: int, line) -> None:
        self.table.item(r, 3).setText(format_dzd(line.from_payment) if line.from_payment
                                      else "—")
        self.table.item(r, 4).setText(format_dzd(line.left))

    def _set_checkable(self, cell, charge_id: int) -> None:
        flags = cell.flags() & ~Qt.ItemFlag.ItemIsUserCheckable
        if self.choose.isChecked():
            cell.setFlags(flags | Qt.ItemFlag.ItemIsUserCheckable)
            cell.setCheckState(Qt.CheckState.Checked if charge_id in self._checked
                               else Qt.CheckState.Unchecked)
        else:
            cell.setFlags(flags)
            cell.setData(Qt.ItemDataRole.CheckStateRole, None)  # no box at all

    def _ticked(self, cell) -> None:
        if cell.column() != 0 or not self.choose.isChecked():
            return
        charge_id = cell.data(ID_ROLE)
        if cell.checkState() == Qt.CheckState.Checked:
            self._checked.add(charge_id)
        else:
            self._checked.discard(charge_id)
        self._update()

    @staticmethod
    def _result_text(plan: PaymentPlan, amount: int | None) -> str:
        """What the payment leaves (the credit's part is said once, in the summary)."""
        parts = []
        if amount and plan.to_credit:
            parts.append(t["payment_dialog.to_credit"].format(amount=format_dzd(plan.to_credit)))
        parts.append(t["payment_dialog.left_after"].format(amount=format_dzd(plan.left_to_pay)))
        return " ".join(parts)

    def save(self) -> None:
        amount = read_money(self.amount)
        self.payment_id = payments.record(self._conn, self._ctx, self._student.id, amount,
                                          self.method.currentData(), self.payer.currentData(),
                                          self.chosen(amount))


class VoidPaymentDialog(FormDialog):
    """Director only: the reason goes to the audit log; what the payment paid is owed
    again."""

    def __init__(self, conn, ctx: UserContext, payment: Payment, parent=None):
        super().__init__(t["void_payment_dialog.title"], t["void_payment_dialog.submit"],
                         parent=parent)
        self._conn, self._ctx, self._payment = conn, ctx, payment
        self.submit.setProperty("variant", "danger")
        self.reason = QLineEdit()
        self.reason.setPlaceholderText(t["void_payment_dialog.placeholder"])
        note = caption(t["void_payment_dialog.caption"].format(
            number=payment.receipt_number or "—",
            amount=format_dzd(payment.amount).replace(" ", " "),  # never split
            name=payment.student_name, date=dates.display_date(payment.paid_at)))
        note.setWordWrap(True)
        self.add(note)
        self.add(labeled(t["void_payment_dialog.reason"], self.reason, required=True))
        self.finish(self.reason)

    def save(self) -> None:
        payments.void(self._conn, self._ctx, self._payment.id, self.reason.text())
