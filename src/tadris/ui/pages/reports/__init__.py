"""Rapports. A top bar as on the dashboard: the page's name, the reports the user may see in
a switch (the desk: Présences and Élèves; the whole width stays for the tables), and on the
right « PDF » and « Excel », which write exactly the report on screen (in the documents
folder, then opened) and « Enregistrer sous… » (a file of one's own, kept). Under it the
chosen report: its filters, figures, chart and table (panels.py, view.py). A row
double-clicked opens the student, the group or the teacher (`open_item`)."""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from tadris import config
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError
from tadris.i18n.fr import t
from tadris.services import reports
from tadris.ui.pages.dashboard import CONTENT_MAX, TOPBAR_HEIGHT, label, link
from tadris.ui.pages.reports.panels import PANELS, Panel
from tadris.ui.widgets.common import PageBanner, open_document, toast
from tadris.ui.widgets.compact import Segments, follow_current


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
        self.stack = QStackedWidget()
        for key in self.keys:
            panel = PANELS[key](conn, ctx)
            panel.opened.connect(self.open_item.emit)
            self.panels[key] = panel
            self.stack.addWidget(panel)
        follow_current(self.stack)
        self.banner = PageBanner()

        content = QWidget()
        content.setMaximumWidth(CONTENT_MAX)
        inner = QVBoxLayout(content)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(12)
        inner.addWidget(self.banner)
        inner.addWidget(self.stack)
        inner.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        holder.setObjectName("page")
        line = QHBoxLayout(holder)
        line.setContentsMargins(24, 16, 24, 16)
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
        line.addStretch()
        self.save_as = link(t["reports.save_as"])
        self.save_as.clicked.connect(self._save_as)
        self.pdf = QPushButton(t["reports.export_pdf"])
        self.pdf.clicked.connect(lambda: self.export("pdf"))
        self.excel = QPushButton(t["reports.export_xlsx"])
        self.excel.clicked.connect(lambda: self.export("xlsx"))
        line.addWidget(self.save_as)
        line.addSpacing(8)
        for button in (self.pdf, self.excel):
            button.setAutoDefault(False)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(t["reports.export_tip"])
            line.addWidget(button)
        return bar

    # ----- the reports -----

    def current(self) -> Panel | None:
        widget = self.stack.currentWidget()
        return widget if isinstance(widget, Panel) else None

    def show_report(self, key: str) -> None:
        self.tabs.buttons[self.keys.index(key)].setChecked(True)
        self.stack.setCurrentWidget(self.panels[key])
        self.panels[key].refresh()

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
        self.banner.clear_error()
        try:
            written = reports.export(self._conn, self._ctx, panel.report, fmt, path)
        except BusinessRuleError as exc:
            self.banner.show_error(exc.message)
            return None
        except OSError as exc:  # a file open in Excel, a folder one may not write to
            self.banner.show_error(t["reports.export_failed"].format(error=exc.strerror or exc))
            return None
        if path is None:
            open_document(written)
        toast(self, t["reports.saved"].format(name=written.name))
        return written

    def _save_as(self) -> None:
        panel = self.current()
        if panel is None or panel.report is None:
            return
        start = config.documents_dir() / panel.report.key
        chosen, picked = QFileDialog.getSaveFileName(
            self, t["reports.save_title"], str(start), t["reports.file_filter"])
        if not chosen:
            return
        path = Path(chosen)
        fmt = "xlsx" if path.suffix.lower() == ".xlsx" or (
            not path.suffix and "xlsx" in picked) else "pdf"
        if path.suffix.lower() != reports.FORMATS[fmt]:
            path = path.with_suffix(reports.FORMATS[fmt])
        self.export(fmt, path)
