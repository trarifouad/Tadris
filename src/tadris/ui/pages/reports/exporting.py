"""A report written to a file, from any page that shows one (Rapports, Élèves): « PDF » and
« Excel » write exactly what is on screen in the documents folder, then open it;
« Enregistrer sous… » writes it where the user chooses, and keeps it there unopened."""

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QFileDialog, QPushButton, QWidget

from tadris import config
from tadris.core.errors import BusinessRuleError
from tadris.domain.models import Report
from tadris.i18n.fr import t
from tadris.services import reports
from tadris.ui.theme import icon
from tadris.ui.widgets.common import PageBanner, open_document, toast


def export_button(text: str, icon_name: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("sheetAction")
    button.setIcon(icon(icon_name, "text", size=40, gap=14))
    button.setIconSize(QSize(23, 16))  # 16 px drawn, 7 px before the label
    button.setAutoDefault(False)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setToolTip(t["reports.export_tip"])
    return button


def write_report(page: QWidget, conn, ctx, report: Report, fmt: str, banner: PageBanner,
                 path: Path | None = None) -> Path | None:
    """The report as a file, opened at once unless saved elsewhere; a failure in `banner`."""
    banner.clear_error()
    try:
        written = reports.export(conn, ctx, report, fmt, path)
    except BusinessRuleError as exc:
        banner.show_error(exc.message)
        return None
    except OSError as exc:  # a file open in Excel, a folder one may not write to
        banner.show_error(t["reports.export_failed"].format(error=exc.strerror or exc))
        return None
    if path is None:
        open_document(written)
    toast(page, t["reports.saved"].format(name=written.name))
    return written


def ask_path(page: QWidget, key: str) -> tuple[str, Path] | None:
    """« Enregistrer sous… »: the format and the file chosen (the report's `key` its first
    name), its extension made right."""
    start = config.documents_dir() / key
    chosen, picked = QFileDialog.getSaveFileName(
        page, t["reports.save_title"], str(start), t["reports.file_filter"])
    if not chosen:
        return None
    path = Path(chosen)
    fmt = "xlsx" if path.suffix.lower() == ".xlsx" or (
        not path.suffix and "xlsx" in picked) else "pdf"
    if path.suffix.lower() != reports.FORMATS[fmt]:
        path = path.with_suffix(reports.FORMATS[fmt])
    return fmt, path
