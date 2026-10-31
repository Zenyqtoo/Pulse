"""CSV/XLSX upload (spec 3.1.4) with flexible column names."""
import csv
import hashlib
import io
from datetime import datetime, timezone

from openpyxl import load_workbook

from app.collectors.base import CollectorError, RawItem

COLS = {
    "text": ["text", "текст", "message", "сообщение", "comment", "комментарий", "отзыв", "review", "обращение"],
    "date": ["date", "дата", "published_at", "datetime", "время", "created", "дата публикации"],
    "url": ["url", "link", "ссылка"],
    "author": ["author", "автор", "user", "пользователь", "author_id"],
    "id": ["id", "external_id", "номер"],
    "reactions": ["reactions", "likes", "лайки", "реакции"],
    "replies": ["replies", "ответы", "comments_count"],
    "views": ["views", "просмотры"],
    "direct": ["is_direct", "direct", "директ"],
}
DATE_FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S",
                "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%d/%m/%Y"]


def _parse_date(v) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    s = str(v).strip()
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(s, f).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _int(v) -> int:
    try:
        return int(float(str(v).replace(" ", ""))) if v not in (None, "") else 0
    except ValueError:
        return 0


def _rows(filename: str, data: bytes) -> list[dict]:
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")):
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        header = [str(h or "").strip().lower() for h in rows[0]]
        return [dict(zip(header, r)) for r in rows[1:]]
    if name.endswith((".csv", ".tsv", ".txt")):
        text = data.decode("utf-8-sig", errors="replace")
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t") if text.strip() else csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        return [{(k or "").strip().lower(): v for k, v in row.items()} for row in reader]
    raise CollectorError("Поддерживаются файлы .csv и .xlsx")


def parse_upload(filename: str, data: bytes) -> tuple[list[RawItem], list[str]]:
    rows = _rows(filename, data)
    if not rows:
        raise CollectorError("Файл пуст")
    header = set(rows[0].keys())
    col = {k: next((c for c in names if c in header), None) for k, names in COLS.items()}
    if not col["text"]:
        raise CollectorError(f"Не найдена колонка с текстом. Ожидается одна из: {', '.join(COLS['text'])}")
    items, warnings = [], []
    for n, row in enumerate(rows, start=2):
        text = str(row.get(col["text"]) or "").strip()
        if not text:
            continue
        date = _parse_date(row.get(col["date"])) if col["date"] else None
        if date is None:
            warnings.append(f"строка {n}: дата не распознана, взято текущее время")
            date = datetime.now(timezone.utc)
        ext = str(row.get(col["id"]) or "") if col["id"] else ""
        if not ext:
            ext = hashlib.sha1(f"{text}|{date.isoformat()}".encode()).hexdigest()[:20]
        direct = str(row.get(col["direct"]) or "").strip().lower() in ("1", "true", "да", "yes") if col["direct"] else False
        items.append(RawItem(
            external_id=ext[:190], text=text, published_at=date,
            url=(str(row.get(col["url"])).strip() or None) if col["url"] and row.get(col["url"]) else None,
            author_id=str(row.get(col["author"])) if col["author"] and row.get(col["author"]) else None,
            platform="upload", reactions=_int(row.get(col["reactions"])) if col["reactions"] else 0,
            replies=_int(row.get(col["replies"])) if col["replies"] else 0,
            views=_int(row.get(col["views"])) if col["views"] else 0, is_direct=direct,
        ))
    return items, warnings[:20]
