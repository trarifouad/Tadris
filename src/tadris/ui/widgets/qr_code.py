from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget
from reportlab.graphics.barcode.qr import QrCodeWidget

QUIET = 4  # modules of white around the code (the standard): phones read it on any background


def modules(text: str) -> list[list[bool]]:
    """The QR code of `text` (ReportLab's encoder, already used for documents), dark True."""
    code = QrCodeWidget(text, barLevel="M").qr
    code.make()
    return [[bool(code.isDark(r, c)) for c in range(code.getModuleCount())]
            for r in range(code.getModuleCount())]


MIN_SIZE = 120  # below, a dense code is hard to scan from a screen


class QrCode(QWidget):
    """A QR code a phone scans with its camera: always black on white, whatever the theme.
    Up to `size` pixels, smaller when its card is short (a small screen): always square,
    centered in the space it gets, never over the text around it."""

    def __init__(self, size: int = 220, parent: QWidget | None = None):
        super().__init__(parent)
        self._modules: list[list[bool]] = []
        self._size = size
        self.setMinimumSize(QSize(MIN_SIZE, MIN_SIZE))
        self.setMaximumHeight(size)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def sizeHint(self) -> QSize:
        return QSize(self._size, self._size)

    def set_text(self, text: str | None) -> None:
        self._modules = modules(text) if text else []
        self.update()

    def is_empty(self) -> bool:
        return not self._modules

    def paintEvent(self, _event) -> None:
        if not self._modules:
            return
        painter = QPainter(self)
        side = min(self.width(), self.height(), self._size)
        painter.translate((self.width() - side) / 2, (self.height() - side) / 2)
        painter.fillRect(QRectF(0, 0, side, side), QColor("white"))
        count = len(self._modules) + 2 * QUIET
        box = side / count
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("black"))
        for r, row in enumerate(self._modules):
            for c, dark in enumerate(row):
                if dark:
                    # A hair larger: no white seams between modules at fractional sizes.
                    painter.drawRect(QRectF((c + QUIET) * box, (r + QUIET) * box,
                                            box + 0.5, box + 0.5))
        painter.end()
