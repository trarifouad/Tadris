"""Small input widgets and the readers that turn their text into domain values."""

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from tadris.core.dates import parse_time
from tadris.core.money import format_dzd, parse_dzd
from tadris.core.percent import format_percent, parse_percent
from tadris.i18n.fr import t
from tadris.ui.theme import icon
from tadris.ui.widgets.common import labeled, variant_button

STEP_MINUTES = 15
# Saturday first, as the Algerian week (weekday numbers stay 1 = Monday ... 7 = Sunday).
WEEK_ORDER = (6, 7, 1, 2, 3, 4, 5)


def money_edit(amount: int | None = None) -> QLineEdit:
    edit = QLineEdit("" if amount is None else format_dzd(amount))
    edit.setProperty("money", True)
    edit.setPlaceholderText("3 000 DA")
    return edit


def read_money(edit: QLineEdit, empty: int | None = None) -> int:
    """The amount typed; `empty` (when given) is the value of a blank field."""
    if empty is not None and not edit.text().strip():
        return empty
    return parse_dzd(edit.text())


def percent_edit(bp: int | None = None) -> QLineEdit:
    edit = QLineEdit("" if bp is None else format_percent(bp))
    edit.setProperty("money", True)
    edit.setPlaceholderText("60 %")
    return edit


def read_percent(edit: QLineEdit) -> int:
    return parse_percent(edit.text())


def count_spin(value: int = 12, maximum: int = 500) -> QSpinBox:
    spin = QSpinBox()  # typed, or mouse wheel and arrow keys; the QSS hides the arrows
    spin.lineEdit().setTextMargins(10, 0, 10, 0)  # QSS padding does not reach the inner field
    spin.setRange(1, maximum)
    spin.setValue(value)
    return spin


def time_combo(value: str = "", first: str = "06:00", last: str = "23:45") -> QComboBox:
    """Quarter hours from `first` to `last` to pick from; any other time can be typed
    (17h10, 1710...)."""
    combo = QComboBox()
    combo.setEditable(True)
    start, end = _minutes(first), _minutes(last)
    for minute in range(start - start % STEP_MINUTES, end + 1, STEP_MINUTES):
        if minute >= start:
            combo.addItem(f"{minute // 60:02d}:{minute % 60:02d}")
    if value:
        combo.setCurrentText(value)
    return combo


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def read_time(combo: QComboBox) -> str:
    return parse_time(combo.currentText())


def id_combo(items: list[tuple[str, int | None]], selected: int | None = None) -> QComboBox:
    """A combo whose items carry ids (None for an "all" or empty choice)."""
    combo = QComboBox()
    fill_combo(combo, items, selected)
    return combo


def fill_combo(combo: QComboBox, items: list[tuple[str, int | None]],
               selected: int | None = None) -> None:
    """Replace the items and restore a selection without emitting change signals: pages
    refill their filters inside refresh(), which those signals would call again."""
    combo.blockSignals(True)
    try:
        combo.clear()
        for label, value in items:
            combo.addItem(label, value)
        select_data(combo, selected)
    finally:
        combo.blockSignals(False)


def select_data(combo: QComboBox, value) -> None:
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)


class FilterButton(QPushButton):
    """« Filtres » button opening a panel of filter combos under it. The text counts the
    combos moved off their default: « Filtres (2) ».

    The panel is a Qt.Popup frame, not a QMenu: a combo's own list inside a QMenu closes
    the menu on click."""

    PANEL_WIDTH = 280

    def __init__(self):
        super().__init__()
        self.setAutoDefault(False)
        self.setIconSize(QSize(22, 16))  # 16 px drawn, 6 px before the label
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._filters: list[tuple[QComboBox, object]] = []
        self.panel = QFrame(self, Qt.WindowType.Popup)
        self.panel.setObjectName("filterPanel")
        self.panel.setFixedWidth(self.PANEL_WIDTH)
        self._rows = QVBoxLayout(self.panel)
        self._rows.setContentsMargins(16, 16, 16, 12)
        self._rows.setSpacing(12)
        self.reset = variant_button(t["filters.reset"], "ghost")
        self.reset.clicked.connect(self.reset_filters)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(self.reset)
        self._rows.addLayout(footer)
        self.clicked.connect(self.show_panel)
        self.update_count()

    def add_filter(self, label: str, combo: QComboBox, default=None) -> None:
        """A labeled combo in the panel; `default` is the item data that counts as unfiltered."""
        self._rows.insertWidget(len(self._filters), labeled(label, combo))
        self._filters.append((combo, default))
        combo.currentIndexChanged.connect(self.update_count)

    def set_default(self, combo: QComboBox, default) -> None:
        self._filters = [(c, default if c is combo else d) for c, d in self._filters]
        self.update_count()

    def active_count(self) -> int:
        return sum(combo.currentData() != default for combo, default in self._filters)

    def update_count(self) -> None:
        count = self.active_count()
        self.setText(t["filters.button"] if not count
                     else t["filters.button_count"].format(count=count))
        self.setIcon(icon("funnel", "primary" if count else "text", gap=15))
        self.setProperty("active", bool(count))
        self.style().unpolish(self)
        self.style().polish(self)

    def reset_filters(self) -> None:
        """Every combo back on its default; each change signal refreshes the page once."""
        for combo, default in self._filters:
            select_data(combo, default)

    def show_panel(self) -> None:
        self.panel.adjustSize()
        pos = self.mapToGlobal(QPoint(0, self.height() + 6))
        screen = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        pos.setX(max(screen.left(), min(pos.x(), screen.right() - self.panel.width())))
        if pos.y() + self.panel.height() > screen.bottom():
            pos.setY(self.mapToGlobal(QPoint(0, 0)).y() - self.panel.height() - 6)
        self.panel.move(pos)
        self.panel.show()
