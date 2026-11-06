"""Make packaging/tadris.ico (the exe's and the installer's icon) from the app's own icon,
src/tadris/ui/resources/icons/tadris.svg, one picture per size. Run it again only when the
icon changes:

    python packaging/make_icon.py
"""

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QGuiApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tadris.ui.theme import APP_ICON_SIZES, app_icon

OUT = ROOT / "packaging" / "tadris.ico"


def png(icon, size: int) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    icon.pixmap(size, size).save(buffer, "PNG")
    return bytes(data)


def ico(images: list[tuple[int, bytes]]) -> bytes:
    """An .ico of PNG pictures (read by Windows since Vista): a header, one entry per
    picture (0 stands for 256), then the pictures."""
    entries, pictures = b"", b""
    offset = 6 + 16 * len(images)
    for size, data in images:
        side = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data),
                               offset + len(pictures))
        pictures += data
    return struct.pack("<HHH", 0, 1, len(images)) + entries + pictures


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    icon = app_icon()
    OUT.write_bytes(ico([(size, png(icon, size)) for size in APP_ICON_SIZES]))
    print(f"wrote {OUT.relative_to(ROOT)}")
