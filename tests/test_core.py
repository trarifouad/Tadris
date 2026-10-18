from datetime import date

import pytest

from tadris.core import permissions, security
from tadris.core.context import UserContext
from tadris.core.dates import add_one_month, iso, weekday_1_to_7
from tadris.core.errors import PermissionDenied, ValidationError
from tadris.core.money import format_dzd, parse_dzd
from tadris.i18n.fr import t

DIRECTOR = UserContext(user_id=1, username="dir", role="director")
RECEPTIONIST = UserContext(user_id=2, username="rec", role="receptionist")


# ----- money -----

@pytest.mark.parametrize("amount, text", [
    (0, "0 DA"),
    (500, "500 DA"),
    (3000, "3 000 DA"),
    (1234567, "1 234 567 DA"),
    (-2500, "-2 500 DA"),
])
def test_format_dzd(amount, text):
    assert format_dzd(amount) == text


@pytest.mark.parametrize("text, amount", [
    ("3000", 3000),
    ("3 000 DA", 3000),
    ("3 000 DA", 3000),
    ("3 000 DA", 3000),
    ("3 000 da", 3000),
    ("3 000 Da", 3000),
    ("3000 DZD", 3000),
    ("  +3000  ", 3000),
    ("-500", -500),
])
def test_parse_dzd(text, amount):
    assert parse_dzd(text) == amount


@pytest.mark.parametrize("text", ["", "  ", "DA", "3DA000", "3.000", "3 000,00 DA", "abc", "30O0"])
def test_parse_dzd_rejects_invalid(text):
    with pytest.raises(ValidationError) as exc:
        parse_dzd(text)
    assert exc.value.message == t["money.invalid"]


@pytest.mark.parametrize("amount", [0, 1, 999, 1000, 60000, 1234567, -2500])
def test_money_round_trip(amount):
    assert parse_dzd(format_dzd(amount)) == amount


# ----- dates -----

@pytest.mark.parametrize("start, expected", [
    (date(2026, 1, 31), date(2026, 2, 28)),
    (date(2028, 1, 31), date(2028, 2, 29)),   # leap year
    (date(2028, 2, 29), date(2028, 3, 29)),
    (date(2026, 3, 31), date(2026, 4, 30)),
    (date(2026, 11, 30), date(2026, 12, 30)),
    (date(2026, 12, 31), date(2027, 1, 31)),
    (date(2026, 9, 1), date(2026, 10, 1)),
])
def test_add_one_month(start, expected):
    assert add_one_month(start) == expected


def test_add_one_month_chain_stays_on_shortened_day():
    # Documented behavior: a 31 Jan start drifts to the 28th and stays there.
    d = date(2027, 1, 31)
    chain = []
    for _ in range(3):
        d = add_one_month(d)
        chain.append(d)
    assert chain == [date(2027, 2, 28), date(2027, 3, 28), date(2027, 4, 28)]


def test_weekday_1_to_7():
    assert weekday_1_to_7(date(2026, 10, 19)) == 1  # Monday
    assert weekday_1_to_7(date(2026, 10, 18)) == 7  # Sunday


def test_iso():
    assert iso(date(2026, 9, 1)) == "2026-09-01"


# ----- passwords -----

def test_password_hash_and_verify():
    stored = security.hash_password("secret123")
    assert stored.startswith("scrypt$")
    assert security.verify_password("secret123", stored)
    assert not security.verify_password("secret124", stored)


def test_password_hash_is_salted():
    assert security.hash_password("same") != security.hash_password("same")


@pytest.mark.parametrize("stored", ["", "garbage", "bcrypt$1$2$3$aa$bb", "scrypt$x$8$1$aa$bb"])
def test_verify_password_rejects_malformed_hash(stored):
    assert not security.verify_password("anything", stored)


# ----- permissions -----

RECEPTIONIST_DENIED = {
    "student.deactivate",
    "enrollment.override",
    "payment.void",
    "refund.approve",
    "refund.reject",
    "payout.view",
    "payout.manage",
    "teacher.manage",
    "sms.manage",
    "settings.view",
    "settings.change",
    "user.create",
    "user.disable",
    "audit.view",
}


@pytest.mark.parametrize("action", sorted(permissions.ACTIONS))
def test_permission_matrix(action):
    assert permissions.allowed(DIRECTOR, action)
    assert permissions.allowed(RECEPTIONIST, action) == (action not in RECEPTIONIST_DENIED)


def test_receptionist_denied_list_only_names_real_actions():
    assert RECEPTIONIST_DENIED <= set(permissions.ACTIONS)


def test_require_raises_french_permission_denied():
    permissions.require(DIRECTOR, "payment.void")
    with pytest.raises(PermissionDenied) as exc:
        permissions.require(RECEPTIONIST, "payment.void")
    assert exc.value.message == t["permission.denied"]


def test_unknown_action_is_a_programming_error():
    # A typo must fail loudly in tests, not silently deny everyone.
    with pytest.raises(KeyError):
        permissions.require(DIRECTOR, "payment.viod")


def test_unknown_role_is_denied():
    ghost = UserContext(user_id=3, username="x", role="teacher")
    assert not permissions.allowed(ghost, "student.view")


def test_nav_differs_by_role():
    director_keys = [key for key, _ in permissions.nav_for(DIRECTOR)]
    receptionist_keys = [key for key, _ in permissions.nav_for(RECEPTIONIST)]
    assert director_keys == [key for key, _, _ in permissions.NAV_ITEMS]
    assert "payouts" not in receptionist_keys
    assert "settings" not in receptionist_keys
    assert "students" in receptionist_keys


def test_nav_items_reference_known_actions_and_labels():
    for _, label_key, action in permissions.NAV_ITEMS:
        assert action in permissions.ACTIONS
        assert label_key in t
