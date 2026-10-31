"""Exports in CSV, XLSX and PDF (spec 3.5.6, criterion 5). Same filters and role scope as the screens;
always masked text; Direct items excluded for the viewer role."""
import csv
import io
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.clusters import cluster_query
from app.api.items import _clusters_for, query_items
from app.api.stats import departments as dept_stats
from app.api.stats import overview
from app.audit import audit
from app.collectors.registry import PLATFORM_NAMES
from app.config import get_settings
from app.db import get_db
from app.filters import Filters, filters_dep
from app.models import User
from app.reference import DEPT_NAMES, PRIORITY_NAMES, SENTIMENT_NAMES, STATUS_NAMES, TYPE_NAMES
from app.security import get_current_user
from app.serializers import cluster_dict

router = APIRouter(prefix="/api/export", tags=["export"])
KIND_NAMES = {"post": "пост", "comment": "комментарий", "reply": "ответ", "message": "личное сообщение",
              "article": "статья", "review": "отзыв"}
GEO_NAMES = {"local": "Павлодар", "possible": "возможно Павлодар", "not_local": "не Павлодар"}
MAX_ROWS = 20000

_FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", str(Path(__file__).parent.parent / "fonts")]


def _register_fonts() -> str:
    if "DejaVu" in pdfmetrics.getRegisteredFontNames():
        return "DejaVu"
    for d in _FONT_DIRS:
        reg, bold = Path(d) / "DejaVuSans.ttf", Path(d) / "DejaVuSans-Bold.ttf"
        if reg.exists():
            pdfmetrics.registerFont(TTFont("DejaVu", str(reg)))
            pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(bold if bold.exists() else reg)))
            return "DejaVu"
    raise HTTPException(500, "Для PDF не найден шрифт DejaVu Sans (установите fonts-dejavu-core)")


def _fmt_dt(s: str | None) -> str:
    if not s:
        return ""
    return datetime.fromisoformat(s).astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M")


ITEM_COLS = [("ID", "id"), ("Дата (UTC)", "date"), ("Платформа", "platform"), ("Источник", "source"), ("Тип записи", "kind"), ("Подразделение", "dept"),
             ("Уверенность", "conf"), ("Тональность", "sent"), ("Оценка", "score"), ("Тип", "type"),
             ("Район", "district"), ("Проблема", "problem"), ("Приоритет проблемы", "priority"),
             ("Статус", "status"), ("Срочность", "urgency"), ("Direct", "direct"), ("Текст (маскированный)", "text"),
             ("Ссылка", "url"), ("Пост-источник", "parent_url"), ("Геопривязка", "geo"), ("Модель", "model")]
CLUSTER_COLS = [("ID", "id"), ("Проблема", "title"), ("Подразделение", "dept"), ("Район", "district"),
                ("Приоритет", "priority"), ("Балл", "score"), ("Обращений", "count"), ("За 24 ч", "c24"),
                ("Доля негатива", "neg"), ("Статус", "status"), ("Первое", "first"), ("Последнее", "last"),
                ("Резюме", "summary")]


def _item_rows(db: Session, f: Filters, user: User) -> list[dict]:
    items, total = query_items(db, f, user, "date_desc", MAX_ROWS)
    clusters = _clusters_for(db, [i.id for i in items])
    out = []
    for i in items:
        e, c = i.enrichment, clusters.get(i.id)
        out.append({
            "id": i.id, "date": i.published_at.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M"),
            "source": i.source.name + (" (синт.)" if i.source.is_synthetic else ""),
            "dept": DEPT_NAMES.get(e.primary_department, e.primary_department) if e else "",
            "conf": round(e.dept_confidence, 2) if e else "", "sent": SENTIMENT_NAMES.get(e.sentiment, "") if e else "",
            "score": round(e.sentiment_score, 2) if e else "", "type": TYPE_NAMES.get(e.message_type, "") if e else "",
            "district": (e.district or "") if e else "", "problem": (e.problem_type or "") if e else "",
            "priority": PRIORITY_NAMES.get(c.priority, "") if c else "", "status": STATUS_NAMES.get(i.status, i.status),
            "urgency": ", ".join(e.urgency_markers or []) if e else "", "direct": "да" if i.is_direct else "",
            "text": i.text_masked, "url": i.url or "", "model": e.model if e else "",
            "platform": PLATFORM_NAMES.get(i.platform, i.platform), "kind": KIND_NAMES.get(i.kind, i.kind),
            "parent_url": i.parent_url or "", "geo": GEO_NAMES.get(i.geo_status, i.geo_status),
        })
    return out


def _cluster_rows(db: Session, user: User, department, priority, status) -> list[dict]:
    rows = db.scalars(cluster_query(user, department, priority, status).order_by()
                      .limit(MAX_ROWS)).all()
    rows = sorted(rows, key=lambda c: -c.priority_score)
    out = []
    for c in rows:
        d = cluster_dict(c)
        out.append({"id": c.id, "title": c.title, "dept": d["department_name"], "district": c.district or "",
                    "priority": PRIORITY_NAMES[c.priority], "score": c.priority_score, "count": c.item_count,
                    "c24": c.count_24h, "neg": f"{round(100 * c.neg_share)}%", "status": STATUS_NAMES[c.status],
                    "first": _fmt_dt(d["first_seen"]), "last": _fmt_dt(d["last_seen"]), "summary": c.summary})
    return out


def _csv(cols, rows, name):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([c[0] for c in cols])
    for r in rows:
        w.writerow([r[k] for _, k in cols])
    return StreamingResponse(iter(["﻿" + buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f"attachment; filename={name}.csv"})


def _xlsx(cols, rows, name, sheet, meta: list[str]):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for line in meta:
        ws.append([line])
    ws.append([])
    ws.append([c[0] for c in cols])
    hdr = ws.max_row
    for cell in ws[hdr]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3A5F")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for r in rows:
        ws.append([r[k] for _, k in cols])
    for i, (title, key) in enumerate(cols, start=1):
        width = 60 if key in ("text", "summary") else 40 if key in ("title", "url") else max(10, len(title) + 2)
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = ws.cell(row=hdr + 1, column=1)
    ws.auto_filter.ref = f"A{hdr}:{get_column_letter(len(cols))}{ws.max_row}"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f"attachment; filename={name}.xlsx"})


def _styles(font):
    return {
        "h1": ParagraphStyle("h1", fontName=f"{font}-Bold", fontSize=16, leading=20, spaceAfter=4),
        "h2": ParagraphStyle("h2", fontName=f"{font}-Bold", fontSize=11.5, leading=15, spaceBefore=8, spaceAfter=4),
        "p": ParagraphStyle("p", fontName=font, fontSize=8.5, leading=11),
        "small": ParagraphStyle("s", fontName=font, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#555555")),
        "cell": ParagraphStyle("c", fontName=font, fontSize=7, leading=8.6),
    }


def _table(data, widths, font):
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font), ("FONTNAME", (0, 0), (-1, 0), f"{font}-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3A5F")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F6FA")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C9D3E0")),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _pdf(build, name, pagesize=landscape(A4)):
    font = _register_fonts()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=pagesize, leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm, title=name)
    story = build(font, _styles(font))

    def footer(canvas, d):
        canvas.setFont(font, 7)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(12 * mm, 7 * mm, f"{get_settings().app_name} · сформировано "
                          f"{datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M')} UTC · стр. {d.page}")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/pdf",
                             headers={"Content-Disposition": f"attachment; filename={name}.pdf"})


def _filter_line(f: Filters) -> str:
    parts = []
    start, end = f.period()
    if start:
        parts.append(f"с {start.strftime('%d.%m.%Y')}")
    if end:
        parts.append(f"по {end.strftime('%d.%m.%Y')}")
    if f.departments:
        parts.append("подразделения: " + ", ".join(DEPT_NAMES.get(d, d) for d in f.departments))
    if f.sentiments:
        parts.append("тональность: " + ", ".join(SENTIMENT_NAMES.get(s, s) for s in f.sentiments))
    if f.statuses:
        parts.append("статус: " + ", ".join(STATUS_NAMES.get(s, s) for s in f.statuses))
    if f.priorities:
        parts.append("приоритет: " + ", ".join(PRIORITY_NAMES.get(s, s) for s in f.priorities))
    if f.districts:
        parts.append("район: " + ", ".join(f.districts))
    if f.q:
        parts.append(f"поиск: «{f.q}»")
    if f.origin:
        parts.append("данные: " + ("реальные" if f.origin == "real" else "синтетические"))
    if f.platforms:
        parts.append("платформы: " + ", ".join(PLATFORM_NAMES.get(x, x) for x in f.platforms))
    parts.append("география: " + {"possible": "возможно Павлодар", "not_local": "не Павлодар", "all": "все"}.get(
        f.geo or "local", "только Павлодар"))
    return "Фильтры: " + ("; ".join(parts) if parts else "нет")


@router.get("/items.{fmt}")
def export_items(fmt: str, f: Filters = Depends(filters_dep), db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    rows = _item_rows(db, f, user)
    audit(db, user, "export.items", fmt=fmt, rows=len(rows))
    db.commit()
    name = f"obrashcheniya_{datetime.now().strftime('%Y%m%d_%H%M')}"
    if fmt == "csv":
        return _csv(ITEM_COLS, rows, name)
    if fmt == "xlsx":
        return _xlsx(ITEM_COLS, rows, name, "Обращения", [f"Обращения жителей — {get_settings().app_name}",
                                                          _filter_line(f), f"Строк: {len(rows)}"])
    if fmt == "pdf":
        def build(font, st):
            head = ["ID", "Дата", "Источник", "Подразделение", "Тон.", "Район", "Статус", "Текст"]
            data = [head] + [[r["id"], r["date"], Paragraph(r["source"], st["cell"]), Paragraph(r["dept"], st["cell"]),
                              r["sent"][:5], Paragraph(r["district"], st["cell"]), Paragraph(r["status"], st["cell"]),
                              Paragraph(r["text"][:600].replace("<", "&lt;"), st["cell"])] for r in rows[:2000]]
            widths = [12 * mm, 24 * mm, 30 * mm, 30 * mm, 14 * mm, 25 * mm, 22 * mm, 116 * mm]
            note = f"Строк: {len(rows)}" + (" (в PDF показаны первые 2000; полный список — XLSX/CSV)" if len(rows) > 2000 else "")
            return [Paragraph("Обращения жителей", st["h1"]), Paragraph(_filter_line(f), st["small"]),
                    Paragraph(note, st["small"]), Spacer(1, 4 * mm), _table(data, widths, font)]
        return _pdf(build, name)
    raise HTTPException(400, "Формат: csv, xlsx или pdf")


@router.get("/clusters.{fmt}")
def export_clusters(fmt: str, department: str | None = None, priority: str | None = None, status: str | None = None,
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = _cluster_rows(db, user, department, priority, status)
    audit(db, user, "export.clusters", fmt=fmt, rows=len(rows))
    db.commit()
    name = f"problemy_{datetime.now().strftime('%Y%m%d_%H%M')}"
    if fmt == "csv":
        return _csv(CLUSTER_COLS, rows, name)
    if fmt == "xlsx":
        return _xlsx(CLUSTER_COLS, rows, name, "Проблемы", [f"Проблемы и приоритеты — {get_settings().app_name}",
                                                            f"Строк: {len(rows)}"])
    if fmt == "pdf":
        def build(font, st):
            head = ["ID", "Проблема", "Подразделение", "Район", "Приоритет", "Балл", "Обращ.", "24 ч", "Негатив", "Статус", "Резюме"]
            data = [head] + [[r["id"], Paragraph(r["title"], st["cell"]), Paragraph(r["dept"], st["cell"]),
                              Paragraph(r["district"], st["cell"]), r["priority"], r["score"], r["count"], r["c24"],
                              r["neg"], Paragraph(r["status"], st["cell"]), Paragraph(r["summary"][:500], st["cell"])]
                             for r in rows]
            widths = [10 * mm, 50 * mm, 28 * mm, 22 * mm, 17 * mm, 11 * mm, 12 * mm, 10 * mm, 14 * mm, 22 * mm, 77 * mm]
            return [Paragraph("Проблемы и приоритеты", st["h1"]), Paragraph(f"Активных проблем: {len(rows)}", st["small"]),
                    Spacer(1, 4 * mm), _table(data, widths, font)]
        return _pdf(build, name)
    raise HTTPException(400, "Формат: csv, xlsx или pdf")


def _bar(labels, values, color, width=250 * mm / 2, font="DejaVu"):
    h = 14 * len(labels) + 20
    d = Drawing(width, h)
    ch = HorizontalBarChart()
    ch.x, ch.y, ch.width, ch.height = 95, 10, width - 120, h - 20
    ch.data = [values or [0]]
    ch.categoryAxis.categoryNames = labels or [""]
    ch.categoryAxis.labels.fontName = font
    ch.categoryAxis.labels.fontSize = 7
    ch.valueAxis.labels.fontName = font
    ch.valueAxis.labels.fontSize = 6.5
    ch.valueAxis.valueMin = 0
    ch.bars[0].fillColor = colors.HexColor(color)
    ch.bars[0].strokeColor = None
    ch.categoryAxis.reverseDirection = 1
    d.add(ch)
    return d


@router.get("/report.pdf")
def export_report(f: Filters = Depends(filters_dep), db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """One-page management report: KPIs, departments, top problems (dashboards 1–3 on paper)."""
    ov = overview(Filters(**f.__dict__), db, user)
    dp = dept_stats(Filters(**f.__dict__), db, user)
    audit(db, user, "export.report", fmt="pdf")
    db.commit()

    def build(font, st):
        k = ov["kpis"]
        delta = f" ({'+' if (k['total_delta_pct'] or 0) >= 0 else ''}{k['total_delta_pct']}% к пред. периоду)" if k["total_delta_pct"] is not None else ""
        kpi = [["Обращений", "Индекс настроения", "Высокий приоритет", "Решено", "На ручной проверке", "Срочных"],
               [f"{k['total']}{delta}", f"{k['mood_index']:+}", f"{k['high_priority_share']}%", f"{k['resolved_share']}%",
                f"{k['review_share']}%", k["urgent"]]]
        sent = ov["sentiment"]
        depts = ov["by_department"][:11]
        story = [Paragraph(f"Сводка обращений жителей — {get_settings().city_name}", st["h1"]),
                 Paragraph(_filter_line(f), st["small"]), Spacer(1, 3 * mm),
                 _table(kpi, [45 * mm] * 6, font), Spacer(1, 2 * mm),
                 Paragraph(f"Тональность: положительных {sent['positive']}, нейтральных {sent['neutral']}, "
                           f"отрицательных {sent['negative']}. Индекс настроения = доля положительных − доля отрицательных, п.п.",
                           st["small"]),
                 Paragraph("Нагрузка по подразделениям", st["h2"]),
                 _bar([d["name"] for d in depts], [d["count"] for d in depts], "#2F6FB0", font=font),
                 Paragraph("Топ проблем по приоритету", st["h2"])]
        top = [["#", "Проблема", "Подразделение", "Приоритет", "Балл", "Обращений", "За 24 ч", "Статус"]]
        for c in ov["top_problems"]:
            top.append([c["id"], Paragraph(c["title"], st["cell"]), c["department_name"], PRIORITY_NAMES[c["priority"]],
                        c["priority_score"], c["item_count"], c["count_24h"], STATUS_NAMES[c["status"]]])
        story.append(_table(top, [10 * mm, 95 * mm, 38 * mm, 20 * mm, 14 * mm, 18 * mm, 15 * mm, 40 * mm], font))
        story.append(Paragraph("Показатели подразделений", st["h2"]))
        rows = [["Подразделение", "Обращений", "Негатив", "Индекс", "Решено", "Ср. время передачи, ч", "Открытых проблем", "Рейтинг"]]
        for d in dp["departments"]:
            rows.append([d["name"], d["count"], d["negative"], d["mood_index"], f"{d['resolved_share']}%",
                         d["avg_hours_to_transfer"] if d["avg_hours_to_transfer"] is not None else "—",
                         d["open_problems"], d["rating"]])
        story.append(_table(rows, [50 * mm, 22 * mm, 20 * mm, 20 * mm, 20 * mm, 40 * mm, 30 * mm, 20 * mm], font))
        story.append(Paragraph(f"Рейтинг: {dp['rating_formula']}. Решения ИИ носят рекомендательный характер (п. 5.4).",
                               st["small"]))
        return story
    return _pdf(build, f"svodka_{datetime.now().strftime('%Y%m%d_%H%M')}")
