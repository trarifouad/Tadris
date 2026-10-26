"""Paiements (sidebar): the students with something left to pay (or only those late, a
filter) and the day's cash report. Payments are taken from here: « Encaisser un paiement »
for any student; a double-click on a student, or several selected (Ctrl, Maj) and
« Encaisser », one payment each. « Voir la fiche » opens the student's page."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.dates import display_date
from tadris.core.errors import BusinessRuleError
from tadris.core.money import format_dzd
from tadris.core.permissions import allowed
from tadris.domain.models import CashReport, Payment
from tadris.i18n.fr import t
from tadris.services import debt, groups, payments
from tadris.ui.collect import collect_many, pick_and_collect
from tadris.ui.pages.payments_tab import payment_state
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets.common import labeled, primary_button
from tadris.ui.widgets.date_edit import DateLineEdit
from tadris.ui.widgets.forms import ListSection, caption, padded
from tadris.ui.widgets.inputs import count_spin, fill_combo, id_combo, money_edit, read_money
from tadris.ui.widgets.tables import CENTER, fit_columns, item

MAX_DAYS = 365
# « État »: every student with something left to pay, or only those late.
STATES = ("all", "late")


class DebtorsView(QWidget):
    open_student = Signal(int)
    collect = Signal(list)  # student ids: a double-click, or « Encaisser » on the selection

    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self.group = id_combo([])
        self.group.currentIndexChanged.connect(lambda _i: self.refresh())
        self.state = id_combo([(t[f"debtors.state.{key}"], key) for key in STATES], "all")
        self.state.currentIndexChanged.connect(lambda _i: self.refresh())
        self.min_amount = money_edit()
        self.min_amount.setPlaceholderText(t["debtors.any_amount"])
        self.min_amount.textChanged.connect(lambda _text: self.refresh())
        self.min_days = count_spin(0, MAX_DAYS)
        self.min_days.setMinimum(0)
        self.min_days.setValue(0)
        self.min_days.valueChanged.connect(lambda _v: self.refresh())
        filters = QHBoxLayout()
        filters.setSpacing(12)
        filters.addWidget(labeled(t["debtors.state"], self.state), 1)
        filters.addWidget(labeled(t["debtors.group"], self.group), 2)
        filters.addWidget(labeled(t["debtors.min_amount"], self.min_amount), 1)
        filters.addWidget(labeled(t["debtors.min_days"], self.min_days), 1)
        filters.addStretch(1)

        self.total = QLabel()
        self.total.setObjectName("sectionTitle")
        self.list = ListSection([t["debtors.col.student"], t["debtors.col.number"],
                                 t["debtors.col.owed"], t["debtors.col.due"],
                                 t["debtors.col.since"], t["debtors.col.days"]],
                                t["debtors.empty.all"], sortable=True, multi=True)
        self.list.toolbar.insertWidget(0, self.total)
        fit_columns(self.list.table, stretch=(0,))
        # A double-click pays the line; « Encaisser » pays every line selected.
        cashes = allowed(ctx, "payment.record")
        if cashes:
            self.list.activated.connect(lambda student_id: self.collect.emit([student_id]))
        self.pay = self.list.add_button(primary_button(t["debtors.collect"]), end=True)
        self.pay.setDefault(False)
        self.pay.setVisible(cashes)
        self.pay.clicked.connect(lambda: self.collect.emit(self.list.selected_ids()))
        self.open_profile = self.list.add_button(QPushButton(t["debtors.open"]), end=True)
        self.open_profile.clicked.connect(
            lambda: self.open_student.emit(self.list.selected_ids()[0]))
        self.list.selection_changed.connect(self._update_buttons)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(filters)
        layout.addWidget(self.list, 1)
        self.load_filters()

    def load_filters(self) -> None:
        fill_combo(self.group, [(t["debtors.all_groups"], None)] + [
            (g.title, g.id) for g in groups.search(self._conn, self._ctx)
            if g.status != "closed"], self.group.currentData())

    def refresh(self) -> None:
        try:
            minimum = read_money(self.min_amount, empty=0)
        except BusinessRuleError as exc:
            self.list.show_error(exc.message)
            return
        self.list.clear_error()
        late_only = self.state.currentData() == "late"
        listed = debt.debtors(self._conn, self._ctx, group_id=self.group.currentData(),
                              min_amount=minimum, min_days=self.min_days.value(),
                              late_only=late_only)
        late = format_dzd(sum(d.owed_now for d in listed))
        if late_only:
            self.total.setText(t["debtors.total"].format(count=len(listed), total=late))
        else:
            self.total.setText(t["debtors.total_all"].format(
                count=len(listed), total=format_dzd(sum(d.due for d in listed)), late=late))
        self.list.empty.setText(t[f"debtors.empty.{self.state.currentData()}"])
        self.list.set_rows([self._cells(d) for d in listed])

    @staticmethod
    def _cells(d) -> list:
        """What is late in the red pen; a student not late shows dashes there."""
        late = d.oldest_overdue is not None
        return [
            item(d.student_name, d.student_name.casefold(), item_id=d.student_id),
            item(d.student_number, mono=True),
            item(format_dzd(d.owed_now), d.owed_now, align=CENTER, mono=True,
                 tone="danger" if d.owed_now else "faint"),
            item(format_dzd(d.due), d.due, align=CENTER, mono=True),
            item(display_date(d.oldest_overdue) if late else "—", d.oldest_overdue or "",
                 align=CENTER),
            item(str(d.days_overdue) if late else "—", d.days_overdue if late else -1,
                 align=CENTER, mono=True),
        ]

    def _update_buttons(self) -> None:
        count = len(self.list.selected_ids())
        self.pay.setEnabled(count > 0)
        self.pay.setText(t["debtors.collect"] if count < 2
                         else t["debtors.collect_many"].format(count=count))
        self.open_profile.setEnabled(count == 1)


class CashView(QWidget):
    """One day's payments: what came in per method and per cashier; voided ones are listed
    but not counted."""

    open_student = Signal(int)

    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self._students: dict[int, int] = {}
        self.day = DateLineEdit()
        self.day.set_value(dates.today())
        self.day.textChanged.connect(lambda _text: self.refresh())
        self.today = QPushButton(t["sessions_page.today"])
        self.today.setAutoDefault(False)
        self.today.clicked.connect(lambda: self.day.set_value(dates.today()))
        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(self.day)
        controls.addWidget(self.today)
        controls.addStretch()

        self.total = QLabel()
        self.total.setObjectName("sectionTitle")
        self.by_method = caption()
        self.by_cashier = caption()
        self.voided = caption()
        self.voided.setWordWrap(True)
        self.teachers_paid = caption()
        self.teachers_paid.setWordWrap(True)
        self.list = ListSection([t["cash.col.time"], t["cash.col.receipt"],
                                 t["cash.col.student"], t["cash.col.amount"],
                                 t["cash.col.method"], t["cash.col.cashier"],
                                 t["cash.col.status"]], t["cash.empty"])
        fit_columns(self.list.table, stretch=(2,))
        self.list.activated.connect(self._open)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addLayout(controls)
        layout.addWidget(self.total)
        layout.addWidget(self.by_method)
        layout.addWidget(self.by_cashier)
        layout.addWidget(self.voided)
        layout.addWidget(self.teachers_paid)
        layout.addSpacing(4)
        layout.addWidget(self.list, 1)

    def refresh(self) -> None:
        day = self.day.value()
        if day is None:
            return
        report = payments.cash_report(self._conn, self._ctx, day)
        self._show(report)

    def _show(self, report: CashReport) -> None:
        self.total.setText(t["cash.total"].format(date=display_date(report.day),
                                                  total=format_dzd(report.total),
                                                  count=len(report.kept)))
        self.by_method.setText(t["cash.by_method"].format(parts=" · ".join(
            f"{t[f'payment_method.{method}']} {format_dzd(amount)}"
            for method, amount in report.by_method().items())))
        cashiers = report.by_cashier()
        self.by_cashier.setText(t["cash.by_cashier"].format(parts=" · ".join(
            f"{name} {format_dzd(amount)}" for name, amount in cashiers.items()) or "—"))
        self.voided.setText(t["cash.voided"].format(
            count=len(report.voided), total=format_dzd(sum(p.amount for p in report.voided))))
        self.voided.setVisible(bool(report.voided))
        self.teachers_paid.setText(t["cash.teachers_paid"].format(
            count=len(report.payouts), total=format_dzd(report.paid_to_teachers),
            drawer=format_dzd(report.cash_in_drawer)))
        self.teachers_paid.setVisible(bool(report.payouts))
        self._students = {p.id: p.student_id for p in report.payments}
        self.list.set_rows([self._cells(p) for p in report.payments])

    @staticmethod
    def _cells(p: Payment) -> list:
        state = payment_state(p)
        return [
            item(p.paid_at[11:16], p.paid_at, item_id=p.id, align=CENTER),
            item(p.receipt_number or "—", mono=True),
            item(p.student_name),
            item(format_dzd(p.amount), align=CENTER, mono=True),
            item(t[f"payment_method.{p.method}"]),
            item(p.cashier),
            item(t[f"payment_state.{state}"], kind=kind_for("payment", state)),
        ]

    def _open(self, payment_id: int) -> None:
        student_id = self._students.get(payment_id)
        if student_id is not None:
            self.open_student.emit(student_id)


class PaymentsPage(QWidget):
    open_student = Signal(int)

    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self.setObjectName("page")
        title = QLabel(t["payments_page.title"])
        title.setObjectName("pageTitle")
        self.receive = primary_button(t["payments_tab.receive"])
        self.receive.setDefault(False)
        self.receive.setVisible(allowed(ctx, "payment.record"))
        self.receive.clicked.connect(
            lambda: self._after(pick_and_collect(self, self._conn, self._ctx)))
        head = QHBoxLayout()
        head.addWidget(title)
        head.addStretch()
        head.addWidget(self.receive)
        intro = QLabel(t["payments_page.caption"])
        intro.setObjectName("caption")
        intro.setWordWrap(True)
        self.debtors = DebtorsView(conn, ctx)
        self.cash = CashView(conn, ctx)
        for view in (self.debtors, self.cash):
            view.open_student.connect(self.open_student.emit)
        self.debtors.collect.connect(lambda ids: self._after(collect_many(
            self, self._conn, self._ctx, [(student_id, None) for student_id in ids])))
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(padded(self.debtors), t["payments_page.tab.debtors"])
        self.tabs.addTab(padded(self.cash), t["payments_page.tab.cash"])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(12)
        layout.addLayout(head)
        layout.addWidget(intro)
        layout.addWidget(self.tabs, 1)
        self.refresh()

    def _after(self, taken) -> None:
        """Once a payment is taken (a payment, or how many): the debtors and the day's cash
        follow."""
        if taken:
            self.refresh()

    def refresh(self) -> None:
        self.debtors.load_filters()
        self.debtors.refresh()
        self.cash.refresh()
