from datetime import date

from PySide6.QtCore import QDate, QLocale, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QTextCharFormat
from PySide6.QtWidgets import (
    QCalendarWidget,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from tadris.core.dates import parse_display_date
from tadris.core.errors import ValidationError
from tadris.i18n.fr import t
from tadris.ui.theme import icon, tokens

SEPARATORS = "/.- "
MAX_DIGITS = 8  # jj mm aaaa
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
# French month and day names, week starting on Saturday as in Algeria.
LOCALE = QLocale(QLocale.Language.French, QLocale.Country.Algeria)
FALLBACK_MIN = date(1900, 1, 1)
FALLBACK_MAX = date(2100, 12, 31)


def date_digits(text: str) -> str:
    return "".join(ch for ch in text.translate(_ARABIC_DIGITS) if "0" <= ch <= "9")[:MAX_DIGITS]


def format_date_typing(text: str) -> str:
    """Regroup the digits as jj/mm/aaaa: '29102003' -> '29/10/2003', '291' -> '29/1'.

    Only digits count, so pasted '29-10-2003' or a digit erased mid-field regroups cleanly.
    """
    digits = date_digits(text)
    return "/".join(part for part in (digits[:2], digits[2:4], digits[4:]) if part)


class DatePopup(QFrame):
    """Calendar under a date field, with three views like common date pickers.

    Days: '‹ Mars 2012 ›'. Clicking the year shows a grid of 12 years (arrows page by 12),
    picking a year shows the 12 months, picking a month comes back to its days. Clicking the
    month name shows the months directly. Years and months outside the bounds are disabled.
    Escape steps back to the days, then closes.
    """

    picked = Signal(date)
    DAYS, MONTHS, YEARS = range(3)
    YEARS_PER_PAGE = 12
    GRID_COLUMNS = 3

    def __init__(self, parent=None, minimum: date | None = None, maximum: date | None = None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("datePopup")
        self.minimum = minimum or FALLBACK_MIN
        self.maximum = maximum or FALLBACK_MAX
        self.view = self.DAYS

        self.prev = self._nav_button("chevron-left")
        self.prev.clicked.connect(lambda: self._step(-1))
        self.next = self._nav_button("chevron-right")
        self.next.clicked.connect(lambda: self._step(1))
        self.month_button = self._title_button(self.show_months)
        self.year_button = self._title_button(self.show_years)
        self.range_label = QLabel()
        self.range_label.setObjectName("calendarRange")
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 4)
        header.setSpacing(2)
        header.addWidget(self.prev)
        header.addStretch()
        header.addWidget(self.month_button)
        header.addWidget(self.year_button)
        header.addWidget(self.range_label)
        header.addStretch()
        header.addWidget(self.next)

        self.calendar = QCalendarWidget()
        self.calendar.setLocale(LOCALE)
        self.calendar.setGridVisible(False)
        self.calendar.setNavigationBarVisible(False)
        self.calendar.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
        )
        self.calendar.setHorizontalHeaderFormat(
            QCalendarWidget.HorizontalHeaderFormat.ShortDayNames
        )
        self.calendar.setMinimumDate(QDate(self.minimum))
        self.calendar.setMaximumDate(QDate(self.maximum))
        self._color_weekdays()
        self.calendar.clicked.connect(self._pick)
        self.calendar.activated.connect(self._pick)
        self.calendar.currentPageChanged.connect(lambda _y, _m: self._refresh())

        self.month_buttons = [
            self._cell(LOCALE.standaloneMonthName(m, QLocale.FormatType.ShortFormat).rstrip("."),
                       lambda _c=False, m=m: self._pick_month(m))
            for m in range(1, 13)
        ]
        self.year_buttons = [self._cell("", self._pick_year_from_sender)
                             for _ in range(self.YEARS_PER_PAGE)]
        self.year_page_start = 0

        self.stack = QStackedWidget()
        self.stack.addWidget(self.calendar)
        self.stack.addWidget(self._grid(self.month_buttons))
        self.stack.addWidget(self._grid(self.year_buttons))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addWidget(self.stack, 1)
        self.setFixedSize(340, 320)
        self._refresh()

    # ----- building -----

    @staticmethod
    def _nav_button(glyph: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("calendarNav")
        button.setIcon(icon(glyph, "text"))
        button.setAutoRaise(True)
        return button

    @staticmethod
    def _title_button(slot) -> QPushButton:
        button = QPushButton()
        button.setObjectName("calendarTitle")
        button.setAutoDefault(False)
        button.clicked.connect(slot)
        return button

    @staticmethod
    def _cell(text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("calendarCell")
        button.setCheckable(True)
        button.setAutoDefault(False)
        button.clicked.connect(slot)
        return button

    def _grid(self, buttons: list[QPushButton]) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 8, 0, 0)
        grid.setSpacing(6)
        for i, button in enumerate(buttons):
            grid.addWidget(button, i // self.GRID_COLUMNS, i % self.GRID_COLUMNS)
        return page

    def _color_weekdays(self) -> None:
        # Qt paints the weekend red, which the design keeps for errors and debt. Every day
        # gets the text color; only days outside the shown month stay faint.
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(tokens()["text"]))
        for day in range(1, 8):
            self.calendar.setWeekdayTextFormat(Qt.DayOfWeek(day), fmt)

    # ----- views -----

    def year(self) -> int:
        return self.calendar.yearShown()

    def month(self) -> int:
        return self.calendar.monthShown()

    def show_days(self) -> None:
        self._set_view(self.DAYS)
        self.calendar.setFocus()

    def show_months(self) -> None:
        self._set_view(self.MONTHS)

    def show_years(self) -> None:
        self.year_page_start = self.year() - self.year() % self.YEARS_PER_PAGE
        self._set_view(self.YEARS)

    def _set_view(self, view: int) -> None:
        self.view = view
        self.stack.setCurrentIndex(view)
        self._refresh()

    def _show_page(self, year: int, month: int) -> None:
        """Show (year, month), clamped to the bounds."""
        low = (self.minimum.year, self.minimum.month)
        high = (self.maximum.year, self.maximum.month)
        year, month = max(low, min(high, (year, month)))
        self.calendar.setCurrentPage(year, month)
        self._refresh()

    def _step(self, direction: int) -> None:
        if self.view == self.DAYS:
            month = self.month() + direction
            self._show_page(self.year() + (month - 1) // 12, (month - 1) % 12 + 1)
        elif self.view == self.MONTHS:
            self._show_page(self.year() + direction, self.month())
        else:
            self.year_page_start += direction * self.YEARS_PER_PAGE
            self._refresh()

    def _pick_month(self, month: int) -> None:
        self._show_page(self.year(), month)
        self.show_days()

    def _pick_year_from_sender(self) -> None:
        self.pick_year(int(self.sender().text()))

    def pick_year(self, year: int) -> None:
        self._show_page(year, self.month())
        self.show_months()

    def _refresh(self) -> None:
        year, month = self.year(), self.month()
        low, high = self.minimum, self.maximum
        days, months, years = (self.view == v for v in (self.DAYS, self.MONTHS, self.YEARS))
        name = LOCALE.standaloneMonthName(month, QLocale.FormatType.LongFormat)
        self.month_button.setText(name[:1].upper() + name[1:])
        self.month_button.setVisible(days)
        self.year_button.setText(str(year))
        self.year_button.setVisible(not years)
        first = self.year_page_start
        last = first + self.YEARS_PER_PAGE - 1
        self.range_label.setText(f"{first} – {last}")
        self.range_label.setVisible(years)

        if days:
            self.prev.setEnabled((year, month) > (low.year, low.month))
            self.next.setEnabled((year, month) < (high.year, high.month))
        elif months:
            self.prev.setEnabled(year > low.year)
            self.next.setEnabled(year < high.year)
        else:
            self.prev.setEnabled(first > low.year)
            self.next.setEnabled(last < high.year)

        for m, button in enumerate(self.month_buttons, start=1):
            button.setChecked(m == month)
            button.setEnabled((low.year, low.month) <= (year, m) <= (high.year, high.month))
        for i, button in enumerate(self.year_buttons):
            value = first + i
            button.setText(str(value))
            button.setChecked(value == year)
            button.setEnabled(low.year <= value <= high.year)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.view != self.DAYS:
            self.show_days()
            return
        super().keyPressEvent(event)

    def _pick(self, value: QDate) -> None:
        self.picked.emit(value.toPython())
        self.close()


class DateLineEdit(QLineEdit):
    """Date field that inserts the slashes itself while the user types digits, with a
    calendar button (also Alt+Down or F4).

    Typing a separator after a single day or month digit pads it: '1/2/2012' -> '01/02/2012'.
    minimum/maximum bound the calendar; suggested is the month it opens on when empty.
    """

    def __init__(self, parent=None, minimum: date | None = None, maximum: date | None = None,
                 suggested: date | None = None):
        super().__init__(parent)
        self.minimum = minimum
        self.maximum = maximum
        self.suggested = suggested
        self.popup: DatePopup | None = None
        self.setPlaceholderText(t["student_dialog.birth_placeholder"])
        self.setMaxLength(10)
        self.textEdited.connect(self._reformat)
        self.calendar_action = self.addAction(
            icon("calendar"), QLineEdit.ActionPosition.TrailingPosition
        )
        self.calendar_action.setToolTip(t["date.pick"])
        self.calendar_action.triggered.connect(self.open_calendar)

    def value(self) -> date | None:
        """The typed date, or None when blank or not a valid date yet."""
        try:
            return parse_display_date(self.text())
        except ValidationError:
            return None

    def set_value(self, value: date | None) -> None:
        self.setText("" if value is None else value.strftime("%d/%m/%Y"))

    def open_calendar(self) -> DatePopup:
        popup = DatePopup(self, self.minimum, self.maximum)
        calendar = popup.calendar
        current = self.value()
        if current is not None:
            calendar.setSelectedDate(QDate(current))
        else:
            page = self.suggested or self.maximum or date.today()
            calendar.setCurrentPage(page.year, page.month)
        popup.picked.connect(self._picked)
        popup.move(self._popup_position(popup))
        popup.show()
        calendar.setFocus()
        self.popup = popup
        return popup

    def _popup_position(self, popup: DatePopup) -> QPoint:
        """Below the field, right edges aligned, kept on screen (above if no room below)."""
        below = self.mapToGlobal(QPoint(self.width() - popup.width(), self.height() + 4))
        screen = self.screen().availableGeometry()
        x = max(screen.left(), min(below.x(), screen.right() - popup.width()))
        y = below.y()
        if y + popup.height() > screen.bottom():
            y = self.mapToGlobal(QPoint(0, -popup.height() - 4)).y()
        return QPoint(x, y)

    def _picked(self, value: date) -> None:
        self.set_value(value)
        self.textEdited.emit(self.text())
        self.setFocus()
        self.setCursorPosition(len(self.text()))

    def keyPressEvent(self, event):
        text, pos = self.text(), self.cursorPosition()
        alt_down = (event.key() == Qt.Key.Key_Down
                    and event.modifiers() & Qt.KeyboardModifier.AltModifier)
        if alt_down or event.key() == Qt.Key.Key_F4:
            self.open_calendar()
            return
        if event.text() and event.text() in SEPARATORS:
            # Slashes come from the formatting; a typed one only pads a lone digit.
            digits = date_digits(text)
            if not self.hasSelectedText() and pos == len(text) and len(digits) in (1, 3):
                self.setText(format_date_typing(digits[:-1] + "0" + digits[-1]))
            return
        # Erasing next to a slash erases the digit beyond it, so the key never looks stuck.
        if not self.hasSelectedText():
            if event.key() == Qt.Key.Key_Backspace and pos > 0 and text[pos - 1] == "/":
                self.setCursorPosition(pos - 1)
            elif event.key() == Qt.Key.Key_Delete and pos < len(text) and text[pos] == "/":
                self.setCursorPosition(pos + 1)
        super().keyPressEvent(event)

    def _reformat(self, text: str) -> None:
        formatted = format_date_typing(text)
        if formatted == text:
            return
        pos = self.cursorPosition()
        at_end = pos >= len(text)
        digits_before = len(date_digits(text[:pos]))
        self.setText(formatted)
        if at_end:
            self.setCursorPosition(len(formatted))
            return
        # Keep the cursor after the same digit it followed before regrouping.
        seen = 0
        for index, ch in enumerate(formatted):
            if seen == digits_before:
                self.setCursorPosition(index)
                return
            seen += ch.isdigit()
        self.setCursorPosition(len(formatted))
