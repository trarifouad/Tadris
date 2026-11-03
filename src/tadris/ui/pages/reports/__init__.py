"""Rapports, as one sheet of paper: what is on screen is what the PDF prints.

The top bar: the page's name and the reports the user may see in a switch (none for one
report alone: the desk sees Présences). Under it, one white sheet: its header names the report and its
period, with « Enregistrer sous… », « PDF » and « Excel » on the right (they write exactly
the report on screen: in the documents folder, then opened; or a file of one's own, kept).
Then the chosen report's filters as chips, its figures, chart and table (panels.py,
view.py; the files: exporting.py). A row double-clicked opens the student, the group or
the teacher (`open_item`). The students' list is printed from the Élèves page."""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tadris.core.context import UserContext
from tadris.i18n.fr import t
from tadris.services import reports
from tadris.ui.pages.dashboard import CONTENT_MAX, TOPBAR_HEIGHT, label, link
from tadris.ui.pages.reports.exporting import ask_path, export_button, write_report
from tadris.ui.pages.reports.panels import PANELS, Panel
from tadris.ui.pages.reports.view import SHEET_PAD
from tadris.ui.widgets.common import PageBanner
from tadris.ui.widgets.compact import Segments
from tadris.ui.widgets.forms import caption


class PanelSwitch(QWidget):
    """The reports one at a time, the others hidden: as tall as the one shown. A
    QStackedWidget keeps the height of the tallest page it has shown (wrapped text gives
    each a height for its width), and a short report's figures stretched into it."""

    def __init__(self):
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._panels: list[QWidget] = []
        self._current: QWidget | None = None

    def addWidget(self, panel: QWidget) -> None:
        """The first one added is shown until another is chosen."""
        self._panels.append(panel)
        self._layout.addWidget(panel)
        if self._current is None:
            self._current = panel
        panel.setVisible(panel is self._current)

    def setCurrentWidget(self, panel: QWidget) -> None:
        self._current = panel
        for other in self._panels:
            other.setVisible(other is panel)

    def currentWidget(self) -> QWidget | None:
        return self._current


class ReportsPage(QWidget):
    open_item = Signal(str, int)

    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self.setObjectName("page")
        self._conn, self._ctx = conn, ctx
        self.keys = reports.available(ctx)
        self.panels: dict[str, Panel] = {}
        self.tabs = Segments([t[f"reports.nav.{key}"] for key in self.keys] or [""])
        self.tabs.changed.connect(lambda index: self.show_report(self.keys[index]))
        self.stack = PanelSwitch()
        for key in self.keys:
            panel = PANELS[key](conn, ctx)
            panel.opened.connect(self.open_item.emit)
            panel.shown.connect(lambda shown=panel: self._show_head(shown))
            self.panels[key] = panel
            self.stack.addWidget(panel)
        self.banner = PageBanner()

        sheet = QFrame()
        sheet.setObjectName("sheet")
        body = QVBoxLayout(sheet)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._sheet_head())
        banner_box = QVBoxLayout()
        banner_box.setContentsMargins(SHEET_PAD, 0, SHEET_PAD, 0)
        banner_box.addWidget(self.banner)
        body.addLayout(banner_box)
        body.addWidget(self.stack)

        content = QWidget()
        content.setMaximumWidth(CONTENT_MAX)
        inner = QVBoxLayout(content)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.addWidget(sheet)
        inner.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        holder.setObjectName("page")
        line = QHBoxLayout(holder)
        line.setContentsMargins(24, 20, 24, 24)
        line.addWidget(content, 1)
        line.addStretch()
        scroll.setWidget(holder)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._top_bar())
        layout.addWidget(scroll, 1)
        if self.keys:
            self.show_report(self.keys[0])

    def _top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topbar")
        bar.setFixedHeight(TOPBAR_HEIGHT)
        line = QHBoxLayout(bar)
        line.setContentsMargins(24, 0, 24, 0)
        line.setSpacing(8)
        line.addWidget(label(t["nav.reports"], "topbarTitle"))
        line.addSpacing(16)
        line.addWidget(self.tabs, 0, Qt.AlignmentFlag.AlignVCenter)
        self.tabs.setVisible(len(self.keys) > 1)  # one report: nothing to switch
        line.addStretch()
        return bar

    def _sheet_head(self) -> QWidget:
        """The report's name and period; its exports on the right."""
        head = QWidget()
        line = QHBoxLayout(head)
        line.setContentsMargins(SHEET_PAD, 20, SHEET_PAD, 4)
        line.setSpacing(8)
        self.title = label("", "sheetTitle")
        self.period = caption()
        self.period.setObjectName("sheetPeriod")
        names = QVBoxLayout()
        names.setSpacing(2)
        names.addWidget(self.title)
        names.addWidget(self.period)
        line.addLayout(names, 1)
        self.save_as = link(t["reports.save_as"])
        self.save_as.clicked.connect(self._save_as)
        self.pdf = export_button(t["reports.export_pdf"], "file-text")
        self.pdf.clicked.connect(lambda: self.export("pdf"))
        self.excel = export_button(t["reports.export_xlsx"], "sheet")
        self.excel.clicked.connect(lambda: self.export("xlsx"))
        line.addWidget(self.save_as, 0, Qt.AlignmentFlag.AlignVCenter)
        line.addSpacing(8)
        line.addWidget(self.pdf, 0, Qt.AlignmentFlag.AlignVCenter)
        line.addWidget(self.excel, 0, Qt.AlignmentFlag.AlignVCenter)
        return head

    # ----- the reports -----

    def current(self) -> Panel | None:
        widget = self.stack.currentWidget()
        return widget if isinstance(widget, Panel) else None

    def show_report(self, key: str) -> None:
        self.tabs.buttons[self.keys.index(key)].setChecked(True)
        self.stack.setCurrentWidget(self.panels[key])
        self.panels[key].refresh()
        self._show_head(self.panels[key])

    def _show_head(self, panel: Panel) -> None:
        """The sheet's title and period: the report shown, or the report's name while it
        cannot be built (no school year yet). The exports need a report."""
        if panel is not self.current():
            return
        report = panel.report
        key = next(k for k, p in self.panels.items() if p is panel)
        self.title.setText(report.title if report else t[f"reports.nav.{key}"])
        if report is None:
            self.period.clear()
        else:
            money = any(column.kind == "money" for column in report.columns)
            self.period.setText(t["reports.amounts_in_da"].format(period=report.period)
                                if money else report.period)
        for button in (self.pdf, self.excel, self.save_as):
            button.setEnabled(report is not None)

    def refresh(self) -> None:
        """The page shown again: other pages may have changed the figures."""
        panel = self.current()
        if panel is not None:
            panel.refresh()

    # ----- exports -----

    def export(self, fmt: str, path: Path | None = None) -> Path | None:
        """The report on screen as a file, opened at once unless saved elsewhere."""
        panel = self.current()
        if panel is None or panel.report is None:
            return None
        return write_report(self, self._conn, self._ctx, panel.report, fmt, self.banner, path)

    def _save_as(self) -> None:
        panel = self.current()
        if panel is None or panel.report is None:
            return
        chosen = ask_path(self, panel.report.key)
        if chosen is not None:
            self.export(*chosen)
