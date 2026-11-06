"""A report as an Excel workbook. Its sheet: the title, the school and the period, the filters
and the key figures on a line each, then the table with real numbers, rates and dates (Excel
sums and filters them), its header frozen and filtered, and the total, whose sums follow
Excel's filters (SUBTOTAL). A second sheet, « Infos », says what was shown and by whom."""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from tadris.core.cells import NUMERIC, excel_value, header, tile_text
from tadris.domain.models import Report
from tadris.i18n.fr import t

FORMATS = {
    "number": "#,##0",
    "money": '#,##0 "DA"',
    "percent": "0.0%",
    "date": "DD/MM/YYYY",
}
WIDTHS = {"number": 11, "money": 16, "percent": 11, "date": 12}
TEXT_MIN, TEXT_MAX = 10, 60  # characters: a longer text wraps inside its cell
HEADER_ROW = 6
SHEET_TITLE_MAX = 31  # Excel's limit
SUM_KINDS = ("number", "money")  # the total of these columns is a SUBTOTAL formula
MUTED = "5A5868"
SHADE = "EFEDF5"


def _width(report: Report, index: int) -> float:
    """Text columns as wide as their longest value (or header), up to TEXT_MAX."""
    column = report.columns[index]
    if column.kind != "text":
        return max(WIDTHS[column.kind], len(header(column)) + 2)
    rows = list(report.rows) + ([report.total] if report.total is not None else [])
    longest = max([len(header(column))] + [len(str(row[index])) for row in rows
                                           if row[index] is not None])
    return min(max(longest + 2, TEXT_MIN), TEXT_MAX)


def _text(cell) -> None:
    """Typed text stays text: « =… » would otherwise be a formula, run on the director's
    computer."""
    if isinstance(cell.value, str):
        cell.data_type = "s"


def build_report_xlsx(report: Report, school: str, printed: str, path: Path) -> Path:
    book = Workbook()
    sheet = book.active
    sheet.title = report.title[:SHEET_TITLE_MAX]
    lines = [
        (report.title, Font(bold=True, size=14)),
        (f"{school} · {report.period}" if school else report.period,
         Font(italic=True, color=MUTED)),
        (" · ".join(f"{name} : {value}" for name, value in report.filters),
         Font(color=MUTED)),
        (" · ".join(f"{tile.label} : {tile_text(tile)}" for tile in report.tiles),
         Font(bold=True)),
    ]
    for row, (text, font) in enumerate(lines, start=1):
        if not text:  # no filters, or no figures (the students' list)
            continue
        cell = sheet.cell(row=row, column=1, value=text)
        cell.font = font
        _text(cell)

    shade = PatternFill("solid", fgColor=SHADE)
    for index, column in enumerate(report.columns, start=1):
        cell = sheet.cell(row=HEADER_ROW, column=index, value=header(column))
        cell.font = Font(bold=True)
        cell.fill = shade
        cell.alignment = Alignment(horizontal="right" if column.kind in NUMERIC else "left",
                                   vertical="center", wrap_text=True)
        sheet.column_dimensions[get_column_letter(index)].width = _width(report, index - 1)

    first = HEADER_ROW + 1
    for row, values in enumerate(report.rows, start=first):
        for index, (column, value) in enumerate(zip(report.columns, values, strict=True),
                                                start=1):
            cell = sheet.cell(row=row, column=index, value=excel_value(column.kind, value))
            _text(cell)
            if column.kind in FORMATS:
                cell.number_format = FORMATS[column.kind]
            elif isinstance(cell.value, str) and len(cell.value) > TEXT_MAX:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
    last = first + len(report.rows) - 1
    total_row = last + 1
    if report.total is not None:
        for index, (column, value) in enumerate(zip(report.columns, report.total, strict=True),
                                                start=1):
            letter = get_column_letter(index)
            if column.kind in SUM_KINDS and value is not None and report.rows:
                cell = sheet.cell(row=total_row, column=index,
                                  value=f"=SUBTOTAL(9,{letter}{first}:{letter}{last})")
            else:
                cell = sheet.cell(row=total_row, column=index,
                                  value=excel_value(column.kind, value))
                _text(cell)
            if column.kind in FORMATS:
                cell.number_format = FORMATS[column.kind]
            cell.font = Font(bold=True)
            cell.border = Border(top=Side(style="thin"))
    if report.note:
        note = sheet.cell(row=total_row + 2, column=1, value=report.note)
        note.font = Font(italic=True, color=MUTED)
        _text(note)
    sheet.freeze_panes = sheet.cell(row=first, column=1)
    if report.rows:
        sheet.auto_filter.ref = (f"A{HEADER_ROW}:{get_column_letter(len(report.columns))}"
                                 f"{last}")
    sheet.page_setup.orientation = "landscape" if len(report.columns) > 6 else "portrait"
    sheet.page_setup.fitToWidth = 1
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.print_title_rows = f"{HEADER_ROW}:{HEADER_ROW}"

    about = book.create_sheet(t["reports.xlsx.about"])
    facts = [(t["reports.xlsx.report"], report.title), (t["reports.xlsx.period"], report.period)]
    facts += list(report.filters)
    facts += [(t["reports.xlsx.rows"], len(report.rows)), (t["reports.xlsx.made"], printed)]
    for row, (name, value) in enumerate(facts, start=1):
        about.cell(row=row, column=1, value=name).font = Font(bold=True)
        _text(about.cell(row=row, column=2, value=value))
    about.column_dimensions["A"].width = 18
    about.column_dimensions["B"].width = 60
    book.save(path)
    return path

