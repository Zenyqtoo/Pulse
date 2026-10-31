"""Deterministic PII masking. Runs BEFORE any text leaves the server for the LLM.

Regex catches structured identifiers exactly (IIN, phones, e-mails, cards, apartment numbers)
and name patterns typical for Russian/Kazakh full names. LLM-detected names are masked as a
second pass (see pipeline), but correctness never depends on the LLM alone.
"""
import re

_IIN = re.compile(r"(?<!\d)\d{12}(?!\d)")
_CARD = re.compile(r"(?<!\d)(?:\d{4}[ \-]?){3}\d{4}(?!\d)")
_PHONE = re.compile(
    r"(?<![\w\d])(?:\+?7|8)[\s\-\(]*\d{3}[\s\-\)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)"
)
_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")
_APARTMENT = re.compile(r"(?i)\b(кв\.?|квартира|пәтер)\s*№?\s*\d+[а-яa-z]?")
_HOUSE_NUM = re.compile(
    r"(?i)((?:ул\.?|улица|пр\.?|проспект|пр-т|мкр\.?|микрорайон|көшесі|даңғылы|бульвар|переулок|пер\.)"
    r"\s+[А-ЯЁӘҒҚҢӨҰҮҺІA-Z][\w\-]+(?:\s+[А-ЯЁӘҒҚҢӨҰҮҺІ][\w\-]+)?)"
    r"(,?\s*(?:д\.|дом|үй)?\s*)(\d+[а-я]?(?:/\d+)?)"
)
_CAP = r"[А-ЯЁӘҒҚҢӨҰҮҺІ][а-яёәғқңөұүһі]+"
_PATRONYMIC = r"[А-ЯЁӘҒҚҢӨҰҮҺІ][а-яёәғқңөұүһі]+(?:ович|евич|овна|евна|ична|инична|ұлы|улы|қызы|кызы)"
_FULLNAME = re.compile(rf"\b{_CAP}\s+{_CAP}\s+{_PATRONYMIC}\b|\b{_CAP}\s+{_PATRONYMIC}\b")
_INITIALS = re.compile(rf"\b{_CAP}\s+[А-ЯЁӘҒҚҢӨҰҮҺІ]\.\s?[А-ЯЁӘҒҚҢӨҰҮҺІ]\.|\b[А-ЯЁӘҒҚҢӨҰҮҺІ]\.\s?[А-ЯЁӘҒҚҢӨҰҮҺІ]\.\s?{_CAP}")
_INTRO_NAME = re.compile(rf"(?i)(меня зовут|мое имя|моё имя|менің атым|я\s*[-—–]\s*)\s*({_CAP}(?:\s+{_CAP}){{0,2}})")


def mask_pii(text: str, strict_address: bool = False) -> tuple[str, list[str]]:
    """Return masked text and the kinds of PII found (never the values).

    strict_address=True (Direct messages) also hides house numbers while keeping the street,
    so analytics can still group by street/district.
    """
    found: list[str] = []

    def sub(pattern: re.Pattern, repl, kind: str, s: str) -> str:
        new, n = pattern.subn(repl, s)
        if n:
            found.append(kind)
        return new

    out = text or ""
    out = sub(_EMAIL, "[EMAIL]", "email", out)
    out = sub(_CARD, "[КАРТА]", "card", out)
    out = sub(_IIN, "[ИИН]", "iin", out)
    out = sub(_PHONE, "[ТЕЛЕФОН]", "phone", out)
    out = sub(_APARTMENT, "кв. [№]", "apartment", out)
    if strict_address:
        out = sub(_HOUSE_NUM, lambda m: f"{m.group(1)}{m.group(2)}[№]", "house_number", out)
    out = sub(_INTRO_NAME, lambda m: f"{m.group(1)} [ФИО]", "name", out)
    out = sub(_FULLNAME, "[ФИО]", "name", out)
    out = sub(_INITIALS, "[ФИО]", "name", out)
    return out, sorted(set(found))


def mask_extra_names(text: str, names: list[str]) -> tuple[str, bool]:
    """Second pass: mask names the LLM detected that regex missed."""
    changed = False
    for name in names or []:
        name = (name or "").strip()
        if len(name) < 3 or name.startswith("["):
            continue
        if name in text:
            text = text.replace(name, "[ФИО]")
            changed = True
    return text, changed
