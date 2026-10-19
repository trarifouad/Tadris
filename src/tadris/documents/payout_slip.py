"""A teacher's payout slip: A4 portrait, black and white. The groups (one line per group and
rate), the total, then every month counted, student by student; signed by the teacher."""

from dataclasses import dataclass
from html import escape
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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
from tadris.documents.receipt import details_table, header_table, signature_table


@dataclass(frozen=True)
class PayoutSlip:
    school: School
    title: str  # « Paiement enseignant »
    number: str  # PE2026-00001 once paid, else the status (« BROUILLON »)
    copy_mark: str  # « DUPLICATA » on a reprint, else ""
    details: list[tuple[str, str]]  # teacher, period, status, decisions
    group_columns: list[str]  # Groupe, Élèves, Mois, Recettes, Taux, Montant
    group_rows: list[list[str]]
    total_label: str
    total: str
    detail_title: str
    detail_columns: list[str]  # Élève, Groupe, Mois, Prix, Taux, Part
    detail_rows: list[list[str]]
    note: str  # how the share is computed
    stamp: str  # PAYÉ, APPROUVÉ or BROUILLON
    stamp_date: str
    signature: str
    footer: Footer


def _table(columns: list[str], rows: list[list[str]], widths: list[float], numbers_from: int,
           total: tuple[str, str] | None = None) -> Table:
    head = [Paragraph(escape(c), style(8.5, bold=True, align=2 if i >= numbers_from else 0))
            for i, c in enumerate(columns)]
    body = [[Paragraph(escape(cell), style(9)) if i < numbers_from else cell
             for i, cell in enumerate(row)] for row in rows]
    data = [head] + body
    if total is not None:
        data.append([Paragraph(escape(total[0]), style(10, bold=True))]
                    + [""] * (len(columns) - 2) + [total[1]])
    table = Table(data, colWidths=widths, repeatRows=1)
    commands = [
        ("FONT", (numbers_from, 1), (-1, -1), MONO, 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("BACKGROUND", (0, 0), (-1, 0), SHADE),
        ("ALIGN", (numbers_from, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if total is not None:
        commands += [("LINEABOVE", (0, -1), (-1, -1), 0.9, INK),
                     ("FONT", (-1, -1), (-1, -1), MONO, 10),
                     ("SPAN", (0, -1), (-2, -1))]
    table.setStyle(TableStyle(commands))
    return table


def build_payout_slip(slip: PayoutSlip, path: Path) -> Path:
    register_fonts()
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=MARGIN, bottomMargin=16 * mm,
                            title=f"{slip.title} {slip.number}")
    usable = A4[0] - 2 * MARGIN
    number = 24 * mm
    groups = _table(slip.group_columns, slip.group_rows,
                    [usable - 5 * number] + [number] * 5, numbers_from=1,
                    total=(slip.total_label, slip.total))
    # Numbers in Plex Mono 9 pt: "01/09/2026" and "12 000 DA" need 24 mm with the padding.
    detail_widths = [0, 0, 24 * mm, 26 * mm, 17 * mm, 26 * mm]
    names = usable - sum(detail_widths)
    detail_widths[0], detail_widths[1] = names * 0.52, names * 0.48
    story = [header_table(slip, usable), Spacer(1, 5 * mm), details_table(slip, usable),
             Spacer(1, 6 * mm), groups, Spacer(1, 2 * mm),
             Paragraph(escape(slip.note), style(8, color=MUTED)), Spacer(1, 10 * mm),
             signature_table(slip, usable), Spacer(1, 8 * mm),
             Paragraph(escape(slip.detail_title), style(11, bold=True)), Spacer(1, 2 * mm),
             _table(slip.detail_columns, slip.detail_rows, detail_widths, numbers_from=3)]
    doc.build(story, onFirstPage=slip.footer.draw, onLaterPages=slip.footer.draw)
    return path

