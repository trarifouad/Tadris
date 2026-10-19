"""Small input widgets and the readers that turn their text into domain values."""

from PySide6.QtWidgets import QComboBox, QLineEdit, QSpinBox

from tadris.core.dates import parse_time
from tadris.core.money import format_dzd, parse_dzd
from tadris.core.percent import format_percent, parse_percent

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
