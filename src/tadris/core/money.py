import re

from tadris.core.errors import ValidationError
from tadris.i18n.fr import t

_PARSE = re.compile(r"^[+-]?\d+$")
_SUFFIX = re.compile(r"\s*(DA|DZD)$", re.IGNORECASE)


def format_dzd(amount: int) -> str:
    sign = "-" if amount < 0 else ""
    digits = f"{abs(amount):,}".replace(",", " ")
    return f"{sign}{digits} DA"


def of_dzd_in_words(amount: int) -> str:
    """The words after « la somme »: « de deux mille dinars », but « d'un million de
    dinars » and « d'un dinar » (« de » elided before « un »)."""
    words = dzd_in_words(amount)
    return f"d'{words}" if words.startswith("un ") else f"de {words}"


def dzd_inline(amount: int) -> str:
    """An amount in a sentence: « 2 000 DA » with non-breaking spaces, never split across
    two lines."""
    return format_dzd(amount).replace(" ", "\u00a0")


def parse_dzd(text: str) -> int:
    raw = _SUFFIX.sub("", text.strip())
    raw = raw.replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    if not _PARSE.fullmatch(raw):
        raise ValidationError(t["money.invalid"])
    return int(raw)


# ----- an amount in words (French, the spelling before the 1990 reform) -----

_UNITS = ("zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix",
          "onze", "douze", "treize", "quatorze", "quinze", "seize")
_TENS = {2: "vingt", 3: "trente", 4: "quarante", 5: "cinquante", 6: "soixante"}


def _below_100(n: int) -> str:
    if n < 17:
        return _UNITS[n]
    if n < 20:
        return f"dix-{_UNITS[n - 10]}"
    if n < 70:
        tens, unit = divmod(n, 10)
        if unit == 0:
            return _TENS[tens]
        return f"{_TENS[tens]} et un" if unit == 1 else f"{_TENS[tens]}-{_UNITS[unit]}"
    if n < 80:  # soixante-dix ... soixante-dix-neuf, and soixante et onze
        return "soixante et onze" if n == 71 else f"soixante-{_below_100(n - 60)}"
    return "quatre-vingts" if n == 80 else f"quatre-vingt-{_below_100(n - 80)}"


def _below_1000(n: int, before_mille: bool = False) -> str:
    """« cents » and « quatre-vingts » take their s at the end of a number, never before
    « mille » (which is invariable); before « million » or « milliard » (nouns) they keep it."""
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        plural = "s" if rest == 0 and not before_mille else ""
        parts.append("cent" if hundreds == 1 else f"{_UNITS[hundreds]} cent{plural}")
    if rest:
        parts.append(_below_100(rest))
    words = " ".join(parts)
    return words[:-1] if before_mille and words.endswith("quatre-vingts") else words


def number_in_words(n: int) -> str:
    """A whole number from 0 up, in French words: 2500 -> « deux mille cinq cents »."""
    if n < 0:
        raise ValueError("a number in words is never negative")
    if n == 0:
        return _UNITS[0]
    billions, rest = divmod(n, 10**9)
    millions, rest = divmod(rest, 10**6)
    thousands, units = divmod(rest, 1000)
    parts = []
    if billions:
        parts.append(f"{_below_1000(billions)} milliard{'s' if billions > 1 else ''}")
    if millions:
        parts.append(f"{_below_1000(millions)} million{'s' if millions > 1 else ''}")
    if thousands:
        parts.append("mille" if thousands == 1
                     else f"{_below_1000(thousands, before_mille=True)} mille")
    if units:
        parts.append(_below_1000(units))
    return " ".join(parts)


def dzd_in_words(amount: int) -> str:
    """2000 -> « deux mille dinars »; 1 -> « un dinar ». « million » and « milliard » are
    nouns: a whole number of them takes « de » (« un million de dinars »), unlike
    « un million deux cent mille dinars »."""
    unit = f"dinar{'s' if amount > 1 else ''}"
    of = "de " if amount >= 10**6 and amount % 10**6 == 0 else ""
    return f"{number_in_words(amount)} {of}{unit}"
