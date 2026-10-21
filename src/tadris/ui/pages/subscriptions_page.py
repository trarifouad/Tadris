"""Abonnements (sidebar): the months to renew soon, those over and not renewed, and the
students left without any month. A double-click opens the student's page."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget

from tadris.core.context import UserContext
from tadris.core.dates import display_date
from tadris.core.money import format_dzd
from tadris.core.permissions import allowed
from tadris.domain.models import MissingSubscription, Subscription
from tadris.i18n.fr import t
from tadris.services import enrollments, subscriptions
from tadris.ui.subscription_dialogs import BulkRenewDialog, StartDialog, period_text
from tadris.ui.widgets.common import ask, primary_button, toast
from tadris.ui.widgets.forms import ListSection, padded
from tadris.ui.widgets.tables import CENTER, fit_columns, item

HEADERS = ("subscriptions_page.col.student", "subscriptions_page.col.number",
           "subscriptions_page.col.group")


class SubscriptionsPage(QWidget):
    open_student = Signal(int)

    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self.setObjectName("page")
        self._students: dict[str, dict[int, int]] = {}  # list -> row id -> student id
        manages = allowed(ctx, "subscription.manage")

        title = QLabel(t["subscriptions_page.title"])
        title.setObjectName("pageTitle")
        intro = QLabel(t["subscriptions_page.caption"])
        intro.setObjectName("caption")
        intro.setWordWrap(True)

        self.soon = self._section("soon", t["subscriptions_page.col.period"])
        self.lapsed = self._section("lapsed", t["subscriptions_page.col.period"])
        self.missing = self._section("missing", t["subscriptions_page.col.entry"])
        for key, section in (("soon", self.soon), ("lapsed", self.lapsed)):
            button = section.add_button(primary_button(t["subscriptions_page.renew"]), end=True)
            button.setDefault(False)
            button.setVisible(manages)
            button.clicked.connect(lambda _c, k=key: self._renew(k))
            setattr(self, f"renew_{key}", button)
        self.start = self.missing.add_button(QPushButton(t["subscriptions.start"]), end=True)
        self.start.setVisible(manages)
        self.start.clicked.connect(self._start)
        self.missing.selection_changed.connect(
            lambda: self.start.setEnabled(self.missing.selected_id() is not None))

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        for section in (self.soon, self.lapsed, self.missing):
            self.tabs.addTab(padded(section), "")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addWidget(self.tabs, 1)
        self.refresh()

    def _section(self, key: str, date_header: str) -> ListSection:
        section = ListSection([t[h] for h in HEADERS] + [date_header,
                                                          t["subscriptions_page.col.due"]],
                              t[f"subscriptions_page.empty.{key}"], sortable=True)
        fit_columns(section.table, stretch=(0, 2))
        section.activated.connect(lambda row_id, k=key: self._open(k, row_id))
        return section

    def refresh(self) -> None:
        self._soon = subscriptions.ending_soon(self._conn, self._ctx)
        self._lapsed = subscriptions.lapsed(self._conn, self._ctx)
        self._missing = subscriptions.missing(self._conn, self._ctx)
        self._fill("soon", self.soon, self._soon)
        self._fill("lapsed", self.lapsed, self._lapsed)
        self._students["missing"] = {m.enrollment_id: m.student_id for m in self._missing}
        self.missing.set_rows([self._missing_cells(m) for m in self._missing])
        for index, (key, rows) in enumerate((("soon", self._soon), ("lapsed", self._lapsed),
                                             ("missing", self._missing))):
            self.tabs.setTabText(index, t[f"subscriptions_page.tab.{key}"].format(
                count=len(rows)))
        self.renew_soon.setEnabled(bool(self._soon))
        self.renew_lapsed.setEnabled(bool(self._lapsed))

    def _fill(self, key: str, section: ListSection, months: list[Subscription]) -> None:
        self._students[key] = {m.id: m.student_id for m in months}
        section.set_rows([[
            item(m.student_name, m.student_name.casefold(), item_id=m.id),
            item(m.student_number, mono=True),
            item(m.group_title),
            item(period_text(m.start_date, m.end_date), m.end_date),
            item(format_dzd(m.due), m.due, align=CENTER, mono=True),
        ] for m in months])

    @staticmethod
    def _missing_cells(m: MissingSubscription) -> list:
        return [
            item(m.student_name, m.student_name.casefold(), item_id=m.enrollment_id),
            item(m.student_number, mono=True),
            item(m.group_title),
            item(display_date(m.enrolled_on), m.enrolled_on),
            item("—", align=CENTER),
        ]

    def _open(self, key: str, row_id: int) -> None:
        student_id = self._students[key].get(row_id)
        if student_id is not None:
            self.open_student.emit(student_id)

    def _renew(self, key: str) -> None:
        months = self._soon if key == "soon" else self._lapsed
        if not months:
            return
        dialog = BulkRenewDialog(self._conn, self._ctx, months,
                                 t[f"subscriptions_page.tab.{key}"].format(count=len(months)),
                                 parent=self)
        if ask(dialog):
            self.refresh()
            toast(self, t["bulk_renew.done"].format(count=len(dialog.renewed)))

    def _start(self) -> None:
        enrollment_id = self.missing.selected_id()
        if enrollment_id is None:
            return
        enrollment = enrollments.get(self._conn, self._ctx, enrollment_id)
        dialog = StartDialog(self._conn, self._ctx, [enrollment], parent=self)
        if ask(dialog):
            self.refresh()
            toast(self, t["subscriptions.started"].format(
                group=enrollment.group_title,
                period=period_text(*self._period(dialog.new_id))))

    def _period(self, subscription_id: int) -> tuple[str, str]:
        s = subscriptions.get(self._conn, self._ctx, subscription_id)
        return s.start_date, s.end_date
