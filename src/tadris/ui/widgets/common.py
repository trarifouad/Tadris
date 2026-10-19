from html import escape

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tadris.i18n.fr import t
from tadris.ui.theme import tokens

TOAST_MS = 3000


class ErrorBanner(QLabel):
    """Inline red banner at the top of a dialog for BusinessRuleError messages."""

    object_name = "errorBanner"

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName(self.object_name)
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


class PageBanner(QLabel):
    """Red banner on a page (not a dialog) for an action's BusinessRuleError."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("errorBanner")
        self.setWordWrap(True)
        self.hide()

    def show_error(self, message: str) -> None:
        self.setText(message)
        self.show()

    def clear_error(self) -> None:
        self.clear()
        self.hide()


class WarningBanner(ErrorBanner):
    """Amber banner for warnings the user may override (possible duplicate, existing contact)."""

    object_name = "warningBanner"

    def show_warning(self, message: str) -> None:
        self.show_error(message)

    def clear_warning(self) -> None:
        self.clear_error()


class Badge(QLabel):
    """Status pill. kind is a STATUS_STYLE value: success, warning, danger, info, neutral."""

    def __init__(self, text: str = "", kind: str = "neutral", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setObjectName("badge")
        self.set_kind(kind)

    def set_kind(self, kind: str) -> None:
        self.setProperty("kind", kind)
        self.style().unpolish(self)
        self.style().polish(self)

    def kind(self) -> str:
        return self.property("kind")


def labeled(text: str, widget: QWidget, required: bool = False) -> QWidget:
    """A field with its label above it. Required fields get a red asterisk."""
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    label = QLabel(text)
    if required:
        label.setText(f'{escape(text)} <span style="color:{tokens()["danger"]}">*</span>')
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


def variant_button(text: str, variant: str) -> QPushButton:
    """'danger' or 'ghost' button; never the dialog default."""
    button = QPushButton(text)
    button.setProperty("variant", variant)
    button.setAutoDefault(False)
    return button


def toast(widget: QWidget, message: str) -> None:
    """Show a success message in the main window's status bar for 3 seconds."""
    window = widget.window()
    if isinstance(window, QMainWindow):
        window.statusBar().showMessage(message, TOAST_MS)


def ask(dialog: QDialog) -> bool:
    """Run a modal dialog; True if accepted. The dialog is then deleted: a dialog with a
    parent page otherwise stays alive, hidden, until the page dies. Its fields can still be
    read right after: Qt deletes it once control returns to the event loop."""
    try:
        return dialog.exec() == QDialog.DialogCode.Accepted
    finally:
        dialog.deleteLater()


def confirm(parent: QWidget, title: str, text: str, action: str) -> bool:
    """Confirm step for destructive actions. The confirm button names the action."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(text)
    accept = box.addButton(action, QMessageBox.ButtonRole.AcceptRole)
    cancel = box.addButton(t["action.cancel"], QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)
    box.exec()
    accepted = box.clickedButton() is accept
    box.deleteLater()
    return accepted


def open_document(path) -> None:
    """Open a printed document (PDF) in the system viewer, where it is printed."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
