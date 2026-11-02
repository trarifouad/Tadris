"""What every report shows, in the same frame: four figures, a chart when the report has one,
then the table in a card (its views on the right of its title, « Par mois | Par groupe »),
sortable, the total in a strip under it that stays in place, and how it is counted.
`opened(page, id)`: a row was double-clicked or Enter pressed on it (a student, a
group, a teacher)."""

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QSizePolicy,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from tadris.core.cells import NUMERIC, display, tile_text
from tadris.core.money import format_dzd
from tadris.domain.models import Report, ReportColumn, ReportTile
from tadris.i18n.fr import t
from tadris.ui.pages.dashboard import PAD, Card, label
from tadris.ui.pages.reports.charts import BarsChart, RatesChart, series_colors
from tadris.ui.widgets.compact import Segments
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

MAX_TABLE_ROWS = 14  # taller than this, the table scrolls inside its card
WIDE_MIN, WIDE_MAX = 160, 260  # the widest text column when the window is short of room


class Tile(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        self.name = caption()
        self.value = label("", "bigNumber")
        self.note = caption()
        self.note.setWordWrap(True)
        box = QVBoxLayout(self)
        box.setContentsMargins(PAD, 14, PAD, 14)
        box.setSpacing(2)
        box.addWidget(self.name)
        box.addWidget(self.value)
        box.addWidget(self.note)
        box.setAlignment(Qt.AlignmentFlag.AlignTop)  # a short note: the figure stays level

    def show_tile(self, tile: ReportTile) -> None:
        self.name.setText(tile.label)
        self.value.setText(tile_text(tile))
        self.note.setText(tile.note)


class TotalBar(QTableWidget):
    """The report's total, one row under the table, column for column (it follows the
    table's widths); it stays at the bottom whatever the table's order."""

    def __init__(self, table: QTableWidget):
        super().__init__(1, 0)
        self.setObjectName("totalBar")
        self._table = table
        self.horizontalHeader().hide()
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.setShowGrid(False)
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
            font.setWeight(font.Weight.DemiBold)
            cell.setFont(font)
            self.setItem(0, c, cell)
            self.setColumnWidth(c, self._table.columnWidth(c))


class ReportView(QWidget):
    opened = Signal(str, int)
    view_changed = Signal(int)

    def __init__(self, views: list[str] | None = None):
        super().__init__()
        self.report: Report | None = None
        self._natural: list[int] = []  # each column's width for its content
        self._height = 0  # the table's rows and header, without a sideways scroll bar
        self._wide: int | None = None  # the column that takes the room left
        self.tiles = [Tile() for _ in range(4)]
        grid = QGridLayout()
        grid.setSpacing(16)
        for i, tile in enumerate(self.tiles):
            grid.addWidget(tile, 0, i)
            grid.setColumnStretch(i, 1)

        self.chart_card = Card("")
        self.readout = caption()
        self.readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.chart_card.side.addWidget(self.readout)
        self.bars = BarsChart()
        self.bars.hovered.connect(self._show_month)
        self.rates = RatesChart()
        chart_box = QVBoxLayout()
        chart_box.setContentsMargins(PAD, 0, PAD, 16)
        chart_box.addWidget(self.bars)
        chart_box.addWidget(self.rates)
        self.chart_card.body.addLayout(chart_box)

        self.table_card = Card("")
        self.views = Segments(views) if views else None
        if self.views is not None:
            self.views.changed.connect(self.view_changed.emit)
            self.table_card.side.addWidget(self.views)
        self.table = ruled_table([], sortable=True)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.table.activated.connect(self._open)  # a double-click, or Enter
        # The viewport, not the table: it also widens when the table's own scroll bar goes.
        # Kept here: at the app's end the table may be gone while its viewport still talks.
        self._viewport = self.table.viewport()
        self._viewport.installEventFilter(self)
        self.total = TotalBar(self.table)
        self.empty = caption(t["reports.empty"])
        self.note = caption()
        self.note.setWordWrap(True)
        table_box = QVBoxLayout()
        table_box.setContentsMargins(PAD, 0, PAD, 16)
        table_box.setSpacing(6)
        table_box.addWidget(self.empty)
        table_box.addWidget(self.table)
        table_box.addWidget(self.total)
        table_box.addSpacing(4)
        table_box.addWidget(self.note)
        self.table_card.body.addLayout(table_box)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addLayout(grid)
        layout.addWidget(self.chart_card)
        layout.addWidget(self.table_card)
        layout.addStretch()

    # ----- showing a report -----

    def show_report(self, report: Report) -> None:
        self.report = report
        for widget, tile in zip(self.tiles, report.tiles, strict=False):
            widget.show_tile(tile)
        for i, widget in enumerate(self.tiles):
            widget.setVisible(i < len(report.tiles))
        self._show_chart(report)
        self.table_card.title.setText(report.title)
        money = any(column.kind == "money" for column in report.columns)
        self.table_card.set_subtitle(t["reports.amounts_in_da"].format(period=report.period)
                                     if money else report.period)
        self._show_table(report)
        self.note.setText(report.note)
        self.note.setVisible(bool(report.note))

    def _show_chart(self, report: Report) -> None:
        chart = report.chart
        has_values = chart is not None and any(v for _n, values in chart.series for v in values)
        self.chart_card.setVisible(has_values)
        if not has_values:
            return
        self.chart_card.title.setText(chart.title)
        self.bars.setVisible(chart.kind == "bars")
        self.rates.setVisible(chart.kind == "rates")
        if chart.kind == "bars":
            self.bars.set_data(chart.labels, chart.series)
            self._legend(chart)
        else:
            self.rates.set_data(chart.labels, chart.series[0][1])
            self.chart_card.set_subtitle("")
            self.readout.clear()

    def _legend(self, chart) -> None:
        """The series' names in their colours, under the chart's title."""
        dots = " &nbsp; ".join(
            f'<span style="color:{color.name()}">●</span> {name}'
            for color, (name, _values) in zip(series_colors(), chart.series, strict=False))
        self.chart_card.set_subtitle(dots)
        self._show_month(-1)

    def _show_month(self, index: int) -> None:
        """The month under the mouse, its figures on the chart's right."""
        chart = self.report.chart if self.report else None
        if chart is None or index < 0:
            self.readout.setText(t["reports.chart.hover"])
            return
        values = " · ".join(f"{name} {format_dzd(values[index])}"
                            for name, values in chart.series)
        self.readout.setText(f"<b>{chart.labels[index]}</b> &nbsp; {values}")

    def _show_table(self, report: Report) -> None:
        columns = report.columns
        table = self.table
        table.setSortingEnabled(False)
        table.setColumnCount(len(columns))
        # The amounts' columns say « DA » once, by the period: the PDF and Excel say it in
        # each title, where there is room.
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
        self._fit(report)
        shown = min(max(len(report.rows), 1), MAX_TABLE_ROWS)
        self._height = table.horizontalHeader().sizeHint().height() + 2 + shown * ROW_HEIGHT
        table.setFixedHeight(self._height)
        table.setVisible(bool(report.rows))
        self.empty.setVisible(not report.rows)
        self.total.setVisible(report.total is not None)
        if report.total is not None:
            self.total.show_total([self._cell(value, column) for value, column
                                   in zip(report.total, columns, strict=True)], report.total)

    def _fit(self, report: Report) -> None:
        """Each column measured once for its content; the text column with the longest
        values is the one that gives or takes room (_spread)."""
        table = self.table
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        for c in range(len(report.columns)):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
        table.resizeColumnsToContents()
        self._natural = [table.columnWidth(c) for c in range(len(report.columns))]
        longest = {c: max((len(str(row[c])) for row in report.rows if row[c] is not None),
                          default=0)
                   for c, column in enumerate(report.columns) if column.kind == "text"}
        self._wide = max(longest, key=longest.get) if longest else None
        self._spread()

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
        return item(display(column.kind, value),
                    sort_key=(value if value is not None else -1) if number or
                    column.kind == "date" else None,
                    align=RIGHT if number else LEFT, mono=number, tone=tone,
                    item_id=row_id)

    def _open(self, index) -> None:
        if self.report is None or self.report.opens is None:
            return
        row_id = self.table.item(index.row(), 0).data(ID_ROLE)
        if row_id is not None:
            self.opened.emit(self.report.opens, row_id)

    def select_view(self, index: int) -> None:
        if self.views is not None:
            self.views.buttons[index].setChecked(True)


def grid_row(*widgets: QWidget) -> QHBoxLayout:
    """Filters in a line, from the left."""
    line = QHBoxLayout()
    line.setSpacing(12)
    for widget in widgets:
        line.addWidget(widget, 0, Qt.AlignmentFlag.AlignBottom)
    line.addStretch()
    return line

