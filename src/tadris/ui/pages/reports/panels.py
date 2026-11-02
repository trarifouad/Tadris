"""One panel per report: its filters in a line, then the report (ReportView). Each change of a
filter builds the report again; `report` is what is shown, what the exports write."""

from datetime import timedelta

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QComboBox, QLineEdit, QVBoxLayout, QWidget

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError
from tadris.domain.models import Report
from tadris.i18n.fr import t
from tadris.services import catalog, groups, reports
from tadris.ui.pages.reports.view import ReportView, grid_row
from tadris.ui.widgets.common import PageBanner, labeled
from tadris.ui.widgets.date_edit import DateLineEdit
from tadris.ui.widgets.inputs import fill_combo

SEARCH_DELAY_MS = 300  # the list follows the search box once typing pauses


class Panel(QWidget):
    opened = Signal(str, int)

    def __init__(self, conn, ctx: UserContext, views: list[str] | None = None):
        super().__init__()
        self._conn, self._ctx = conn, ctx
        self.view = ReportView(views)
        self.view.opened.connect(self.opened.emit)
        self.view.view_changed.connect(lambda _index: self.refresh())
        self.banner = PageBanner()
        self.filters = grid_row()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addLayout(self.filters)
        layout.addWidget(self.banner)
        layout.addWidget(self.view)

    @property
    def report(self) -> Report | None:
        return self.view.report

    def add_filter(self, text: str, widget: QWidget) -> None:
        self.filters.insertWidget(self.filters.count() - 1, labeled(text, widget))

    def view_index(self) -> int:
        views = self.view.views
        return 0 if views is None else next(
            i for i, button in enumerate(views.buttons) if button.isChecked())

    def refresh(self) -> None:
        try:
            report = self.build()
        except BusinessRuleError as exc:
            self.banner.show_error(exc.message)
            return
        self.banner.clear_error()
        self.view.show_report(report)

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
    """This month at first; a preset or two dates of one's own."""

    def __init__(self, conn, ctx: UserContext):
        super().__init__(conn, ctx, [t["reports.view.by_group"], t["reports.view.by_student"]])
        self.period = QComboBox()
        for key in reports.PERIODS:
            self.period.addItem(t[f"reports.preset.{key}"], key)
        self.period.setCurrentIndex(reports.PERIODS.index("month"))
        self.first, self.last = DateLineEdit(), DateLineEdit()
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
        self.group.currentIndexChanged.connect(lambda _i: self.refresh())

    def _preset(self) -> None:
        """The dates of the chosen preset, in the fields (which only « Dates choisies »
        leaves editable)."""
        key = self.period.currentData()
        custom = key == "custom"
        for field in (self.first, self.last):
            field.setEnabled(custom)
        if custom:
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

    def _dates_changed(self) -> None:
        if self.first.value() is not None and self.last.value() is not None:
            self.refresh()  # not while a date is half typed

    def build(self) -> Report:
        first = self.first.value() or dates.today().replace(day=1)
        last = self.last.value() or first + timedelta(days=30)
        return reports.attendance(self._conn, self._ctx, first, last,
                                  self.group.currentData(),
                                  ("group", "student")[self.view_index()])


class StudentsPanel(Panel):
    def __init__(self, conn, ctx: UserContext):
        super().__init__(conn, ctx)
        self.status = QComboBox()
        for status in reports.STUDENT_STATUSES:
            self.status.addItem(t[f"reports.status.{status or 'all'}"], status)
        self.level = QComboBox()
        fill_combo(self.level, [(t["reports.all_levels"], None)] + [
            (item.name, item.id) for item in catalog.list_items(conn, ctx, "level")])
        self.group = QComboBox()
        fill_combo(self.group, group_items(conn, ctx))
        self.search = QLineEdit()
        self.search.setPlaceholderText(t["reports.search_hint"])
        self.search.setClearButtonEnabled(True)
        self._pause = QTimer(self)
        self._pause.setSingleShot(True)
        self._pause.setInterval(SEARCH_DELAY_MS)
        self._pause.timeout.connect(self.refresh)
        self.add_filter(t["reports.filter.status"], self.status)
        self.add_filter(t["reports.filter.level"], self.level)
        self.add_filter(t["reports.filter.group"], self.group)
        self.add_filter(t["reports.filter.search"], self.search)
        for combo in (self.status, self.level, self.group):
            combo.currentIndexChanged.connect(lambda _i: self.refresh())
        self.search.textChanged.connect(lambda _text: self._pause.start())

    def build(self) -> Report:
        return reports.student_list(self._conn, self._ctx, self.status.currentData(),
                                    self.level.currentData(), self.group.currentData(),
                                    self.search.text())


PANELS = {"revenue": RevenuePanel, "attendance": AttendancePanel, "teachers": TeachersPanel,
          "students": StudentsPanel}
