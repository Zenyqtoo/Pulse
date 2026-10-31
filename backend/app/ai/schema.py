"""Validated structure of one enrichment result (one LLM call per message)."""
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.reference import URGENCY_MARKERS


class Entities(BaseModel):
    district: str | None = None
    address: str | None = None
    object: str | None = None
    problem_type: str | None = None


class Geo(BaseModel):
    relevance: Literal["local", "possible", "not_local"]
    place: str | None = None
    reason: str | None = Field(None, max_length=300)


class EnrichmentResult(BaseModel):
    departments: list[str] = Field(min_length=1, max_length=3)
    primary_department: str
    department_confidence: float = Field(ge=0, le=1)
    sentiment: Literal["positive", "neutral", "negative"]
    sentiment_score: float = Field(ge=-1, le=1)
    sentiment_confidence: float = Field(default=0.8, ge=0, le=1)
    message_type: Literal["complaint", "question", "proposal", "gratitude", "info"]
    is_spam: bool = False
    spam_reason: str | None = None
    entities: Entities = Field(default_factory=Entities)
    urgency_markers: list[str] = Field(default_factory=list)
    pii_names: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=3, max_length=600)
    geo: Geo | None = None

    @field_validator("urgency_markers")
    @classmethod
    def _known_markers(cls, v: list[str]) -> list[str]:
        return [m for m in v if m in URGENCY_MARKERS]

    def validate_departments(self, allowed: set[str]) -> "EnrichmentResult":
        depts = [d for d in self.departments if d in allowed]
        primary = self.primary_department if self.primary_department in allowed else (depts[0] if depts else "other")
        if primary not in depts:
            depts = [primary] + depts
        self.departments = depts[:3]
        self.primary_department = primary
        return self


def tool_schema(dept_codes: list[str]) -> dict:
    """JSON schema given to Claude as a forced tool, so the reply always parses."""
    return {
        "type": "object",
        "properties": {
            "departments": {"type": "array", "items": {"type": "string", "enum": dept_codes},
                            "minItems": 1, "maxItems": 3,
                            "description": "All responsible departments, most relevant first"},
            "primary_department": {"type": "string", "enum": dept_codes},
            "department_confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
            "sentiment_score": {"type": "number", "minimum": -1, "maximum": 1},
            "sentiment_confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "message_type": {"type": "string", "enum": ["complaint", "question", "proposal", "gratitude", "info"]},
            "is_spam": {"type": "boolean"},
            "spam_reason": {"type": ["string", "null"]},
            "entities": {
                "type": "object",
                "properties": {
                    "district": {"type": ["string", "null"], "description": "Район или микрорайон, если указан"},
                    "address": {"type": ["string", "null"], "description": "Улица/адрес объекта проблемы"},
                    "object": {"type": ["string", "null"], "description": "Объект: школа №, дом, остановка, поликлиника…"},
                    "problem_type": {"type": ["string", "null"], "description": "Короткое название проблемы, 2–5 слов, по-русски"},
                },
            },
            "urgency_markers": {"type": "array", "items": {"type": "string", "enum": list(URGENCY_MARKERS)}},
            "pii_names": {"type": "array", "items": {"type": "string"},
                          "description": "Имена/ФИО частных лиц, оставшиеся в тексте без маски"},
            "rationale": {"type": "string", "description": "1–2 предложения по-русски: почему такое подразделение и тональность"},
            "geo": {
                "type": "object",
                "description": "Касается ли сообщение именно города (см. раздел ГЕОГРАФИЯ)",
                "properties": {
                    "relevance": {"type": "string", "enum": ["local", "possible", "not_local"]},
                    "place": {"type": ["string", "null"], "description": "Населённый пункт, о котором речь, если понятно"},
                    "reason": {"type": ["string", "null"], "description": "Одно короткое предложение по-русски"},
                },
                "required": ["relevance", "reason"],
            },
        },
        "required": ["departments", "primary_department", "department_confidence", "sentiment",
                     "sentiment_score", "sentiment_confidence", "message_type", "is_spam", "entities",
                     "urgency_markers", "pii_names", "rationale", "geo"],
    }
