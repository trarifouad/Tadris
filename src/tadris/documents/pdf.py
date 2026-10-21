"""What every printed document shares: fonts, the school header and the footer."""

from dataclasses import dataclass
from importlib.resources import files

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONT, FONT_BOLD = "Readex", "Readex-SemiBold"
MONO = "PlexMono"  # amounts and numbers: digits line up
INK = colors.HexColor("#1F1B2D")
MUTED = colors.HexColor("#5A5868")
RULE = colors.HexColor("#C9C5D6")
SHADE = colors.HexColor("#EFEDF5")
MARGIN = 14 * mm

_registered = False


def register_fonts() -> None:
    """Readex Pro, the app's font: French accents now, Arabic later."""
    global _registered
    if _registered:
        return
    fonts = files("tadris.ui.resources") / "fonts"
    pdfmetrics.registerFont(TTFont(FONT, str(fonts / "ReadexPro-Regular.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(fonts / "ReadexPro-SemiBold.ttf")))
    pdfmetrics.registerFont(TTFont(MONO, str(fonts / "IBMPlexMono-Medium.ttf")))
    _registered = True


def style(size: float = 9.5, bold: bool = False, color=INK, leading: float | None = None,
          align: int = 0) -> ParagraphStyle:
    return ParagraphStyle("s", fontName=FONT_BOLD if bold else FONT, fontSize=size,
                          leading=leading or size * 1.3, textColor=color, alignment=align)


@dataclass(frozen=True)
class School:
    name: str
    address: str
    phone: str
    header: str = ""  # Paramètres: a line under the contact on receipts and slips


@dataclass(frozen=True)
class Footer:
    printed: str  # « Imprimé le 19/10/2026 à 17:05 par accueil »

    def draw(self, canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(FONT, 7.5)
        canvas.setFillColor(MUTED)
        width, _height = doc.pagesize
        canvas.drawString(MARGIN, 8 * mm, self.printed)
        canvas.drawRightString(width - MARGIN, 8 * mm, f"{doc.page}")
        canvas.restoreState()
