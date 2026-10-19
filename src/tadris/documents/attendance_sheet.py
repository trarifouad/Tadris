"""Attendance sheets: one session (portrait), or a group's week (landscape)."""

from dataclasses import dataclass, field
from html import escape
from pathlib import Path

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from tadris.documents.pdf import (
    FONT,
    FONT_BOLD,
    INK,
    MARGIN,
    MUTED,
    RULE,
    SHADE,
    Footer,
    School,
    register_fonts,
    style,
)

TICK = "X"  # every font has it
NUMBER = 22 * mm  # 2026-0016


@dataclass(frozen=True)
class SessionSheet:
    school: School
    title: str  # « Feuille de présence »
    heading: str  # the group
    details: list[str]  # date and hours, room and teacher
    columns: list[str]  # N°, Élève, Remarque, the four statuses, Observation
    rows: list[list[str]]  # one per student, the same columns
    footer: Footer
    empty: str = ""  # shown instead of the table when nobody is expected


@dataclass(frozen=True)
class WeekSheet:
    school: School
    title: str
    heading: str
    details: list[str]
    columns: list[str]  # N°, Élève, then one per session (markup: escape the parts)
    rows: list[list[str]]
    footer: Footer
    legend: str = ""
    empty: str = ""
    cancelled_columns: list[int] = field(default_factory=list)  # greyed: session cancelled


def _header(sheet) -> list:
    """Texts are escaped: a name with « & » or « < » must not break the paragraph markup."""
    school = sheet.school
    lines = [Paragraph(escape(school.name), style(13, bold=True))]
    contact = " · ".join(part for part in (school.address, school.phone) if part)
    if contact:
        lines.append(Paragraph(escape(contact), style(8.5, color=MUTED)))
    lines += [Spacer(1, 5 * mm), Paragraph(escape(sheet.title), style(15, bold=True)),
              Spacer(1, 1.5 * mm), Paragraph(escape(sheet.heading), style(11.5, bold=True))]
    lines += [Paragraph(escape(detail), style(9.5, color=MUTED)) for detail in sheet.details]
    return lines + [Spacer(1, 5 * mm)]


def _table(columns: list[str], rows: list[list[str]], widths: list[float],
           centered_from: int, extra: list | None = None) -> Table:
    data = [[Paragraph(c, style(8.5, bold=True)) for c in columns]] + rows  # columns: markup
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("FONT", (0, 1), (-1, -1), FONT, 9.5),
        ("FONT", (0, 0), (-1, 0), FONT_BOLD, 8.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("BACKGROUND", (0, 0), (-1, 0), SHADE),
        ("GRID", (0, 0), (-1, -1), 0.5, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (centered_from, 1), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [None, SHADE.clone(alpha=0.35)]),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        *(extra or []),
    ]))
    return table


def build_session_sheet(sheet: SessionSheet, path: Path) -> Path:
    register_fonts()
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=MARGIN, bottomMargin=16 * mm, title=sheet.title)
    usable = A4[0] - 2 * MARGIN
    mark = 17 * mm
    widths = [NUMBER, 0, 24 * mm, mark, mark, mark, mark, 36 * mm]
    widths[1] = usable - sum(widths)
    story = _header(sheet)
    if sheet.rows:
        story.append(_table(sheet.columns, sheet.rows, widths, centered_from=3))
    else:
        story.append(Paragraph(sheet.empty, style(10, color=MUTED)))
    doc.build(story, onFirstPage=sheet.footer.draw, onLaterPages=sheet.footer.draw)
    return path


def build_week_sheet(sheet: WeekSheet, path: Path) -> Path:
    register_fonts()
    size = landscape(A4)
    doc = SimpleDocTemplate(str(path), pagesize=size, leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=MARGIN, bottomMargin=16 * mm, title=sheet.title)
    usable = size[0] - 2 * MARGIN
    sessions = len(sheet.columns) - 2
    name = max(60 * mm, usable - NUMBER - sessions * 24 * mm)
    each = (usable - NUMBER - name) / max(sessions, 1)
    widths = [NUMBER, name] + [each] * sessions
    story = _header(sheet)
    if sheet.rows and sessions:
        grey = [("BACKGROUND", (c, 1), (c, -1), SHADE) for c in sheet.cancelled_columns]
        story.append(_table(sheet.columns, sheet.rows, widths, centered_from=2, extra=grey))
        if sheet.legend:
            story += [Spacer(1, 3 * mm), Paragraph(sheet.legend, style(8, color=MUTED))]
    else:
        story.append(Paragraph(sheet.empty, style(10, color=MUTED)))
    doc.build(story, onFirstPage=sheet.footer.draw, onLaterPages=sheet.footer.draw)
    return path
