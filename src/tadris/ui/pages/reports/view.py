"""The body of a report, on the sheet, from top to bottom:

- The figures as four soft blocks (label, figure, one small line). With a chart they stand
  two by two on the left and the chart takes the rest of the line; without one, in a row.
- The chart: bars by month, one month read out on the right (the hovered one, else the
  latest with figures), its dot-coloured figures standing in for a legend; or the groups'
  attendance, the lowest first, eight of them until « Voir les N groupes ».
- A rule, then the table, flat on the sheet: how many lines and what a double-click opens
  above it, sortable, the total as its last line (it stays there whatever the order).
  Figures in the UI font with tabular digits; a zero or a « — » faint. Nothing to show:
  an empty state that offers to reset the filters.
- At the foot of the sheet, how it is counted, its lines kept short enough to read.

`opened(page, id)`: a row was double-clicked or Enter pressed on it (a student, a
group, a teacher). `reset_requested`: the empty state's « Réinitialiser les filtres »."""

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from tadris.core.cells import NUMERIC, display, tile_text
from tadris.core.money import format_dzd
from tadris.core.percent import format_percent
from tadris.domain.models import Report, ReportColumn, ReportTile
from tadris.i18n.fr import t
from tadris.ui.pages.dashboard import capitalized, label, plural
from tadris.ui.pages.dues_view import tabular
from tadris.ui.pages.reports.charts import BarsChart, RatesBars, rate_tone, series_colors
from tadris.ui.pages.student_overview import EmptyState
from tadris.ui.theme import tokens
from tadris.ui.widgets.compact import heading, rule
from tadris.ui.widgets.forms import caption
from tadris.ui.widgets.tables import (
    ID_ROLE,
    LEFT,
    RIGHT,
    ROW_HEIGHT,
    fill,
    item,
    ruled_table,
)

SHEET_PAD = 28  # the sheet's side margin
MAX_TABLE_ROWS = 14  # taller than this, the table scrolls inside the sheet
WIDE_MIN, WIDE_MAX = 160, 260  # the widest text column when the window is short of room
NOTE_WIDTH = 860  # « how it is counted »: about 120 characters a line, no more
KPI_GAP = 12


class Tile(QFrame):
    """One figure: its label, the figure, one small line. On the report's sheet a soft
    block; card=True, on a page's background (Élèves), an ordinary card with its border."""

    def __init__(self, card: bool = False):
        super().__init__()
        self.setObjectName("card" if card else "kpi")
        self.name = label("", "kpiLabel")
        self.value = label("", "kpiValue")
        self.note = caption()
        self.note.setWordWrap(True)
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(2)
        box.addWidget(self.name)
        box.addWidget(self.value)
        box.addWidget(self.note)
        box.addStretch()

    def show_tile(self, tile: ReportTile) -> None:
        self.name.setText(tile.label)
        self.value.setText(tile_text(tile))
        self.note.setText(tile.note)


class TotalBar(QTableWidget):
    """The report's total, one line under the table, column for column (it follows the
    table's widths); it stays at the bottom whatever the table's order."""

    def __init__(self, table: QTableWidget):
        super().__init__(1, 0)
        self.setObjectName("totalBar")
        self._table = table
        self.horizontalHeader().hide()
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(ROW_HEIGHT + 2)
        table.horizontalHeader().sectionResized.connect(
            lambda index, _old, new: self.setColumnWidth(index, new))
        table.horizontalScrollBar().valueChanged.connect(
            self.horizontalScrollBar().setValue)

    def show_total(self, cells: list, values: tuple) -> None:
        """The label spans the empty cells after it (« 25 élève(s) » over the names)."""
        self.clearSpans()
        self.setColumnCount(len(cells))
        span = 1
        while span < len(values) and values[span] is None:
            span += 1
        if span > 1:
            self.setSpan(0, 0, 1, span)
        for c, cell in enumerate(cells):
            font = cell.font()
            font.setWeight(QFont.Weight.DemiBold)
            cell.setFont(font)
            self.setItem(0, c, cell)
            self.setColumnWidth(c, self._table.columnWidth(c))


class NoteText(QLabel):
    """Wrapped text no wider than NOTE_WIDTH, its height measured at that width: the layout
    asks for the height at the whole sheet's width, and a second line was cut off."""

    def heightForWidth(self, width: int) -> int:
        return super().heightForWidth(min(width, self.maximumWidth()))


class NoteBlock(QFrame):
    """How a report is counted, at the foot of the sheet."""

    def __init__(self):
        super().__init__()
        self.setObjectName("sheetFoot")
        self.text = NoteText()
        self.text.setObjectName("noteText")
        self.text.setWordWrap(True)
        self.text.setMaximumWidth(NOTE_WIDTH)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box = QVBoxLayout(self)
        box.setContentsMargins(SHEET_PAD, 14, SHEET_PAD, 18)
        box.setSpacing(4)
        box.addWidget(heading(t["reports.note_title"]))
        box.addWidget(self.text)

    def setText(self, text: str) -> None:  # a QLabel's name: the view sets it as before
        self.text.setText(text)


class ChartBlock(QWidget):
    """The chart beside the figures: its title and one line under it on the left, the
    readout on the right: the month picked (bars) or the group picked (rates)."""

    def __init__(self):
        super().__init__()
        self.title = label("", "blockTitle")
        self.subtitle = caption()
        names = QVBoxLayout()
        names.setSpacing(1)
        names.addWidget(self.title)
        names.addWidget(self.subtitle)
        self.readout_month = label("", "readoutMonth", Qt.AlignmentFlag.AlignRight)
        self.readout = QLabel()
        self.readout.setTextFormat(Qt.TextFormat.RichText)
        self.readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.readout.setFont(tabular(size=13))
        readout = QVBoxLayout()
        readout.setSpacing(1)
        readout.addWidget(self.readout_month)
        readout.addWidget(self.readout)
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addLayout(names, 1)
        head.addLayout(readout)
        self.bars = BarsChart()
        self.rates = RatesBars()
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)
        box.addLayout(head)
        box.addWidget(self.bars, 1)
        box.addWidget(self.rates, 1)


class ReportView(QWidget):
    opened = Signal(str, int)
    reset_requested = Signal()

    def __init__(self, views: QWidget | None = None):
        """views: the report's switch (« Par mois | Par groupe »), set above the table."""
        super().__init__()
        self.report: Report | None = None
        self._natural: list[int] = []  # each column's width for its content
        self._height = 0  # the table's rows and header, without a sideways scroll bar
        self._wide: int | None = None  # the column that takes the room left
        self._filtered = False  # filters other than the first ones: the empty state resets

        self.tiles = [Tile() for _ in range(4)]
        self._kpis = QGridLayout()
        self._kpis.setSpacing(KPI_GAP)
        self._kpis.setContentsMargins(0, 0, 0, 0)
        kpi_box = QWidget()
        kpi_box.setLayout(self._kpis)
        self.chart = ChartBlock()
        self.chart.bars.hovered.connect(self._show_month)
        self.chart.rates.hovered.connect(self._show_group)
        summary = QHBoxLayout()
        summary.setContentsMargins(SHEET_PAD, 4, SHEET_PAD, 24)
        summary.setSpacing(28)
        # At the top, as tall as they need: beside a long chart they do not stretch.
        summary.addWidget(kpi_box, 2, Qt.AlignmentFlag.AlignTop)
        summary.addWidget(self.chart, 3)
        self._summary = summary

        self.table = ruled_table([], sortable=True)
        self.table.setObjectName("reportTable")
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.table.activated.connect(self._open)  # a double-click, or Enter
        # The viewport, not the table: it also widens when the table's own scroll bar goes.
        # Kept here: at the app's end the table may be gone while its viewport still talks.
        self._viewport = self.table.viewport()
        self._viewport.installEventFilter(self)
        self.total = TotalBar(self.table)
        self.count = caption()
        self.count.setObjectName("tableCount")
        self.hint = caption()
        counts = QHBoxLayout()
        counts.setSpacing(14)
        if views is not None:
            counts.addWidget(views)
        counts.addWidget(self.count)
        counts.addStretch()
        counts.addWidget(self.hint)
        self.empty = EmptyState("funnel")
        self.empty.setMinimumHeight(220)
        self.empty.action.clicked.connect(self.reset_requested.emit)
        table_box = QVBoxLayout()
        table_box.setContentsMargins(SHEET_PAD, 16, SHEET_PAD, 24)
        table_box.setSpacing(0)
        table_box.addLayout(counts)
        table_box.addSpacing(10)
        table_box.addWidget(self.empty)
        table_box.addWidget(self.table)
        table_box.addWidget(self.total)
        self.note = NoteBlock()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(summary)
        layout.addWidget(rule())
        layout.addLayout(table_box)
        layout.addWidget(self.note)

    # the parts as the tests and the page know them
    @property
    def bars(self) -> BarsChart:
        return self.chart.bars

    @property
    def rates(self) -> RatesBars:
        return self.chart.rates

    @property
    def readout(self) -> QLabel:
        return self.chart.readout

    @property
    def readout_month(self) -> QLabel:
        return self.chart.readout_month

    # ----- showing a report -----

    def show_report(self, report: Report) -> None:
        self.report = report
        for widget, tile in zip(self.tiles, report.tiles, strict=False):
            widget.show_tile(tile)
        for i, widget in enumerate(self.tiles):
            widget.setVisible(i < len(report.tiles))
        charted = self._show_chart(report)
        self._place_tiles(charted)
        self._show_table(report)
        self.note.setText(report.note)
        self.note.setVisible(bool(report.note))

    def _place_tiles(self, charted: bool) -> None:
        """Two by two beside a chart; four in a row without one."""
        columns = 2 if charted else 4
        for i, tile in enumerate(self.tiles):
            self._kpis.addWidget(tile, i // columns, i % columns)
        for c in range(4):
            self._kpis.setColumnStretch(c, 1 if c < columns else 0)
        self._summary.setStretch(0, 2 if charted else 1)
        self._summary.setStretch(1, 3 if charted else 0)

    def set_filtered(self, filtered: bool) -> None:
        """Filters other than the first ones: an empty report offers to reset them."""
        self._filtered = filtered
        self._show_empty()

    def _show_empty(self) -> None:
        self.empty.set_message(
            t["reports.empty"],
            t["reports.empty_filtered" if self._filtered else "reports.empty_hint"],
            t["reports.reset_filters"] if self._filtered else "")

    def _show_chart(self, report: Report) -> bool:
        chart = report.chart
        has_values = chart is not None and any(v for _n, values in chart.series for v in values)
        self.chart.setVisible(has_values)
        if not has_values:
            return False
        block = self.chart
        block.title.setText(chart.title)
        bars = chart.kind == "bars"
        block.bars.setVisible(bars)
        block.rates.setVisible(not bars)
        if bars:
            block.bars.set_data(chart.labels, chart.series, self._latest(chart))
            block.subtitle.setText(t["reports.chart.hover"])
            self._show_month(-1)
        else:
            block.rates.set_data(chart.labels, chart.series[0][1])
            count = len(chart.labels)
            block.subtitle.setText(
                t["reports.rates.lowest"].format(shown=RatesBars.LIMIT, count=count)
                if count > RatesBars.LIMIT else t["reports.rates.hover"])
            self._show_group(-1)
        return True

    @staticmethod
    def _latest(chart) -> int:
        """The last label with a figure: the month the readout shows by default."""
        for i in reversed(range(len(chart.labels))):
            if any(values[i] for _name, values in chart.series):
                return i
        return -1

    def _show_group(self, _index: int) -> None:
        """The group picked on the chart (under the mouse, else the lowest): its whole
        title, its rate in its band's colour."""
        rates = self.rates
        index = rates.picked()
        if index < 0:
            self.readout_month.clear()
            self.readout.clear()
            return
        value = rates.values[index]
        tone = rate_tone(value)
        color = tokens()["text" if tone == "success" else tone]
        self.readout_month.setText(rates.labels[index])
        self.readout.setText(f'<b style="color:{color}">{format_percent(value)}</b>')

    def _show_month(self, _index: int) -> None:
        """The month picked on the chart (under the mouse, else the latest), each series'
        figure after a dot in its colour."""
        chart = self.report.chart if self.report else None
        index = self.bars.picked()
        if chart is None or index < 0:
            self.readout_month.clear()
            self.readout.clear()
            return
        muted = tokens()["muted"]
        self.readout_month.setText(capitalized(chart.labels[index]))
        self.readout.setText(" &nbsp;&nbsp; ".join(
            f'<span style="color:{color.name()}">●</span>'
            f' <span style="color:{muted}">{name}</span> &nbsp;<b>{format_dzd(values[index])}</b>'
            for color, (name, values) in zip(series_colors(), chart.series, strict=False)))

    def _show_table(self, report: Report) -> None:
        columns = report.columns
        table = self.table
        table.setSortingEnabled(False)
        table.setColumnCount(len(columns))
        # The amounts' columns say « DA » once, under the sheet's title: the PDF and Excel
        # say it in each title, where there is room.
        table.setHorizontalHeaderLabels([c.title for c in columns])
        for c, column in enumerate(columns):
            table.horizontalHeaderItem(c).setTextAlignment(
                RIGHT if column.kind in NUMERIC else LEFT)
        rows = []
        for r, row in enumerate(report.rows):
            tone = report.tones[r] if r < len(report.tones) else None
            row_id = report.row_ids[r] if r < len(report.row_ids) else None
            rows.append([self._cell(value, column, tone if c == len(row) - 1 else None,
                                    row_id if c == 0 else None)
                         for c, (value, column) in enumerate(zip(row, columns, strict=True))])
        fill(table, rows)
        table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        table.setSortingEnabled(True)
        # The total first: its bold figures are wider, the columns are measured with them.
        self.total.setVisible(report.total is not None and bool(report.rows))
        if report.total is not None:
            self.total.show_total([self._cell(value, column) for value, column
                                   in zip(report.total, columns, strict=True)], report.total)
        self._fit(report)
        shown = min(max(len(report.rows), 1), MAX_TABLE_ROWS)
        self._height = table.horizontalHeader().sizeHint().height() + 2 + shown * ROW_HEIGHT
        table.setFixedHeight(self._height)
        table.setVisible(bool(report.rows))
        self.empty.setVisible(not report.rows)
        self.count.setText(plural("reports.rows", len(report.rows)))
        self.hint.setText(t[f"reports.open_hint.{report.opens}"]
                          if report.opens and report.rows else "")
        if not report.rows:
            self._show_empty()

    def _fit(self, report: Report) -> None:
        """Each column measured once for its content; the text column with the longest
        values is the one that gives or takes room (_spread)."""
        table = self.table
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        for c in range(len(report.columns)):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
        # Qt keeps a square as tall as the header for the sort arrow, on every column: a
        # column of short figures came out some 20 px wider than its title, and the table
        # scrolled sideways. The arrow needs half of it (Qt draws it half the height wide).
        arrow_square = header.sizeHint().height() // 2
        total = report.total is not None
        self._natural = [max(table.sizeHintForColumn(c),
                             header.sectionSizeFromContents(c).width() - arrow_square,
                             self._total_width(c) if total else 0)
                         for c in range(len(report.columns))]
        longest = {c: max((len(str(row[c])) for row in report.rows if row[c] is not None),
                          default=0)
                   for c, column in enumerate(report.columns) if column.kind == "text"}
        self._wide = max(longest, key=longest.get) if longest else None
        self._spread()

    def _total_width(self, c: int) -> int:
        """The total's cell in column c, bold; the label spanning the first columns counts
        in none of them (the names under it are wider)."""
        if self.total.columnSpan(0, c) > 1 or (c > 0 and self.total.columnSpan(0, 0) > c):
            return 0
        return self.total.sizeHintForColumn(c)

    def _spread(self) -> None:
        """The columns on the table's width: the wide one takes what is left; short of
        room, it keeps WIDE_MIN to WIDE_MAX (« … », the tooltip says it whole) and the
        table scrolls sideways, its total with it."""
        if not self._natural:
            return
        room = self.table.viewport().width()
        widths = list(self._natural)
        wide = self._wide if self._wide is not None else len(widths) - 1
        others = sum(widths) - widths[wide]
        if sum(widths) > room and self._wide is not None:
            widths[wide] = max(min(widths[wide], WIDE_MAX, room - others), WIDE_MIN)
        widths[wide] += max(room - sum(widths), 0)
        for c, width in enumerate(widths):
            self.table.setColumnWidth(c, width)
        # Scrolling sideways, the bar takes room under the rows: the table grows by it
        # rather than scroll a short list up and down.
        bar = self.table.horizontalScrollBar().sizeHint().height()
        self.table.setFixedHeight(self._height + (bar if sum(widths) > room else 0))

    def eventFilter(self, watched, event) -> bool:
        if watched is self._viewport and event.type() == QEvent.Type.Resize:
            self._spread()
        return super().eventFilter(watched, event)

    @staticmethod
    def _cell(value, column: ReportColumn, tone: str | None = None,
              row_id: int | None = None):
        number = column.kind in NUMERIC
        quiet = number and not value  # 0, or nothing: faint, the figures that count stand out
        cell = item(display(column.kind, value),
                    sort_key=(value if value is not None else -1) if number or
                    column.kind == "date" else None,
                    align=RIGHT if number else LEFT, tone=tone or ("faint" if quiet else None),
                    item_id=row_id)
        if number or column.kind == "date":
            cell.setFont(tabular())
        if value is None and not number:
            cell.setForeground(QColor(tokens()["faint"]))  # « — »
        return cell

    def _open(self, index) -> None:
        if self.report is None or self.report.opens is None:
            return
        row_id = self.table.item(index.row(), 0).data(ID_ROLE)
        if row_id is not None:
            self.opened.emit(self.report.opens, row_id)
