from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tadris.core.errors import BusinessRuleError
from tadris.i18n.fr import t
from tadris.ui.widgets.common import ErrorBanner, PageBanner, fit_to_content, primary_button
from tadris.ui.widgets.tables import ID_ROLE, fill, ruled_table, selected_id, selected_ids


def row(*widgets, stretch_last: bool = False) -> QHBoxLayout:
    """Fields side by side, sharing the width."""
    layout = QHBoxLayout()
    layout.setSpacing(12)
    for widget in widgets:
        layout.addWidget(widget, 1)
    if stretch_last:
        layout.addStretch(1)
    return layout


class FormDialog(QDialog):
    """Dialog with a title, an error banner, fields and Annuler / submit at the bottom.

    Subclasses add fields with add(), call finish() at the end of __init__, and implement
    save(): a BusinessRuleError it raises shows in the banner and keeps the dialog open.
    """

    def __init__(self, title: str, submit_text: str, width: int = 480, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedWidth(width)
        heading = QLabel(title)
        heading.setObjectName("dialogTitle")
        self.banner = ErrorBanner()
        self.cancel = QPushButton(t["action.cancel"])
        self.cancel.setAutoDefault(False)
        self.cancel.clicked.connect(self.reject)
        self.submit = primary_button(submit_text)
        self.submit.clicked.connect(self._submit)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        self.actions.addStretch()
        self.actions.addWidget(self.cancel)
        self.actions.addWidget(self.submit)
        self._fields = QVBoxLayout()
        self._fields.setSpacing(16)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        layout.addWidget(heading)
        layout.addWidget(self.banner)
        layout.addLayout(self._fields)
        layout.addSpacing(4)
        layout.addLayout(self.actions)

    def add(self, item) -> None:
        if isinstance(item, QWidget):
            self._fields.addWidget(item)
        else:
            self._fields.addLayout(item)

    def add_left_action(self, button: QPushButton) -> None:
        """A secondary action at the start of the button row (e.g. a danger "Retirer")."""
        button.setAutoDefault(False)
        self.actions.insertWidget(0, button)

    def finish(self, focus: QWidget | None = None) -> None:
        fit_to_content(self)
        if focus is not None:
            focus.setFocus()

    def save(self) -> None:
        raise NotImplementedError

    def _submit(self) -> None:
        self.banner.clear_error()
        try:
            self.save()
        except BusinessRuleError as exc:
            self.banner.show_error(exc.message)
            return
        self.accept()


class ListSection(QWidget):
    """Toolbar, ruled table with an id per row, empty state and an error banner."""

    activated = Signal(int)
    selection_changed = Signal()

    def __init__(self, headers: list[str], empty_text: str, sortable: bool = False,
                 multi: bool = False):
        """multi: several rows can be selected (Ctrl, Maj), for an action on all of them."""
        super().__init__()
        self.error = PageBanner()
        self.toolbar = QHBoxLayout()
        self.toolbar.setSpacing(8)
        self._end = QHBoxLayout()
        self._end.setSpacing(8)
        self.toolbar.addStretch()
        self.toolbar.addLayout(self._end)
        self.table = ruled_table(headers, sortable=sortable)
        if multi:
            self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        if sortable:
            # Qt starts descending; lists open sorted A to Z on their first column.
            self.table.setSortingEnabled(True)
            self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.table.itemSelectionChanged.connect(self.selection_changed.emit)
        self.table.activated.connect(self._activated)
        self.empty = QLabel(empty_text)
        self.empty.setObjectName("emptyState")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self.error)
        layout.addLayout(self.toolbar)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.empty)
        layout.addStretch(0)

    def add_button(self, button: QPushButton, end: bool = False) -> QPushButton:
        """Row actions at the start of the toolbar; the main action at its end."""
        button.setAutoDefault(False)
        if end:
            self._end.addWidget(button)
        else:
            self.toolbar.insertWidget(self.toolbar.count() - 2, button)
        return button

    def set_rows(self, rows: list[list[QTableWidgetItem]]) -> None:
        keep = self.selected_id()
        fill(self.table, rows)
        self.table.setVisible(bool(rows))
        self.empty.setVisible(not rows)
        if keep is not None:
            self.select_id(keep)
        self.selection_changed.emit()

    def selected_id(self) -> int | None:
        return selected_id(self.table)

    def selected_ids(self) -> list[int]:
        return selected_ids(self.table)

    def select_id(self, item_id: int) -> None:
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(ID_ROLE) == item_id:
                self.table.selectRow(r)
                return

    def ids(self) -> list[int]:
        return [self.table.item(r, 0).data(ID_ROLE) for r in range(self.table.rowCount())]

    def show_error(self, message: str) -> None:
        self.error.show_error(message)

    def clear_error(self) -> None:
        self.error.clear_error()

    def run(self, action, *args) -> bool:
        """Call a service action; a BusinessRuleError shows in the banner. The action's
        return value is kept in last_result."""
        self.last_result = None
        try:
            self.last_result = action(*args)
        except BusinessRuleError as exc:
            self.show_error(exc.message)
            return False
        self.clear_error()
        return True

    def _activated(self, index) -> None:
        self.activated.emit(self.table.item(index.row(), 0).data(ID_ROLE))


class HeaderCard(QFrame):
    """Top of a detail page: title, a meta row (badges, captions), a note, and actions."""

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        self.title = QLabel()
        self.title.setObjectName("pageTitle")
        self.meta = QHBoxLayout()
        self.meta.setSpacing(12)
        self.note = QLabel()
        self.note.setObjectName("caption")
        self.note.setWordWrap(True)
        self.note.hide()
        identity = QVBoxLayout()
        identity.setSpacing(6)
        identity.addWidget(self.title)
        identity.addLayout(self.meta)
        identity.addWidget(self.note)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.addLayout(identity, 1)
        layout.addLayout(self.actions)
        layout.setAlignment(self.actions, Qt.AlignmentFlag.AlignTop)

    def add_meta(self, widget: QWidget) -> QWidget:
        self.meta.addWidget(widget)
        return widget

    def add_action(self, button: QPushButton) -> QPushButton:
        button.setAutoDefault(False)
        self.actions.addWidget(button)
        return button

    def close_meta(self) -> None:
        self.meta.addStretch()

    def set_note(self, text: str) -> None:
        self.note.setText(text)
        self.note.setVisible(bool(text))


def caption(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("caption")
    return label


class ListDetailPage(QWidget):
    """A list that opens a detail view in its place; the detail's back signal returns.

    list_view needs an `opened(int)` signal and refresh(); make_detail(id) returns a widget
    with a `back` signal.
    """

    def __init__(self, list_view: QWidget, make_detail):
        super().__init__()
        self.setObjectName("page")
        self.list = list_view
        self._make_detail = make_detail
        self.detail: QWidget | None = None
        self.list.opened.connect(self.open)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.list)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

    def open(self, item_id: int) -> None:
        self._drop_detail()
        self.detail = self._make_detail(item_id)
        self.detail.back.connect(self.show_list)
        self.stack.addWidget(self.detail)
        self.stack.setCurrentWidget(self.detail)

    def show_list(self) -> None:
        self.list.refresh()
        self.stack.setCurrentWidget(self.list)
        self._drop_detail()

    def refresh(self) -> None:
        """Reload what is on screen (the page is shown again after other pages changed
        the data)."""
        if self.detail is not None:
            self.detail.refresh()
        else:
            self.list.refresh()

    def _drop_detail(self) -> None:
        if self.detail is not None:
            self.stack.removeWidget(self.detail)
            self.detail.deleteLater()
            self.detail = None


def padded(widget: QWidget, stretch: bool = False) -> QWidget:
    """Tab content with breathing room under the tab bar."""
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 16, 0, 0)
    layout.addWidget(widget)
    if stretch:
        layout.addStretch()
    return box
