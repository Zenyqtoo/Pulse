"""Transparent priority score (spec 3.4.3). Every term is stored so the UI can show the breakdown.

P = 25·neg + 20·min(1, log10(n)/2) + 20·min(1, g/3) + 15·reach + 15·urgent + 5·min(1, d/14)
High ≥ 55, Medium 35–54, Low < 35. A life-threat marker always forces High.
"""
import math
from dataclasses import dataclass

HIGH, MEDIUM = 55.0, 35.0


@dataclass
class PriorityInput:
    neg_share: float          # share of negative items, 0..1
    n: int                    # items in cluster
    count_24h: int
    count_prev_24h: int
    engagement: int           # reactions + replies + views/100
    urgent_markers: set[str]
    days_unresolved: float


def growth(count_24h: int, count_prev_24h: int) -> float:
    if count_24h == 0:
        return 0.0
    return count_24h / max(1, count_prev_24h)


def compute(p: PriorityInput) -> tuple[str, float, dict]:
    g = growth(p.count_24h, p.count_prev_24h)
    reach = min(1.0, math.log10(1 + max(0, p.engagement)) / 3)
    urgent = 1.0 if p.urgent_markers else 0.0
    terms = {
        "negativity": {"label": "Доля негатива", "value": round(p.neg_share, 2), "points": 25 * p.neg_share, "max": 25},
        "volume": {"label": "Число обращений", "value": p.n, "points": 20 * min(1.0, math.log10(max(1, p.n)) / 2), "max": 20},
        "growth": {"label": "Рост за 24 ч", "value": f"{p.count_24h} vs {p.count_prev_24h}",
                   "points": 20 * min(1.0, g / 3), "max": 20},
        "reach": {"label": "Охват (реакции, ответы, просмотры)", "value": p.engagement, "points": 15 * reach, "max": 15},
        "urgency": {"label": "Маркеры срочности", "value": ", ".join(sorted(p.urgent_markers)) or "нет",
                    "points": 15 * urgent, "max": 15},
        "duration": {"label": "Дней без решения", "value": round(p.days_unresolved, 1),
                     "points": 5 * min(1.0, p.days_unresolved / 14), "max": 5},
    }
    for t in terms.values():
        t["points"] = round(t["points"], 1)
    score = round(sum(t["points"] for t in terms.values()), 1)
    if "life_threat" in p.urgent_markers or score >= HIGH:
        level = "high"
    elif score >= MEDIUM:
        level = "medium"
    else:
        level = "low"
    forced = "life_threat" in p.urgent_markers and score < HIGH
    return level, score, {"terms": terms, "score": score, "thresholds": {"high": HIGH, "medium": MEDIUM},
                          "forced_by_life_threat": forced}
