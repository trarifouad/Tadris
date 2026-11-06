"""The payment receipt, and the refund receipt laid out the same way: an 80 mm ticket for the
desk's thermal printer, as tall as its content, black only (thermal paper prints grey as
dots). The A4 helpers below (header, details, signature) are the payout slip's."""

from dataclasses import dataclass
from html import escape
from pathlib import Path

from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    HRFlowable,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from tadris.documents.pdf import (
    FONT_BOLD,
    INK,
    MONO,
    MUTED,
    Footer,
    School,
    register_fonts,
    style,
)

STAMP_GREY = MUTED
TICKET_WIDTH = 80 * mm  # the roll
TICKET_MARGIN = 4 * mm  # most 80 mm printers print 72 mm of it


@dataclass(frozen=True)
class ReceiptDoc:
    school: School
    title: str  # « Reçu de paiement », « Reçu de remboursement »
    number: str  # R2026-00001, RB2026-00001
    copy_mark: str  # « DUPLICATA » on a reprint, else ""
    paid_at: str  # « Le 05/11/2026 à 20:49 »
    details: list[tuple[str, str]]  # (label, value): student, payer, method, cashier
    lines: list[tuple[str, str, str]]  # (what, its dates or "", amount)
    total: tuple[str, str]  # (« Total payé », amount)
    balance: list[tuple[str, str]]  # Reste à payer, À venir... (none on a refund)
    stamp: str  # « PAYÉ », « ANNULÉ » or « REMBOURSÉ »
    stamp_date: str  # dd/mm/yyyy
    voided_note: str  # « Reçu annulé le ... : motif », else ""
    thanks: str
    signature: str
    footer: Footer
    note: str = ""  # Paramètres: a line at the foot of the receipt (e.g. fees not refundable)
    amount_words: str = ""  # the total in words, under it (a refund receipt)


class Stamp(Flowable):
    """A rotated double ring with a word and a date, drawn as a grey outline: room is left
    for the school's real stamp next to the signature line."""

    def __init__(self, text: str, day: str, size: float = 34 * mm, color=STAMP_GREY):
        super().__init__()
        self.text, self.day, self.size, self.color = text, day, size, color
        self.width = self.height = size

    def text_size(self, largest: float = 15) -> float:
        """The word fits inside the inner ring: PAYÉ at full size, a longer word smaller."""
        room = (self.size / 2 - 4.5) * 2 * 0.82
        return min(largest, largest * room / stringWidth(self.text, FONT_BOLD, largest))

    def draw(self) -> None:
        c = self.canv
        r = self.size / 2
        c.saveState()
        c.translate(r, r)
        c.rotate(10)
        c.setStrokeColor(self.color)
        c.setFillColor(self.color)
        c.setLineWidth(1.6)
        c.circle(0, 0, r - 1, stroke=1, fill=0)
        c.setLineWidth(0.7)
        c.circle(0, 0, r - 4.5, stroke=1, fill=0)
        c.setFont(FONT_BOLD, self.text_size())
        c.drawCentredString(0, 1, self.text)
        c.setFont(MONO, min(8, self.size / mm / 4))
        c.drawCentredString(0, -self.size * 0.115, self.day)
        c.restoreState()


def number_box(receipt) -> Table:
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


def header_table(receipt, usable: float) -> Table:
    """School, title and the number box. `receipt`: anything with school, title, number and
    copy_mark (a receipt, a payout slip)."""
    school = receipt.school
    left = [Paragraph(escape(school.name), style(14, bold=True))]
    contact = " · ".join(part for part in (school.address, school.phone) if part)
    if contact:
        left.append(Paragraph(escape(contact), style(8.5, color=MUTED)))
    if school.header:
        left.append(Paragraph(escape(school.header), style(8.5, color=MUTED)))
    left += [Spacer(1, 4 * mm), Paragraph(escape(receipt.title), style(16, bold=True))]
    header = Table([[left, number_box(receipt)]], colWidths=[usable - 48 * mm, 48 * mm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, MUTED),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return header


def details_table(receipt, usable: float) -> Table:
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


def signature_table(receipt, usable: float) -> Table:
    """The stamp on the left; on the right, a line to sign on with its label under it.
    `receipt`: anything with stamp, stamp_date and signature."""
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


# ----- the 80 mm ticket -----
# Top to bottom: the school; the title, number and date; who paid; what was paid, one line
# each (a month's dates under its group); the total in a box, the largest thing printed;
# what is left; the stamp beside the signature line; the school's note.

LABEL_WIDTH = 17 * mm
AMOUNT_WIDTH = 24 * mm
_FLAT = [("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]


def _rule(width: float = 0.6, dash=None) -> HRFlowable:
    return HRFlowable(width="100%", thickness=width, color=INK, dash=dash, spaceBefore=2 * mm,
                      spaceAfter=2 * mm)


def _amount(text: str, size: float) -> Paragraph:
    right = style(size, align=2)
    right.fontName = MONO
    return Paragraph(escape(text), right)


def _details(receipt: ReceiptDoc, usable: float) -> Table:
    rows = [[Paragraph(escape(label), style(7.5)), Paragraph(escape(value), style(8.5))]
            for label, value in receipt.details]
    table = Table(rows, colWidths=[LABEL_WIDTH, usable - LABEL_WIDTH])
    table.setStyle(TableStyle(_FLAT + [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return table


def _lines(receipt: ReceiptDoc, usable: float) -> Table:
    rows = []
    for what, when, amount in receipt.lines:
        cell = [Paragraph(escape(what), style(8.5, bold=True))]
        if when:
            cell.append(Paragraph(escape(when), style(7.5)))
        rows.append([cell, _amount(amount, 8.5)])
    table = Table(rows, colWidths=[usable - AMOUNT_WIDTH, AMOUNT_WIDTH])
    table.setStyle(TableStyle(_FLAT + [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return table


def _total(receipt: ReceiptDoc, usable: float) -> Table:
    label, amount = receipt.total
    big = style(12, bold=True, align=2)
    big.fontName = MONO
    box = Table([[Paragraph(escape(label.upper()), style(10, bold=True)),
                  Paragraph(escape(amount), big)]],
                colWidths=[usable - 32 * mm, 32 * mm])
    box.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1.2, INK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return box


def _balance(receipt: ReceiptDoc, usable: float) -> Table:
    rows = [[Paragraph(escape(label), style(8.5)), _amount(value, 8.5)]
            for label, value in receipt.balance]
    table = Table(rows, colWidths=[usable - AMOUNT_WIDTH, AMOUNT_WIDTH])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]))
    return table


def _stamp_and_signature(receipt: ReceiptDoc, usable: float) -> Table:
    """The stamp on the left; a line to sign on at the right, its label under it."""
    size = 22 * mm
    sign = Table([[Paragraph(escape(receipt.signature), style(7.5, align=1))]],
                 colWidths=[usable - size - 6 * mm])
    sign.setStyle(TableStyle(_FLAT + [("LINEABOVE", (0, 0), (-1, 0), 0.6, INK),
                                      ("TOPPADDING", (0, 0), (-1, -1), 3)]))
    table = Table([[Stamp(receipt.stamp, receipt.stamp_date, size=size, color=INK), sign]],
                  colWidths=[size + 6 * mm, usable - size - 6 * mm])
    table.setStyle(TableStyle(_FLAT + [("VALIGN", (0, 0), (-1, -1), "BOTTOM")]))
    return table


def _voided(receipt: ReceiptDoc, usable: float) -> Table:
    box = Table([[Paragraph(escape(receipt.voided_note), style(8.5, bold=True, align=1))]],
                colWidths=[usable])
    box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1.2, INK),
                             ("TOPPADDING", (0, 0), (-1, -1), 4),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return box


def ticket_story(receipt: ReceiptDoc, usable: float) -> list:
    center = 1
    school = receipt.school
    story = [Paragraph(escape(school.name), style(12, bold=True, align=center))]
    for line in (" · ".join(part for part in (school.address, school.phone) if part),
                 school.header):
        if line:
            story.append(Paragraph(escape(line), style(7.5, align=center)))
    number = style(9.5, align=center)
    number.fontName = MONO
    story += [_rule(0.8),
              Paragraph(escape(receipt.title.upper()), style(10.5, bold=True, align=center)),
              Paragraph(escape(receipt.number), number),
              Paragraph(escape(receipt.paid_at), style(8, align=center))]
    if receipt.copy_mark:
        story.append(Paragraph(escape(receipt.copy_mark), style(9, bold=True, align=center)))
    if receipt.voided_note:
        story += [Spacer(1, 2 * mm), _voided(receipt, usable)]
    story += [_rule(0.4), _details(receipt, usable), _rule(0.4, dash=(2, 2)),
              _lines(receipt, usable), Spacer(1, 3 * mm), _total(receipt, usable)]
    if receipt.amount_words:
        story += [Spacer(1, 1.5 * mm), Paragraph(escape(receipt.amount_words), style(8))]
    if receipt.balance:
        story += [Spacer(1, 1.5 * mm), _balance(receipt, usable)]
    story += [Spacer(1, 6 * mm), _stamp_and_signature(receipt, usable), Spacer(1, 4 * mm),
              Paragraph(escape(receipt.thanks), style(8, align=center))]
    if receipt.note:
        story += [Spacer(1, 1 * mm), Paragraph(escape(receipt.note), style(8, align=center))]
    story += [Spacer(1, 3 * mm), Paragraph(escape(receipt.footer.printed),
                                           style(6.5, align=center))]
    return story


def _height(story: list, usable: float) -> float:
    """What the story takes on a page `usable` wide: the ticket is cut that long."""
    total = 0.0
    for flowable in story:
        _width, height = flowable.wrap(usable, 10_000 * mm)
        total += height + flowable.getSpaceBefore() + flowable.getSpaceAfter()
    return total


def build_receipt(receipt: ReceiptDoc, path: Path) -> Path:
    register_fonts()
    usable = TICKET_WIDTH - 2 * TICKET_MARGIN
    height = _height(ticket_story(receipt, usable), usable) + 2 * TICKET_MARGIN + 4 * mm
    # A frame without reportlab's 6 pt padding: the story is laid out exactly as measured.
    frame = Frame(TICKET_MARGIN, TICKET_MARGIN, usable, height - 2 * TICKET_MARGIN,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc = BaseDocTemplate(str(path), pagesize=(TICKET_WIDTH, height),
                          leftMargin=TICKET_MARGIN, rightMargin=TICKET_MARGIN,
                          topMargin=TICKET_MARGIN, bottomMargin=TICKET_MARGIN,
                          title=f"{receipt.title} {receipt.number}",
                          pageTemplates=[PageTemplate(frames=[frame])])
    # Measuring wraps the flowables: the page is built from a fresh story.
    doc.build(ticket_story(receipt, usable))
    return path
