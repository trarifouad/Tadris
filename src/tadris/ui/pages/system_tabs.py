"""Paramètres tabs about the app itself: « Sauvegardes » (the copies, a second location,
restore) and « À propos » (versions, where the data lives)."""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from tadris.core.context import UserContext
from tadris.core.dates import display_date
from tadris.core.errors import BusinessRuleError
from tadris.domain.models import Backup
from tadris.i18n.fr import t
from tadris.services import about, backup, restore
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets import common
from tadris.ui.widgets.common import PageBanner, confirm, primary_button, toast, variant_button
from tadris.ui.widgets.forms import ListSection, caption
from tadris.ui.widgets.tables import CENTER, fit_columns, item


def value_label() -> QLabel:
    """A value the user may select and copy (a path to read out on the phone)."""
    label = QLabel()
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setWordWrap(True)
    return label


class AboutTab(QWidget):
    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        intro = caption(t["about.caption"])
        intro.setWordWrap(True)
        self.app_version = value_label()
        self.schema_version = value_label()
        self.database = value_label()
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)
        for r, (label, value) in enumerate(((t["about.app_version"], self.app_version),
                                            (t["about.schema_version"], self.schema_version),
                                            (t["about.database"], self.database))):
            name = QLabel(label)
            name.setObjectName("fieldLabel")
            grid.addWidget(name, r, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(value, r, 1)
        grid.setColumnStretch(1, 1)
        self.open_folder = QPushButton(t["about.open_folder"])
        self.open_folder.setAutoDefault(False)
        self.open_folder.clicked.connect(self._open_folder)
        actions = QHBoxLayout()
        actions.addWidget(self.open_folder)
        actions.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(intro)
        layout.addLayout(grid)
        layout.addLayout(actions)
        layout.addStretch()
        self.refresh()

    def refresh(self) -> None:
        info = about.info(self._conn, self._ctx)
        self._info = info
        self.app_version.setText(info.app_version)
        self.schema_version.setText(str(info.schema_version))  # always the latest once open
        self.database.setText(str(info.database) if info.database else t["about.in_memory"])
        self.open_folder.setEnabled(info.database is not None)

    def _open_folder(self) -> None:
        if self._info.database is not None:
            common.open_folder(self._info.database.parent)


def display_stamp(stamp: str | None) -> str:
    """'2026-10-21T18:05:12' -> '21/10/2026 18:05'."""
    if not stamp:
        return "—"
    return f"{display_date(stamp[:10])} {stamp[11:16]}"


def size_text(size: int | None) -> str:
    if size is None:
        return "—"
    return t["backups.size"].format(size=f"{size / 1_000_000:.1f}".replace(".", ","))


def kind_text(b: Backup) -> str:
    if Path(b.file_path).stem.endswith(restore.SAFETY_LABEL):
        return t["backups.kind.safety"]
    return t[f"backups.kind.{b.type}"]


def backups_folder(conn) -> Path | None:
    """Next to the database in use, as config.backup_dir() (None: a test in memory)."""
    database = about.database_file(conn)
    return None if database is None else database.parent / "backups"


def take_now(conn, ctx: UserContext, folder: Path) -> tuple[Backup | None, str | None]:
    """« Sauvegarder maintenant »: the copy made (None when refused) and what to tell the
    user when something went wrong (refused, or made but missing from the second
    location)."""
    try:
        return backup.take_now(conn, ctx, folder), None
    except backup.MirrorFailed as exc:  # made here; only the second copy is missing
        return exc.backup, t["backups.second_warning"].format(error=exc.message)
    except BusinessRuleError as exc:
        return None, exc.message


class BackupsTab(QWidget):
    """The copies of the database (latest first), « Sauvegarder maintenant », the second
    location, and restoring a copy. `restored(safety copy's path)` is emitted once a copy is
    in place: the window then goes back to the login screen."""

    restored = Signal(str)

    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self._backups: dict[int, Backup] = {}
        self.folder = backups_folder(conn)

        intro = caption(t["backups.caption"])
        intro.setWordWrap(True)
        self.error = PageBanner()
        self.where = value_label()
        self.open_folder = QPushButton(t["backups.open_folder"])
        self.open_folder.setAutoDefault(False)
        self.open_folder.clicked.connect(lambda: common.open_folder(self.folder))
        where_row = QHBoxLayout()
        where_row.addWidget(self.where, 1)
        where_row.addWidget(self.open_folder)

        second_title = QLabel(t["backups.second_title"])
        second_title.setObjectName("sectionTitle")
        self.second = value_label()
        self.choose_second = QPushButton(t["backups.second_choose"])
        self.choose_second.setAutoDefault(False)
        self.choose_second.clicked.connect(self._choose_second)
        self.remove_second = QPushButton(t["backups.second_remove"])
        self.remove_second.setAutoDefault(False)
        self.remove_second.clicked.connect(self._remove_second)
        second_row = QHBoxLayout()
        second_row.addWidget(self.second, 1)
        second_row.addWidget(self.choose_second)
        second_row.addWidget(self.remove_second)

        self.list = ListSection([t["backups.col.date"], t["backups.col.kind"],
                                 t["backups.col.size"], t["backups.col.status"]],
                                t["backups.empty"])
        list_title = QLabel(t["backups.list_title"])
        list_title.setObjectName("sectionTitle")
        self.list.toolbar.insertWidget(0, list_title)
        self.restore_file = self.list.add_button(QPushButton(t["backups.restore_file"]))
        self.restore_file.clicked.connect(self._restore_file)
        self.restore_selected = self.list.add_button(
            variant_button(t["backups.restore"], "danger"))
        self.restore_selected.clicked.connect(self._restore_selected)
        self.take_now = self.list.add_button(primary_button(t["backups.take_now"]), end=True)
        self.take_now.setDefault(False)
        self.take_now.clicked.connect(self._take_now)
        self.list.selection_changed.connect(self._update_buttons)
        fit_columns(self.list.table, stretch=(1,))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(intro)
        layout.addWidget(self.error)
        layout.addLayout(where_row)
        layout.addSpacing(4)
        layout.addWidget(second_title)
        layout.addLayout(second_row)
        layout.addSpacing(4)
        layout.addWidget(self.list, 1)
        self.refresh()

    # ----- loading -----

    def refresh(self) -> None:
        on_disk = self.folder is not None
        self.where.setText(t["backups.where"].format(folder=self.folder) if on_disk
                           else t["backups.in_memory"])
        self.open_folder.setEnabled(on_disk)
        self.take_now.setEnabled(on_disk)
        self.restore_file.setEnabled(on_disk)
        root = backup.second_root(self._conn)
        if root is None:
            self.second.setText(t["backups.second_none"])
        else:
            self.second.setText(t["backups.second_set"].format(
                folder=backup.second_folder(self._conn)))
        self.remove_second.setVisible(root is not None)
        listed = backup.list_backups(self._conn)
        self._backups = {b.id: b for b in listed}
        self.list.set_rows([self._cells(b) for b in listed])
        self._update_buttons()

    @staticmethod
    def _cells(b: Backup) -> list:
        return [
            item(display_stamp(b.created_at), b.created_at, item_id=b.id),
            item(kind_text(b)),
            item(size_text(b.size_bytes), align=CENTER, mono=True),
            item(t[f"backups.status.{b.status}"], kind=kind_for("backup", b.status),
                 align=CENTER),
        ]

    def selected(self) -> Backup | None:
        backup_id = self.list.selected_id()
        return None if backup_id is None else self._backups.get(backup_id)

    def _update_buttons(self) -> None:
        b = self.selected()
        self.restore_selected.setEnabled(b is not None and b.status == "verified"
                                         and self.folder is not None)

    def _show(self, message: str | None) -> None:
        if message:
            self.error.show_error(message)
        else:
            self.error.clear_error()

    # ----- a copy now -----

    def _take_now(self) -> None:
        taken, problem = take_now(self._conn, self._ctx, self.folder)
        self.refresh()
        self._show(problem)
        if taken is not None:
            self.list.select_id(taken.id)
        if problem is None:
            toast(self, t["backups.taken"].format(name=Path(taken.file_path).name))

    # ----- second location -----

    def _choose_second(self) -> None:
        start = backup.second_root(self._conn) or Path.home()
        chosen = common.ask_folder(self, t["backups.second_choose"], start)
        if chosen is None:
            return
        try:
            backup.set_second_root(self._conn, self._ctx, str(chosen))
        except BusinessRuleError as exc:
            self._show(exc.message)
            return
        self._show(None)
        self.refresh()
        toast(self, t["backups.second_saved"].format(folder=chosen))

    def _remove_second(self) -> None:
        if not confirm(self, t["backups.second_remove"], t["backups.second_remove_confirm"],
                       t["backups.second_remove"]):
            return
        backup.set_second_root(self._conn, self._ctx, "")
        self._show(None)
        self.refresh()
        toast(self, t["backups.second_removed"])

    # ----- restore -----

    def _restore_selected(self) -> None:
        b = self.selected()
        if b is None:
            return
        try:
            info = restore.inspect_backup(self._conn, self._ctx, b.id)
        except BusinessRuleError as exc:
            self.refresh()
            self._show(exc.message)
            return
        self._restore(info, display_stamp(b.created_at))

    def _restore_file(self) -> None:
        start = backup.second_folder(self._conn) or self.folder
        chosen = common.ask_open_path(self, t["backups.restore_file"], start,
                                      t["backups.file_filter"])
        if chosen is None:
            return
        try:
            info = restore.inspect(chosen)
        except BusinessRuleError as exc:
            self._show(exc.message)
            return
        self._restore(info, chosen.name)

    def _restore(self, info: restore.CopyInfo, name: str) -> None:
        text = t["restore.confirm"].format(
            name=name, school=info.school or "—", students=info.students,
            last=display_stamp(info.last_activity))
        if not confirm(self, t["restore.confirm_title"], text, t["restore.action"]):
            return
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            done = restore.restore(self._conn, self._ctx, info.path, self.folder)
        except BusinessRuleError as exc:
            self.refresh()
            self._show(exc.message)
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        self.restored.emit(done.safety.file_path)
