"""The payment receipt: A4 portrait, black and white (see DESIGN.md, Print documents)."""

from dataclasses import dataclass
from html import escape
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from tadris.documents.pdf import (
    FONT_BOLD,
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

STAMP_GREY = MUTED


@dataclass(frozen=True)
class ReceiptDoc:
    school: School
    title: str  # « Reçu de paiement »
    number: str  # R2026-00001
    copy_mark: str  # « DUPLICATA » on a reprint, else ""
    details: list[tuple[str, str]]  # (label, value): date, student, payer, method, cashier
    columns: tuple[str, str]  # Désignation, Montant
    lines: list[tuple[str, str]]  # (description, amount), credit line included
    totals: list[tuple[str, str]]  # Total payé, Reste à payer...
    stamp: str  # « PAYÉ » or « ANNULÉ »
    stamp_date: str  # dd/mm/yyyy
    voided_note: str  # « Reçu annulé le ... : motif », else ""
    thanks: str
    signature: str
    footer: Footer


class Stamp(Flowable):
    """A rotated double ring with a word and a date, drawn as a grey outline: room is left
    for the school's real stamp next to the signature line."""

    def __init__(self, text: str, day: str, size: float = 34 * mm):
        super().__init__()
        self.text, self.day, self.size = text, day, size
        self.width = self.height = size

    def draw(self) -> None:
        c = self.canv
        r = self.size / 2
        c.saveState()
        c.translate(r, r)
        c.rotate(10)
        c.setStrokeColor(STAMP_GREY)
        c.setFillColor(STAMP_GREY)
        c.setLineWidth(1.6)
        c.circle(0, 0, r - 1, stroke=1, fill=0)
        c.setLineWidth(0.7)
        c.circle(0, 0, r - 4.5, stroke=1, fill=0)
        c.setFont(FONT_BOLD, 15)
        c.drawCentredString(0, 1, self.text)
        c.setFont(MONO, 8)
        c.drawCentredString(0, -11, self.day)
        c.restoreState()


def _number_box(receipt: ReceiptDoc) -> Table:
    number = style(12, align=1)
    number.fontName = MONO
    rows = [[Paragraph(escape(receipt.number), number)]]
    if receipt.copy_mark:
        rows.append([Paragraph(escape(receipt.copy_mark),
                               style(8, bold=True, color=MUTED, align=1))])
    box = Table(rows, colWidths=[44 * mm])
    box.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, INK),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return box


def _header(receipt: ReceiptDoc, usable: float) -> Table:
    school = receipt.school
    left = [Paragraph(escape(school.name), style(14, bold=True))]
    contact = " · ".join(part for part in (school.address, school.phone) if part)
    if contact:
        left.append(Paragraph(escape(contact), style(8.5, color=MUTED)))
    left += [Spacer(1, 4 * mm), Paragraph(escape(receipt.title), style(16, bold=True))]
    header = Table([[left, _number_box(receipt)]], colWidths=[usable - 48 * mm, 48 * mm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, MUTED),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return header


def _details(receipt: ReceiptDoc, usable: float) -> Table:
    rows = [[Paragraph(escape(label), style(9, color=MUTED)),
             Paragraph(escape(value), style(10))] for label, value in receipt.details]
    table = Table(rows, colWidths=[34 * mm, usable - 34 * mm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return table


def _lines(receipt: ReceiptDoc, usable: float) -> Table:
    amount_width = 36 * mm
    data = [[Paragraph(escape(receipt.columns[0]), style(8.5, bold=True)),
             Paragraph(escape(receipt.columns[1]), style(8.5, bold=True, align=2))]]
    data += [[Paragraph(escape(text), style(10)), amount] for text, amount in receipt.lines]
    first_total = len(data)
    data += [[Paragraph(escape(label), style(10, bold=True, align=2)), amount]
             for label, amount in receipt.totals]
    table = Table(data, colWidths=[usable - amount_width, amount_width], repeatRows=1)
    table.setStyle(TableStyle([
        ("FONT", (1, 1), (1, -1), MONO, 10),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("BACKGROUND", (0, 0), (-1, 0), SHADE),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, first_total - 1), 0.5, RULE),
        ("LINEABOVE", (0, first_total), (-1, first_total), 0.9, INK),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _signature(receipt: ReceiptDoc, usable: float) -> Table:
    """The stamp on the left; on the right, a line to sign on with its label under it."""
    stamp = Stamp(receipt.stamp, receipt.stamp_date)
    sign = Table([[Paragraph(escape(receipt.signature), style(9, color=MUTED, align=1))]],
                 colWidths=[70 * mm])
    sign.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.6, MUTED),
                              ("TOPPADDING", (0, 0), (-1, -1), 4)]))
    table = Table([[stamp, "", sign]], colWidths=[40 * mm, usable - 110 * mm, 70 * mm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


def build_receipt(receipt: ReceiptDoc, path: Path) -> Path:
    register_fonts()
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=MARGIN, bottomMargin=16 * mm,
                            title=f"{receipt.title} {receipt.number}")
    usable = A4[0] - 2 * MARGIN
    story = [_header(receipt, usable), Spacer(1, 5 * mm), _details(receipt, usable),
             Spacer(1, 6 * mm)]
    if receipt.voided_note:
        story += [Paragraph(escape(receipt.voided_note), style(10.5, bold=True)),
                  Spacer(1, 4 * mm)]
    story += [_lines(receipt, usable), Spacer(1, 10 * mm), _signature(receipt, usable),
              Spacer(1, 8 * mm), Paragraph(escape(receipt.thanks), style(9, color=MUTED,
                                                                          align=1))]
    doc.build(story, onFirstPage=receipt.footer.draw, onLaterPages=receipt.footer.draw)
    return path
