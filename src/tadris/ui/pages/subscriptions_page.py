"""Abonnements (sidebar), the renewals: every student in every group (not on trial), one
line each, with the latest month, where it stands and, for information, what is left to pay
on that group's months (after the student's credit). A search, and « Filtres »: the state
(running, ending soon, expired, without a month) and the group. Renew or start a month from
the list, or renew a whole view at once; a double-click or « Voir la fiche » opens the
student's page. Money is taken on the Paiements page."""

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from tadris.core.context import UserContext
from tadris.core.money import format_dzd
from tadris.core.permissions import allowed
from tadris.core.text import fold
from tadris.domain.models import SubscriptionLine
from tadris.i18n.fr import t
from tadris.services import enrollments, subscriptions
from tadris.ui.standing import standing_badge
from tadris.ui.subscription_dialogs import BulkRenewDialog, RenewDialog, StartDialog, period_text
from tadris.ui.widgets.common import ask, primary_button, toast
from tadris.ui.widgets.forms import ListSection
from tadris.ui.widgets.inputs import FilterButton, fill_combo, id_combo
from tadris.ui.widgets.tables import CENTER, fit_columns, item

SEARCH_DELAY_MS = 250
# The states to filter on, in the order of their list.
VIEWS = ("all", "active", "expiring", "ended", "none")
# The views whose lines « Tout renouveler » takes.
RENEWABLE_VIEWS = ("expiring", "ended")


def in_view(line: SubscriptionLine, view: str) -> bool:
    return view == "all" or line.standing == view


class SubscriptionsPage(QWidget):
    open_student = Signal(int)

    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self.setObjectName("page")
        self._lines: dict[int, SubscriptionLine] = {}  # by enrollment
        self._shown: list[SubscriptionLine] = []
        self._manages = allowed(ctx, "subscription.manage")

        title = QLabel(t["subscriptions_page.title"])
        title.setObjectName("pageTitle")
        intro = QLabel(t["subscriptions_page.caption"])
        intro.setObjectName("caption")
        intro.setWordWrap(True)

        self.search = QLineEdit()
        self.search.setPlaceholderText(t["subscriptions_page.search"])
        self.search.setClearButtonEnabled(True)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(SEARCH_DELAY_MS)
        self._debounce.timeout.connect(self._show)
        self.search.textChanged.connect(self._debounce.start)
        # « Filtres »: the state (each with its count) and the group.
        self.status = id_combo([(t[f"subscriptions_page.view.{key}"], key) for key in VIEWS],
                               "all")
        self.status.currentIndexChanged.connect(lambda _index: self._show())
        self.group = id_combo([(t["subscriptions_page.all_groups"], None)])
        self.group.currentIndexChanged.connect(lambda _index: self._show())
        self.filters = FilterButton()
        self.filters.add_filter(t["subscriptions_page.filter.status"], self.status, "all")
        self.filters.add_filter(t["subscriptions_page.filter.group"], self.group)
        filters = QHBoxLayout()
        filters.setSpacing(12)
        filters.addWidget(self.search, 3)
        filters.addWidget(self.filters)
        filters.addStretch(3)

        self.list = ListSection([
            t["subscriptions_page.col.student"], t["subscriptions_page.col.number"],
            t["subscriptions_page.col.group"], t["subscriptions_page.col.period"],
            t["subscriptions_page.col.due"], t["subscriptions_page.col.state"],
        ], t["subscriptions_page.empty"], sortable=True)
        fit_columns(self.list.table, stretch=(0, 2))
        # A double-click opens the student's page, as « Voir la fiche ».
        self.list.activated.connect(lambda _enrollment_id: self._open())
        self.list.selection_changed.connect(self._update_buttons)
        self.open_profile = self.list.add_button(QPushButton(t["subscriptions_page.open"]))
        self.open_profile.clicked.connect(self._open)
        self.renew = self.list.add_button(QPushButton(t["subscriptions_page.renew"]))
        self.renew.clicked.connect(self._renew)
        self.start = self.list.add_button(QPushButton(t["subscriptions.start"]))
        self.start.clicked.connect(self._start)
        self.renew_all = self.list.add_button(primary_button(""), end=True)
        self.renew_all.setDefault(False)
        self.renew_all.clicked.connect(self._renew_all)
        self.count = QLabel()
        self.count.setObjectName("caption")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addLayout(filters)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.count)
        self.refresh()

    # ----- the lines -----

    def view(self) -> str:
        return self.status.currentData() or "all"

    def refresh(self) -> None:
        listed = subscriptions.lines(self._conn, self._ctx)
        self._lines = {line.enrollment_id: line for line in listed}
        fill_combo(self.status, [(t[f"subscriptions_page.view.{key}"].format(
            count=sum(in_view(line, key) for line in listed)), key) for key in VIEWS],
            self.view())
        groups = sorted({(line.group_title, line.group_id) for line in listed},
                        key=lambda g: fold(g[0]))
        fill_combo(self.group, [(t["subscriptions_page.all_groups"], None), *groups],
                   self.group.currentData())
        self.filters.update_count()  # refilled without their change signals
        self._show()

    def _show(self) -> None:
        """The lines of the view that the search and the group keep."""
        self._debounce.stop()
        view, group, words = self.view(), self.group.currentData(), fold(self.search.text())
        self._shown = [
            line for line in self._lines.values()
            if in_view(line, view) and (group is None or line.group_id == group)
            and (not words or words in fold(line.student_name) or words in line.student_number)
        ]
        self.list.set_rows([self._cells(line) for line in self._shown])
        self.count.setText(t["subscriptions_page.count"].format(count=len(self._shown)))
        renewable = self._renewable()
        self.renew_all.setText(t["subscriptions_page.renew_all"].format(count=len(renewable)))
        self.renew_all.setVisible(self._manages and view in RENEWABLE_VIEWS)
        self.renew_all.setEnabled(bool(renewable))
        self._update_buttons()

    @staticmethod
    def _cells(line: SubscriptionLine) -> list:
        m = line.month
        label, kind, tip = standing_badge(m)
        state = item(label, kind=kind)
        state.setToolTip(tip)
        return [
            item(line.student_name, fold(line.student_name), item_id=line.enrollment_id),
            item(line.student_number, mono=True),
            item(line.group_title, fold(line.group_title)),
            item(period_text(line.period_start, m.end_date) if m else "—",
                 m.end_date if m else ""),
            item(format_dzd(line.owed), line.owed, align=CENTER, mono=True,
                 tone="danger" if line.owed else None),
            state,
        ]

    def selected(self) -> SubscriptionLine | None:
        enrollment_id = self.list.selected_id()
        return None if enrollment_id is None else self._lines.get(enrollment_id)

    def _renewable(self) -> list:
        return [line.month for line in self._shown if line.standing in RENEWABLE_VIEWS]

    def _update_buttons(self) -> None:
        line = self.selected()
        self.open_profile.setEnabled(line is not None)
        self.renew.setVisible(self._manages)
        self.start.setVisible(self._manages)
        self.renew.setEnabled(line is not None and line.month is not None)
        self.start.setEnabled(line is not None and line.month is None)

    # ----- actions -----

    def _open(self) -> None:
        """« Voir la fiche » or a double-click: the selected student's page."""
        line = self.selected()
        if line is not None:
            self.open_student.emit(line.student_id)

    def _renew(self) -> None:
        line = self.selected()
        if line is None or line.month is None:
            return
        dialog = RenewDialog(self._conn, self._ctx, line.month, parent=self)
        if ask(dialog):
            self.refresh()
            s = subscriptions.get(self._conn, self._ctx, dialog.new_id)
            toast(self, t["subscriptions.renewed"].format(
                group=line.group_title, period=period_text(s.start_date, s.end_date)))

    def _renew_all(self) -> None:
        months = self._renewable()
        if not months:
            return
        title = self.status.currentText()
        dialog = BulkRenewDialog(self._conn, self._ctx, months, title, parent=self)
        if ask(dialog):
            self.refresh()
            toast(self, t["bulk_renew.done"].format(count=len(dialog.renewed)))

    def _start(self) -> None:
        line = self.selected()
        if line is None or line.month is not None:
            return
        enrollment = enrollments.get(self._conn, self._ctx, line.enrollment_id)
        dialog = StartDialog(self._conn, self._ctx, [enrollment], parent=self)
        if ask(dialog):
            self.refresh()
            s = subscriptions.get(self._conn, self._ctx, dialog.new_id)
            toast(self, t["subscriptions.started"].format(
                group=line.group_title, period=period_text(s.start_date, s.end_date)))
