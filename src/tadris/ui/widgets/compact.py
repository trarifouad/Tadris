"""Lists made small enough to share a card (the student page): a small uppercase heading,
smaller buttons, the actions on the selected row in a line under the list, and the list as
tall as its rows, up to a cap (then it scrolls)."""

from collections.abc import Callable

import shiboken6
from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QWidget,
)

from tadris.ui.widgets.forms import ListSection
from tadris.ui.widgets.tables import ROW_HEIGHT


def heading(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("cardSection")
    return label


def small(button: QPushButton) -> QPushButton:
    """A button at the size of a list's row actions (its variant colours stay)."""
    button.setObjectName("rowAction")
    return button


class _OnRows(QObject):
    """Runs `react` when the table's rows change. A child of the table: deleted with it, so
    nothing runs on a table already gone (the page's other sections outlive it briefly)."""

    def __init__(self, table: QTableWidget, react: Callable[[], None], cells: bool = False):
        """cells: also when a cell is set (rows are added before their cells are)."""
        super().__init__(table)
        self._table, self._react = table, react
        model = table.model()
        signals = [model.rowsInserted, model.rowsRemoved, model.modelReset]
        if cells:
            signals.append(model.dataChanged)
        for signal in signals:
            signal.connect(self.run)

    @Slot()
    def run(self) -> None:
        # The model still speaks while the table is being destroyed: nothing to fit then.
        if shiboken6.isValid(self._table):
            self._react()


def fit_height(table: QTableWidget, max_rows: int) -> None:
    """The table as tall as its rows, `max_rows` at most: no empty box under three rows,
    no page-long table either. Follows the rows as they change."""

    def apply() -> None:
        rows = max(min(table.rowCount(), max_rows), 1)
        header = table.horizontalHeader().sizeHint().height()
        table.setFixedHeight(header + ROW_HEIGHT * rows + 2 * table.frameWidth() + 2)

    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    _OnRows(table, apply)
    apply()


def compact_empty(label: QLabel) -> None:
    """The big centered empty box of a page becomes one plain line."""
    label.setObjectName("caption")
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    label.setWordWrap(True)


def row_actions_below(table: QTableWidget, buttons: list[QPushButton],
                      layout, index: int) -> QWidget:
    """The selected row's actions in a line under the list (inserted at `index` of
    `layout`), shown while the list has rows."""
    line = QWidget()
    row = QHBoxLayout(line)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    for button in buttons:
        row.addWidget(small(button))
    row.addStretch()
    layout.insertWidget(index, line)

    def show() -> None:
        line.setVisible(table.rowCount() > 0)

    _OnRows(table, show)
    show()
    return line


def compact_list(section: ListSection, title: str | None, max_rows: int) -> None:
    """A ListSection in a card: `title` as a small heading (None keeps what its toolbar
    starts with), the main action small at the end, the row actions under the list."""
    layout = section.layout()
    layout.setSpacing(8)
    row_buttons = []
    for i in reversed(range(section.toolbar.count())):
        widget = section.toolbar.itemAt(i).widget()
        if isinstance(widget, QPushButton):
            section.toolbar.removeWidget(widget)
            row_buttons.insert(0, widget)
    for i in range(section._end.count()):
        widget = section._end.itemAt(i).widget()
        if isinstance(widget, QPushButton):
            small(widget)
    if title is not None:
        section.toolbar.insertWidget(0, heading(title))
    compact_empty(section.empty)
    fit_height(section.table, max_rows)
    if row_buttons:
        section.row_actions = row_actions_below(
            section.table, row_buttons, layout, layout.indexOf(section.table) + 1)


class Segments(QFrame):
    """A few views of one card, one at a time (« À payer », « Reçus »...)."""

    changed = Signal(int)

    def __init__(self, labels: list[str]):
        super().__init__()
        self.setObjectName("segments")
        line = QHBoxLayout(self)
        line.setContentsMargins(3, 3, 3, 3)
        line.setSpacing(2)
        self.group = QButtonGroup(self)
        self.buttons: list[QPushButton] = []
        for i, text in enumerate(labels):
            button = QPushButton(text)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setAutoDefault(False)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _on, index=i: self.changed.emit(index))
            self.group.addButton(button)
            self.buttons.append(button)
            line.addWidget(button)
        self.buttons[0].setChecked(True)

    def select(self, index: int) -> None:
        self.buttons[index].setChecked(True)
        self.changed.emit(index)


def follow_current(stack: QStackedWidget) -> None:
    """The stack as tall as the view it shows, not as its tallest one."""

    def apply(index: int) -> None:
        for i in range(stack.count()):
            vertical = (QSizePolicy.Policy.Preferred if i == index
                        else QSizePolicy.Policy.Ignored)
            stack.widget(i).setSizePolicy(QSizePolicy.Policy.Preferred, vertical)
        stack.updateGeometry()

    stack.currentChanged.connect(apply)
    apply(stack.currentIndex())


def share_width(card: QWidget) -> None:
    """The row's stretch factors decide the card's width (not what its tables would like),
    never below what its buttons and labels need."""
    card.setMinimumWidth(card.minimumSizeHint().width())
    card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)


def hide_empty_columns(table: QTableWidget, columns: tuple[int, ...]) -> None:
    """Those columns only when a row has something in them (a remark, a date left)."""

    def apply() -> None:
        for column in columns:
            empty = all(table.item(r, column) is None or not table.item(r, column).text()
                        for r in range(table.rowCount()))
            table.setColumnHidden(column, empty)

    _OnRows(table, apply, cells=True)
    apply()
