"""A report on A4, black and white: the school, the title and period, the table with its
total, the note. Columns as wide as their content needs, landscape when the table would
rather be wider than a portrait page."""

import re
from dataclasses import dataclass
from html import escape
from pathlib import Path

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from tadris.core.cells import display
from tadris.documents.pdf import (
    FONT,
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
from tadris.domain.models import ReportTable

SMALL_FROM = 7  # columns: a smaller font from there
_NUMERIC = ("number", "money", "percent")
_PLAIN = _NUMERIC + ("date", "datetime")  # one line, in the mono font: never wrapped
PAD = 6  # reportlab's default cell padding, each side
MAX_TEXT = 300  # points: a text column wider than this wraps
MIN_TEXT = 48
KEEP_WHOLE = 115  # points (about 4 cm): a text column this narrow never wraps


@dataclass(frozen=True)
class ReportDoc:
    school: School
    table: ReportTable
    footer: Footer


def _missing(font: str) -> callable:
    """Characters the font cannot draw (Readex Pro has no arrows), drawn in Plex Mono."""
    glyphs = pdfmetrics.getFont(font).face.charToGlyph
    return lambda ch: ord(ch) not in glyphs


_AMOUNT = re.compile(r"\d{1,3}(?: \d{3})*(?: DA)?")


def markup(text: str, font: str = FONT) -> str:
    """Escaped text for a Paragraph, with the characters `font` lacks (→, ←) in Plex Mono,
    which has them, instead of a box. An amount (« 21 725 DA ») never wraps."""
    text = escape(_AMOUNT.sub(lambda m: m.group(0).replace(" ", "\u00a0"), text))
    lacks = _missing(font)
    for ch in {ch for ch in text if not ch.isascii() and not ch.isspace() and lacks(ch)}:
        text = text.replace(ch, f'<font name="{MONO}">{ch}</font>')
    return text


def _width(text: str, font: str, size: float) -> float:
    return pdfmetrics.stringWidth(text, font, size)


def _longest_word(text: str, font: str, size: float) -> float:
    return max((_width(word, font, size) for word in text.split()), default=0)


def layout(report: ReportTable, size: float) -> tuple[list[float], float]:
    """Each column's width, and the width the table would like (its longest lines). Numbers
    and dates get exactly their longest value (they never wrap); a header never breaks a
    word; text columns share the rest, from their longest word up to their longest line."""
    head = size - 0.5
    plain, minimum, natural = [], [], []
    rows = list(report.rows) + ([report.total] if report.total is not None else [])
    for index, column in enumerate(report.columns):
        label = _longest_word(column.label, FONT_BOLD, head) + 2 * PAD
        texts = [display(column.kind, row[index]) for row in rows if row[index] is not None]
        if column.kind in _PLAIN:
            width = max([label] + [_width(x, MONO, size) + 2 * PAD for x in texts])
            plain.append(True)
            minimum.append(width)
            natural.append(width)
            continue
        plain.append(False)
        words = max([label, MIN_TEXT] + [_longest_word(x, FONT, size) + 2 * PAD
                                         for x in texts])
        lines = max([words] + [_width(x, FONT, size) + 2 * PAD for x in texts])
        # A short text (a name, a phone, a status) stays on one line; only long ones (the
        # groups, a detail) wrap.
        minimum.append(lines if lines <= KEEP_WHOLE else min(words, MAX_TEXT))
        natural.append(min(max(lines, words), MAX_TEXT))
    return [minimum, natural, plain], sum(natural)


def _fit(sizes, usable: float) -> list[float]:
    minimum, natural, plain = sizes
    fixed = sum(w for w, p in zip(minimum, plain, strict=True) if p)
    text_min = [w if not p else 0 for w, p in zip(minimum, plain, strict=True)]
    text_nat = [w if not p else 0 for w, p in zip(natural, plain, strict=True)]
    room = usable - fixed
    if room <= sum(text_min):  # too many columns even at their narrowest: shrink them all
        scale = usable / (fixed + sum(text_min))
        return [w * scale for w in minimum]
    if sum(text_nat) <= room:  # everything fits on one line: text columns share the rest
        extra = room - sum(text_nat)
        weight = sum(text_nat) or 1
        return [w if p else n + extra * n / weight
                for w, n, p in zip(minimum, text_nat, plain, strict=True)]
    # Some text wraps: from each one's longest word, the rest by how much each wants.
    extra = room - sum(text_min)
    want = [n - m for n, m in zip(text_nat, text_min, strict=True)]
    total = sum(want) or 1
    return [w if p else m + extra * x / total
            for w, m, x, p in zip(minimum, text_min, want, plain, strict=True)]


def build_report(doc: ReportDoc, path: Path) -> Path:
    register_fonts()
    report = doc.table
    size = 8 if len(report.columns) >= SMALL_FROM else 9
    sizes, wanted = layout(report, size)
    # Landscape when the table would rather be wider than a portrait page (the Journal's
    # details, many columns).
    pagesize = landscape(A4) if wanted > A4[0] - 2 * MARGIN else A4
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

    numeric = [c.kind in _NUMERIC for c in report.columns]
    plain = [c.kind in _PLAIN for c in report.columns]
    head = [Paragraph(markup(c.label, FONT_BOLD),
                      style(size - 0.5, bold=True, align=2 if n else 0))
            for c, n in zip(report.columns, numeric, strict=True)]

    def cells(row, bold=False):
        out = []
        for column, value, one_line in zip(report.columns, row, plain, strict=True):
            text = display(column.kind, value) if value is not None or not bold else ""
            out.append(text if one_line else Paragraph(markup(text, FONT_BOLD if bold else FONT),
                                                       style(size, bold=bold)))
        return out

    data = [head] + [cells(row) for row in report.rows]
    if report.total is not None:
        data.append(cells(report.total, bold=True))
    table = Table(data, colWidths=_fit(sizes, usable), repeatRows=1)
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
        story += [Spacer(1, 5 * mm), Paragraph(markup(report.note), style(8, color=MUTED))]
    pdf.build(story, onFirstPage=doc.footer.draw, onLaterPages=doc.footer.draw)
    return path
