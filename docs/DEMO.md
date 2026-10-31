# Demo preparation and script

## Before the demo (Friday–Saturday)

1. Fill `.env`: `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALERT_CHAT_ID`, and Telethon credentials.
2. `docker compose up -d --build`, log in as admin, open **Источники и сбор**:
   - Telegram channels: 5–10 public city channels; Telethon: the same channels for comments plus public city chats.
   - News: the local portal's RSS.
   - Upload a CSV of 2GIS reviews for schools/clinics if you have one.
   - Press «Собрать сейчас» on each. Keep collection running until the demo.
3. Label 150–200 real messages on **Качество ИИ → Разметка** (two people, not the person tuning the prompt). Run the evaluation on «Реальные данные / Тестовая».
4. Do **not** load the synthetic demo set into the production database. If live sources fail, load it into a separate instance and say so.
5. Rehearse twice; record a backup video of the full script.

## 4-minute script

1. **(30 s) Problem.** "Residents complain in dozens of channels; the akimat sees a fraction, late. Since Friday our system has read N real messages from 4 sources." Show **Источники и сбор**: collection log with timestamps.
2. **(45 s) Overview.** Mood index and daily pulse; top-5 problems. Click the biggest negative day → the feed filtered to that day → open a message → «Оригинал» opens the real post.
3. **(60 s) Problem and priority.** Open the top problem: summary, 11 messages, +9 in 24 h, the priority breakdown ("why high"). Press «Передать в подразделение»: all its messages change status.
4. **(45 s) Human in the loop.** **Проверка ИИ**: a low-confidence message, rationale, correct the department. Point out "model suggested X" kept for honest evaluation.
5. **(45 s) Live Direct.** A judge sends a message with a phone number to the bot. Within ~20 s it appears in **Личные обращения**, classified, phone masked. Log in as viewer in a second window: no Direct menu. Back as operator: «Показать оригинал» → audit log entry. If it's critical, the alert arrives in the operators' Telegram chat.
6. **(30 s) Quality and export.** **Качество ИИ**: measured accuracy on the real test set vs targets, Kazakh subset. Download the PDF summary.
7. **(15 s) Close.** Architecture (one pipeline, one LLM call per message, transparent priority), privacy by design, roadmap: Instagram/WhatsApp, state appeal systems and CRM.

## Questions to expect

- *Is the accuracy real?* Blind labels, fixed test split, measured on the model's original answer, test items never used as examples.
- *Is scraping legal?* Only public pages and official APIs; author IDs are salted hashes; no private chats; deletion on request.
- *What if the AI is wrong?* Every result is a recommendation with confidence and rationale; below 0.6 goes to an operator; corrections improve the prompt.
