"""WhatsApp « click to chat » links: the chat opens with the message typed, and the desk
presses Envoyer. Nothing is sent by Tadris, so it needs no account, no API and no internet;
WhatsApp sends it once the device it opens on is online."""

import re
import shutil
import subprocess
import sys
from functools import cache
from urllib.parse import quote

from tadris.core.phones import is_mobile

STUDENT = "{élève}"  # in a message: the student's name, or the siblings' (« Amine et Sara »)
MAX_LENGTH = 1000  # a message, in characters
# A longer link makes a QR code too dense for a phone to read on a screen (an accented
# letter takes 6 of them): « Ouvrir WhatsApp » still works.
QR_MAX_LINK = 600
# A group's invite link, as WhatsApp copies it (Infos du groupe → Inviter via lien), with
# or without https:// and a trailing ?mode=… WhatsApp may add.
_INVITE = re.compile(r"(?:https?://)?chat\.whatsapp\.com/(?:invite/)?([A-Za-z0-9]{16,32})"
                     r"/?(?:\?\S*)?")


def international(phone: str) -> str | None:
    """'0661902547' -> '213661902547'. None for a landline: it has no WhatsApp."""
    return "213" + phone[1:] if is_mobile(phone) else None


def personal(text: str, names: list[str]) -> str:
    """The message for one contact: {élève} becomes the names of their children."""
    if len(names) > 1:
        joined = f"{', '.join(names[:-1])} et {names[-1]}"
    else:
        joined = names[0] if names else ""
    return text.replace(STUDENT, joined)


def web_link(phone: str, text: str) -> str:
    """Opens WhatsApp from a phone's camera (the QR code): the app, or its web page."""
    return f"https://wa.me/{international(phone)}?text={quote(text, safe='')}"


def fits_qr(link: str) -> bool:
    return len(link) <= QR_MAX_LINK


def app_link(phone: str, text: str) -> str:
    """Opens WhatsApp Desktop directly, without a browser."""
    return f"whatsapp://send?phone={international(phone)}&text={quote(text, safe='')}"


def browser_link(phone: str, text: str) -> str:
    """Opens the chat in WhatsApp Web, the ordinary account linked by its QR code once."""
    return (f"https://web.whatsapp.com/send?phone={international(phone)}"
            f"&text={quote(text, safe='')}")


def invite_code(text: str) -> str | None:
    """'https://chat.whatsapp.com/AbCd…?mode=ac_t' -> 'AbCd…'. None: not an invite link."""
    match = _INVITE.fullmatch(text.strip())
    return match.group(1) if match else None


def invite_link(code: str) -> str:
    """What parents open or scan to join the group (any phone, any app)."""
    return f"https://chat.whatsapp.com/{code}"


def group_app_link(code: str) -> str:
    """Opens the group in WhatsApp Desktop. A link cannot type a message in a group: the
    desk pastes it."""
    return f"whatsapp://chat?code={code}"


def group_browser_link(code: str) -> str:
    """Opens the group in WhatsApp Web."""
    return f"https://web.whatsapp.com/accept?code={code}"


@cache
def desktop_app_installed() -> bool:
    """Whether a program opens whatsapp:// links. Asked of the system, not tried: a link
    nothing opens shows « no apps available » on Linux, never an error to fall back on."""
    if sys.platform == "win32":
        import winreg

        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "whatsapp"))
            return True
        except OSError:
            return False
    if sys.platform.startswith("linux") and shutil.which("xdg-mime"):
        try:
            found = subprocess.run(["xdg-mime", "query", "default", "x-scheme-handler/whatsapp"],
                                   capture_output=True, text=True, timeout=3, check=False)
        except (OSError, subprocess.SubprocessError):
            return False
        return bool(found.stdout.strip())
    return False  # macOS and the rest: WhatsApp Web
