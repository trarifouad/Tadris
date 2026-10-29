"""Contacts: a WhatsApp message to the parents of one student or of a whole group. Tadris
opens each chat with the message typed; the desk presses Envoyer in WhatsApp, one parent
after the other. With no internet on this computer, the QR code opens the same chat on a
phone.

A group linked to its WhatsApp group (created once by the desk, Tadris cannot) gets its
announcements in one send: « Publier dans le groupe » copies the message and opens the
group, the desk pastes it. The parents are invited once, with the « Invitation » model; the
list remembers who was. Models (séance annulée, vacances…) write the message from the data."""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from tadris.core import dates, whatsapp
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError
from tadris.core.phones import format_phone
from tadris.i18n.fr import t
from tadris.services import announcements, groups, messages, students
from tadris.ui.student_picker import StudentPicker
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets.common import (
    ask,
    confirm,
    labeled,
    primary_button,
    toast,
    variant_button,
)
from tadris.ui.widgets.forms import FormDialog, caption
from tadris.ui.widgets.qr_code import QrCode
from tadris.ui.widgets.tables import fill, fit_columns, item, ruled_table

QR_CARD_WIDTH = 292
QR_CARD_MARGIN = 16

MODES = (("contacts.to_student", "student"), ("contacts.to_group", "group"))


def open_chat(phone: str, text: str) -> None:
    """WhatsApp Desktop if it is installed, else WhatsApp Web in the browser."""
    if whatsapp.desktop_app_installed():
        QDesktopServices.openUrl(QUrl(whatsapp.app_link(phone, text)))
    else:
        QDesktopServices.openUrl(QUrl(whatsapp.browser_link(phone, text)))


def open_group(code: str, text: str) -> None:
    """A link cannot type in a group: the message goes to the clipboard, the desk pastes."""
    QGuiApplication.clipboard().setText(text)
    if whatsapp.desktop_app_installed():
        QDesktopServices.openUrl(QUrl(whatsapp.group_app_link(code)))
    else:
        QDesktopServices.openUrl(QUrl(whatsapp.group_browser_link(code)))


class LinkGroupDialog(FormDialog):
    """The invite link of the WhatsApp group the desk created for this group."""

    def __init__(self, conn, ctx: UserContext, group_id: int, parent=None):
        super().__init__(t["whatsapp_group.link_title"], t["action.save"], width=540,
                         parent=parent)
        self._conn, self._ctx, self._group_id = conn, ctx, group_id
        self.link = QLineEdit()
        self.link.setPlaceholderText("https://chat.whatsapp.com/…")
        code = messages.group_code(conn, ctx, group_id)
        if code:
            self.link.setText(whatsapp.invite_link(code))
        self.add(labeled(t["whatsapp_group.link_label"], self.link, required=True))
        self.finish(self.link)

    def save(self) -> None:
        messages.link_group(self._conn, self._ctx, self._group_id, self.link.text())


class ContactsPage(QWidget):
    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn, self._ctx = conn, ctx
        self.setObjectName("page")
        self.student_id: int | None = None
        self.recipients: list[messages.Recipient] = []
        self.opened: set[int] = set()  # contact ids whose chat was opened
        self.code: str | None = None  # the WhatsApp group of the group shown, if linked
        self.invited: dict[int, str] = {}  # contact_id: invited_at, for that group
        self.choices: list[announcements.Choice] = []  # what the model can be about

        heading = QLabel(t["nav.contacts"])
        heading.setObjectName("pageTitle")
        intro = caption(t["contacts.intro"])
        intro.setWordWrap(True)

        self.mode = QComboBox()
        for label_key, value in MODES:
            self.mode.addItem(t[label_key], value)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.choose_student = variant_button(t["contacts.choose_student"], "ghost")
        self.choose_student.clicked.connect(self._pick_student)
        self.student_label = QLabel()
        self.group = QComboBox()
        self.group.currentIndexChanged.connect(lambda _i: self._load())
        who = QHBoxLayout()
        who.setSpacing(12)
        who.addWidget(self.mode)
        who.addWidget(self.choose_student)
        who.addWidget(self.student_label)
        who.addWidget(self.group, 1)
        who.addStretch()

        # The WhatsApp group of the group shown: how to link it, or one send to everyone.
        self.wa_card = QFrame()
        self.wa_card.setObjectName("card")
        wa_title = QLabel(t["whatsapp_group.title"])
        wa_title.setObjectName("cardTitle")
        self.wa_text = caption()
        self.wa_text.setWordWrap(True)
        self.link_button = variant_button(t["whatsapp_group.link"], "ghost")
        self.link_button.clicked.connect(self._link_group)
        self.unlink_button = variant_button(t["whatsapp_group.unlink"], "ghost")
        self.unlink_button.clicked.connect(self._unlink_group)
        self.post_button = primary_button(t["whatsapp_group.post"])
        self.post_button.setDefault(False)
        self.post_button.clicked.connect(self.post_to_group)
        wa_text_side = QVBoxLayout()
        wa_text_side.setSpacing(4)
        wa_text_side.addWidget(wa_title)
        wa_text_side.addWidget(self.wa_text)
        # Stays until the message or the group changes: the toast alone was missed.
        self.paste_hint = QLabel(t["whatsapp_group.paste_now"])
        self.paste_hint.setObjectName("warningBanner")
        self.paste_hint.setWordWrap(True)
        self.paste_hint.hide()
        wa_layout = QHBoxLayout(self.wa_card)
        wa_layout.setContentsMargins(16, 12, 16, 12)
        wa_layout.setSpacing(8)
        wa_layout.addLayout(wa_text_side, 1)
        wa_layout.addWidget(self.unlink_button, 0, Qt.AlignmentFlag.AlignVCenter)
        wa_layout.addWidget(self.link_button, 0, Qt.AlignmentFlag.AlignVCenter)
        wa_layout.addWidget(self.post_button, 0, Qt.AlignmentFlag.AlignVCenter)

        # A model writes the message; « À propos de » picks the session, holiday, month…
        self.template = QComboBox()
        self.template.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.template.currentIndexChanged.connect(lambda _i: self._template_changed())
        self.about = QComboBox()
        self.about.setMinimumWidth(320)
        self.about.currentIndexChanged.connect(lambda _i: self._compose())
        self.template_note = caption()
        self.template_note.setWordWrap(True)
        models = QHBoxLayout()
        models.setSpacing(12)
        models.addWidget(labeled(t["contacts.template"], self.template))
        models.addWidget(labeled(t["contacts.about"], self.about))
        models.addStretch()

        self.message = QPlainTextEdit()
        self.message.setPlaceholderText(t["contacts.message_placeholder"])
        self.message.setFixedHeight(110)
        self.message.textChanged.connect(self._message_changed)
        self.insert_name = variant_button(t["contacts.insert_name"], "ghost")
        self.insert_name.clicked.connect(lambda: self.message.insertPlainText(whatsapp.STUDENT))
        self.length = caption()
        under_message = QHBoxLayout()
        under_message.addWidget(self.insert_name)
        under_message.addStretch()
        under_message.addWidget(self.length)

        self.table = ruled_table([t["contacts.col.name"], t["contacts.col.relation"],
                                  t["contacts.col.students"], t["contacts.col.phone"],
                                  t["contacts.col.state"]])
        fit_columns(self.table, stretch=(0, 2))
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.activated.connect(lambda _index: self.open_selected())
        self.empty = QLabel()
        self.empty.setObjectName("emptyState")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.count = caption()

        self.open_button = primary_button(t["contacts.open"])
        self.open_button.setDefault(False)
        self.open_button.clicked.connect(self.open_selected)
        self.next_button = variant_button(t["contacts.open_next"], "ghost")
        self.next_button.clicked.connect(self.open_next)
        actions = QHBoxLayout()
        actions.addWidget(self.count)
        actions.addStretch()
        actions.addWidget(self.next_button)
        actions.addWidget(self.open_button)

        list_side = QVBoxLayout()
        list_side.setSpacing(12)
        list_side.addWidget(self.table, 1)
        list_side.addWidget(self.empty)
        list_side.addLayout(actions)

        self.qr = QrCode(260)
        self.qr_title = qr_title = QLabel(t["contacts.qr_title"])
        qr_title.setObjectName("cardTitle")
        self.qr_caption = caption()
        self.qr_caption.setWordWrap(True)
        card = QFrame()
        card.setObjectName("card")
        card.setFixedWidth(QR_CARD_WIDTH)
        self.qr_card = card
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(QR_CARD_MARGIN, 14, QR_CARD_MARGIN, 16)
        card_layout.setSpacing(10)
        card_layout.addWidget(qr_title)
        card_layout.addWidget(self.qr, 1)
        card_layout.addWidget(self.qr_caption)

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addLayout(list_side, 1)
        body.addWidget(card)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(14)
        layout.addWidget(heading)
        layout.addWidget(intro)
        layout.addLayout(who)
        layout.addWidget(self.wa_card)
        layout.addWidget(self.paste_hint)
        layout.addLayout(models)
        layout.addWidget(self.template_note)
        layout.addWidget(self.message)
        layout.addLayout(under_message)
        layout.addLayout(body, 1)

        self._fill_groups()
        self._mode_changed()

    def refresh(self) -> None:
        """Back on the page: groups and contacts may have changed elsewhere."""
        self._fill_groups()
        self._load()

    # ----- who -----

    def _fill_groups(self) -> None:
        current = self.group.currentData()
        self.group.blockSignals(True)
        self.group.clear()
        for g in groups.search(self._conn, self._ctx):
            if g.state != "closed":
                self.group.addItem(g.title, g.id)
        index = self.group.findData(current)
        self.group.setCurrentIndex(max(index, 0))
        self.group.blockSignals(False)

    def _mode_changed(self) -> None:
        by_student = self.mode.currentData() == "student"
        self.choose_student.setVisible(by_student)
        self.student_label.setVisible(by_student)
        self.group.setVisible(not by_student)
        self.template.blockSignals(True)
        self.template.clear()
        for kind in announcements.kinds("student" if by_student else "group"):
            self.template.addItem(t[f"announce.kind.{kind}"], kind)
        self.template.blockSignals(False)
        self._load()

    def _pick_student(self) -> None:
        picker = StudentPicker(self._conn, self._ctx, title=t["contacts.choose_student"],
                               parent=self)
        if ask(picker):
            self.show_student(picker.student_id)

    def show_student(self, student_id: int) -> None:
        self.student_id = student_id
        self.mode.setCurrentIndex(self.mode.findData("student"))
        self._load()

    def show_group(self, group_id: int) -> None:
        self.mode.setCurrentIndex(self.mode.findData("group"))
        self.group.setCurrentIndex(max(self.group.findData(group_id), 0))
        self._load()

    def _by_student(self) -> bool:
        return self.mode.currentData() == "student"

    def _load(self) -> None:
        by_student = self._by_student()
        group_id = None if by_student else self.group.currentData()
        if by_student:
            if self.student_id is None:
                self.student_label.setText("")
                found, empty = [], t["contacts.pick_first"]
            else:
                student = students.get(self._conn, self._ctx, self.student_id)
                self.student_label.setText(student.full_name)
                found = messages.for_student(self._conn, self._ctx, self.student_id)
                empty = t["contacts.none_for_student"]
        else:
            found = [] if group_id is None else messages.for_group(self._conn, self._ctx,
                                                                   group_id)
            empty = t["contacts.none_for_group" if group_id is not None
                      else "contacts.no_groups"]
        self.code = None if group_id is None else messages.group_code(self._conn, self._ctx,
                                                                      group_id)
        self.invited = {} if self.code is None else messages.invited(self._conn, self._ctx,
                                                                     group_id)
        self.recipients = found
        self.opened = set()
        self.empty.setText(empty)
        self.empty.setVisible(not found)
        self.table.setVisible(bool(found))
        self._refresh_group_card()
        self._fill_table()
        if found:
            self.table.selectRow(0)
        self._template_changed()

    # ----- the WhatsApp group -----

    def _refresh_group_card(self) -> None:
        self.paste_hint.hide()
        group_id = None if self._by_student() else self.group.currentData()
        self.wa_card.setVisible(group_id is not None)
        if group_id is None:
            return
        linked = self.code is not None
        if linked:
            self.wa_text.setText(t["whatsapp_group.linked_intro"])
        else:
            g = groups.get(self._conn, self._ctx, group_id)
            self.wa_text.setText(t["whatsapp_group.not_linked_intro"].format(
                name=announcements.group_label(g)))
        self.link_button.setText(t["whatsapp_group.change" if linked
                                   else "whatsapp_group.link"])
        self.unlink_button.setVisible(linked)
        self.post_button.setVisible(linked)

    def _link_group(self) -> None:
        group_id = self.group.currentData()
        if group_id is None:
            return
        if ask(LinkGroupDialog(self._conn, self._ctx, group_id, parent=self)):
            self._load()
            self.template.setCurrentIndex(self.template.findData("invite"))
            toast(self, t["whatsapp_group.linked"])

    def _unlink_group(self) -> None:
        group_id = self.group.currentData()
        if group_id is None or not confirm(
                self, t["whatsapp_group.unlink"],
                t["whatsapp_group.unlink_confirm"].format(group=self.group.currentText()),
                t["whatsapp_group.unlink"]):
            return
        messages.unlink_group(self._conn, self._ctx, group_id)
        self._load()
        toast(self, t["whatsapp_group.unlinked"])

    def _can_post(self) -> bool:
        """One send to the WhatsApp group: not the invitation (it is for those not in yet),
        nor a message naming {élève} (a group message names nobody)."""
        return (self.code is not None and self._message_ok() and self._kind() != "invite"
                and whatsapp.STUDENT not in self.message.toPlainText())

    def post_to_group(self) -> None:
        if not self._can_post():
            return
        open_group(self.code, self.message.toPlainText().strip())
        self.paste_hint.show()
        toast(self, t["whatsapp_group.posted"])

    # ----- the model -----

    def _kind(self) -> str:
        return self.template.currentData() or "free"

    def _template_changed(self) -> None:
        kind = self._kind()
        self._fill_table()  # the invitation shows who was invited
        self.about.blockSignals(True)
        self.about.clear()
        self.choices = []
        if kind in announcements.NEEDS_CHOICE and self._target_ready():
            self.choices = announcements.choices(self._conn, self._ctx, kind,
                                                 self.group.currentData(), self.student_id)
            for choice in self.choices:
                self.about.addItem(choice.label, choice.id)
        self.about.blockSignals(False)
        self.about.parentWidget().setVisible(bool(self.choices))  # never an empty list
        self._compose()

    def _target_ready(self) -> bool:
        if self._by_student():
            return self.student_id is not None
        return self.group.currentData() is not None

    def _show_note(self, text: str) -> None:
        self.template_note.setText(text)
        self.template_note.setVisible(bool(text))

    def _compose(self) -> None:
        kind = self._kind()
        self._show_note("")
        if kind == "free":
            self._selection_changed()
            return
        if not self._target_ready():
            self.message.clear()
            return
        try:
            text = announcements.compose(
                self._conn, self._ctx, kind, self.about.currentData(),
                None if self._by_student() else self.group.currentData(), self.student_id)
        except BusinessRuleError as exc:
            self._show_note(exc.message)
            self.message.clear()
            return
        self.message.setPlainText(text)

    # ----- the list -----

    def _inviting(self) -> bool:
        return self._kind() == "invite" and self.code is not None

    def _state(self, r: messages.Recipient) -> str:
        if r.phone is None:
            return "no_mobile"
        if self._inviting() and r.contact_id in self.invited:
            return "invited"
        return "opened" if r.contact_id in self.opened else "to_send"

    def _state_text(self, r: messages.Recipient, state: str) -> str:
        if state == "invited":
            return t["contacts.invited_on"].format(
                day=dates.display_date(self.invited[r.contact_id]))
        return t[f"contacts.state.{state}"]

    def _fill_table(self) -> None:
        rows = []
        for r in self.recipients:
            state = self._state(r)
            rows.append([
                item(r.full_name, item_id=r.contact_id),
                item(r.relation or ""),
                item(", ".join(r.students)),
                item(format_phone(r.phone) if r.phone else "—", mono=True),
                item(self._state_text(r, state), state, kind=kind_for("message", state)),
            ])
        selected = self._selected_row()
        fill(self.table, rows)
        if selected is not None:
            self.table.selectRow(selected)
        reachable = [r for r in self.recipients if r.phone is not None]
        if not self.recipients:
            self.count.setText("")
        elif self._inviting():
            self.count.setText(t["contacts.invited_count"].format(
                invited=sum(1 for r in reachable if r.contact_id in self.invited),
                count=len(reachable)))
        else:
            self.count.setText(t["contacts.count"].format(opened=len(self.opened),
                                                          count=len(reachable)))

    def _selected_row(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def selected(self) -> messages.Recipient | None:
        row = self._selected_row()
        return None if row is None else self.recipients[row]

    def text_for(self, r: messages.Recipient) -> str:
        return whatsapp.personal(self.message.toPlainText().strip(), list(r.students))

    def _message_ok(self) -> bool:
        text = self.message.toPlainText().strip()
        return bool(text) and len(text) <= whatsapp.MAX_LENGTH

    def _message_changed(self) -> None:
        self.paste_hint.hide()  # another message: not copied yet
        size = len(self.message.toPlainText().strip())
        key = "contacts.too_long" if size > whatsapp.MAX_LENGTH else "contacts.length"
        self.length.setText(t[key].format(size=size, max=whatsapp.MAX_LENGTH))
        self._selection_changed()

    def _selection_changed(self) -> None:
        r = self.selected()
        ready = self._message_ok()
        self.open_button.setEnabled(ready and r is not None and r.phone is not None)
        self.next_button.setEnabled(ready and self._next() is not None)
        self.post_button.setEnabled(self._can_post())
        self.qr_title.setText(t["contacts.qr_invite_title" if self._inviting()
                                else "contacts.qr_title"])
        if self._inviting():
            # Parents at the desk join by scanning: the group's own link, not a chat.
            self.qr.set_text(whatsapp.invite_link(self.code))
            self.qr_caption.setText(t["contacts.qr_invite_caption"])
        elif r is None:
            self.qr.set_text(None)
            self.qr_caption.setText(t["contacts.qr_none"])
        elif r.phone is None:
            self.qr.set_text(None)
            self.qr_caption.setText(t["contacts.qr_no_mobile"].format(name=r.full_name))
        elif not ready:
            self.qr.set_text(None)
            self.qr_caption.setText(t["contacts.qr_write_first"])
        else:
            link = whatsapp.web_link(r.phone, self.text_for(r))
            fits = whatsapp.fits_qr(link)
            self.qr.set_text(link if fits else None)
            self.qr_caption.setText(t["contacts.qr_caption" if fits else "contacts.qr_too_long"]
                                    .format(name=r.full_name))
        # A wrapped label does not tell the layout its height: without this, a short window
        # draws the code over it instead of scrolling the page.
        self.qr_caption.setMinimumHeight(self.qr_caption.heightForWidth(
            QR_CARD_WIDTH - 2 * QR_CARD_MARGIN))
        self.qr_card.setMinimumHeight(self.qr_card.layout().minimumSize().height())

    def _next(self) -> int | None:
        """The first row still to send, after the one selected, then from the top."""
        start = self._selected_row()
        start = -1 if start is None else start
        order = list(range(start + 1, len(self.recipients))) + list(range(start + 1))
        return next((i for i in order if self._state(self.recipients[i]) == "to_send"), None)

    # ----- opening WhatsApp -----

    def open_selected(self) -> None:
        r = self.selected()
        if r is None or r.phone is None or not self._message_ok():
            return
        open_chat(r.phone, self.text_for(r))
        self.opened.add(r.contact_id)
        if self._inviting():
            group_id = self.group.currentData()
            messages.mark_invited(self._conn, self._ctx, group_id, r.contact_id)
            self.invited = messages.invited(self._conn, self._ctx, group_id)
        self._fill_table()
        self._selection_changed()
        toast(self, t["contacts.opened"].format(name=r.full_name))

    def open_next(self) -> None:
        row = self._next()
        if row is None:
            return
        self.table.selectRow(row)
        self.open_selected()
