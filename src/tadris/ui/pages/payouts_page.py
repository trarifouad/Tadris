"""Paiements enseignants (director only): what each teacher is owed up to a date, the drafts,
approved and paid payouts; a payout's groups and its months student by student."""

from datetime import timedelta

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
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
from tadris.core.percent import format_percent
from tadris.domain.models import Payout, PayoutDue
from tadris.i18n.fr import t
from tadris.services import payouts
from tadris.ui.payout_dialogs import PayoutActions, period_text
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets.common import (
    Badge,
    PageBanner,
    WarningBanner,
    labeled,
    primary_button,
    toast,
    variant_button,
)
from tadris.ui.widgets.date_edit import DateLineEdit
from tadris.ui.widgets.forms import HeaderCard, ListDetailPage, ListSection, caption, padded
from tadris.ui.widgets.tables import CENTER, RIGHT, fit_columns, item

FILTERS = (("open", ("draft", "approved")), ("paid", ("paid",)),
           ("all", ("draft", "approved", "paid")))


def last_month_end():
    """The default date to pay up to: the last day of the previous month."""
    return dates.today().replace(day=1) - timedelta(days=1)


def payout_cells(p: Payout) -> list:
    return [
        item(p.teacher, p.teacher.casefold(), item_id=p.id),
        item(period_text(p), p.period_end),
        item(str(p.months), p.months, align=RIGHT, mono=True),
        item(format_dzd(p.base_amount), p.base_amount, align=RIGHT, mono=True),
        item(format_dzd(p.amount_due), p.amount_due, align=RIGHT, mono=True),
        item(t[f"payout_status.{p.status}"], kind=kind_for("payout", p.status)),
        item(p.receipt_number or "—", mono=True),
    ]


class PayoutListView(QWidget):
    opened = Signal(int)

    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self.setObjectName("page")
        self._payouts: dict[int, Payout] = {}
        self._due: dict[int, PayoutDue] = {}

        title = QLabel(t["nav.payouts"])
        title.setObjectName("pageTitle")
        intro = caption(t["payouts.caption"])
        intro.setWordWrap(True)
        self.until = DateLineEdit()
        self.until.set_value(last_month_end())
        self.until.textChanged.connect(lambda _text: self._load_due())
        self.run = primary_button(t["payouts.run"])
        self.run.setDefault(False)
        self.run.clicked.connect(self._run)
        controls = QHBoxLayout()
        controls.setSpacing(12)
        controls.addWidget(labeled(t["payouts.until"], self.until))
        controls.addStretch()
        controls.addWidget(self.run, 0)
        self.error = PageBanner()

        due_title = QLabel(t["payouts.due_title"])
        due_title.setObjectName("sectionTitle")
        self.due = ListSection([t["payouts.col.teacher"], t["payouts.col.months"],
                                t["payouts.col.revenue"], t["payouts.col.draft"]],
                               t["payouts.due_empty"])
        self.due.toolbar.insertWidget(0, due_title)
        self.prepare = self.due.add_button(QPushButton(t["payouts.prepare"]), end=True)
        self.prepare.clicked.connect(self._prepare)
        self.due.selection_changed.connect(
            lambda: self.prepare.setEnabled(self.due.selected_id() is not None))
        fit_columns(self.due.table, stretch=(0,))

        list_title = QLabel(t["payouts.list_title"])
        list_title.setObjectName("sectionTitle")
        self.filter = QComboBox()
        for key, _statuses in FILTERS:
            self.filter.addItem(t[f"payouts.filter.{key}"], key)
        self.filter.currentIndexChanged.connect(lambda _i: self._load_payouts())
        self.list = ListSection([t["payouts.col.teacher"], t["payouts.col.period"],
                                 t["payouts.col.months"], t["payouts.col.revenue"],
                                 t["payouts.col.amount"], t["payouts.col.status"],
                                 t["payouts.col.number"]], t["payouts.empty"], sortable=True)
        self.list.toolbar.insertWidget(0, list_title)
        self.list.toolbar.insertWidget(1, self.filter)
        self.rebuild = self.list.add_button(QPushButton(t["payouts.rebuild"]))
        self.rebuild.clicked.connect(lambda: self._act("rebuild"))
        self.delete = self.list.add_button(variant_button(t["payouts.delete"], "danger"))
        self.delete.clicked.connect(lambda: self._act("delete"))
        self.approve = self.list.add_button(QPushButton(t["payouts.approve"]))
        self.approve.clicked.connect(lambda: self._act("approve"))
        self.pay = self.list.add_button(QPushButton(t["payouts.pay"]))
        self.pay.clicked.connect(lambda: self._act("pay"))
        self.print = self.list.add_button(QPushButton(t["payouts.print"]))
        self.print.clicked.connect(lambda: self._act("print"))
        self.list.selection_changed.connect(self._update_buttons)
        self.list.activated.connect(self.opened.emit)
        fit_columns(self.list.table, stretch=(0, 1))
        self.actions = PayoutActions(conn, ctx, self, self.error.show_error)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addLayout(controls)
        layout.addWidget(self.error)
        layout.addWidget(self.due, 2)
        layout.addWidget(self.list, 3)
        self.refresh()

    def refresh(self) -> None:
        self._load_due()
        self._load_payouts()

    def _load_due(self) -> None:
        until = self.until.value()
        self.run.setEnabled(until is not None)
        if until is None:
            return
        try:
            listed = payouts.due(self._conn, self._ctx, until)
        except BusinessRuleError as exc:
            self.error.show_error(exc.message)
            return
        self._due = {d.teacher_id: d for d in listed}
        self.due.set_rows([[
            item(d.teacher, item_id=d.teacher_id),
            item(str(d.months), align=RIGHT, mono=True),
            item(format_dzd(d.revenue), align=RIGHT, mono=True),
            item(t["payouts.has_draft"] if d.draft_id else "—"),
        ] for d in listed])

    def _load_payouts(self) -> None:
        statuses = dict(FILTERS)[self.filter.currentData()]
        listed = payouts.listing(self._conn, self._ctx, statuses)
        self._payouts = {p.id: p for p in listed}
        self.list.set_rows([payout_cells(p) for p in listed])

    def selected(self) -> Payout | None:
        payout_id = self.list.selected_id()
        return None if payout_id is None else self._payouts.get(payout_id)

    def _update_buttons(self) -> None:
        p = self.selected()
        status = None if p is None else p.status
        self.rebuild.setEnabled(status == "draft")
        self.delete.setEnabled(status == "draft")
        self.approve.setEnabled(status == "draft")
        self.pay.setEnabled(status == "approved")
        self.print.setEnabled(p is not None)

    def _after(self, select: int | None = None) -> None:
        self.error.clear_error()
        self.refresh()
        if select is not None:
            self.list.select_id(select)

    def _act(self, name: str) -> None:
        p = self.selected()
        if p is None:
            return
        if name == "print":
            self.actions.print(p.id)
            return
        result = getattr(self.actions, name)(p)
        if result:
            self._after(result if name == "rebuild" else (None if name == "delete" else p.id))

    def _until(self):
        until = self.until.value()
        if until is None:
            self.error.show_error(t["date.invalid"])
        return until

    def _run(self) -> None:
        until = self._until()
        if until is None:
            return
        try:
            built, refused = payouts.run(self._conn, self._ctx, until)
        except BusinessRuleError as exc:
            self.error.show_error(exc.message)
            return
        self.refresh()
        if refused:
            self.error.show_error("\n".join(refused))
        else:
            self.error.clear_error()
        toast(self, t["payouts.run_done"].format(count=len(built)))

    def _prepare(self) -> None:
        until, teacher_id = self._until(), self.due.selected_id()
        if until is None or teacher_id is None:
            return
        try:
            payout_id = payouts.build_draft(self._conn, self._ctx, teacher_id, until)
        except BusinessRuleError as exc:
            self.error.show_error(exc.message)
            return
        self._after(payout_id)
        toast(self, t["payouts.prepared"].format(teacher=self._due[teacher_id].teacher))


class PayoutDetailView(QWidget):
    back = Signal()

    def __init__(self, conn, ctx: UserContext, payout_id: int):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self.payout_id = payout_id
        self.setObjectName("page")
        self.back_button = variant_button(t["payouts.back"], "ghost")
        self.back_button.setObjectName("backLink")
        self.back_button.clicked.connect(self.back.emit)
        back_row = QHBoxLayout()
        back_row.addWidget(self.back_button)
        back_row.addStretch()

        self.header = HeaderCard()
        self.status = self.header.add_meta(Badge())
        self.period = self.header.add_meta(caption())
        self.number = self.header.add_meta(QLabel())
        self.number.setObjectName("mono")
        self.header.close_meta()
        self.rebuild = self.header.add_action(QPushButton(t["payouts.rebuild"]))
        self.rebuild.clicked.connect(lambda: self._act("rebuild"))
        self.delete = self.header.add_action(variant_button(t["payouts.delete"], "danger"))
        self.delete.clicked.connect(lambda: self._act("delete"))
        self.approve = self.header.add_action(QPushButton(t["payouts.approve"]))
        self.approve.clicked.connect(lambda: self._act("approve"))
        self.pay = self.header.add_action(primary_button(t["payouts.pay"]))
        self.pay.clicked.connect(lambda: self._act("pay"))
        self.print = self.header.add_action(QPushButton(t["payouts.print"]))
        self.print.clicked.connect(lambda: self.actions.print(self.payout_id))

        self.stale = WarningBanner()
        self.error = PageBanner()
        self.lines = ListSection([t["payouts.col.group"], t["payouts.col.students"],
                                  t["payouts.col.months"], t["payouts.col.revenue"],
                                  t["payouts.col.rate"], t["payouts.col.amount"]],
                                 t["payouts.empty"])
        fit_columns(self.lines.table, stretch=(0,))
        self.months = ListSection([t["payouts.col.student"], t["payouts.col.number_student"],
                                   t["payouts.col.group"], t["payouts.col.from"],
                                   t["payouts.col.price"], t["payouts.col.rate"],
                                   t["payouts.col.share"]], t["payouts.empty"], sortable=True)
        fit_columns(self.months.table, stretch=(0, 2))
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(padded(self.lines), t["payouts.tab.groups"])
        self.tabs.addTab(padded(self.months), t["payouts.tab.months"])
        self.actions = PayoutActions(conn, ctx, self, self.error.show_error)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 14, 24, 24)
        layout.setSpacing(16)
        layout.addLayout(back_row)
        layout.addWidget(self.error)
        layout.addWidget(self.stale)
        layout.addWidget(self.header)
        layout.addWidget(self.tabs, 1)
        self.refresh()

    def refresh(self) -> None:
        p = payouts.get(self._conn, self._ctx, self.payout_id)
        self.payout = p
        self.header.title.setText(t["payouts.detail_title"].format(
            teacher=p.teacher, amount=format_dzd(p.amount_due)))
        self.status.setText(t[f"payout_status.{p.status}"])
        self.status.set_kind(kind_for("payout", p.status))
        self.period.setText(t["payouts.detail_period"].format(
            period=period_text(p), months=p.months, revenue=format_dzd(p.base_amount)))
        self.number.setText(p.receipt_number or "")
        self.number.setVisible(bool(p.receipt_number))
        draft = p.status == "draft"
        for button in (self.rebuild, self.delete, self.approve):
            button.setVisible(draft)
        self.pay.setVisible(p.status == "approved")
        late = payouts.stale(self._conn, self._ctx, p.id) if draft else 0
        if late:
            self.stale.setText(t["payouts.stale"].format(count=late))
        self.stale.setVisible(bool(late))
        self.lines.set_rows([[
            item(line.group_title, item_id=line.id),
            item(str(line.students), align=RIGHT, mono=True),
            item(str(line.months), align=RIGHT, mono=True),
            item(format_dzd(line.revenue_basis), align=RIGHT, mono=True),
            item(format_percent(line.percentage_bp), align=RIGHT, mono=True),
            item(format_dzd(line.amount), align=RIGHT, mono=True),
        ] for line in payouts.lines(self._conn, self._ctx, p.id)])
        self.months.set_rows([[
            item(m.student_name, m.student_name.casefold(), item_id=m.charge_id),
            item(m.student_number, mono=True),
            item(m.group_title),
            item(display_date(m.accrual_date), m.accrual_date, align=CENTER),
            item(format_dzd(m.amount), m.amount, align=RIGHT, mono=True),
            item(format_percent(m.percentage_bp), align=RIGHT, mono=True),
            item(format_dzd(m.share), m.share, align=RIGHT, mono=True),
        ] for m in payouts.months(self._conn, self._ctx, p.id)])

    def _act(self, name: str) -> None:
        result = getattr(self.actions, name)(self.payout)
        if not result:
            return
        self.error.clear_error()
        if name == "delete":
            self.back.emit()
            return
        if name == "rebuild":
            self.payout_id = result
        self.refresh()


class PayoutsPage(ListDetailPage):
    """Paiements enseignants: the list, and a payout's detail in place of it."""

    def __init__(self, conn, ctx: UserContext):
        super().__init__(PayoutListView(conn, ctx),
                         lambda payout_id: PayoutDetailView(conn, ctx, payout_id))
