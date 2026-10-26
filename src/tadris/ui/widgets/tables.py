from collections.abc import Callable
from contextlib import contextmanager

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from tadris.ui.theme import tokens
from tadris.ui.theme.delegates import KIND_ROLE, BadgeDelegate

ROW_HEIGHT = 40
SORT_ROLE = Qt.ItemDataRole.UserRole
ID_ROLE = Qt.ItemDataRole.UserRole + 1

LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
CENTER = Qt.AlignmentFlag.AlignCenter
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


class Item(QTableWidgetItem):
    """Read-only cell that sorts by SORT_ROLE when set (dates, folded names), else by text."""

    def __lt__(self, other):
        mine, theirs = self.data(SORT_ROLE), other.data(SORT_ROLE)
        if mine is not None and theirs is not None:
            return mine < theirs
        return super().__lt__(other)


def item(text: str, sort_key=None, align=LEFT, mono: bool = False, kind: str | None = None,
         item_id: int | None = None, tone: str | None = None) -> Item:
    """kind paints a status pill; tone colors the text with a token (e.g. 'danger' for a
    late amount, 'info' for a credit)."""
    cell = Item(text)
    cell.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    cell.setTextAlignment(align)
    if sort_key is not None:
        cell.setData(SORT_ROLE, sort_key)
    if mono:
        font = QFont("IBM Plex Mono")
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.Medium)
        cell.setFont(font)
    if kind is not None:
        cell.setData(KIND_ROLE, kind)
    if tone is not None:
        cell.setForeground(QColor(tokens()[tone]))
    if item_id is not None:
        cell.setData(ID_ROLE, item_id)
    if align == LEFT and kind is None and text:
        cell.setToolTip(text)  # the whole text when the column cuts it short
    return cell


def align_headers(table: QTableWidget) -> None:
    """Each column's header lines up with its cells: a centered date, a right-aligned
    amount. The first row's cell decides; a table without rows keeps its headers."""
    for column in range(table.columnCount()):
        cell, header = table.item(0, column), table.horizontalHeaderItem(column)
        if cell is None or header is None:
            continue
        horizontal = Qt.AlignmentFlag(cell.textAlignment()) & Qt.AlignmentFlag.AlignHorizontal_Mask
        header.setTextAlignment(horizontal | Qt.AlignmentFlag.AlignVCenter)


def _align_headers_soon(table: QTableWidget) -> None:
    """Once the cells being set are all in: a table filled cell by cell is aligned once."""
    if table.property("aligning"):
        return
    table.setProperty("aligning", True)

    def run() -> None:
        table.setProperty("aligning", False)
        align_headers(table)

    QTimer.singleShot(0, table, run)  # dropped if the table is deleted first


def ruled_table(headers: list[str], sortable: bool = False) -> QTableWidget:
    """Read-only, row-selecting table with Seyès rules and badge cells."""
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setItemDelegate(BadgeDelegate(tokens(), table))
    table.setShowGrid(False)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setWordWrap(False)
    table.verticalHeader().hide()
    table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
    header = table.horizontalHeader()
    header.setDefaultAlignment(LEFT)
    header.setHighlightSections(False)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    header.setSortIndicatorShown(sortable)
    header.setSectionsClickable(sortable)
    table.model().dataChanged.connect(lambda *_args: _align_headers_soon(table))
    return table


def fit_columns(table: QTableWidget, stretch: tuple[int, ...] = (0,)) -> None:
    """Columns fit their content, except `stretch` ones, which share the rest of the width
    (long group names stay readable next to short dates and badges)."""
    header = table.horizontalHeader()
    for column in range(table.columnCount()):
        mode = (QHeaderView.ResizeMode.Stretch if column in stretch
                else QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(column, mode)


@contextmanager
def frozen_columns(table: QTableWidget):
    """While cells go in, columns that fit their content are frozen and the table is not
    redrawn: otherwise Qt measures the whole column again for every cell, and refilling a
    table that already has rows takes seconds (64 rows x 10 columns: 3.5 s, the window
    « not responding »). They are measured once at the end."""
    header = table.horizontalHeader()
    fitted = [c for c in range(table.columnCount())
              if header.sectionResizeMode(c) == QHeaderView.ResizeMode.ResizeToContents]
    for c in fitted:
        header.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
    table.setUpdatesEnabled(False)
    try:
        yield
    finally:
        for c in fitted:
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        table.setUpdatesEnabled(True)


def fill(table: QTableWidget, rows: list[list[QTableWidgetItem]]) -> None:
    """Replace the rows, keeping the user's sort column and order."""
    sorting = table.isSortingEnabled()
    table.setSortingEnabled(False)
    table.clearSelection()
    with frozen_columns(table):
        table.setRowCount(0)  # new cells go into empty rows, never replace old ones
        table.setRowCount(len(rows))
        for r, cells in enumerate(rows):
            for c, cell in enumerate(cells):
                table.setItem(r, c, cell)
    table.setSortingEnabled(sorting)
    align_headers(table)


def selected_id(table: QTableWidget) -> int | None:
    rows = table.selectionModel().selectedRows()
    if not rows:
        return None
    return table.item(rows[0].row(), 0).data(ID_ROLE)


def selected_ids(table: QTableWidget) -> list[int]:
    """Every selected row's id, top to bottom (a table that selects several rows)."""
    rows = sorted(index.row() for index in table.selectionModel().selectedRows())
    return [table.item(r, 0).data(ID_ROLE) for r in rows]


PAGE_SIZE = 100  # rows a long list shows first, then this many more as it is scrolled
MORE_AHEAD_ROWS = 10  # the next page is loaded this many rows before the end


class MoreOnScroll(QObject):
    """A long list shows its first page; the next one is loaded once the table is scrolled
    near its end (or does not fill its height yet). load_more() adds rows and returns
    whether more are left. It runs once the current event is over: the scroll range also
    changes while a page is going in, and a page must never land in another."""

    def __init__(self, table: QTableWidget, load_more: Callable[[], bool]):
        super().__init__(table)
        self._table = table
        self._load_more = load_more
        self.more_left = False
        self._soon = QTimer(self)
        self._soon.setSingleShot(True)
        self._soon.setInterval(0)
        self._soon.timeout.connect(self._check)
        bar = table.verticalScrollBar()
        bar.valueChanged.connect(lambda _v: self._soon.start())
        bar.rangeChanged.connect(lambda _a, _b: self._soon.start())

    def reset(self, more_left: bool) -> None:
        """A new first page is shown: are there more rows after it?"""
        self.more_left = more_left
        self._soon.start()

    def rows_below(self) -> float:
        """Rows under the last one on screen (the scroll bar counts rows, or pixels in
        per-pixel mode)."""
        table = self._table
        row = table.verticalHeader().defaultSectionSize()
        top = table.verticalScrollBar().value()
        if table.verticalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerPixel:
            top /= row
        return table.rowCount() - top - table.viewport().height() / row

    def _check(self) -> None:
        if not self.more_left or not self._table.isVisible():  # hidden: no layout yet
            return
        if self.rows_below() > MORE_AHEAD_ROWS:
            return
        self.more_left = self._load_more()
        if self.more_left:
            self._soon.start()  # still short of the end (a tall window): one more
