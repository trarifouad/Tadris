"""Dialogs of the student's Abonnements tab: renew a month, start one again, cancel one."""

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit, QWidget

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.money import format_dzd
from tadris.domain.models import Enrollment, Subscription
from tadris.i18n.fr import t
from tadris.services import groups, subscriptions
from tadris.ui.payment_dialogs import debt_banner
from tadris.ui.setup_dialogs import required_date
from tadris.ui.widgets.common import labeled
from tadris.ui.widgets.date_edit import DateLineEdit
from tadris.ui.widgets.forms import FormDialog, caption, row
from tadris.ui.widgets.inputs import id_combo
from tadris.ui.widgets.tables import (
    ID_ROLE,
    RIGHT,
    ROW_HEIGHT,
    fill,
    fit_columns,
    item,
    ruled_table,
)


def period_text(start: str, end: str) -> str:
    return t["subscriptions.period"].format(start=dates.display_date(start),
                                            end=dates.display_date(end))


class _MonthDialog(FormDialog):
    """A start date and a preview of the month it makes, at the group's current price."""

    def __init__(self, conn, ctx: UserContext, title: str, submit: str, parent=None):
        super().__init__(title, submit, width=520, parent=parent)
        self._conn, self._ctx = conn, ctx
        self.date = DateLineEdit()
        self.preview = caption()
        self.preview.setWordWrap(True)
        self.date.textChanged.connect(lambda _text: self._update_preview())

    def _price(self) -> int:
        raise NotImplementedError

    def _update_preview(self) -> None:
        start = self.date.value()
        if start is None:
            self.preview.setText("")
            return
        end = dates.add_one_month(start)
        self.preview.setText(t["renew_dialog.preview"].format(
            period=period_text(dates.iso(start), dates.iso(end)), price=format_dzd(self._price())))


class RenewDialog(_MonthDialog):
    def __init__(self, conn, ctx: UserContext, subscription: Subscription, parent=None):
        super().__init__(conn, ctx, t["renew_dialog.title"], t["renew_dialog.submit"], parent)
        self._subscription = subscription
        self._group_price = groups.get(conn, ctx, subscription.group_id).price
        self.new_id: int | None = None
        previous_end = date.fromisoformat(subscription.end_date)
        self.date.minimum = previous_end
        banner = debt_banner(conn, ctx, subscription.student_id)
        if banner is not None:
            self.add(banner)
        note = caption(t["renew_dialog.caption"].format(
            group=subscription.group_title,
            period=period_text(subscription.start_date, subscription.end_date)))
        note.setWordWrap(True)
        self.add(note)
        self.add(row(labeled(t["renew_dialog.start"], self.date, required=True), QWidget()))
        self.add(self.preview)
        self.date.set_value(previous_end)
        self.finish(self.date)

    def _price(self) -> int:
        return self._group_price

    def save(self) -> None:
        self.new_id = subscriptions.renew(self._conn, self._ctx, self._subscription.id,
                                          required_date(self.date))


class StartDialog(_MonthDialog):
    """A month for a group the student is in without any subscription left."""

    def __init__(self, conn, ctx: UserContext, enrollments: list[Enrollment], parent=None):
        super().__init__(conn, ctx, t["start_dialog.title"], t["start_dialog.submit"], parent)
        self._enrollments = {e.id: e for e in enrollments}
        self.new_id: int | None = None
        self.enrollment = id_combo([(e.group_title, e.id) for e in enrollments])
        self.enrollment.currentIndexChanged.connect(lambda _i: self._picked())
        note = caption(t["start_dialog.caption"])
        note.setWordWrap(True)
        self.add(note)
        self.add(row(labeled(t["start_dialog.group"], self.enrollment, required=True),
                     labeled(t["renew_dialog.start"], self.date, required=True)))
        self.add(self.preview)
        self._picked()
        self.finish(self.date)

    def _selected(self) -> Enrollment:
        return self._enrollments[self.enrollment.currentData()]

    def _picked(self) -> None:
        e = self._selected()
        self.date.minimum = date.fromisoformat(e.enrolled_on)
        self.date.set_value(max(dates.today(), self.date.minimum))
        self._update_preview()

    def _price(self) -> int:
        return groups.get(self._conn, self._ctx, self._selected().group_id).price

    def save(self) -> None:
        self.new_id = subscriptions.start(self._conn, self._ctx, self._selected().id,
                                          required_date(self.date))


class CancelSubscriptionDialog(FormDialog):
    """Director only: the reason goes to the audit log; the month's charge is cancelled."""

    def __init__(self, conn, ctx: UserContext, subscription: Subscription, parent=None):
        super().__init__(t["cancel_subscription_dialog.title"],
                         t["cancel_subscription_dialog.submit"], parent=parent)
        self._conn, self._ctx, self._subscription = conn, ctx, subscription
        self.submit.setProperty("variant", "danger")
        self.reason = QLineEdit()
        self.reason.setPlaceholderText(t["cancel_registration_dialog.placeholder"])
        note = caption(t["cancel_subscription_dialog.caption"].format(
            group=subscription.group_title,
            period=period_text(subscription.start_date, subscription.end_date),
            price=format_dzd(subscription.price).replace(" ", "\u00a0")))  # never split
        note.setWordWrap(True)
        self.add(note)
        self.add(labeled(t["cancel_registration_dialog.reason"], self.reason, required=True))
        self.finish(self.reason)

    def save(self) -> None:
        subscriptions.cancel(self._conn, self._ctx, self._subscription.id, self.reason.text())


class BulkRenewDialog(FormDialog):
    """Renew several months at once from their end dates: every row starts ticked; untick the
    students who stop. All or nothing."""

    VISIBLE_ROWS = 8

    def __init__(self, conn, ctx: UserContext, months: list[Subscription], title: str,
                 parent=None):
        super().__init__(title, t["bulk_renew.submit"], width=1040, parent=parent)
        self._conn, self._ctx = conn, ctx
        self.renewed: list[int] = []
        prices: dict[int, int] = {}
        for m in months:
            if m.group_id not in prices:
                prices[m.group_id] = groups.get(conn, ctx, m.group_id).price
        self._prices = {m.id: prices[m.group_id] for m in months}
        note = caption(t["bulk_renew.caption"])
        note.setWordWrap(True)
        self.table = ruled_table([t["bulk_renew.col.student"], t["bulk_renew.col.group"],
                                  t["bulk_renew.col.current"], t["bulk_renew.col.next"],
                                  t["bulk_renew.col.price"]])
        fill(self.table, [self._cells(m) for m in months])
        fit_columns(self.table, stretch=(0, 1))
        header = self.table.horizontalHeader().height() or ROW_HEIGHT
        self.table.setFixedHeight(header + 2 + ROW_HEIGHT * max(min(len(months),
                                                                    self.VISIBLE_ROWS), 1))
        self.table.itemChanged.connect(lambda _item: self._update_total())
        self.total = caption()
        self.add(note)
        self.add(self.table)
        self.add(self.total)
        self._update_total()
        self.finish(self.table)

    def _cells(self, m: Subscription) -> list:
        end = date.fromisoformat(m.end_date)
        name = item(m.student_name, item_id=m.id)
        name.setFlags(name.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        name.setCheckState(Qt.CheckState.Checked)
        return [
            name,
            item(m.group_title),
            item(period_text(m.start_date, m.end_date)),
            item(period_text(m.end_date, dates.iso(dates.add_one_month(end)))),
            item(format_dzd(self._prices[m.id]), align=RIGHT, mono=True),
        ]

    def checked(self) -> list[int]:
        return [self.table.item(r, 0).data(ID_ROLE) for r in range(self.table.rowCount())
                if self.table.item(r, 0).checkState() == Qt.CheckState.Checked]

    def _update_total(self) -> None:
        ids = self.checked()
        self.total.setText(t["bulk_renew.total"].format(
            count=len(ids), total=format_dzd(sum(self._prices[i] for i in ids))))
        self.submit.setEnabled(bool(ids))

    def save(self) -> None:
        self.renewed = subscriptions.renew_many(self._conn, self._ctx, self.checked())
