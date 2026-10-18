from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class ErrorBanner(QLabel):
    """Inline red banner at the top of a dialog for BusinessRuleError messages."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("errorBanner")
        self.setWordWrap(True)
        self.hide()

    def show_error(self, message: str) -> None:
        self.setText(message)
        self.show()
        fit_to_content(self.window())

    def clear_error(self) -> None:
        self.clear()
        self.hide()
        fit_to_content(self.window())


def labeled(text: str, widget: QWidget) -> QWidget:
    """A field with its label above it."""
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    label = QLabel(text)
    label.setObjectName("fieldLabel")
    label.setBuddy(widget)
    layout.addWidget(label)
    layout.addWidget(widget)
    return box


def brand_row() -> QHBoxLayout:
    """Wordmark for dialogs: "Tadris" with its Arabic name."""
    row = QHBoxLayout()
    row.setSpacing(10)
    latin = QLabel("Tadris")
    latin.setObjectName("brandWordmark")
    arabic = QLabel("تدريس")
    arabic.setObjectName("brandWordmarkAr")
    row.addWidget(latin)
    row.addWidget(arabic)
    row.addStretch()
    return row


def fit_to_content(dialog: QWidget) -> None:
    """Fix a fixed-width dialog's height to what its layout needs at that width.

    adjustSize() undersizes layouts with word-wrapped labels, which clips the inputs.
    """
    dialog.ensurePolished()
    layout = dialog.layout()
    if layout.hasHeightForWidth():
        height = layout.heightForWidth(dialog.width())
    else:
        height = layout.sizeHint().height()
    dialog.setFixedHeight(height)


def primary_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setProperty("variant", "primary")
    button.setDefault(True)
    return button
