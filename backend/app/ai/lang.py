"""Language detection for Russian / Kazakh / mixed text without an LLM call."""
import re

KK_LETTERS = set("әғқңөұүһіӘҒҚҢӨҰҮҺІ")
KK_WORDS = {"және", "мен", "бар", "жоқ", "емес", "үшін", "қала", "көше", "біз", "сіз", "бұл", "осы",
            "керек", "рахмет", "неге", "қашан", "ма", "ме", "па", "пе", "ғой", "дейін", "туралы", "жоқпа"}
RU_WORDS = {"и", "в", "не", "на", "что", "это", "как", "уже", "нет", "когда", "почему", "у", "нас",
            "очень", "есть", "для", "по", "до", "все", "так", "сколько", "можно"}
_word = re.compile(r"[a-zа-яёәғқңөұүһі]+", re.IGNORECASE)


def detect_language(text: str) -> str:
    words = [w.lower() for w in _word.findall(text or "")]
    if not words:
        return "other"
    letters = [c for c in text if c.isalpha()]
    cyr = sum(1 for c in letters if "Ѐ" <= c <= "ӿ")
    latin = sum(1 for c in letters if c.isascii())
    if letters and latin / len(letters) > 0.7:
        return "other"
    kk_char_words = sum(1 for w in words if any(c in KK_LETTERS for c in w))
    kk_hits = kk_char_words + sum(1 for w in words if w in KK_WORDS)
    ru_hits = sum(1 for w in words if w in RU_WORDS)
    if cyr == 0:
        return "other"
    kk_share = kk_hits / len(words)
    if kk_share >= 0.25 and ru_hits >= 2:
        return "mixed"
    if kk_share >= 0.15:
        return "kk"
    if kk_hits >= 2 and ru_hits >= 2:
        return "mixed"
    return "ru"
