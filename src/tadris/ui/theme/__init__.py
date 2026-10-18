from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from tadris.ui.theme.qss import build_qss
from tadris.ui.theme.tokens import DARK, LIGHT

RESOURCES_DIR = Path(__file__).resolve().parents[1] / "resources"
FONTS_DIR = RESOURCES_DIR / "fonts"
ICONS_DIR = RESOURCES_DIR / "icons"

_current: dict = LIGHT


def tokens() -> dict:
    """Tokens of the theme last applied, for widgets that paint themselves."""
    return _current


def load_fonts() -> set[str]:
    """Register the bundled fonts. Call once, before building any widget."""
    families: set[str] = set()
    for path in sorted(FONTS_DIR.glob("*.ttf")):
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id != -1:
            families.update(QFontDatabase.applicationFontFamilies(font_id))
    return families


def apply_theme(app: QApplication, mode: str = "light") -> dict:
    global _current
    mode = "dark" if mode == "dark" else "light"
    _current = DARK if mode == "dark" else LIGHT
    chevron = (ICONS_DIR / f"chevron-down-{mode}.svg").as_posix()
    font = QFont("Readex Pro")
    font.setPixelSize(14)
    app.setFont(font)
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(_current["faint"]))
    app.setPalette(palette)
    app.setStyleSheet(build_qss(_current, chevron))
    return _current
