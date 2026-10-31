"""Gazetteer for Pavlodar city (not the region).

Weights: strong (unambiguous city references), medium (city landmarks, utilities, institutions),
weak (streets and areas that also exist elsewhere: only supporting evidence). Lists are editable;
they are evidence for the classifier, never the only signal (the LLM judges the context).
"""
import re

# Word forms of the city name in Russian, Kazakh and Latin. Region forms («Павлодарская область»,
# «Павлодар облысы») are matched separately and do NOT count as the city.
CITY_PATTERNS = [
    r"\bпавлодар(?:а|е|у|ом)?\b(?!\s*облыс)",
    r"\bпавлодар(?:да|дың|ға|дан|ды|қа)\b",
    r"\bпавлодар\s+қаласы\w*",
    r"\bг\.\s?павлодар\w*",
    r"\bpavlodar\b(?!\s*(?:region|oblast|province))",
    r"\bпавлодарц\w*|\bпавлодарк[аиу]\b|\bпавлодарлық\w*",
    r"#павлодар\b|#pavlodar\b|\bпвл\b|\bpvl\b",
]
REGION_PATTERNS = [r"\bпавлодарск\w+\s+област\w*", r"\bпавлодар\s+облыс\w*", r"\bpavlodar\s+(?:region|oblast|province)\b",
                   r"\bпо\s+области\b", r"\bв\s+регионе\b", r"\bоблыс\w*\b"]

MEDIUM = [  # institutions, utilities and landmarks of Pavlodar city
    "павлодарэнерго", "павлодарские тепловые сети", "павлодарских тепловых сет", "прэк", "павлодар-водоканал",
    "павлодарводоканал", "пнхз", "нефтехимическ", "электролизн", "кэз", "алюминиевый завод", "торайгыров университет",
    "университет торайгырова", "пгу им", "маргулан университет", "пгпу", "мечеть машхур", "машхур жусуп мешіт",
    "благовещенский собор", "набережная иртыша", "набережной иртыша", "трамва", "аким павлодара",
    "акимат павлодара", "иртыш павлодар", "аэропорт павлодара",
    "усольск", "усолк", "химгородок", "лесозавод",
]
WEAK = [  # streets and areas of Pavlodar that also occur in other cities
    "естая", "камзина", "ломова", "дюсенова", "бекхожина", "кривенко", "жаяу мусы", "луначарского", "торайгырова",
    "сатпаева", "кутузова", "толстого", "чокина", "маргулана", "академика сатпаева", "ткачева", "катаева",
    "северная промзона", "южный промрайон", "иртыш", "ертіс", "восточный микрорайон", "мкр восточный",
]
# Settlements under the city akimat: part of the city territory, but kept as supporting evidence only
SUBURBS = ["ленинский", "кенжеколь", "кенжекөл", "павлодарское", "мичурино", "жетекши"]

# Other places: Pavlodar region towns/districts and other cities. A message about them is not local.
OTHER_PLACES = {
    "Экибастуз": [r"экибастуз\w*", r"екібастұз\w*", r"ekibastuz"],
    "Аксу": [r"\bаксу\b", r"\bаксуйск\w*", r"\bақсу\w*", r"\baksu\b", r"\bв\s+аксу\b"],
    "Майкаин": [r"майкаин\w*", r"майқайың\w*"],
    "Баянаул": [r"баянаул\w*", r"баянауыл\w*", r"bayanaul"],
    "Щербакты": [r"щербакт\w*", r"шарбақт\w*"],
    "Иртышск": [r"иртышск\w*"],
    "Теренколь/Качиры": [r"теренкол\w*", r"тереңкөл\w*", r"качир\w*"],
    "Успенка": [r"успенк\w*"],
    "Железинка": [r"железинк\w*"],
    "Лебяжье/Аккулы": [r"лебяж\w*", r"аққулы\w*", r"аккулы\w*"],
    "Калкаман": [r"калкаман\w*", r"қалқаман\w*"],
    "Шидерты": [r"шидерт\w*"],
    "Астана": [r"\bастан[аеуы]\w*", r"нур-султан\w*", r"\bastana\b"],
    "Алматы": [r"\bалмат[ыа]\w*", r"\balmaty\b"],
    "Шымкент": [r"шымкент\w*"],
    "Караганда": [r"караганд\w*", r"қарағанд\w*"],
    "Семей": [r"\bсемей\w*", r"\bсемипалатинск\w*"],
    "Усть-Каменогорск": [r"усть-каменогорск\w*", r"өскемен\w*"],
    "Костанай": [r"костана\w*", r"қостана\w*"],
    "Петропавловск": [r"петропавловск\w*"],
    "Актобе": [r"актоб\w*", r"ақтөбе\w*"],
    "Атырау": [r"атырау\w*"],
    "Актау": [r"\bактау\w*", r"\bақтау\w*"],
    "Уральск": [r"уральск\w*", r"\bорал\w*"],
    "Кокшетау": [r"кокшетау\w*", r"көкшетау\w*"],
    "Тараз": [r"\bтараз\w*"],
    "Кызылорда": [r"кызылорд\w*", r"қызылорд\w*"],
    "Талдыкорган": [r"талдыкорган\w*", r"талдықорған\w*"],
    "Туркестан": [r"туркестан\w*", r"түркістан\w*"],
    "Темиртау": [r"темиртау\w*", r"теміртау\w*"],
    "Жезказган": [r"жезказган\w*", r"жезқазған\w*"],
    "Рудный": [r"\bрудн(?:ый|ом|ого)\b"],
    "Степногорск": [r"степногорск\w*"],
    "Омск": [r"\bомск\w*"],
    "Новосибирск": [r"новосибирск\w*"],
    "Павлоград (Украина)": [r"павлоград\w*"],
}

CITY_RE = [re.compile(p, re.IGNORECASE) for p in CITY_PATTERNS]
REGION_RE = [re.compile(p, re.IGNORECASE) for p in REGION_PATTERNS]
OTHER_RE = {name: [re.compile(p, re.IGNORECASE) for p in pats] for name, pats in OTHER_PLACES.items()}
