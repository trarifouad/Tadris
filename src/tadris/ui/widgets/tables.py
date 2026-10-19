from PySide6.QtCore import Qt
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
    return cell


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
    return table


def fit_columns(table: QTableWidget, stretch: tuple[int, ...] = (0,)) -> None:
    """Columns fit their content, except `stretch` ones, which share the rest of the width
    (long group names stay readable next to short dates and badges)."""
    header = table.horizontalHeader()
    for column in range(table.columnCount()):
        mode = (QHeaderView.ResizeMode.Stretch if column in stretch
                else QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(column, mode)


def fill(table: QTableWidget, rows: list[list[QTableWidgetItem]]) -> None:
    """Replace the rows, keeping the user's sort column and order."""
    sorting = table.isSortingEnabled()
    table.setSortingEnabled(False)
    table.clearSelection()
    table.setRowCount(len(rows))
    for r, cells in enumerate(rows):
        for c, cell in enumerate(cells):
            table.setItem(r, c, cell)
    table.setSortingEnabled(sorting)


def selected_id(table: QTableWidget) -> int | None:
    rows = table.selectionModel().selectedRows()
    if not rows:
        return None
    return table.item(rows[0].row(), 0).data(ID_ROLE)
