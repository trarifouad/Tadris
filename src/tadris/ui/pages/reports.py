"""Rapports (sidebar): one tab per report, each with its filters, the table, its total and
« PDF » / « Excel ». The tabs follow the user's rights; money and the audit log are the
director's. A double-click on a student row opens the student."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, timedelta
from html import escape

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from tadris import config
from tadris.core import dates
from tadris.core.cells import display
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, ValidationError
from tadris.core.permissions import allowed
from tadris.domain.models import AuditEntry, ReportTable
from tadris.i18n.fr import t
from tadris.services import groups, printing, reports, school_years
from tadris.ui.theme import tokens
from tadris.ui.widgets import common
from tadris.ui.widgets.common import PageBanner, labeled, toast
from tadris.ui.widgets.date_edit import DateLineEdit
from tadris.ui.widgets.forms import caption, padded
from tadris.ui.widgets.inputs import fill_combo, id_combo
from tadris.ui.widgets.tables import (
    CENTER,
    ID_ROLE,
    LEFT,
    PAGE_SIZE,
    MoreOnScroll,
    fill,
    fit_columns,
    frozen_columns,
    item,
    ruled_table,
)

# One export at a time, in the background: the window keeps answering while it is written.
EXPORTS = ThreadPoolExecutor(max_workers=1, thread_name_prefix="export")

NUMERIC = ("number", "money", "percent")
MONO = ("number", "money", "percent", "date", "datetime")


class ReportView(QWidget):
    """A report on screen: period, table with its total row, note, and the exports.
    load() returns the ReportTable to show; a BusinessRuleError shows in the banner."""

    open_student = Signal(int)
    row_selected = Signal(int)  # the row's index, -1 for none (or the total)
    exported = Signal(object)  # the file written (a Path)

    def __init__(self, conn, ctx: UserContext, load, filters: QHBoxLayout | None = None,
                 stretch: tuple[int, ...] | None = None):
        super().__init__()
        self._stretch = stretch
        self._conn = conn
        self._ctx = ctx
        self._load = load
        self.report: ReportTable | None = None
        self.banner = PageBanner()
        self.period = QLabel()
        self.period.setObjectName("sectionTitle")
        self.pdf = QPushButton(t["report.pdf"])
        self.excel = QPushButton(t["report.excel"])
        for button in (self.pdf, self.excel):
            button.setAutoDefault(False)
        self.pdf.clicked.connect(lambda: self.export("pdf"))
        self.excel.clicked.connect(lambda: self.export("xlsx"))
        self.folder = QPushButton(t["report.open_folder"])
        self.folder.setAutoDefault(False)
        self.folder.setToolTip(t["report.open_folder_tip"])
        self.folder.clicked.connect(lambda: common.open_folder(config.documents_dir()))
        self._job = self._future = None
        self._poll = QTimer(self)
        self._poll.setInterval(40)
        self._poll.timeout.connect(self._export_done)
        self.busy = caption()
        self.busy.hide()
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        toolbar.addWidget(self.period)
        toolbar.addStretch()
        toolbar.addWidget(self.busy)
        toolbar.addWidget(self.folder)
        toolbar.addWidget(self.pdf)
        toolbar.addWidget(self.excel)
        self.table = ruled_table([])
        self.table.activated.connect(self._activated)
        self.table.itemSelectionChanged.connect(self._selected)
        self._shown = 0
        self.pager = MoreOnScroll(self.table, self._load_more)
        self.empty = QLabel(t["report.empty"])
        self.empty.setObjectName("emptyState")
        self.empty.setWordWrap(True)
        self.note = caption()
        self.note.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        if filters is not None:
            layout.addLayout(filters)
        layout.addWidget(self.banner)
        layout.addLayout(toolbar)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.empty)
        layout.addWidget(self.note)

    def refresh(self) -> None:
        try:
            report = self._load()
        except BusinessRuleError as exc:
            self.banner.show_error(exc.message)
            return
        self.banner.clear_error()
        self.show_report(report)

    def show_report(self, report: ReportTable) -> None:
        """The report's first PAGE_SIZE rows (and its total); the next ones come as the
        table is scrolled (more_rows), so a long report never freezes the window."""
        self.report = report
        self.period.setText(report.period)
        self.table.setColumnCount(len(report.columns))
        self.table.setHorizontalHeaderLabels([c.label for c in report.columns])
        first = report.rows[:PAGE_SIZE]
        self._shown = len(first)
        rows = [self._cells(values, self._row_id(i)) for i, values in enumerate(first)]
        if report.total is not None:
            rows.append(self._cells(report.total, None, bold=True))
        fill(self.table, rows)
        # The others fit their content; by default the first text column takes the rest.
        fit_columns(self.table, stretch=self._stretch or (next(
            (i for i, c in enumerate(report.columns) if c.kind == "text"), 0),))
        for index, column in enumerate(report.columns):
            align = CENTER if column.kind in NUMERIC else LEFT
            self.table.horizontalHeaderItem(index).setTextAlignment(align)
        self.table.setVisible(bool(report.rows))
        self.empty.setVisible(not report.rows)
        self.note.setText(report.note)
        self.note.setVisible(bool(report.note))
        for button in (self.pdf, self.excel):  # not while an export is being written
            button.setEnabled(self._job is None and allowed(self._ctx, "print.document"))
        self.pager.reset(self.has_more())

    def _row_id(self, index: int) -> int | None:
        ids = self.report.row_ids
        return ids[index] if index < len(ids) else None

    # ----- paging: what has_more / more_rows say, the table follows -----

    def has_more(self) -> bool:
        """Rows left to show (the report's own, already computed)."""
        return self._shown < len(self.report.rows)

    def more_rows(self) -> int:
        """Make the next rows available in self.report (a report read a page at a time
        fetches them); returns how many there are past the ones shown."""
        return len(self.report.rows) - self._shown

    def after_more(self) -> None:
        """Hook once a page is shown (the Journal updates its count)."""

    def _load_more(self) -> bool:
        if self.report is None or self.more_rows() <= 0:
            return False
        start = self._shown
        new = self.report.rows[start:start + PAGE_SIZE]
        with frozen_columns(self.table):
            # New rows go above the total row, which moves down (made anew: one row).
            self.table.setRowCount(start + len(new) + (self.report.total is not None))
            for r, values in enumerate(new, start):
                for c, cell in enumerate(self._cells(values, self._row_id(r))):
                    self.table.setItem(r, c, cell)
            if self.report.total is not None:
                for c, cell in enumerate(self._cells(self.report.total, None, bold=True)):
                    self.table.setItem(start + len(new), c, cell)
        self._shown += len(new)
        self.after_more()
        return self.has_more()

    def _cells(self, values: tuple, row_id: int | None, bold: bool = False) -> list:
        out = []
        for index, (column, value) in enumerate(zip(self.report.columns, values, strict=True)):
            text = "" if bold and value is None else display(column.kind, value)
            cell = item(text, align=CENTER if column.kind in NUMERIC else LEFT,
                        mono=column.kind in MONO, item_id=row_id if index == 0 else None)
            if bold:
                font = cell.font()
                font.setWeight(QFont.Weight.DemiBold)
                cell.setFont(font)
            out.append(cell)
        return out

    def export_report(self) -> ReportTable:
        """What PDF and Excel write: the report on screen (the Journal: every entry its
        filters match, not only the pages loaded)."""
        return self.report

    def rows_shown(self) -> list[list[str]]:
        return [[self.table.item(r, c).text() for c in range(self.table.columnCount())]
                for r in range(self.table.rowCount())]

    def export(self, extension: str) -> None:
        """Write the PDF or the Excel file without freezing the window: the file is built
        in the background (the Journal's PDF takes a second or two), the buttons wait,
        then it is recorded and opened. exported(path) says when it is there."""
        if self.report is None or self._job is not None:
            return
        report = self.export_report()
        path = None
        if extension == "xlsx":  # a file to keep or send: the user says where
            path = common.ask_save_path(
                self, t["report.save_title"],
                config.save_dir() / printing.report_file_name(report, "xlsx"),
                t["report.save_filter"])
            if path is None:
                return
            if path.suffix.lower() != ".xlsx":
                path = path.with_name(path.name + ".xlsx")
        try:
            job = printing.prepare_report(self._conn, self._ctx, report, extension,
                                          path=path)
        except BusinessRuleError as exc:
            self.banner.show_error(exc.message)
            return
        self._job, self._future = job, EXPORTS.submit(job.build)
        self._set_busy(t[f"report.preparing.{extension}"])
        self._poll.start()

    def _set_busy(self, text: str | None) -> None:
        for button in (self.pdf, self.excel):
            button.setEnabled(text is None and allowed(self._ctx, "print.document"))
        self.busy.setText(text or "")
        self.busy.setVisible(text is not None)
        if text is None:
            self.unsetCursor()
        else:
            self.setCursor(Qt.CursorShape.BusyCursor)

    def _export_done(self) -> None:
        if not self._future.done():
            return
        self._poll.stop()
        job, future = self._job, self._future
        self._job = self._future = None
        self._set_busy(None)
        try:
            future.result()
            path = printing.finish_report(self._conn, self._ctx, job)
        except Exception as exc:  # noqa: BLE001 - whatever stopped the file, say so
            self.banner.show_error(getattr(exc, "message", None) or t["print.failed"])
            return
        common.open_document(path)
        toast(self, t["report.exported"].format(path=path))
        self.exported.emit(path)

    def _row(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        if not rows or self.report is None or rows[0].row() >= self._shown:
            return -1  # none, or the total
        return rows[0].row()

    def _selected(self) -> None:
        self.row_selected.emit(self._row())

    def _activated(self, index) -> None:
        student_id = self.table.item(index.row(), 0).data(ID_ROLE)
        if student_id is not None:
            self.open_student.emit(student_id)


def _filters(*widgets: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(12)
    for widget in widgets:
        row.addWidget(widget, 1)
    row.addStretch(max(1, 5 - len(widgets)))
    return row


def _choices(items: list[tuple[str, object]], selected=None) -> QComboBox:
    combo = QComboBox()
    combo.blockSignals(True)
    for label, value in items:
        combo.addItem(label, value)
    if selected is not None:
        combo.setCurrentIndex(max(combo.findData(selected), 0))
    combo.blockSignals(False)
    return combo


def _date_field(value: date) -> DateLineEdit:
    field = DateLineEdit()
    field.set_value(value)
    return field


def _read_range(first: DateLineEdit, last: DateLineEdit) -> tuple[date, date]:
    start, end = first.value(), last.value()
    if start is None or end is None:
        raise ValidationError(t["date.invalid"])
    return start, end


class YearFilter:
    """The school years, the open one first selected."""

    def __init__(self, conn, ctx: UserContext):
        years = school_years.list_years(conn, ctx)
        current = school_years.current(conn, ctx)
        self.combo = id_combo([(y.label, y.id) for y in years],
                              current.id if current else None)

    def value(self) -> int:
        if self.combo.currentData() is None:
            raise ValidationError(t["report.no_year"])
        return self.combo.currentData()


def _group_items(conn, ctx: UserContext, label_key: str) -> list[tuple[str, int | None]]:
    return [(t[label_key], None)] + [(g.title, g.id) for g in groups.search(conn, ctx)
                                     if g.status != "closed"]


# ----- the tabs -----

class RevenueTab(ReportView):
    def __init__(self, conn, ctx: UserContext):
        self.year = YearFilter(conn, ctx)
        self.view = _choices([(t["report.view.month"], "month"),
                              (t["report.view.group"], "group")])
        self.month = QComboBox()
        self.month_box = labeled(t["report.filter.month"], self.month)
        super().__init__(conn, ctx, self._report, _filters(
            labeled(t["report.filter.year"], self.year.combo),
            labeled(t["report.filter.view"], self.view), self.month_box))
        self.year.combo.currentIndexChanged.connect(lambda _i: self._year_changed())
        self.view.currentIndexChanged.connect(lambda _i: self.refresh())
        self.month.currentIndexChanged.connect(lambda _i: self.refresh())
        self._year_changed()

    def _year_changed(self) -> None:
        months: list[tuple[str, object]] = [(t["report.whole_year"], None)]
        year_id = self.year.combo.currentData()
        if year_id is not None:
            year = school_years.get(self._conn, self._ctx, year_id)
            # ISO text, not a date: Qt would hand a QDate back.
            months += [(reports.month_label(m), dates.iso(m)) for m in reports.year_months(
                date.fromisoformat(year.start_date), date.fromisoformat(year.end_date))]
        self.month.blockSignals(True)
        self.month.clear()
        for label, value in months:
            self.month.addItem(label, value)
        self.month.blockSignals(False)
        self.refresh()

    def _report(self) -> ReportTable:
        by_group = self.view.currentData() == "group"
        self.month_box.setVisible(by_group)
        if by_group:
            month = self.month.currentData()
            return reports.revenue_by_group(self._conn, self._ctx, self.year.value(),
                                            date.fromisoformat(month) if month else None)
        return reports.revenue_by_month(self._conn, self._ctx, self.year.value())


class DebtorsTab(ReportView):
    def __init__(self, conn, ctx: UserContext):
        self.group = id_combo(_group_items(conn, ctx, "report.all_groups"))
        super().__init__(conn, ctx, lambda: reports.debtors_by_age(
            self._conn, self._ctx, self.group.currentData()),
            _filters(labeled(t["report.filter.group"], self.group)))
        self.group.currentIndexChanged.connect(lambda _i: self.refresh())

    def load_filters(self) -> None:
        fill_combo(self.group, _group_items(self._conn, self._ctx, "report.all_groups"),
                   self.group.currentData())


class AttendanceTab(ReportView):
    def __init__(self, conn, ctx: UserContext):
        today = dates.today()
        self.first = _date_field(today.replace(day=1))
        self.last = _date_field(today)
        self.view = _choices([(t["report.view.group"], "group"),
                              (t["report.view.student"], "student")])
        self.group = id_combo(_group_items(conn, ctx, "report.all_groups"))
        self.group_box = labeled(t["report.filter.group"], self.group)
        super().__init__(conn, ctx, self._report, _filters(
            labeled(t["report.filter.from"], self.first),
            labeled(t["report.filter.to"], self.last),
            labeled(t["report.filter.view"], self.view), self.group_box))
        for field in (self.first, self.last):
            field.textChanged.connect(lambda _text: self._dates_changed())
        self.view.currentIndexChanged.connect(lambda _i: self.refresh())
        self.group.currentIndexChanged.connect(lambda _i: self.refresh())

    def _dates_changed(self) -> None:
        if self.first.value() is not None and self.last.value() is not None:
            self.refresh()

    def load_filters(self) -> None:
        fill_combo(self.group, _group_items(self._conn, self._ctx, "report.all_groups"),
                   self.group.currentData())

    def _report(self) -> ReportTable:
        first, last = _read_range(self.first, self.last)
        by_student = self.view.currentData() == "student"
        self.group_box.setVisible(by_student)
        if by_student:
            return reports.attendance_by_student(self._conn, self._ctx, first, last,
                                                 self.group.currentData())
        return reports.attendance_by_group(self._conn, self._ctx, first, last)


class TeachersTab(ReportView):
    def __init__(self, conn, ctx: UserContext):
        self.year = YearFilter(conn, ctx)
        super().__init__(conn, ctx, lambda: reports.teachers_summary(
            self._conn, self._ctx, self.year.value()),
            _filters(labeled(t["report.filter.year"], self.year.combo)))
        self.year.combo.currentIndexChanged.connect(lambda _i: self.refresh())


class StudentsTab(ReportView):
    def __init__(self, conn, ctx: UserContext):
        self.status = _choices([(t["report.status.active"], "active"),
                                (t["report.status.inactive"], "inactive"),
                                (t["report.status.all"], None)])
        self.group = id_combo(_group_items(conn, ctx, "report.all_groups"))
        self._total = 0
        super().__init__(conn, ctx, self._first_page,
                         _filters(labeled(t["report.filter.status"], self.status),
                                  labeled(t["report.filter.group"], self.group)), stretch=(5,))
        self.status.currentIndexChanged.connect(lambda _i: self.refresh())
        self.group.currentIndexChanged.connect(lambda _i: self.refresh())

    def _first_page(self) -> ReportTable:
        """A page from the database; the next ones as the list is scrolled (with 5 000
        students, the whole list would freeze the window)."""
        status, group = self.status.currentData(), self.group.currentData()
        self._total = reports.student_count(self._conn, self._ctx, status, group)
        return reports.student_list(self._conn, self._ctx, status, group, limit=PAGE_SIZE)

    def has_more(self) -> bool:
        return self._shown < self._total

    def more_rows(self) -> int:
        if self._shown >= len(self.report.rows):  # read the next page
            page = reports.student_list(self._conn, self._ctx, self.status.currentData(),
                                        self.group.currentData(), limit=PAGE_SIZE,
                                        offset=len(self.report.rows))
            if not page.rows:
                self._total = len(self.report.rows)
                return 0
            self.report = replace(self.report, rows=self.report.rows + page.rows,
                                  row_ids=self.report.row_ids + page.row_ids)
        return len(self.report.rows) - self._shown

    def export_report(self) -> ReportTable:
        """Every student the filters match, not only the pages scrolled through."""
        return reports.student_list(self._conn, self._ctx, self.status.currentData(),
                                    self.group.currentData())

    def load_filters(self) -> None:
        fill_combo(self.group, _group_items(self._conn, self._ctx, "report.all_groups"),
                   self.group.currentData())


class AuditTab(ReportView):
    """What people did, in plain French: filters, the entries (latest first) and, under
    them, what the selected entry recorded."""

    def __init__(self, conn, ctx: UserContext):
        today = dates.today()
        self.first = _date_field(today - timedelta(days=7))
        self.last = _date_field(today)
        self.user = QComboBox()
        self.family = QComboBox()
        self.entity = QLineEdit()
        self.entity.setPlaceholderText(t["report.filter.any"])
        self.entries: list[AuditEntry] = []
        self.detail = QTextBrowser()
        self.detail.setObjectName("journalDetail")
        self.detail.setMaximumHeight(170)
        self.detail.setPlaceholderText(t["report.audit.pick"])
        filters = _filters(
            labeled(t["report.filter.from"], self.first),
            labeled(t["report.filter.to"], self.last),
            labeled(t["report.filter.user"], self.user),
            labeled(t["report.filter.family"], self.family),
            labeled(t["report.filter.entity"], self.entity))
        super().__init__(conn, ctx, self._report, filters, stretch=(4,))
        self.layout().addWidget(self.detail)
        self.load_filters()
        for field in (self.first, self.last):
            field.textChanged.connect(lambda _text: self._dates_changed())
        self.user.currentIndexChanged.connect(lambda _i: self.refresh())
        self.family.currentIndexChanged.connect(lambda _i: self.refresh())
        self.entity.editingFinished.connect(self.refresh)
        self.row_selected.connect(self._show_detail)
        self._total = 0
        self._filters: dict = {}

    def load_filters(self) -> None:
        fill_combo(self.user, [(t["report.all_users"], None)]
                   + [(name, user_id) for user_id, name
                      in reports.audit_users(self._conn, self._ctx)],
                   self.user.currentData())
        self.family.blockSignals(True)
        chosen = self.family.currentData()
        self.family.clear()
        self.family.addItem(t["report.all_families"], None)
        for family in sorted(reports.audit_families(self._conn, self._ctx),
                             key=lambda f: reports.family_label(f).casefold()):
            self.family.addItem(reports.family_label(family), family)
        self.family.setCurrentIndex(max(self.family.findData(chosen), 0))
        self.family.blockSignals(False)

    def _dates_changed(self) -> None:
        if self.first.value() is not None and self.last.value() is not None:
            self.refresh()

    def _report(self) -> ReportTable:
        """The latest page of what the filters match; the next pages come as the list is
        scrolled (_more)."""
        first, last = _read_range(self.first, self.last)
        text = self.entity.text().strip()
        if text and not text.isdigit():
            raise ValidationError(t["report.entity_invalid"])
        self._filters = {"first": first, "last": last, "user_id": self.user.currentData(),
                         "family": self.family.currentData(),
                         "entity_id": int(text) if text else None}
        self._total = reports.audit_count(self._conn, self._ctx, **self._filters)
        self.entries = reports.audit_log(self._conn, self._ctx, **self._filters)
        self.detail.clear()
        return self._counted(reports.audit_table(self._conn, self.entries, first, last))

    def _counted(self, report: ReportTable) -> ReportTable:
        """The report with « 100 sur 765 opérations » under it."""
        shown = len(self.entries)
        key = "report.audit.shown_all" if shown >= self._total else "report.audit.shown_part"
        return replace(report, note=t[key].format(shown=shown, total=self._total))

    def has_more(self) -> bool:
        return len(self.entries) < self._total

    def more_rows(self) -> int:
        """The next page from the database, older than the last entry shown."""
        if self._shown < len(self.report.rows):
            return len(self.report.rows) - self._shown
        page = reports.audit_log(self._conn, self._ctx, **self._filters,
                                 before_id=self.entries[-1].id)
        if not page:
            self._total = len(self.entries)  # deleted meanwhile: nothing more
            return 0
        rows = reports.audit_table(self._conn, page, self._filters["first"],
                                   self._filters["last"]).rows
        self.entries += page
        self.report = self._counted(replace(self.report, rows=self.report.rows + rows))
        return len(rows)

    def after_more(self) -> None:
        self.report = self._counted(self.report)
        self.note.setText(self.report.note)

    def export_report(self) -> ReportTable:
        """Every entry the filters match (up to AUDIT_EXPORT_LIMIT), not only the pages
        scrolled through."""
        entries = reports.audit_log(self._conn, self._ctx, **self._filters,
                                    limit=reports.AUDIT_EXPORT_LIMIT)
        return reports.audit_table(self._conn, entries, self._filters["first"],
                                   self._filters["last"])

    def _show_detail(self, index: int) -> None:
        if index < 0 or index >= len(self.entries):
            self.detail.clear()
            return
        entry = self.entries[index]
        _when, user, action, item, _summary = self.report.rows[index]
        self.detail.setHtml(detail_html(
            t["report.audit.by"].format(action=action, user=user) if entry.user
            else t["report.audit.by_app"].format(action=action),
            t["report.audit.when"].format(date=display("date", entry.created_at),
                                          time=entry.created_at[11:16], item=item),
            reports.audit_fields(self._conn, self._ctx, entry)))


def detail_html(title: str, meta: str, fields) -> str:
    """The selected Journal entry as a small card: a title in bold (« Paiement annulé par
    directeur »), when and on what in grey, then each value on its own row, a changed one
    as « avant → après » with the new value in bold."""
    colors = tokens()
    rows = []
    for f in fields:
        if f.before is not None:
            value = (f'<span style="color:{colors["muted"]}">{escape(f.before)}</span>'
                     f'&nbsp;&nbsp;→&nbsp;&nbsp;<b>{escape(f.value)}</b>')
        else:
            value = escape(f.value)
        rows.append(f'<tr><td style="color:{colors["muted"]}; padding:3px 28px 3px 0">'
                    f'{escape(f.label)}</td><td style="padding:3px 0">{value}</td></tr>')
    body = (f'<table cellspacing="0" cellpadding="0" style="margin-top:10px">'
            f'{"".join(rows)}</table>' if rows else
            f'<p style="color:{colors["muted"]}; margin-top:10px">'
            f'{escape(t["report.audit.nothing"])}</p>')
    return (f'<div style="font-size:15px; font-weight:600">{escape(title)}</div>'
            f'<div style="color:{colors["muted"]}; margin-top:2px">{escape(meta)}</div>'
            f'{body}')


# (key, tab label, permissions needed, tab class)
TABS = (
    ("revenue", "report.tab.revenue", ("report.finance",), RevenueTab),
    ("debtors", "report.tab.debtors", ("payment.record",), DebtorsTab),
    ("attendance", "report.tab.attendance", ("session.view",), AttendanceTab),
    ("teachers", "report.tab.teachers", ("report.finance", "payout.view"), TeachersTab),
    ("students", "report.tab.students", ("student.view",), StudentsTab),
    ("audit", "report.tab.audit", ("audit.view",), AuditTab),
)


class ReportsPage(QWidget):
    open_student = Signal(int)

    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self.setObjectName("page")
        title = QLabel(t["reports_page.title"])
        title.setObjectName("pageTitle")
        intro = QLabel(t["reports_page.caption"])
        intro.setObjectName("caption")
        intro.setWordWrap(True)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.views: dict[str, ReportView] = {}
        for key, label, rights, view_class in TABS:
            if all(allowed(ctx, right) for right in rights):
                view = view_class(conn, ctx)
                view.open_student.connect(self.open_student.emit)
                self.views[key] = view
                self.tabs.addTab(padded(view), t[label])
        self.tabs.currentChanged.connect(lambda _i: self.refresh())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addWidget(self.tabs, 1)
        self.refresh()

    def _current(self) -> ReportView:
        return list(self.views.values())[self.tabs.currentIndex()]

    def refresh(self) -> None:
        """Only the tab on screen loads; the others load when chosen."""
        if not self.views:
            return
        view = self._current()
        if hasattr(view, "load_filters"):
            view.load_filters()
        view.refresh()
