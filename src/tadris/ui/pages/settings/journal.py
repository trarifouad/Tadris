"""Paramètres → Données → « Voir le journal »: what people did, latest first, in plain French
(services/journal.py). Filters: the dates (the last week at first) and the user. A page at a
time, the next one as the list is scrolled. Read only."""

from datetime import timedelta

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QVBoxLayout, QWidget

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError
from tadris.i18n.fr import t
from tadris.services import journal
from tadris.services.journal import Entry
from tadris.ui.pages.system_tabs import display_stamp
from tadris.ui.widgets.common import PageBanner, labeled
from tadris.ui.widgets.date_edit import DateLineEdit
from tadris.ui.widgets.forms import caption
from tadris.ui.widgets.inputs import fill_combo
from tadris.ui.widgets.tables import (
    MoreOnScroll,
    fill,
    fit_columns,
    frozen_columns,
    item,
    ruled_table,
)

FIRST_DAYS = 7  # the Journal opens on the last week


class JournalView(QWidget):
    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn, self._ctx = conn, ctx
        self.entries: list[Entry] = []
        self._total = 0
        self._filters: tuple | None = None  # (first, last, user_id) of the list shown

        today = dates.today()
        self.first = DateLineEdit(maximum=today)
        self.first.set_value(today - timedelta(days=FIRST_DAYS))
        self.last = DateLineEdit(maximum=today)
        self.last.set_value(today)
        self.user = QComboBox()
        fill_combo(self.user, [(t["journal.all_users"], None)]
                   + [(name, user_id) for user_id, name in journal.users(conn, ctx)])
        filters = QHBoxLayout()
        filters.setSpacing(12)
        for text, widget in ((t["journal.from"], self.first), (t["journal.to"], self.last),
                             (t["journal.user"], self.user)):
            filters.addWidget(labeled(text, widget))
        filters.addStretch()

        self.banner = PageBanner()
        self.table = ruled_table([t["journal.col.when"], t["journal.col.user"],
                                  t["journal.col.action"], t["journal.col.item"],
                                  t["journal.col.detail"]])
        # The detail takes the width left; its tooltip shows it whole.
        fit_columns(self.table, stretch=(4,))
        self.empty = caption(t["journal.empty"])
        self.count = caption()
        self.pager = MoreOnScroll(self.table, self._load_more)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(filters)
        layout.addWidget(self.banner)
        layout.addWidget(self.empty)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.count)

        for field in (self.first, self.last):
            field.textChanged.connect(lambda _text: self._dates_changed())
        self.user.currentIndexChanged.connect(lambda _index: self.refresh())
        self.refresh()

    def _dates_changed(self) -> None:
        if self.first.value() is not None and self.last.value() is not None:
            self.refresh()  # not while a date is half typed

    def refresh(self) -> None:
        """The latest page of what the filters match; the next ones come as the list is
        scrolled."""
        self.banner.clear_error()
        first, last, user_id = self.first.value(), self.last.value(), self.user.currentData()
        if first is None or last is None:
            return
        try:
            self._total = journal.count(self._conn, self._ctx, first, last, user_id)
            self.entries = journal.entries(self._conn, self._ctx, first, last, user_id)
        except BusinessRuleError as exc:
            self.banner.show_error(exc.message)
            return
        self._filters = (first, last, user_id)
        fill(self.table, [self._cells(entry) for entry in self.entries])
        self._show_count()
        self.pager.reset(len(self.entries) < self._total)

    def _load_more(self) -> bool:
        """The next page, older than the last entry shown. True while more are left."""
        first, last, user_id = self._filters
        page = journal.entries(self._conn, self._ctx, first, last, user_id,
                               before_id=self.entries[-1].id)
        if not page:
            self._total = len(self.entries)  # nothing more after all
        start = self.table.rowCount()
        with frozen_columns(self.table):
            self.table.setRowCount(start + len(page))
            for r, entry in enumerate(page, start):
                for c, cell in enumerate(self._cells(entry)):
                    self.table.setItem(r, c, cell)
        self.entries += page
        self._show_count()
        return len(self.entries) < self._total

    @staticmethod
    def _cells(entry: Entry) -> list:
        return [item(display_stamp(entry.created_at), sort_key=entry.created_at),
                item(entry.user), item(entry.action), item(entry.item), item(entry.detail)]

    def _show_count(self) -> None:
        shown = len(self.entries)
        key = "journal.shown_all" if shown >= self._total else "journal.shown_part"
        self.count.setText(t[key].format(shown=shown, total=self._total))
        self.empty.setVisible(shown == 0)
        self.table.setVisible(shown > 0)
        self.count.setVisible(shown > 0)
