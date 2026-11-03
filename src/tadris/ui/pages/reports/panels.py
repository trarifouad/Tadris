"""One panel per report, inside the sheet: its filters as chips (« Année 2026-2027 ▾ »),
wrapping to a second line on a narrow window; then the report (ReportView), its views
(« Par mois | Par groupe ») above its table, which they change. A chip moved off what the page
opened with turns violet, and « Réinitialiser » follows the chips. Each change of a
filter builds the report again (`shown`); `report` is what is shown, what the exports
write.

Présences: the dates are always editable; typing or picking one turns the period to
« Dates choisies », so a preset is a starting point, never a lock."""

from datetime import timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError
from tadris.domain.models import Report
from tadris.i18n.fr import t
from tadris.services import groups, reports
from tadris.ui.pages.dashboard import link
from tadris.ui.pages.reports.view import SHEET_PAD, ReportView
from tadris.ui.widgets.chips import Chip
from tadris.ui.widgets.common import PageBanner
from tadris.ui.widgets.compact import Segments
from tadris.ui.widgets.date_edit import DateLineEdit
from tadris.ui.widgets.flow import FlowLayout
from tadris.ui.widgets.inputs import fill_combo

DATE_WIDTH = 124  # dd/mm/yyyy and the calendar button
CHIP_GAP = 8


class FilterRow(QWidget):
    """The chips from the left, wrapping; « Réinitialiser » after the last one."""

    def __init__(self):
        super().__init__()
        line = QVBoxLayout(self)
        line.setContentsMargins(SHEET_PAD, 12, SHEET_PAD, 18)
        self._flow = FlowLayout(spacing=CHIP_GAP)
        holder = QWidget()
        holder.setLayout(self._flow)
        line.addWidget(holder)
        self.reset = link(t["reports.reset"])
        self.reset.setToolTip(t["reports.reset_filters"])
        self._reset_box = QWidget()
        self._reset_box.setMinimumHeight(36)
        box = QHBoxLayout(self._reset_box)
        box.setContentsMargins(6, 0, 0, 0)
        box.addWidget(self.reset, 0, Qt.AlignmentFlag.AlignVCenter)
        self._reset_box.hide()
        self._flow.addWidget(self._reset_box)

    def add(self, chip: Chip) -> None:
        self._flow.takeAt(self._flow.count() - 1)  # « Réinitialiser » stays the last
        self._flow.addWidget(chip)
        self._flow.addWidget(self._reset_box)

    def show_reset(self, shown: bool) -> None:
        self._reset_box.setVisible(shown)


class Panel(QWidget):
    opened = Signal(str, int)
    shown = Signal()  # the report was built again (or could not be)

    def __init__(self, conn, ctx: UserContext, views: list[str] | None = None):
        super().__init__()
        self._conn, self._ctx = conn, ctx
        self._defaults: list[tuple[QWidget, object, Chip]] = []  # as the page opened
        self.views = Segments(views) if views else None
        if self.views is not None:
            self.views.changed.connect(lambda _index: self.refresh())
        self.view = ReportView(self.views)
        self.view.opened.connect(self.opened.emit)
        self.view.reset_requested.connect(self.reset)
        self.banner = PageBanner()
        self.filters = FilterRow()
        self.filters.reset.clicked.connect(self.reset)
        banner_box = QVBoxLayout()
        banner_box.setContentsMargins(SHEET_PAD, 0, SHEET_PAD, 12)
        banner_box.addWidget(self.banner)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.filters)
        layout.addLayout(banner_box)
        layout.addWidget(self.view)

    @property
    def report(self) -> Report | None:
        return self.view.report

    def add_filter(self, text: str, widget: QWidget, icon_name: str | None = None) -> Chip:
        """A filter as a chip, kept as it is now: what « Réinitialiser » comes back to.
        Dates are left out: they follow the period."""
        chip = Chip(text, widget, icon_name)
        self.filters.add(chip)
        if isinstance(widget, QComboBox):
            widget.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
            self._defaults.append((widget, widget.currentIndex(), chip))
        elif isinstance(widget, QLineEdit) and not isinstance(widget, DateLineEdit):
            self._defaults.append((widget, widget.text(), chip))
        return chip

    @staticmethod
    def _moved(widget: QWidget, value) -> bool:
        if isinstance(widget, QComboBox):
            return widget.currentIndex() != value
        return widget.text().strip() != value

    def is_default(self) -> bool:
        return not any(self._moved(widget, value) for widget, value, _chip in self._defaults)

    def reset(self) -> None:
        """Every filter back to how the page opened, the report built once."""
        for widget, value, _chip in self._defaults:
            widget.blockSignals(True)
            if isinstance(widget, QComboBox):
                widget.setCurrentIndex(value)
            else:
                widget.setText(value)
            widget.blockSignals(False)
        self.after_reset()
        self.refresh()

    def after_reset(self) -> None:
        """What follows the filters once they are back (Présences: the period's dates)."""

    def _show_filtered(self) -> None:
        for widget, value, chip in self._defaults:
            chip.set_active(self._moved(widget, value))
        filtered = not self.is_default()
        self.filters.show_reset(filtered)
        self.view.set_filtered(filtered)

    def view_index(self) -> int:
        views = self.views
        return 0 if views is None else next(
            i for i, button in enumerate(views.buttons) if button.isChecked())

    def refresh(self) -> None:
        self._show_filtered()
        try:
            report = self.build()
        except BusinessRuleError as exc:
            self.banner.show_error(exc.message)
            self.shown.emit()
            return
        self.banner.clear_error()
        self.view.show_report(report)
        self.shown.emit()

    def build(self) -> Report:
        raise NotImplementedError


def year_combo(conn, ctx: UserContext) -> QComboBox:
    combo = QComboBox()
    fill_combo(combo, [(label, year_id) for year_id, label in reports.years(conn, ctx)],
               reports.default_year(conn))
    return combo


class RevenuePanel(Panel):
    def __init__(self, conn, ctx: UserContext):
        super().__init__(conn, ctx, [t["reports.view.month"], t["reports.view.group"]])
        self.year = year_combo(conn, ctx)
        self.year.currentIndexChanged.connect(lambda _i: self.refresh())
        self.add_filter(t["reports.filter.year"], self.year)

    def build(self) -> Report:
        return reports.revenue(self._conn, self._ctx, self.year.currentData(),
                               ("month", "group")[self.view_index()])


class TeachersPanel(Panel):
    def __init__(self, conn, ctx: UserContext):
        super().__init__(conn, ctx)
        self.year = year_combo(conn, ctx)
        self.year.currentIndexChanged.connect(lambda _i: self.refresh())
        self.add_filter(t["reports.filter.year"], self.year)

    def build(self) -> Report:
        return reports.teacher_summary(self._conn, self._ctx, self.year.currentData())


def group_items(conn, ctx: UserContext) -> list[tuple[str, int | None]]:
    """The groups of the school year shown by default, for a filter."""
    year_id = reports.default_year(conn)
    found = groups.search(conn, ctx, year_id=year_id) if year_id is not None else []
    return [(t["reports.all_groups"], None)] + sorted(
        ((g.title, g.id) for g in found), key=lambda item: item[0].casefold())


class AttendancePanel(Panel):
    """This month at first; a preset, or two dates of one's own."""

    def __init__(self, conn, ctx: UserContext):
        super().__init__(conn, ctx, [t["reports.view.by_group"], t["reports.view.by_student"]])
        self.period = QComboBox()
        for key in reports.PERIODS:
            self.period.addItem(t[f"reports.preset.{key}"], key)
        self.period.setCurrentIndex(reports.PERIODS.index("month"))
        self.first, self.last = DateLineEdit(), DateLineEdit()
        for field in (self.first, self.last):
            field.setFixedWidth(DATE_WIDTH)
        self.group = QComboBox()
        fill_combo(self.group, group_items(conn, ctx))
        self.add_filter(t["reports.filter.period"], self.period)
        self.add_filter(t["reports.filter.from"], self.first)
        self.add_filter(t["reports.filter.to"], self.last)
        self.add_filter(t["reports.filter.group"], self.group)
        self._preset()
        self.period.currentIndexChanged.connect(lambda _i: self._preset_changed())
        for field in (self.first, self.last):
            field.textChanged.connect(lambda _text: self._dates_changed())
            field.textEdited.connect(lambda _text: self._typed_date())  # typed or picked
        self.group.currentIndexChanged.connect(lambda _i: self.refresh())

    def _preset(self) -> None:
        """The dates of the chosen preset, in the fields; « Dates choisies » keeps them."""
        key = self.period.currentData()
        if key == "custom":
            return
        first, last = reports.period_range(self._conn, key, dates.today(),
                                           reports.default_year(self._conn))
        for field, day in ((self.first, first), (self.last, last)):
            field.blockSignals(True)
            field.set_value(day)
            field.blockSignals(False)

    def _preset_changed(self) -> None:
        self._preset()
        self.refresh()

    def _typed_date(self) -> None:
        """A date of one's own: the period becomes « Dates choisies »."""
        custom = self.period.findData("custom")
        if self.period.currentIndex() != custom:
            self.period.blockSignals(True)
            self.period.setCurrentIndex(custom)
            self.period.blockSignals(False)
            self._show_filtered()

    def _dates_changed(self) -> None:
        if self.first.value() is not None and self.last.value() is not None:
            self.refresh()  # not while a date is half typed

    def after_reset(self) -> None:
        self._preset()

    def _range(self) -> tuple:
        first = self.first.value() or dates.today().replace(day=1)
        return first, self.last.value() or first + timedelta(days=30)

    def build(self) -> Report:
        return reports.attendance(self._conn, self._ctx, *self._range(),
                                  self.group.currentData(),
                                  ("group", "student")[self.view_index()])


PANELS = {"revenue": RevenuePanel, "attendance": AttendancePanel, "teachers": TeachersPanel}
