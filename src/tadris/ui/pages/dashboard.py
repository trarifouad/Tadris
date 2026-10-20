"""Tableau de bord: four stat cards, then today's sessions and the months ending on the left,
the largest debts and the groups' fill on the right. A double-click on a student opens their
page; « Voir tout » opens the page that handles the list.

It is read at a glance, so the page never scrolls and no list scrolls either: each list
shows as many rows as the window leaves room for (the two panels of a column share it) and
« Voir les N » says how many there are when some are left out."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tadris.core.context import UserContext
from tadris.core.dates import display_date
from tadris.core.money import format_dzd
from tadris.core.percent import format_percent
from tadris.core.permissions import allowed
from tadris.domain.models import Dashboard
from tadris.i18n.fr import t
from tadris.services import reports
from tadris.ui.subscription_dialogs import period_text
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets.forms import ListSection, caption
from tadris.ui.widgets.tables import CENTER, RIGHT, fit_columns, item

ROW_HEIGHT = 34  # a little tighter than the list pages' 40
SPACING = 12
MIN_ROWS = 1  # a list with rows always shows at least this many


class StatCard(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("card")
        self.title = caption(title)
        self.value = QLabel()
        self.value.setObjectName("bigNumber")
        self.detail = caption()
        self.detail.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(0)
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.detail)
        layout.addStretch()

    def set(self, value: str, detail: str) -> None:
        self.value.setText(value)
        self.detail.setText(detail)


class Panel(QFrame):
    """A titled list on the dashboard: as many rows as its share of the window, and « Voir
    tout » (« Voir les N » when rows are left out) opening the page with the whole list.
    As tall as the rows it shows: no empty box, no scroll bar."""

    def __init__(self, title: str, headers: list[str], empty: str, page: str | None,
                 navigate: Signal):
        super().__init__()
        self.setObjectName("card")
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        self.list = ListSection(headers, empty)
        self.list.layout().setSpacing(8)
        self.list.toolbar.insertWidget(0, heading)
        table = self.list.table
        table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Ask for the rows' height (not Qt's default), so the layout gives it when it can.
        table.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self.list.empty.setObjectName("caption")  # one plain line, not an empty box
        self.list.empty.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.more: QPushButton | None = None
        if page is not None:
            self.more = QPushButton(t["dashboard.see_all"])
            self.more.setProperty("variant", "ghost")
            self.more.clicked.connect(lambda: navigate.emit(page))
            self.list.add_button(self.more, end=True)
        self._rows: list = []
        self._total = 0
        self._stale = True  # new rows not on the table yet
        self.shown = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 12)
        layout.addWidget(self.list)

    def set_rows(self, rows: list, total: int | None = None) -> None:
        """total: how many there are when `rows` is already a top few (the debtors). Shows
        them all until the page says how many fit (show_rows())."""
        self._rows = rows
        self._total = len(rows) if total is None else total
        self._stale = True
        self.show_rows(len(rows))

    @property
    def count(self) -> int:
        return len(self._rows)

    def _header(self) -> int:
        return self.list.table.horizontalHeader().sizeHint().height() + 2

    def frame_height(self) -> int:
        """The panel's height without its rows: margins, title row, table header (or the
        empty line)."""
        margins = self.layout().contentsMargins()
        fixed = (margins.top() + margins.bottom() + self.list.toolbar.sizeHint().height()
                 + self.list.layout().spacing())
        if not self._rows:
            return fixed + self.list.empty.sizeHint().height()
        return fixed + self._header()

    def show_rows(self, rows: int) -> None:
        rows = min(rows, len(self._rows))
        if rows == self.shown and not self._stale:
            return  # a resize that changes nothing here: the table is not rebuilt
        self._stale = False
        self.shown = rows
        # Copies: the table deletes the cells it drops, and the panel shows them again later.
        self.list.set_rows([[cell.clone() for cell in row] for row in self._rows[:self.shown]])
        # Exactly the rows shown, but no minimum beyond one row: a fixed height would hold the
        # window up when it gets smaller, before fit_rows() takes rows away.
        table = self.list.table
        table.setMinimumHeight(self._header() + ROW_HEIGHT * min(self.shown, MIN_ROWS))
        table.setMaximumHeight(self._header() + ROW_HEIGHT * self.shown)
        if self.more is not None:
            self.more.setText(t["dashboard.see_count"].format(count=self._total)
                              if self._total > self.shown else t["dashboard.see_all"])


def share_rows(capacity: int, counts: list[int]) -> list[int]:
    """Split `capacity` rows between lists that have `counts` rows: an equal share each, and
    what a short list does not need goes to the others (a list of 3 next to a list of 9 in
    10 rows: 3 and 7). Every list with rows gets MIN_ROWS, even past the capacity."""
    shown = [0] * len(counts)
    left = capacity
    waiting = [i for i, count in enumerate(counts) if count > 0]
    while left > 0 and waiting:
        share = max(left // len(waiting), 1)
        for i in list(waiting):
            given = min(share, counts[i] - shown[i], left)
            shown[i] += given
            left -= given
            if shown[i] == counts[i]:
                waiting.remove(i)
            if left == 0:
                break
    return [max(rows, min(count, MIN_ROWS)) for rows, count in zip(shown, counts, strict=True)]


class DashboardPage(QWidget):
    open_student = Signal(int)
    navigate = Signal(str)

    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self.setObjectName("page")
        self._conn = conn
        self._ctx = ctx
        title = QLabel(t["dashboard.title"])
        title.setObjectName("pageTitle")
        self.day = caption()
        heading = QHBoxLayout()
        heading.setSpacing(12)
        heading.addWidget(title)
        heading.addWidget(self.day, 0, Qt.AlignmentFlag.AlignBottom)
        heading.addStretch()

        self.sessions_card = StatCard(t["dashboard.card.sessions"])
        self.renew_card = StatCard(t["dashboard.card.renew"])
        self.debt_card = StatCard(t["dashboard.card.debt"])
        self.money_card = StatCard(t["dashboard.card.money"])
        self.fill_card = StatCard(t["dashboard.card.fill"])
        cards = QHBoxLayout()
        cards.setSpacing(12)
        for card in (self.sessions_card, self.renew_card, self.debt_card):
            cards.addWidget(card, 1)
        self.money = allowed(ctx, "report.finance")
        cards.addWidget(self.money_card if self.money else self.fill_card, 1)

        self.sessions = Panel(t["dashboard.sessions"], [
            t["dashboard.col.time"], t["dashboard.col.group"], t["dashboard.col.room"],
            t["dashboard.col.teacher"], t["dashboard.col.status"]],
            t["dashboard.sessions_empty"], "attendance", self.navigate)
        fit_columns(self.sessions.list.table, stretch=(1,))
        self.ending = Panel(t["dashboard.ending"], [
            t["dashboard.col.student"], t["dashboard.col.group"], t["dashboard.col.period"],
            t["dashboard.col.due"]], t["dashboard.ending_empty"], "subscriptions", self.navigate)
        fit_columns(self.ending.list.table, stretch=(0, 1))
        self.debtors = Panel(t["dashboard.debtors"], [
            t["dashboard.col.student"], t["dashboard.col.owed"], t["dashboard.col.since"]],
            t["dashboard.debtors_empty"], "payments", self.navigate)
        fit_columns(self.debtors.list.table, stretch=(0,))
        self.groups = Panel(t["dashboard.groups"], [
            t["dashboard.col.group"], t["dashboard.col.enrolled"], t["dashboard.col.seats"],
            t["dashboard.col.fill"]], t["dashboard.groups_empty"], "groups", self.navigate)
        fit_columns(self.groups.list.table, stretch=(0,))
        for panel in (self.ending, self.debtors):
            panel.list.activated.connect(self.open_student.emit)

        # Two columns of panels, each panel as tall as its rows (top-aligned, no stretch).
        self.columns = ((self.sessions, self.ending), (self.debtors, self.groups))
        left, right = QVBoxLayout(), QVBoxLayout()
        for column, panels in zip((left, right), self.columns, strict=True):
            column.setSpacing(SPACING)
            for panel in panels:
                column.addWidget(panel)
            column.addStretch()
        columns = QHBoxLayout()
        columns.setSpacing(12)
        columns.addLayout(left, 3)
        columns.addLayout(right, 2)

        self.heading, self.cards = heading, cards
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(SPACING)
        layout.addLayout(heading)
        layout.addLayout(cards)
        layout.addLayout(columns, 1)
        self.refresh()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.fit_rows()

    def showEvent(self, event) -> None:
        # The first resize arrives while the page is being shown, before it counts as
        # visible: fit again once it is.
        super().showEvent(event)
        self.fit_rows()

    def lists_height(self) -> int:
        """What the two columns of lists have, under the title and the cards."""
        margins = self.layout().contentsMargins()
        return (self.height() - margins.top() - margins.bottom() - 2 * SPACING
                - self.heading.sizeHint().height() - self.cards.sizeHint().height())

    def fit_rows(self) -> None:
        """As many rows in each list as the window leaves room for. Not before the page is
        on screen: until then its size is Qt's default, not the window's."""
        if not self.isVisible():
            return
        room = self.lists_height()
        for panels in self.columns:
            frames = sum(panel.frame_height() for panel in panels) + SPACING * (len(panels) - 1)
            capacity = max((room - frames) // ROW_HEIGHT, 0)
            for panel, rows in zip(panels, share_rows(capacity, [p.count for p in panels]),
                                   strict=True):
                panel.show_rows(rows)

    def refresh(self) -> None:
        self.show_board(reports.dashboard(self._conn, self._ctx))

    def show_board(self, board: Dashboard) -> None:
        self.day.setText(t["dashboard.today"].format(date=display_date(board.today)))
        left = len(board.sessions_left)
        self.sessions_card.set(str(board.sessions_held),
                               t["dashboard.card.sessions_left"].format(count=left))
        self.renew_card.set(str(len(board.ending) + board.lapsed),
                            t["dashboard.card.renew_detail"].format(
                                ending=len(board.ending), lapsed=board.lapsed))
        self.debt_card.set(format_dzd(board.debt_total),
                           t["dashboard.card.debt_detail"].format(count=board.debtors))
        if board.collected is not None:
            self.money_card.set(format_dzd(board.collected), t["dashboard.card.money_detail"]
                                .format(charged=format_dzd(board.charged),
                                        settled=format_dzd(board.settled),
                                        refunded=format_dzd(board.refunded)))
        fill = board.enrolled * 10000 // board.seats if board.seats else 0
        self.fill_card.set(format_percent(fill // 100 * 100), t["dashboard.card.fill_detail"].format(
            enrolled=board.enrolled, seats=board.seats))

        self.sessions.set_rows([[
            item(f"{s.start_time}–{s.end_time}", s.start_time, item_id=s.id, align=CENTER,
                 mono=True),
            item(s.group_title), item(s.room), item(s.teacher),
            item(t[f"session_status.{s.status}"], kind=kind_for("session", s.status)),
        ] for s in board.sessions])
        self.ending.set_rows([[
            item(m.student_name, item_id=m.student_id), item(m.group_title),
            item(period_text(m.start_date, m.end_date)),
            item(format_dzd(m.due), align=RIGHT, mono=True,
                 tone="danger" if m.due else None),
        ] for m in board.ending])
        self.debtors.set_rows([[
            item(d.student_name, item_id=d.student_id),
            item(format_dzd(d.owed_now), align=RIGHT, mono=True, tone="danger"),
            item(t["dashboard.days"].format(days=d.days_overdue), align=RIGHT),
        ] for d in board.top_debtors], total=board.debtors)
        self.groups.set_rows([[
            item(g.title, item_id=g.group_id),
            item(str(g.enrolled), align=RIGHT, mono=True),
            item(str(g.seats), align=RIGHT, mono=True),
            item(format_percent(g.rate_bp // 100 * 100), align=RIGHT, mono=True,
                 tone="success" if g.rate_bp >= 10000 else None),
        ] for g in board.groups])
        self.fit_rows()

