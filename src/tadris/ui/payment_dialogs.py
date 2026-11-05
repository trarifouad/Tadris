"""Dialogs of the student's Paiements tab: receive a payment, void one. Also the debt warning
shown by the enrollment and renewal dialogs."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QLineEdit, QWidget

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError
from tadris.core.money import format_dzd
from tadris.core.permissions import allowed
from tadris.domain.models import PAYMENT_METHODS, NextMonths, Payment, Student
from tadris.i18n.fr import t
from tadris.services import contacts, debt, payments, subscriptions
from tadris.services.payments import PaymentPlan, PlannedLine
from tadris.ui.widgets.common import WarningBanner, fit_to_content, labeled
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
AHEAD_PER_ROW = 3  # « Payer d'avance »: the groups side by side


def debt_banner(conn, ctx: UserContext, student_id: int) -> WarningBanner | None:
    """An amber banner when the student's late debt reaches the threshold (Paramètres)."""
    message = debt.warning(conn, ctx, student_id)
    if message is None:
        return None
    banner = WarningBanner()
    banner.setText(message)
    banner.show()
    return banner


def method_combo(selected: str = "cash") -> QComboBox:
    combo = QComboBox()
    for method in PAYMENT_METHODS:
        combo.addItem(t[f"payment_method.{method}"], method)
    select_data(combo, selected)
    return combo


def ahead_combo(group: NextMonths) -> QComboBox:
    """« Aucun », then « 1 mois (18 nov. → 18 déc.) », « 2 mois (18 nov. → 18 janv.) »…"""
    combo = QComboBox()
    combo.addItem(t["payment_dialog.ahead_none"], 0)
    first = group.months[0][0]
    for count, (_start, end) in enumerate(group.months, 1):
        combo.addItem(t["payment_dialog.ahead_months"].format(
            count=count, period=dates.short_period(first, end)), count)
    combo.setToolTip(t["payment_dialog.ahead_tip"])
    return combo


class PaymentDialog(FormDialog):
    """The student's debt, the amount and how it is paid, and what it will pay: the oldest
    lines first, unless the desk ticks the lines to pay. « Payer d'avance » adds the next
    months of a group: renewed with the payment, they are paid by it. A payment is never more
    than what is left on the lines it pays (there is no credit). The submit button names the
    amount ("Encaisser 2 500 DA")."""

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
        self._owing = [c.id for c in current.charges]  # the lines that can be ticked

        self.summary = caption(t["payment_dialog.summary"].format(
            name=student.full_name, due=format_dzd(current.due),
            overdue=format_dzd(current.overdue)))
        self.summary.setWordWrap(True)
        self.amount = money_edit(current.owed_now or current.due or None)
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

        # « Payer d'avance »: how many of each group's next months this payment renews.
        groups = (subscriptions.next_months(conn, ctx, student.id)
                  if allowed(ctx, "subscription.manage") else [])
        self.ahead: dict[int, QComboBox] = {}
        self._prices = {g.enrollment_id: g.price for g in groups}
        self._counts = dict.fromkeys(self._prices, 0)
        fields = []
        for g in groups:
            combo = ahead_combo(g)
            combo.currentIndexChanged.connect(
                lambda _index, enrollment_id=g.enrollment_id: self._ahead_changed(enrollment_id))
            self.ahead[g.enrollment_id] = combo
            fields.append(labeled(t["payment_dialog.ahead_group"].format(
                group=g.group_title, price=format_dzd(g.price)), combo))

        self.choose = QCheckBox(t["payment_dialog.choose"])
        self.table = ruled_table([t["payment_dialog.col.item"], t["payment_dialog.col.due_date"],
                                  t["payment_dialog.col.left"], t["payment_dialog.col.this"],
                                  t["payment_dialog.col.after"]])
        fit_columns(self.table, stretch=(0,))
        # Room for the months ahead too: the dialog keeps its height as they are added.
        rows = max(min(len(self._owing) + sum(len(g.months) for g in groups), VISIBLE_ROWS), 1)
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
        if fields:
            title = QLabel(t["payment_dialog.ahead"])
            title.setObjectName("cardTitle")
            self.add(title)
            for first in range(0, len(fields), AHEAD_PER_ROW):
                line = fields[first:first + AHEAD_PER_ROW]
                line += [QWidget() for _ in range(AHEAD_PER_ROW - len(line))]  # same widths
                self.add(row(*line))
        self.add(self.choose)
        self.add(self.table)
        self.add(self.nothing)
        self.add(self.outcome)
        self.choose.setVisible(bool(self._owing))

        if preselect:
            self._checked = set(preselect) & set(self._owing)
            if self._checked:
                self.choose.setChecked(True)
                left = sum(c.due for c in current.charges if c.id in self._checked)
                self.amount.setText(format_dzd(left))
        self.amount.textChanged.connect(lambda _text: self._update())
        self.choose.toggled.connect(lambda _on: self._update())
        self.table.itemChanged.connect(self._ticked)
        self._update(fit=False)
        self.finish(self.amount)
        self.amount.selectAll()

    # ----- what the desk chose -----

    def _read_amount(self) -> int | None:
        try:
            amount = read_money(self.amount)
        except BusinessRuleError:
            return None
        return amount if amount > 0 else None

    def chosen(self) -> list[int] | None:
        """With "choose" on: the lines ticked (the months ahead are paid all the same).
        None: every line, oldest first."""
        if not self.choose.isChecked():
            return None
        return [charge_id for charge_id in self._owing if charge_id in self._checked]

    def ahead_counts(self) -> dict[int, int]:
        """{enrollment id: months ahead} for the groups with some."""
        return {enrollment_id: combo.currentData() for enrollment_id, combo in self.ahead.items()
                if combo.currentData()}

    def _ahead_changed(self, enrollment_id: int) -> None:
        """A month more (or less) ahead adds (or takes off) its price to the amount."""
        count = self.ahead[enrollment_id].currentData()
        change = (count - self._counts[enrollment_id]) * self._prices[enrollment_id]
        self._counts[enrollment_id] = count
        amount = max((self._read_amount() or 0) + change, 0)
        self.amount.blockSignals(True)
        self.amount.setText(format_dzd(amount) if amount else "")
        self.amount.blockSignals(False)
        self._update()

    # ----- the preview -----

    def _update(self, fit: bool = True) -> None:
        amount = self._read_amount()
        self.submit.setText(t["payment_dialog.submit_amount"].format(amount=format_dzd(amount))
                            if amount else t["payment_dialog.submit"])
        ahead = self.ahead_counts()
        try:
            plan = payments.preview(self._conn, self._ctx, self._student.id, amount or 0,
                                    self.chosen(), ahead)
        except BusinessRuleError as exc:
            # The lines as they stand, nothing paid on them, and why it cannot be recorded.
            plan = payments.preview(self._conn, self._ctx, self._student.id, 0, None, ahead)
            self._say(exc.message, refused=True)
            self.submit.setEnabled(False)
        else:
            self._say(t["payment_dialog.left_after"].format(amount=format_dzd(plan.left_to_pay)))
            self.submit.setEnabled(amount is not None)
        self._fill(plan)
        has_lines = bool(plan.lines)
        if self.table.isHidden() == has_lines or self.nothing.isHidden() != has_lines:
            self.table.setVisible(has_lines)
            self.nothing.setVisible(not has_lines)
            if fit:
                fit_to_content(self)

    def _say(self, text: str, refused: bool = False) -> None:
        """What the payment leaves, or why it cannot be recorded (in red)."""
        self.outcome.setText(text)
        if self.outcome.property("tone") != ("danger" if refused else None):
            self.outcome.setProperty("tone", "danger" if refused else None)
            self.outcome.style().unpolish(self.outcome)
            self.outcome.style().polish(self.outcome)

    def _fill(self, plan: PaymentPlan) -> None:
        """Rows are made again only when the lines change; otherwise the cells change in
        place. A tick fires itemChanged from the ticked cell, which must not be deleted while
        it does."""
        ids = [line.charge.id for line in plan.lines]
        self.table.blockSignals(True)
        try:
            if ids != self._row_ids():
                fill(self.table, [self._cells(line) for line in plan.lines])
            for r, line in enumerate(plan.lines):
                self._set_amounts(r, line)
                self._set_checkable(self.table.item(r, 0), line)
        finally:
            self.table.blockSignals(False)

    def _row_ids(self) -> list[int]:
        return [self.table.item(r, 0).data(ID_ROLE) for r in range(self.table.rowCount())]

    @staticmethod
    def _cells(line: PlannedLine) -> list:
        c = line.charge
        name = (t["payment_dialog.new_month"].format(description=c.description) if line.ahead
                else c.description)
        return [
            item(name, item_id=c.id),
            item(dates.display_date(c.due_date), align=CENTER),
            item(format_dzd(c.due), align=CENTER, mono=True),
            item("", align=CENTER, mono=True),
            item("", align=CENTER, mono=True),
        ]

    def _set_amounts(self, r: int, line: PlannedLine) -> None:
        self.table.item(r, 3).setText(format_dzd(line.from_payment) if line.from_payment
                                      else "—")
        self.table.item(r, 4).setText(format_dzd(line.left))

    def _set_checkable(self, cell, line: PlannedLine) -> None:
        """A box on each line while "choose" is on; a month ahead is always paid: ticked,
        and its box cannot be unticked (set it to « Aucun » above instead)."""
        flags = cell.flags() & ~Qt.ItemFlag.ItemIsUserCheckable
        if not self.choose.isChecked():
            cell.setFlags(flags)
            cell.setData(Qt.ItemDataRole.CheckStateRole, None)  # no box at all
            return
        ticked = line.ahead or line.charge.id in self._checked
        cell.setFlags(flags if line.ahead else flags | Qt.ItemFlag.ItemIsUserCheckable)
        cell.setCheckState(Qt.CheckState.Checked if ticked else Qt.CheckState.Unchecked)

    def _ticked(self, cell) -> None:
        charge_id = cell.data(ID_ROLE)
        if cell.column() != 0 or not self.choose.isChecked() or charge_id not in self._owing:
            return
        if cell.checkState() == Qt.CheckState.Checked:
            self._checked.add(charge_id)
        else:
            self._checked.discard(charge_id)
        self._update()

    def save(self) -> None:
        amount = read_money(self.amount)
        self.payment_id = payments.record(self._conn, self._ctx, self._student.id, amount,
                                          self.method.currentData(), self.payer.currentData(),
                                          self.chosen(), self.ahead_counts())


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
