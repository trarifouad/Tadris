from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from tadris.core.context import UserContext
from tadris.core.dates import display_date
from tadris.core.errors import BusinessRuleError
from tadris.core.money import format_dzd
from tadris.core.percent import format_percent
from tadris.core.permissions import allowed
from tadris.core.phones import format_phone
from tadris.core.text import fold
from tadris.domain.models import Teacher
from tadris.i18n.fr import t
from tadris.services import groups, payouts, teachers
from tadris.ui.payout_dialogs import period_text
from tadris.ui.teacher_dialogs import RateDialog, TeacherDialog
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets.common import (
    Badge,
    PageBanner,
    ask,
    confirm,
    primary_button,
    toast,
    variant_button,
)
from tadris.ui.widgets.forms import HeaderCard, ListDetailPage, ListSection, caption, padded
from tadris.ui.widgets.tables import CENTER, fit_columns, item

SEARCH_DELAY_MS = 250
STATUS_FILTERS = (("teachers.filter.active", "active"),
                  ("teachers.filter.inactive", "inactive"),
                  ("filter.all", None))


class TeachersPage(ListDetailPage):
    def __init__(self, conn, ctx: UserContext):
        super().__init__(TeacherListView(conn, ctx),
                         lambda teacher_id: TeacherDetailView(conn, ctx, teacher_id))


class TeacherListView(QWidget):
    opened = Signal(int)

    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self.setObjectName("page")
        self.sees_rates = allowed(ctx, "teacher.manage")

        heading = QLabel(t["nav.teachers"])
        heading.setObjectName("pageTitle")
        self.new_teacher = primary_button(t["teachers.new"])
        self.new_teacher.setDefault(False)
        self.new_teacher.clicked.connect(self._create)
        self.new_teacher.setVisible(self.sees_rates)
        head = QHBoxLayout()
        head.addWidget(heading)
        head.addStretch()
        head.addWidget(self.new_teacher)

        self.search = QLineEdit()
        self.search.setPlaceholderText(t["teachers.search"])
        self.search.setClearButtonEnabled(True)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(SEARCH_DELAY_MS)
        self._debounce.timeout.connect(self.refresh)
        self.search.textChanged.connect(self._debounce.start)
        self.status = QComboBox()
        for label_key, value in STATUS_FILTERS:
            self.status.addItem(t[label_key], value)
        self.status.currentIndexChanged.connect(self.refresh)
        filters = QHBoxLayout()
        filters.setSpacing(12)
        filters.addWidget(self.search, 3)
        filters.addWidget(self.status, 1)
        filters.addStretch(2)

        headers = [t["teachers.col.name"], t["teachers.col.phone"]]
        if self.sees_rates:
            headers.append(t["teachers.col.rate"])
        headers += [t["teachers.col.groups"], t["teachers.col.status"]]
        self.list = ListSection(headers, t["teachers.empty"], sortable=True)
        self.list.activated.connect(self.opened.emit)
        self.count = caption()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(16)
        layout.addLayout(head)
        layout.addLayout(filters)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.count)
        self.refresh()

    def refresh(self) -> None:
        self._debounce.stop()
        found = teachers.search(self._conn, self._ctx, self.search.text(),
                                self.status.currentData())
        self.list.set_rows([self._cells(x) for x in found])
        filtered = bool(self.search.text().strip()) or self.status.currentIndex() != 0
        self.list.empty.setText(t["teachers.no_match" if filtered else "teachers.empty"])
        self.count.setText(t["teachers.count"].format(count=len(found)))

    def _cells(self, x: Teacher) -> list:
        cells = [
            item(x.full_name, fold(x.full_name), item_id=x.id),
            item(format_phone(x.phone), x.phone or "", mono=True),
        ]
        if self.sees_rates:
            rate = x.current_rate_bp
            cells.append(item("" if rate is None else format_percent(rate), rate or 0,
                              align=CENTER, mono=True))
        cells += [
            item(str(x.group_count), x.group_count, align=CENTER),
            item(t[f"teacher_status.{x.status}"], x.status, kind=kind_for("teacher", x.status)),
        ]
        return cells

    def _create(self) -> None:
        dialog = TeacherDialog(self._conn, self._ctx, parent=self)
        if not ask(dialog):
            return
        name = teachers.get(self._conn, self._ctx, dialog.teacher_id).full_name
        toast(self, t["teachers.created"].format(name=name))
        self.refresh()
        self.opened.emit(dialog.teacher_id)


class TeacherDetailView(QWidget):
    back = Signal()

    def __init__(self, conn, ctx: UserContext, teacher_id: int):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self.teacher_id = teacher_id
        self.setObjectName("page")
        manages = allowed(ctx, "teacher.manage")

        self.back_button = variant_button(t["teachers.back"], "ghost")

        self.back_button.setObjectName("backLink")
        self.back_button.clicked.connect(self.back.emit)
        back_row = QHBoxLayout()
        back_row.addWidget(self.back_button)
        back_row.addStretch()

        self.header = HeaderCard()
        self.status = self.header.add_meta(Badge())
        self.phone = self.header.add_meta(QLabel())
        self.phone.setObjectName("mono")
        self.since = self.header.add_meta(caption())
        self.rate = self.header.add_meta(caption())
        self.header.close_meta()
        self.edit = self.header.add_action(QPushButton(t["action.edit"]))
        self.edit.clicked.connect(self._edit)
        self.new_rate = self.header.add_action(QPushButton(t["teacher_detail.new_rate"]))
        self.new_rate.clicked.connect(self._new_rate)
        self.deactivate = self.header.add_action(
            variant_button(t["action.deactivate"], "danger"))
        self.deactivate.clicked.connect(self._deactivate)
        self.reactivate = self.header.add_action(QPushButton(t["action.activate"]))
        self.reactivate.clicked.connect(self._reactivate)
        for button in (self.edit, self.new_rate, self.deactivate, self.reactivate):
            button.setVisible(manages)

        self.groups = ListSection([
            t["groups.col.name"], t["groups.col.subject"], t["groups.col.level"],
            t["groups.col.places"], t["groups.col.price"], t["groups.col.status"],
        ], t["teacher_detail.groups_empty"])
        self.rates = ListSection([t["rates.col.rate"], t["rates.col.from"], t["rates.col.to"]],
                                 t["rates.empty"])
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.payouts = ListSection([t["payouts.col.period"], t["payouts.col.months"],
                                    t["payouts.col.amount"], t["payouts.col.status"],
                                    t["payouts.col.number"]], t["teacher_detail.payouts_empty"])
        fit_columns(self.payouts.table, stretch=(0,))
        self.tabs.addTab(padded(self.groups), t["teacher_detail.tab.groups"])
        if manages:
            self.tabs.addTab(padded(self.rates), t["teacher_detail.tab.rates"])
        if allowed(ctx, "payout.view"):
            self.tabs.addTab(padded(self.payouts), t["teacher_detail.tab.payouts"])

        self.error = PageBanner()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 14, 24, 24)
        layout.setSpacing(16)
        layout.addLayout(back_row)
        layout.addWidget(self.error)
        layout.addWidget(self.header)
        layout.addWidget(self.tabs, 1)
        self.refresh()

    def refresh(self) -> None:
        x = teachers.get(self._conn, self._ctx, self.teacher_id)
        self.teacher = x
        self.header.title.setText(x.full_name)
        self.status.setText(t[f"teacher_status.{x.status}"])
        self.status.set_kind(kind_for("teacher", x.status))
        self.phone.setText(format_phone(x.phone))
        self.phone.setVisible(bool(x.phone))
        self.since.setText(t["teacher_detail.hired"].format(date=display_date(x.hire_date))
                           if x.hire_date else "")
        self.rate.setText("" if x.current_rate_bp is None else
                          t["teacher_detail.rate"].format(rate=format_percent(x.current_rate_bp)))
        manages = allowed(self._ctx, "teacher.manage")
        self.deactivate.setVisible(manages and x.status == "active")
        self.reactivate.setVisible(manages and x.status != "active")
        self.groups.set_rows([[
            item(g.name, item_id=g.id),
            item(g.subject),
            item(g.level),
            item(f"{g.enrolled} / {g.seats}", g.enrolled, align=CENTER, mono=True),
            item(format_dzd(g.price), g.price, align=CENTER, mono=True),
            item(t[f"group_state.{g.state}"], kind=kind_for("group", g.state)),
        ] for g in groups.search(self._conn, self._ctx, teacher_id=x.id)])
        if manages:
            self.rates.set_rows([[
                item(format_percent(r.percentage_bp), item_id=r.id, mono=True),
                item(display_date(r.valid_from), align=CENTER),
                item(t["rates.current"] if r.valid_to is None else display_date(r.valid_to),
                     align=CENTER),
            ] for r in teachers.rates(self._conn, self._ctx, x.id)])
        if allowed(self._ctx, "payout.view"):
            self.payouts.set_rows([[
                item(period_text(p), item_id=p.id),
                item(str(p.months), align=CENTER, mono=True),
                item(format_dzd(p.amount_due), align=CENTER, mono=True),
                item(t[f"payout_status.{p.status}"], kind=kind_for("payout", p.status)),
                item(p.receipt_number or "—", mono=True),
            ] for p in payouts.for_teacher(self._conn, self._ctx, x.id)])

    def _edit(self) -> None:
        dialog = TeacherDialog(self._conn, self._ctx, self.teacher, parent=self)
        if ask(dialog):
            self.refresh()
            toast(self, t["teachers.updated"].format(name=self.teacher.full_name))

    def _new_rate(self) -> None:
        dialog = RateDialog(self._conn, self._ctx, self.teacher, parent=self)
        if ask(dialog):
            self.refresh()
            rate = format_percent(teachers.rates(self._conn, self._ctx,
                                                 self.teacher_id)[0].percentage_bp)
            toast(self, t["teachers.rate_set"].format(name=self.teacher.full_name, rate=rate))

    def _deactivate(self) -> None:
        if confirm(self, t["teacher_detail.confirm_deactivate_title"],
                   t["teacher_detail.confirm_deactivate"].format(name=self.teacher.full_name),
                   t["action.deactivate"]):
            self._run(teachers.deactivate, "teachers.deactivated")

    def _reactivate(self) -> None:
        self._run(teachers.reactivate, "teachers.reactivated")

    def _run(self, action, message_key: str) -> None:
        try:
            action(self._conn, self._ctx, self.teacher_id)
        except BusinessRuleError as exc:
            self.error.show_error(exc.message)
            return
        self.error.clear_error()
        self.refresh()
        toast(self, t[message_key].format(name=self.teacher.full_name))

