# Пульс города — citizen feedback monitoring for Pavlodar

Hackathon track «Городская обратная связь». The system monitors **Pavlodar city** (not the region) across Telegram,
Instagram, Threads, news sites and Direct messages to the akimat. It keeps only messages about the city
(geographic relevance filter), masks personal data, classifies each message into one of 11
departments with confidence, detects sentiment, type, urgency and entities, groups similar complaints into
problems, computes a transparent priority, and shows it all on role-based dashboards with drill-down and export.

- `backend/` — FastAPI, SQLAlchemy 2, PostgreSQL, Alembic, APScheduler, Claude API, scikit-learn
- `frontend/` — React 19 + Vite + TypeScript, Ant Design 6, ECharts
- `docs/ACCEPTANCE.md` — acceptance criteria (spec section 8) with how each is implemented and verified
- `docs/DEMO.md` — demo preparation and a 4-minute script
- `docs/SOURCES.md` — verified Pavlodar sources and what each platform's official API allows

## Quick start with Docker (recommended)

```bash
cp .env.example .env          # set SECRET_KEY, AUTHOR_HASH_SALT, passwords, ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN
docker compose up -d --build  # builds UI + API, runs migrations, seeds departments, users and default sources
open http://localhost:8000    # log in as operator / admin / viewer (passwords from .env)
```

Optional fallback demo data (synthetic, clearly labelled in the UI):

```bash
docker compose exec app python -m app.cli load-demo
```

## Local development without Docker

Requirements: Python 3.12+, Node 20+, PostgreSQL 16.

```bash
createuser -P pulse && createdb -O pulse pulse            # password: pulse (or change DATABASE_URL)
cp .env.example backend/.env                               # edit values
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head
python -m app.cli load-demo                                # optional synthetic demo set
uvicorn app.main:app --reload --port 8000

cd ../frontend
npm install
npm run dev                                                # http://localhost:5173 (proxies /api to :8000)
# or: npm run build  → output goes to backend/static and is served by FastAPI on :8000
```

## Connecting real sources

All configuration is in the UI under **Источники и сбор** (admin role) and in `.env`.

| Source | What you provide | Notes |
| --- | --- | --- |
| Telegram public channels (t.me/s) | Channel usernames | No login. Posts, dates, views. |
| Telegram comments and public chats (Telethon) | `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` from my.telegram.org, then once: `python -m app.cli telethon-login` (Docker: `docker compose exec app python -m app.cli telethon-login`) | Comments under posts — where most complaints are. Use a dedicated account. |
| News portal | RSS URLs; optional CSS selectors for reader comments | Check the site's robots.txt and terms. |
| Direct (Telegram bot) | `TELEGRAM_BOT_TOKEN` from @BotFather | Long polling every 20 s, no public URL needed. Auto-acknowledges receipt; operator replies from the item card. |
| CSV / XLSX upload | A file with a text column (date, url, author optional) | For exports from 2GIS, portals, or data from the organisers. |
| Instagram | `INSTAGRAM_APP_ID/SECRET` + **Подключить Instagram** (or `INSTAGRAM_ACCESS_TOKEN`) | Official API only: comments/replies on the connected account's posts, posts of other business accounts, hashtags (App Review), Direct. See below. |
| Threads | `THREADS_APP_ID/SECRET` + **Подключить Threads** (or `THREADS_ACCESS_TOKEN`) | Keyword search, replies, own posts, public profiles; public search needs Meta approval. See below. |

**Recommended Pavlodar sources** (verified, see `docs/SOURCES.md`) are listed on the Sources page with one-click add.
Each source has a **geographic scope** (city / region / national) that the geo filter uses as context.

### Connecting Instagram

1. developers.facebook.com → Create app (type Business) → add product **Instagram** → "API setup with Instagram business login".
2. Add the redirect URI `{PUBLIC_BASE_URL}/api/connect/instagram/callback` (HTTPS in production; set `PUBLIC_BASE_URL`).
3. Copy the Instagram app ID and secret into `INSTAGRAM_APP_ID` / `INSTAGRAM_APP_SECRET`, restart.
4. As admin: **Источники и сбор → Instagram → Подключить Instagram**, log in with the **professional** account to monitor
   (ideally the akimat's @pavlodar_akimdigi; the account owner must log in). Tokens are stored encrypted and refreshed automatically.
5. Enable the Instagram source. Without App Review, Meta returns data only for accounts with a role on your app;
   hashtag search needs the **Instagram Public Content Access** feature and a Facebook Login token (`INSTAGRAM_API_HOST=graph.facebook.com`, `INSTAGRAM_USER_ID`).

### Connecting Threads

1. developers.facebook.com → Create app → use case **Access the Threads API**; add permissions `threads_basic`,
   `threads_read_replies`, `threads_keyword_search` (and `threads_profile_discovery` if needed).
2. Redirect URI `{PUBLIC_BASE_URL}/api/connect/threads/callback`; copy the Threads app ID/secret to `THREADS_APP_ID/SECRET`.
3. Add your Threads account as a tester, then **Подключить Threads** on the Sources page.
4. Until Meta approves `threads_keyword_search` (App Review), keyword search returns only your own posts — the UI states this.

## Pavlodar-only geographic filter

Every message gets **Павлодар / Возможно Павлодар / Не Павлодар**:
1. Rules: city name forms in Russian/Kazakh/Latin («Павлодарда», «павлодарцы», «Pavlodar»), city landmarks and utilities,
   streets (weak evidence), other towns of the region and other cities (Экибастуз, Аксу, Майкаин, Баянаул…), region-only wording,
   the source's scope, and the parent post for comments. Messages clearly about another place are excluded **before** any LLM call.
2. The same Claude call that classifies the department judges the geography in context (source description and parent post);
   it can exclude incidental mentions such as sports results.
3. Only «Павлодар» enters dashboards, clusters and priorities. «Возможно» goes to the **Геопривязка** queue, where an operator decides
   (the decision is logged and never overwritten). Edit the gazetteer in `backend/app/geo/pavlodar.py`, then run `python -m app.cli geo-reclassify`.

Problems are clustered across platforms: the same complaint on Telegram, Instagram and Threads becomes one problem that lists
all platforms and links to every original post; exact reposts on another platform are counted as attention there.

Collection runs on schedule (hourly by default) and on «Собрать сейчас». Every run is in the collection log with counts and errors.

## How the AI works

1. **Before any external call:** regex masking of IIN, phones, e-mails, cards, apartment numbers and full names
   (plus house numbers for Direct). The LLM only ever sees masked text; names it finds that regex missed are masked in a second pass.
2. **One Claude call per message** (forced tool call with a JSON schema, validated with Pydantic, one corrective retry, SDK retries
   with backoff): departments (1–3) + confidence, sentiment + score, type, spam, district/address/object/problem type,
   urgency markers, rationale in Russian. Confidence < 0.6 → review queue.
3. **Fallback:** without a key or if the API fails, a rules analyser runs and is labelled `rules-v1` everywhere. It is a safety net, not the target quality.
4. **Clustering:** per department, agglomerative clustering on embeddings (local sentence-transformers if installed, else character
   n-gram TF-IDF), plus a rule that the same normalised problem type in the same district is one problem. Titles and summaries by Claude (extractive without it).
5. **Priority (0–100):** `25·negativity + 20·volume + 20·growth(24h) + 15·reach + 15·urgency + 5·days unresolved`; high ≥ 55, medium ≥ 35;
   a life-threat marker forces high. Every term is stored and shown.
6. **Operator corrections** are kept separately from the model's original answer and become few-shot examples (test-set items excluded).

## Accuracy (acceptance criterion 6)

Label real messages on **Качество ИИ → Разметка** (blind: the model's answer is hidden). Each label is assigned to test (75%) or dev (25%).
Then **Качество ИИ → Оценить** with «Реальные данные / Тестовая». Metrics are computed on the model's original output, with a confusion
matrix and a per-language breakdown. CLI: `python -m app.cli evaluate --origin real --split test`.
Accuracy on the synthetic demo set is shown separately and marked as not representative.

## Roles

| Role | Can |
| --- | --- |
| viewer | Dashboards, public feed, problems, exports (masked text, no Direct messages) |
| operator | + Direct messages (masked; original on request, audited), corrections, routing, statuses, replies, collection, labelling |
| admin | + users, departments directory, sources, audit log, deletion on request |

Any user can be limited to one department (spec 3.8.6).

## Tests

```bash
cd backend && . .venv/bin/activate
createdb -O pulse pulse_test
pytest -q                                   # 69 tests: masking, parsers, priority, LLM schema/fallbacks, API, roles, exports,
                                            # geo filter, Instagram/Threads collectors and OAuth (mocked Meta API), cross-platform clusters
cd ../frontend && python e2e/smoke.py http://localhost:8000 shots   # browser walk-through (needs Playwright + Chromium)
```

## Limits and next steps

- Instagram and Threads collectors are implemented on the official APIs and tested against mocked Meta responses; they need your Meta app credentials, and several capabilities need Meta App Review (see `docs/SOURCES.md`). WhatsApp is not connected.
- 2GIS reviews are loaded via CSV export; no documented public reviews API was found.
- Production version: Kazakhstan hosting, encryption at rest, Celery/Redis workers for >10k messages/day, SSO.
