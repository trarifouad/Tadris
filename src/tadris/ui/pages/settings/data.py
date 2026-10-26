"""Paramètres → Données: the backups at a glance (the latest copy, the second location,
« Sauvegarder maintenant »; « Gérer les sauvegardes » opens every copy, the second location
and restoring in a window) and « À propos » (versions, where the data lives).
`restored(safety copy's path)` once a copy was put back: the window goes back to login."""

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from tadris.core.context import UserContext
from tadris.i18n.fr import t
from tadris.services import backup
from tadris.ui.pages.system_tabs import (
    AboutTab,
    BackupsTab,
    backups_folder,
    display_stamp,
    take_now,
)
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets.common import Badge, PageBanner, primary_button, toast
from tadris.ui.widgets.compact import section_card, summary_card
from tadris.ui.widgets.forms import SectionWindow, caption


class DataSection(QWidget):
    restored = Signal(str)

    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn, self._ctx = conn, ctx
        self.folder = backups_folder(conn)

        backups, body, self.manage = summary_card(t["data.backups"], t["data.manage"])
        self.error = PageBanner()
        self.last = QLabel()
        self.last.setObjectName("summaryValue")
        self.last_state = Badge()
        last_row = QHBoxLayout()
        last_row.setSpacing(8)
        last_row.addWidget(self.last)
        last_row.addWidget(self.last_state)
        last_row.addStretch()
        self.second = caption()
        self.second.setWordWrap(True)
        self.take = primary_button(t["backups.take_now"])
        self.take.setDefault(False)
        self.take.clicked.connect(self._take_now)
        take_row = QHBoxLayout()
        take_row.addWidget(self.take)
        take_row.addStretch()
        body.addWidget(self.error)
        body.addLayout(last_row)
        body.addWidget(self.second)
        body.addSpacing(4)
        body.addLayout(take_row)
        self.manage.clicked.connect(self.open_backups)

        about_card = section_card()
        about_title = QLabel(t["data.about"])
        about_title.setObjectName("sectionTitle")
        self.about = AboutTab(conn, ctx)
        self.about.layout().setContentsMargins(0, 0, 0, 0)
        about_card.layout().addWidget(about_title)
        about_card.layout().addWidget(self.about)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(backups)
        layout.addWidget(about_card)
        self.refresh()

    def refresh(self) -> None:
        latest = next(iter(backup.list_backups(self._conn)), None)
        if latest is None:
            self.last.setText(t["data.none"])
        else:
            self.last.setText(t["data.last"].format(when=display_stamp(latest.created_at)))
            self.last_state.setText(t[f"backups.status.{latest.status}"])
            self.last_state.set_kind(kind_for("backup", latest.status))
        self.last_state.setVisible(latest is not None)
        root = backup.second_root(self._conn)
        self.second.setText(t["data.no_second"] if root is None else t["data.second"].format(
            folder=backup.second_folder(self._conn)))
        self.take.setEnabled(self.folder is not None)
        self.about.refresh()

    def _take_now(self) -> None:
        taken, problem = take_now(self._conn, self._ctx, self.folder)
        self.refresh()
        if problem:
            self.error.show_error(problem)
            return
        self.error.clear_error()
        toast(self, t["backups.taken"].format(name=Path(taken.file_path).name))

    def open_backups(self) -> SectionWindow:
        """Every copy, the second location and restoring, in a window. A copy put back
        closes it and sends the user to log in again."""
        tab = BackupsTab(self._conn, self._ctx)
        window = SectionWindow(t["data.backups"], tab, self)
        put_back: list[str] = []
        tab.restored.connect(lambda safety: (put_back.append(safety), window.accept()))
        window.exec()
        if put_back:  # the data underneath changed: log in again, nothing to read here
            self.restored.emit(put_back[0])
        else:
            self.refresh()
        return window
