"""The student's Abonnements tab: every month of every group, latest first."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from tadris.core.context import UserContext
from tadris.core.money import format_dzd
from tadris.core.permissions import allowed
from tadris.domain.models import Enrollment, Subscription
from tadris.i18n.fr import t
from tadris.services import enrollments, subscriptions
from tadris.ui.subscription_dialogs import (
    CancelSubscriptionDialog,
    RenewDialog,
    StartDialog,
    period_text,
)
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets.common import ask, primary_button, toast, variant_button
from tadris.ui.widgets.forms import ListSection
from tadris.ui.widgets.tables import RIGHT, fit_columns, item


class SubscriptionsTab(QWidget):
    changed = Signal()

    def __init__(self, conn, ctx: UserContext, student_id: int):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self._student_id = student_id
        self._subscriptions: dict[int, Subscription] = {}
        self._latest: set[int] = set()  # the latest month of each enrollment
        self._without: list[Enrollment] = []

        self.summary = QLabel()
        self.summary.setObjectName("sectionTitle")
        self.list = ListSection([t["subscriptions.col.group"], t["subscriptions.col.period"],
                                 t["subscriptions.col.price"], t["subscriptions.col.due"],
                                 t["subscriptions.col.status"]], t["subscriptions.empty"])
        self.list.toolbar.insertWidget(0, self.summary)
        self.renew = self.list.add_button(primary_button(t["subscriptions.renew"]))
        self.renew.setDefault(False)
        self.renew.clicked.connect(self._renew)
        self.cancel = self.list.add_button(variant_button(t["subscriptions.cancel"], "danger"))
        self.cancel.clicked.connect(self._cancel)
        self.start = self.list.add_button(QPushButton(t["subscriptions.start"]), end=True)
        self.start.clicked.connect(self._start)
        manages = allowed(ctx, "subscription.manage")
        self.renew.setVisible(manages)
        self.cancel.setVisible(allowed(ctx, "subscription.cancel"))
        self.list.selection_changed.connect(self._update_buttons)
        if manages:
            self.list.activated.connect(lambda _id: self._renew())
        fit_columns(self.list.table, stretch=(0,))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.addWidget(self.list)
        self.refresh()

    def refresh(self) -> None:
        listed = subscriptions.for_student(self._conn, self._ctx, self._student_id)
        self._subscriptions = {s.id: s for s in listed}
        latest: dict[int, Subscription] = {}
        for s in listed:
            if s.status != "cancelled" and (s.enrollment_id not in latest
                                            or s.end_date > latest[s.enrollment_id].end_date):
                latest[s.enrollment_id] = s
        self._latest = {s.id for s in latest.values()}
        covered = {s.enrollment_id for s in listed if s.status != "cancelled"}
        self._without = [e for e in enrollments.for_student(self._conn, self._ctx,
                                                            self._student_id)
                         if e.status == "active" and e.id not in covered]
        due = sum(s.due for s in listed)
        self.summary.setText(t["subscriptions.summary"].format(due=format_dzd(due)))
        self.start.setVisible(bool(self._without) and allowed(self._ctx, "subscription.manage"))
        self.list.set_rows([self._cells(s) for s in listed])

    def _cells(self, s: Subscription) -> list:
        if s.status == "cancelled":
            due = "—"
        elif s.charge_id is None:
            due = t["subscriptions.free"]
        else:
            due = format_dzd(s.due)
        return [
            item(s.group_title, item_id=s.id),
            item(period_text(s.start_date, s.end_date)),
            item(format_dzd(s.price), align=RIGHT, mono=True),
            item(due, align=RIGHT, mono=True),
            item(t[f"subscription_state.{s.state}"], kind=kind_for("subscription", s.state)),
        ]

    def selected(self) -> Subscription | None:
        subscription_id = self.list.selected_id()
        return None if subscription_id is None else self._subscriptions.get(subscription_id)

    def _update_buttons(self) -> None:
        s = self.selected()
        self.renew.setEnabled(s is not None and s.id in self._latest
                              and s.enrollment_status == "active")
        # Money paid and not refunded keeps the month (refund it first).
        self.cancel.setEnabled(s is not None and s.status != "cancelled" and not s.kept
                               and not s.in_payout)

    def _done(self, message: str, select: int | None = None) -> None:
        self.list.clear_error()
        self.refresh()
        if select is not None:
            self.list.select_id(select)
        self.changed.emit()
        toast(self, message)

    def _renew(self) -> None:
        s = self.selected()
        if s is None or not self.renew.isEnabled():
            return
        dialog = RenewDialog(self._conn, self._ctx, s, parent=self)
        if ask(dialog):
            new = subscriptions.get(self._conn, self._ctx, dialog.new_id)
            self._done(t["subscriptions.renewed"].format(
                group=new.group_title, period=period_text(new.start_date, new.end_date)),
                dialog.new_id)

    def _start(self) -> None:
        if not self._without:
            return
        dialog = StartDialog(self._conn, self._ctx, self._without, parent=self)
        if ask(dialog):
            new = subscriptions.get(self._conn, self._ctx, dialog.new_id)
            self._done(t["subscriptions.started"].format(
                group=new.group_title, period=period_text(new.start_date, new.end_date)),
                dialog.new_id)

    def _cancel(self) -> None:
        s = self.selected()
        if s is None:
            return
        if ask(CancelSubscriptionDialog(self._conn, self._ctx, s, parent=self)):
            self._done(t["subscriptions.cancelled_msg"].format(group=s.group_title), s.id)
