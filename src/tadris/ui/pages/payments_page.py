"""Paiements (sidebar): the debtors list and the day's cash report. A double-click opens the
student's page, where payments are received."""

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
from tadris.domain.models import CashReport, Payment
from tadris.i18n.fr import t
from tadris.services import debt, groups, payments, refunds
from tadris.ui.pages.payments_tab import payment_state
from tadris.ui.pages.refunds_section import RefundsSection
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets.common import labeled
from tadris.ui.widgets.date_edit import DateLineEdit
from tadris.ui.widgets.forms import ListSection, caption, padded
from tadris.ui.widgets.inputs import count_spin, fill_combo, id_combo, money_edit, read_money
from tadris.ui.widgets.tables import CENTER, RIGHT, fit_columns, item

MAX_DAYS = 365


class DebtorsView(QWidget):
    open_student = Signal(int)

    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self.group = id_combo([])
        self.group.currentIndexChanged.connect(lambda _i: self.refresh())
        self.min_amount = money_edit()
        self.min_amount.setPlaceholderText(t["debtors.any_amount"])
        self.min_amount.textChanged.connect(lambda _text: self.refresh())
        self.min_days = count_spin(0, MAX_DAYS)
        self.min_days.setMinimum(0)
        self.min_days.setValue(0)
        self.min_days.valueChanged.connect(lambda _v: self.refresh())
        filters = QHBoxLayout()
        filters.setSpacing(12)
        filters.addWidget(labeled(t["debtors.group"], self.group), 2)
        filters.addWidget(labeled(t["debtors.min_amount"], self.min_amount), 1)
        filters.addWidget(labeled(t["debtors.min_days"], self.min_days), 1)
        filters.addStretch(1)

        self.total = QLabel()
        self.total.setObjectName("sectionTitle")
        self.list = ListSection([t["debtors.col.student"], t["debtors.col.number"],
                                 t["debtors.col.owed"], t["debtors.col.due"],
                                 t["debtors.col.since"], t["debtors.col.days"]],
                                t["debtors.empty"], sortable=True)
        self.list.toolbar.insertWidget(0, self.total)
        fit_columns(self.list.table, stretch=(0,))
        self.list.activated.connect(self.open_student.emit)

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
        listed = debt.debtors(self._conn, self._ctx, group_id=self.group.currentData(),
                              min_amount=minimum, min_days=self.min_days.value())
        self.total.setText(t["debtors.total"].format(
            count=len(listed), total=format_dzd(sum(d.owed_now for d in listed))))
        self.list.set_rows([[
            item(d.student_name, d.student_name.casefold(), item_id=d.student_id),
            item(d.student_number, mono=True),
            item(format_dzd(d.owed_now), d.owed_now, align=RIGHT, mono=True, tone="danger"),
            item(format_dzd(d.due), d.due, align=RIGHT, mono=True),
            item(display_date(d.oldest_overdue) if d.oldest_overdue else "—",
                 d.oldest_overdue or "", align=CENTER),
            item(str(d.days_overdue), d.days_overdue, align=RIGHT, mono=True),
        ] for d in listed])


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
        self.refunded = caption()
        self.refunded.setWordWrap(True)
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
        layout.addWidget(self.refunded)
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
        self.refunded.setText(t["cash.refunded"].format(
            count=len(report.refunds), total=format_dzd(report.refunded),
            drawer=format_dzd(report.cash_in_drawer)))
        self.refunded.setVisible(bool(report.refunds))
        self._students = {p.id: p.student_id for p in report.payments}
        self.list.set_rows([self._cells(p) for p in report.payments])

    @staticmethod
    def _cells(p: Payment) -> list:
        state = payment_state(p)
        return [
            item(p.paid_at[11:16], p.paid_at, item_id=p.id, align=CENTER),
            item(p.receipt_number or "—", mono=True),
            item(p.student_name),
            item(format_dzd(p.amount), align=RIGHT, mono=True),
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
        self.setObjectName("page")
        title = QLabel(t["payments_page.title"])
        title.setObjectName("pageTitle")
        intro = QLabel(t["payments_page.caption"])
        intro.setObjectName("caption")
        intro.setWordWrap(True)
        self.debtors = DebtorsView(conn, ctx)
        self.cash = CashView(conn, ctx)
        self.refunds = RefundsSection(conn, ctx, lambda: refunds.queue(conn, ctx),
                                      show_student=True, empty_text=t["refunds.queue_empty"])
        self.refunds.changed.connect(self._refunds_changed)
        for view in (self.debtors, self.cash, self.refunds):
            view.open_student.connect(self.open_student.emit)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(padded(self.debtors), t["payments_page.tab.debtors"])
        self.tabs.addTab(padded(self.cash), t["payments_page.tab.cash"])
        self.tabs.addTab(padded(self.refunds), "")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addWidget(self.tabs, 1)
        self.refresh()

    def refresh(self) -> None:
        self.debtors.load_filters()
        self.debtors.refresh()
        self.cash.refresh()
        self._refunds_changed()

    def _refunds_changed(self) -> None:
        """A decision or a payout: the queue's count, and the day's cash."""
        self.refunds.refresh()
        self.tabs.setTabText(2, t["payments_page.tab.refunds"].format(
            count=len(self.refunds.ids())))
        self.cash.refresh()
