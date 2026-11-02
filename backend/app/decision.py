"""Evidence brief computed from visible messages, without inventing missing facts."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import re

from app.reference import DEPT_NAMES, URGENCY_MARKERS
from app.serializers import voice

CITY_TZ = timezone(timedelta(hours=5))
# Below this many messages in the previous day a percentage swings wildly (1 → 4 is "+300%"),
# so the card shows the absolute change instead.
MIN_GROWTH_BASE = 10
DEMAND = re.compile(r"(?i)\b(просим|прошу|требуем|требую|нужно|необходимо|пожалуйста|сделайте|помогите|"
                    r"примите меры|разберитесь|өтінем|сұраймыз)\b")


def object_key(label: str) -> str:
    """«школы №12» and «школы 12» are the same place for counting purposes."""
    return re.sub(r"[\s№#.,]+", "", label.lower())


def aware(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def build_decision(cluster, items, now=None, hidden_direct=0):
    now = now or datetime.now(timezone.utc)
    items = sorted(items, key=lambda i: aware(i.published_at), reverse=True)
    count = len(items)
    current = sum(now - timedelta(hours=24) <= aware(i.published_at) <= now for i in items)
    previous = sum(now - timedelta(hours=48) <= aware(i.published_at) < now - timedelta(hours=24) for i in items)
    growth = round(100 * (current - previous) / previous) if previous else None
    authors = {i.author_hash for i in items if i.author_hash}
    sources = {i.source_id for i in items}
    hours = Counter(aware(i.published_at).astimezone(CITY_TZ).hour for i in items)
    days = Counter(aware(i.published_at).astimezone(CITY_TZ).date().isoformat() for i in items)
    topics, topic_ids, demands, objects, object_names = Counter(), {}, [], Counter(), {}
    markers, related = set(), set()
    for i in items:
        e = i.enrichment
        topic = (e.problem_type if e else None) or "Тема не уточнена"
        topics[topic] += 1
        topic_ids.setdefault(topic, []).append(i.id)
        if e:
            markers.update(e.urgency_markers or [])
            related.update(e.departments or [])
            if e.object and e.object.strip():
                key = object_key(e.object)
                objects[key] += 1
                object_names.setdefault(key, Counter())[e.object.strip()] += 1
        if voice(i) != "resident":
            continue   # requests are quoted from residents only, never from news or official posts
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", i.text_masked):
            if DEMAND.search(sentence):
                demands.append({"text": sentence[:260], "item_id": i.id, "is_direct": i.is_direct})
                break
    related.discard(cluster.department)
    synthetic_count = sum(bool(i.source and i.source.is_synthetic) for i in items)

    gaps = []
    if not cluster.district:
        gaps.append("Уточнить место: район не определён по сообщениям." if objects else
                    "Уточнить место: ни район, ни конкретный объект в сообщениях не определены.")
    if not objects:
        gaps.append("Уточнить конкретный объект: номер маршрута, дома или учреждения.")
    if len(sources) < 2:
        gaps.append("Найти подтверждение за пределами единственного источника.")
    else:
        gaps.append("Проверить независимость источников: разные каналы могут перепечатывать одно сообщение.")
    if not demands:
        gaps.append("Уточнить желаемый результат: явных просьб в сообщениях не найдено.")
    if count and previous < MIN_GROWTH_BASE and current:
        gaps.append("Оценивать динамику осторожно: сообщений слишком мало для устойчивого вывода о росте.")
    gaps.append("Сверить сообщения с данными ответственного подразделения: причины и ресурсы пока не подтверждены.")

    residents = [i for i in items if voice(i) == "resident"]
    media = count - len(residents)
    if media and not residents:
        gaps.insert(0, "Найти сообщения самих жителей: сейчас проблема видна только по публикациям СМИ и официальных каналов.")
    # Residents only; public messages first: quoting a private Direct message in a shared brief needs a reason
    voices = [i for i in residents if not i.is_direct][:2] or residents[:2]
    evidence = lambda i: {"id": i.id, "text": i.text_masked[:500], "source": i.source.name if i.source else "Источник",
                          "url": i.url, "published_at": aware(i.published_at).isoformat(), "is_direct": i.is_direct,
                          "synthetic": bool(i.source and i.source.is_synthetic), "voice": voice(i)}
    return {
        "cluster_id": cluster.id, "title": cluster.title, "department": cluster.department,
        "department_name": DEPT_NAMES.get(cluster.department, cluster.department), "district": cluster.district,
        "generated_at": now.isoformat(), "synthetic": synthetic_count > 0, "available": bool(items),
        "status": getattr(cluster, "status", "new"),
        "period_start": min((aware(i.published_at) for i in items), default=now).isoformat(),
        "period_end": max((aware(i.published_at) for i in items), default=now).isoformat(),
        "metrics": {"messages": count, "known_accounts": len(authors),
                    "messages_without_author": sum(not i.author_hash for i in items), "sources": len(sources),
                    "current_24h": current, "previous_24h": previous, "growth_pct": growth,
                    "growth_abs": current - previous, "small_base": previous < MIN_GROWTH_BASE,
                    "synthetic_messages": synthetic_count, "direct_messages": sum(i.is_direct for i in items),
                    "hidden_direct": hidden_direct, "resident_messages": len(residents), "media_posts": media},
        "peaks": [{"hour": h, "count": n} for h, n in sorted(hours.items())],
        "daily": [{"date": d, "count": n} for d, n in sorted(days.items())],
        "objects": [{"label": object_names[k].most_common(1)[0][0], "count": n} for k, n in objects.most_common(3)],
        "topics": [{"label": t, "count": n, "share": round(n * 100 / count), "item_ids": topic_ids[t]}
                   for t, n in topics.most_common(5)] if count else [],
        "demands": demands[:5], "affected": [URGENCY_MARKERS[m] for m in sorted(markers) if m in ("children", "elderly")],
        "related_departments": [DEPT_NAMES.get(d, d) for d in sorted(related)],
        "checks": gaps,
        "voices": [evidence(i) for i in voices],
        "evidence": [evidence(i) for i in items],
        "method": "Числа рассчитаны по доступным вам сообщениям без дубликатов и спама. Темы и объекты взяты из "
                  "автоматической классификации, просьбы — дословные цитаты. Сводка не устанавливает причины "
                  "и не принимает решения.",
    }
