"""Browser smoke test: logs in, walks every page and the critical demo path, collects console errors
and screenshots. Usage: python e2e/smoke.py http://localhost:8000 OUT_DIR"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "e2e-shots")
OUT.mkdir(parents=True, exist_ok=True)
errors: list[str] = []


def shot(page, name):
    page.wait_for_timeout(700)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 900}, locale="ru-RU")
    page.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

    page.goto(BASE)
    shot(page, "00_login")
    page.get_by_label("Логин").fill("operator")
    page.get_by_label("Пароль").fill("wrong-password")
    page.get_by_role("button", name="Войти").click()
    page.get_by_text("Неверный логин или пароль").wait_for()
    page.get_by_label("Пароль").fill("operator123")
    page.get_by_role("button", name="Войти").click()
    page.get_by_text("Индекс настроения города").wait_for(timeout=15000)
    shot(page, "01_overview")

    # drill-down: top problem → problem drawer → item drawer
    page.locator(".prob").first.click()
    page.get_by_text("Почему такой приоритет").wait_for()
    shot(page, "02_problem_drawer")
    page.locator(".ant-drawer .prob").first.click()
    page.get_by_text("Анализ ИИ").wait_for()
    shot(page, "03_item_drawer")
    page.keyboard.press("Escape")

    for path, marker, name in [
        ("/problems", "Проблемы и приоритеты", "04_problems"),
        ("/departments", "Рейтинг подразделений", "05_departments"),
        ("/feed?department=housing", "Лента обращений", "06_feed_filtered"),
        ("/review", "Проверка ИИ", "07_review"),
        ("/direct", "Личные обращения (Direct)", "08_direct"),
        ("/sources", "Журнал сбора", "09_sources"),
        ("/quality", "Качество ИИ", "10_quality"),
    ]:
        page.goto(BASE + path)
        page.get_by_role("heading", name=marker).first.wait_for(timeout=15000)
        shot(page, name)

    # Direct: open a message, reveal original (audited)
    page.goto(BASE + "/direct")
    page.locator(".ant-table-row").first.click()
    page.get_by_text("Личное обращение в официальный аккаунт").wait_for()
    shot(page, "11_direct_masked")
    btn = page.get_by_role("button", name="Показать оригинал (запишется в журнал)")
    if btn.count():
        btn.click()
        page.get_by_text("Оригинал — просмотр записан в журнал").wait_for()
        shot(page, "12_direct_original")
    page.keyboard.press("Escape")

    # Correction on an item from the review queue
    page.goto(BASE + "/review")
    page.locator(".ant-table-row").first.click()
    page.get_by_text("Проверка и исправление").wait_for()
    page.get_by_role("button", name="Подтвердить результат ИИ").click()
    page.get_by_text("Результат ИИ подтверждён").wait_for()
    page.keyboard.press("Escape")

    # Geo queue: possible-Pavlodar item → operator decision
    page.goto(BASE + "/geo")
    page.get_by_role("heading", name="Проверка геопривязки").wait_for()
    shot(page, "16_geo_queue")
    if page.get_by_role("button", name="Не Павлодар").count():
        page.get_by_role("button", name="Не Павлодар").first.click()
        page.get_by_text("Исключено из аналитики").wait_for()

    # Excluded view in the feed
    page.goto(BASE + "/feed")
    page.get_by_role("heading", name="Лента обращений").wait_for()
    page.get_by_label("Геопривязка").click()
    page.get_by_text("Исключённые (не Павлодар)").click()
    page.get_by_text("Экибастуз").first.wait_for()
    shot(page, "17_feed_excluded")

    # Sources: platform tabs, connection panel, recommended list
    page.goto(BASE + "/sources?tab=telegram")
    page.get_by_text("Рекомендованные источники о Павлодаре").wait_for()
    shot(page, "18_sources_telegram")
    page.goto(BASE + "/sources?tab=instagram")
    page.get_by_text("Подключение Instagram").wait_for()
    shot(page, "19_sources_instagram")
    page.goto(BASE + "/sources?tab=threads")
    page.get_by_text("Подключение Threads").wait_for()

    # Assistant
    page.goto(BASE + "/assistant")
    page.get_by_role("button", name="Какие главные жалобы по ЖКХ за последнюю неделю?").click()
    page.get_by_text("Исходные обращения").wait_for(timeout=20000)
    shot(page, "13_assistant")

    # Export from feed (download event)
    page.goto(BASE + "/feed")
    page.get_by_role("button", name="Экспорт").hover()
    with page.expect_download() as dl:
        page.get_by_text("Excel (XLSX)").click()
    d = dl.value
    print("download:", d.suggested_filename)

    # Admin: add a recommended source with one click, open its history
    page.evaluate("localStorage.clear()")
    page.goto(BASE)
    page.get_by_label("Логин").fill("admin")
    page.get_by_label("Пароль").fill("admin123")
    page.get_by_role("button", name="Войти").click()
    page.get_by_text("Индекс настроения города").wait_for(timeout=15000)
    page.goto(BASE + "/sources?tab=telegram")
    page.get_by_text("Рекомендованные источники о Павлодаре").wait_for()
    add = page.get_by_role("button", name="Добавить", exact=True)
    if add.count():
        add.first.click()
        page.get_by_text("Источник добавлен").wait_for()
    page.get_by_role("button", name="История сбора").first.click()
    page.get_by_text("История сбора:").wait_for()
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Добавить источник").click()
    page.get_by_text("Географический охват источника").wait_for()
    shot(page, "20_source_modal")
    page.get_by_role("button", name="Отмена").click()

    # Viewer cannot see Direct / review
    page.evaluate("localStorage.clear()")
    page.goto(BASE)
    page.get_by_label("Логин").fill("viewer")
    page.get_by_label("Пароль").fill("viewer123")
    page.get_by_role("button", name="Войти").click()
    try:
        page.get_by_text("Индекс настроения города").wait_for(timeout=15000)
    except Exception:
        shot(page, "viewer_fail")
        raise
    assert page.get_by_text("Личные обращения").count() == 0, "viewer sees Direct menu"
    page.goto(BASE + "/direct")   # viewers are redirected to the public feed
    page.get_by_role("heading", name="Лента обращений").wait_for()
    assert "/feed" in page.url

    # Mobile layout
    m = b.new_page(viewport={"width": 390, "height": 844})
    m.goto(BASE)
    m.get_by_label("Логин").fill("admin")
    m.get_by_label("Пароль").fill("admin123")
    m.get_by_role("button", name="Войти").click()
    m.get_by_text("Индекс настроения города").wait_for(timeout=15000)
    shot(m, "14_mobile_overview")
    m.goto(BASE + "/admin")
    m.get_by_role("heading", name="Администрирование").wait_for()
    shot(m, "15_mobile_admin")
    b.close()

ignored = ("fonts.googleapis", "fonts.gstatic", "ERR_TUNNEL", "net::ERR")
real = [e for e in errors if not any(x in e for x in ignored)]
print("console errors:", len(real))
for e in real[:30]:
    print(" ", e[:300])
