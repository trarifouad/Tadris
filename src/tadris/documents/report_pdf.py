"""A report on A4, black and white: the school, the title, the period and the filters, the
four key figures in boxes, the table (its header repeated on every page) with its total in
bold, and how it is counted. Columns as wide as their content needs, landscape when the
table would rather be wider than a portrait page."""

import re
from html import escape
from pathlib import Path

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from tadris.core.cells import NUMERIC, display, header, tile_text
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
from tadris.domain.models import Report

SMALL_FROM = 7  # columns: a smaller font from there
PLAIN = NUMERIC + ("date",)  # one line, in the mono font: never wrapped
PAD = 6  # reportlab's default cell padding, each side
MAX_TEXT = 300  # points: a text column wider than this wraps
MIN_TEXT = 48
KEEP_WHOLE = 115  # points (about 4 cm): a text column this narrow never wraps


def _missing(font: str):
    """Characters the font cannot draw (Readex Pro has no arrows), drawn in Plex Mono."""
    glyphs = pdfmetrics.getFont(font).face.charToGlyph
    return lambda ch: ord(ch) not in glyphs


_AMOUNT = re.compile(r"\d{1,3}(?: \d{3})*(?: DA)?")


def markup(text: str, font: str = FONT) -> str:
    """Escaped text for a Paragraph, with the characters `font` lacks (→, ●) in Plex Mono
    instead of a box. An amount (« 21 725 DA ») never wraps."""
    text = escape(_AMOUNT.sub(lambda m: m.group(0).replace(" ", " "), text))
    lacks = _missing(font)
    for ch in {ch for ch in text if not ch.isascii() and not ch.isspace() and lacks(ch)}:
        text = text.replace(ch, f'<font name="{MONO}">{ch}</font>')
    return text


def _width(text: str, font: str, size: float) -> float:
    return pdfmetrics.stringWidth(text, font, size)


def _longest_word(text: str, font: str, size: float) -> float:
    return max((_width(word, font, size) for word in text.split()), default=0)


def layout(report: Report, size: float) -> tuple[list, float]:
    """Each column's narrowest and natural width, and the width the table would like.
    Numbers and dates get exactly their longest value (they never wrap); a header never
    breaks a word; text columns share the rest, from their longest word up."""
    head = size - 0.5
    plain, minimum, natural = [], [], []
    rows = list(report.rows) + ([report.total] if report.total is not None else [])
    for index, column in enumerate(report.columns):
        label = _longest_word(header(column), FONT_BOLD, head) + 2 * PAD + 4  # no split
        texts = [display(column.kind, row[index]) for row in rows if row[index] is not None]
        if column.kind in PLAIN:
            width = max([label] + [_width(x, MONO, size) + 2 * PAD for x in texts])
            plain.append(True)
            minimum.append(width)
            natural.append(width)
            continue
        plain.append(False)
        words = max([label, MIN_TEXT] + [_longest_word(x, FONT, size) + 2 * PAD
                                         for x in texts])
        lines = max([words] + [_width(x, FONT, size) + 2 * PAD for x in texts])
        minimum.append(lines if lines <= KEEP_WHOLE else min(words, MAX_TEXT))
        natural.append(min(max(lines, words), MAX_TEXT))
    return [minimum, natural, plain], sum(natural)


def fit(sizes, usable: float) -> list[float]:
    """The columns' widths on `usable` points."""
    minimum, natural, plain = sizes
    fixed = sum(w for w, p in zip(minimum, plain, strict=True) if p)
    text_min = [w if not p else 0 for w, p in zip(minimum, plain, strict=True)]
    text_nat = [w if not p else 0 for w, p in zip(natural, plain, strict=True)]
    room = usable - fixed
    if room <= sum(text_min):  # too many columns even at their narrowest: shrink them all
        scale = usable / (fixed + sum(text_min))
        return [w * scale for w in minimum]
    if sum(text_nat) <= room:  # everything on one line: text columns share the rest
        extra = room - sum(text_nat)
        weight = sum(text_nat) or 1
        return [w if p else n + extra * n / weight
                for w, n, p in zip(minimum, text_nat, plain, strict=True)]
    extra = room - sum(text_min)  # some text wraps: from its longest word, by what it wants
    want = [n - m for n, m in zip(text_nat, text_min, strict=True)]
    total = sum(want) or 1
    return [w if p else m + extra * x / total
            for w, m, x, p in zip(minimum, text_min, want, plain, strict=True)]


def _tiles(report: Report, usable: float) -> Table:
    """The key figures in a row of boxes: the label, the figure, its small line."""
    cells = [[Paragraph(markup(tile.label), style(8, color=MUTED)),
              Paragraph(markup(tile_text(tile)), style(13, bold=True, leading=17)),
              Paragraph(markup(tile.note), style(7.5, color=MUTED))]
             for tile in report.tiles]
    gap = 4 * mm
    width = (usable - gap * (len(cells) - 1)) / len(cells)
    data, widths = [], []
    for i, cell in enumerate(cells):
        if i:
            data.append("")
            widths.append(gap)
        data.append(cell)
        widths.append(width)
    table = Table([data], colWidths=widths)
    commands = [("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]
    for i in range(0, len(data), 2):
        commands.append(("BOX", (i, 0), (i, 0), 0.6, RULE))
    table.setStyle(TableStyle(commands))
    return table


def build_report_pdf(report: Report, school: School, footer: Footer, path: Path) -> Path:
    register_fonts()
    size = 8 if len(report.columns) >= SMALL_FROM else 9
    sizes, wanted = layout(report, size)
    pagesize = landscape(A4) if wanted > A4[0] - 2 * MARGIN else A4
    pdf = SimpleDocTemplate(str(path), pagesize=pagesize, leftMargin=MARGIN,
                            rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=16 * mm,
                            title=report.title, author=school.name)
    usable = pagesize[0] - 2 * MARGIN
    contact = " · ".join(part for part in (school.address, school.phone) if part)
    story = [Paragraph(escape(school.name), style(12, bold=True))]
    if contact:
        story.append(Paragraph(escape(contact), style(8.5, color=MUTED)))
    story += [Spacer(1, 4 * mm), Paragraph(markup(report.title), style(16, bold=True)),
              Paragraph(markup(report.period), style(10, color=MUTED))]
    shown = [f"{name} : {value}" for name, value in report.filters]
    if shown:
        story.append(Paragraph(markup(" · ".join(shown)), style(8.5, color=MUTED)))
    if report.tiles:
        story += [Spacer(1, 5 * mm), _tiles(report, usable)]
    story.append(Spacer(1, 5 * mm))

    numeric = [c.kind in NUMERIC for c in report.columns]
    plain = [c.kind in PLAIN for c in report.columns]
    head = [Paragraph(markup(header(c), FONT_BOLD),
                      style(size - 0.5, bold=True, align=2 if n else 0))
            for c, n in zip(report.columns, numeric, strict=True)]

    def cells(row, bold=False):
        out = []
        for column, value, one_line in zip(report.columns, row, plain, strict=True):
            text = display(column.kind, value) if value is not None or not bold else ""
            out.append(text if one_line else Paragraph(
                markup(text, FONT_BOLD if bold else FONT), style(size, bold=bold)))
        return out

    data = [head] + [cells(row) for row in report.rows]
    if report.total is not None:
        data.append(cells(report.total, bold=True))
    table = Table(data, colWidths=fit(sizes, usable), repeatRows=1)
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
        commands += [("LINEABOVE", (0, -1), (-1, -1), 0.9, INK),
                     ("FONT", (0, -1), (-1, -1), FONT_BOLD, size)]
        commands += [("FONT", (i, -1), (i, -1), MONO, size)
                     for i, one_line in enumerate(plain) if one_line]
    table.setStyle(TableStyle(commands))
    story.append(table)
    if not report.rows:
        story += [Spacer(1, 4 * mm), Paragraph(markup("—"), style(9, color=MUTED))]
    if report.note:
        story += [Spacer(1, 5 * mm), Paragraph(markup(report.note), style(8, color=MUTED))]
    pdf.build(story, onFirstPage=footer.draw, onLaterPages=footer.draw)
    return path
