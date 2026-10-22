"""Dialogs of the Présences page: cancel a session, schedule its makeup, set a substitute; and
of the timetable: move one session to another day of its week (« Reporter »)."""

from datetime import date, timedelta

from PySide6.QtWidgets import QLineEdit

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.domain.models import Session
from tadris.i18n.fr import t
from tadris.services import rooms, sessions, settings, teachers
from tadris.ui.group_dialogs import required_id
from tadris.ui.setup_dialogs import required_date
from tadris.ui.widgets.common import labeled
from tadris.ui.widgets.date_edit import DateLineEdit
from tadris.ui.widgets.forms import FormDialog, caption, row
from tadris.ui.widgets.inputs import id_combo, read_time, time_combo


def session_text(s: Session) -> str:
    return t["session_dialog.what"].format(
        group=s.group_title, date=dates.display_date(s.date), start=s.start_time,
        end=s.end_time)


def teacher_combo(conn, ctx: UserContext, selected: int | None):
    return id_combo([(teacher.full_name, teacher.id)
                     for teacher in teachers.search(conn, ctx)], selected)


class CancelSessionDialog(FormDialog):
    def __init__(self, conn, ctx: UserContext, session: Session, parent=None):
        super().__init__(t["cancel_session_dialog.title"], t["cancel_session_dialog.submit"],
                         parent=parent)
        self._conn, self._ctx, self._session = conn, ctx, session
        self.submit.setProperty("variant", "danger")
        self.reason = QLineEdit()
        self.reason.setPlaceholderText(t["cancel_session_dialog.placeholder"])
        note = caption(session_text(session))
        note.setWordWrap(True)
        self.add(note)
        self.add(labeled(t["cancel_registration_dialog.reason"], self.reason, required=True))
        self.finish(self.reason)

    def save(self) -> None:
        sessions.cancel(self._conn, self._ctx, self._session.id, self.reason.text())


class MakeupDialog(FormDialog):
    """Another date and time for a cancelled session, in a room, with a teacher."""

    def __init__(self, conn, ctx: UserContext, session: Session, parent=None):
        super().__init__(t["makeup_dialog.title"], t["makeup_dialog.submit"], width=560,
                         parent=parent)
        self._conn, self._ctx, self._session = conn, ctx, session
        self.makeup_id: int | None = None
        opens_at, closes_at = settings.school_hours(conn)
        self.date = DateLineEdit(minimum=dates.today())
        self.date.set_value(max(dates.today(), date.fromisoformat(session.date))
                            + timedelta(days=1))
        self.start = time_combo(session.start_time, opens_at, closes_at)
        self.end = time_combo(session.end_time, opens_at, closes_at)
        self.room = id_combo([(r.name, r.id) for r in rooms.list_rooms(conn, ctx, True)],
                             session.room_id)
        self.teacher = teacher_combo(conn, ctx, session.teacher_id)
        note = caption(t["makeup_dialog.caption"].format(what=session_text(session),
                                                         reason=session.cancellation_reason))
        note.setWordWrap(True)
        self.add(note)
        self.add(row(labeled(t["makeup_dialog.date"], self.date, required=True),
                     labeled(t["makeup_dialog.start"], self.start, required=True),
                     labeled(t["makeup_dialog.end"], self.end, required=True)))
        self.add(row(labeled(t["makeup_dialog.room"], self.room, required=True),
                     labeled(t["makeup_dialog.teacher"], self.teacher, required=True)))
        self.finish(self.date)

    def save(self) -> None:
        self.makeup_id = sessions.schedule_makeup(
            self._conn, self._ctx, self._session.id, required_date(self.date),
            read_time(self.start), read_time(self.end), required_id(self.room),
            required_id(self.teacher))


class RescheduleDialog(FormDialog):
    """One session of the week elsewhere, with a reason: it is cancelled and a makeup takes
    its place, the same week (from today). The timetable does not change."""

    def __init__(self, conn, ctx: UserContext, session: Session, parent=None):
        super().__init__(t["reschedule_dialog.title"], t["reschedule_dialog.submit"],
                         width=560, parent=parent)
        self._conn, self._ctx, self._session = conn, ctx, session
        self.makeup_id: int | None = None
        opens_at, closes_at = settings.school_hours(conn)
        first = dates.week_start(date.fromisoformat(session.date))
        self.first, self.last = max(first, dates.today()), first + timedelta(days=6)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText(t["reschedule_dialog.placeholder"])
        self.date = DateLineEdit(minimum=self.first, maximum=self.last)
        self.date.set_value(date.fromisoformat(session.date))
        self.start = time_combo(session.start_time, opens_at, closes_at)
        self.end = time_combo(session.end_time, opens_at, closes_at)
        self.room = id_combo([(r.name, r.id) for r in rooms.list_rooms(conn, ctx, True)],
                             session.room_id)
        self.teacher = teacher_combo(conn, ctx, session.teacher_id)
        note = caption(t["reschedule_dialog.caption"].format(
            what=session_text(session), first=dates.display_date(dates.iso(self.first)),
            last=dates.display_date(dates.iso(self.last))))
        note.setWordWrap(True)
        self.add(note)
        self.add(labeled(t["reschedule_dialog.reason"], self.reason, required=True))
        self.add(row(labeled(t["makeup_dialog.date"], self.date, required=True),
                     labeled(t["makeup_dialog.start"], self.start, required=True),
                     labeled(t["makeup_dialog.end"], self.end, required=True)))
        self.add(row(labeled(t["makeup_dialog.room"], self.room, required=True),
                     labeled(t["makeup_dialog.teacher"], self.teacher, required=True)))
        self.finish(self.reason)

    def save(self) -> None:
        self.makeup_id = sessions.reschedule(
            self._conn, self._ctx, self._session.id, required_date(self.date),
            read_time(self.start), read_time(self.end), required_id(self.room),
            self.reason.text(), required_id(self.teacher))


class SubstituteDialog(FormDialog):
    """Another teacher for this session only; the group's teacher again removes it."""

    def __init__(self, conn, ctx: UserContext, session: Session, parent=None):
        super().__init__(t["substitute_dialog.title"], t["action.save"], parent=parent)
        self._conn, self._ctx, self._session = conn, ctx, session
        self.teacher = teacher_combo(conn, ctx, session.teacher_id)
        note = caption(t["substitute_dialog.caption"].format(what=session_text(session)))
        note.setWordWrap(True)
        self.add(note)
        self.add(labeled(t["substitute_dialog.teacher"], self.teacher, required=True))
        self.finish(self.teacher)

    def save(self) -> None:
        sessions.set_teacher(self._conn, self._ctx, self._session.id,
                             required_id(self.teacher))
