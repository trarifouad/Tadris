"""A report on A4, black and white: the school, the title and period, the table with its
total, the note. Landscape when the table is wide."""

from dataclasses import dataclass
from html import escape
from pathlib import Path

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from tadris.core.cells import display
from tadris.documents.pdf import (
    INK,
    MARGIN,
    MONO,
    MUTED,
    RULE,
    SHADE,
    Footer,
    School,
    register_fonts,
    style,
)
from tadris.domain.models import ReportTable

LANDSCAPE_FROM = 7  # columns
_NUMERIC = ("number", "money", "percent")
_PLAIN = _NUMERIC + ("date", "datetime")  # one line, in the mono font: never wrapped
# Relative widths: text columns get more room than numbers and dates.
_WEIGHT = {"text": 2.2, "number": 1.0, "money": 1.4, "percent": 1.1, "date": 1.4,
           "datetime": 1.9}


@dataclass(frozen=True)
class ReportDoc:
    school: School
    table: ReportTable
    footer: Footer


def _widths(report: ReportTable, usable: float) -> list[float]:
    """Numbers and dates by kind; a text column by its longest value (capped), so a long
    list of groups gets the room a student number does not need."""
    weights = []
    for index, column in enumerate(report.columns):
        if column.kind != "text":
            weights.append(_WEIGHT[column.kind])
            continue
        longest = max([len(column.label)] + [len(str(row[index] or "")) for row in report.rows])
        weights.append(min(max(longest / 9, 1.1), 3.6))
    scale = usable / sum(weights)
    return [w * scale for w in weights]


def build_report(doc: ReportDoc, path: Path) -> Path:
    register_fonts()
    report = doc.table
    pagesize = landscape(A4) if len(report.columns) >= LANDSCAPE_FROM else A4
    pdf = SimpleDocTemplate(str(path), pagesize=pagesize, leftMargin=MARGIN,
                            rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=16 * mm,
                            title=report.title, author=doc.school.name)
    usable = pagesize[0] - 2 * MARGIN
    contact = " · ".join(part for part in (doc.school.address, doc.school.phone) if part)
    story = [Paragraph(escape(doc.school.name), style(12, bold=True))]
    if contact:
        story.append(Paragraph(escape(contact), style(8.5, color=MUTED)))
    story += [Spacer(1, 4 * mm), Paragraph(escape(report.title), style(16, bold=True)),
              Paragraph(escape(report.period), style(10, color=MUTED)), Spacer(1, 5 * mm)]

    size = 8 if len(report.columns) >= LANDSCAPE_FROM else 9
    numeric = [c.kind in _NUMERIC for c in report.columns]
    plain = [c.kind in _PLAIN for c in report.columns]
    head = [Paragraph(escape(c.label), style(size - 0.5, bold=True, align=2 if n else 0))
            for c, n in zip(report.columns, numeric, strict=True)]

    def cells(row, bold=False):
        out = []
        for column, value, one_line in zip(report.columns, row, plain, strict=True):
            text = display(column.kind, value) if value is not None or not bold else ""
            out.append(text if one_line else Paragraph(escape(text), style(size, bold=bold)))
        return out

    data = [head] + [cells(row) for row in report.rows]
    if report.total is not None:
        data.append(cells(report.total, bold=True))
    table = Table(data, colWidths=_widths(report, usable), repeatRows=1)
    commands = [
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("BACKGROUND", (0, 0), (-1, 0), SHADE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for index, (is_number, one_line) in enumerate(zip(numeric, plain, strict=True)):
        if one_line:
            commands.append(("FONT", (index, 1), (index, -1), MONO, size))
        if is_number:
            commands.append(("ALIGN", (index, 0), (index, -1), "RIGHT"))
    if report.total is not None:
        commands.append(("LINEABOVE", (0, -1), (-1, -1), 0.9, INK))
    table.setStyle(TableStyle(commands))
    story.append(table)
    if not report.rows:
        story += [Spacer(1, 4 * mm), Paragraph(escape("—"), style(9, color=MUTED))]
    if report.note:
        story += [Spacer(1, 5 * mm), Paragraph(escape(report.note), style(8, color=MUTED))]
    pdf.build(story, onFirstPage=doc.footer.draw, onLaterPages=doc.footer.draw)
    return path
