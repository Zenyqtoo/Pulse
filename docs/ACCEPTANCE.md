# Acceptance criteria (spec section 8)

Status as of 30.10.2026. "Verified" = covered by an automated test or the browser walk-through in this build.
"Needs on site" = depends on credentials or data only the team can provide.

| # | Criterion | Implementation | Verification | Status |
| --- | --- | --- | --- | --- |
| 1 | ≥ 3 sources in one feed | Collectors: Telegram t.me/s, Telethon comments/chats, news RSS(+comments), Telegram bot (Direct), CSV/XLSX upload; synthetic demo set as fallback | Parsers unit-tested on recorded HTML/RSS/Bot API payloads; upload + dedup tested end-to-end; error handling checked against unreachable sources | Code verified. **Needs on site:** configure ≥ 3 real sources and run them (this sandbox cannot reach Telegram) |
| 2 | Department + sentiment with confidence | One Claude tool call per message, Pydantic-validated JSON, retry + labelled rules fallback; confidence bar and rationale on every card | `test_llm_*` (valid, invalid→retry, API error→fallback, unknown dept coerced); feed and card in browser test | Verified (LLM path with a fake client; real calls need `ANTHROPIC_API_KEY`) |
| 3 | Filter/group by date, problem, department, sentiment, priority | Shared URL filter for feed, dashboards and exports; also status, source, district, type, language, urgency, text search | `test_feed_filters`, browser test | Verified |
| 4 | Similar messages grouped, priority computed | Clustering + same-problem rule; transparent 6-term priority with breakdown; growth/hot topics | `test_priority_*`, `test_clusters_and_status_propagation`; demo groups purity 0.91, coverage 0.91 (`scripts/cluster_quality.py`) | Verified |
| 5 | Dashboards 1–3 with filters, drill-down, export XLSX/CSV/PDF | Общая картина, Подразделения, Проблемы и приоритеты; click any chart → feed → card → original link; CSV/XLSX/PDF for items and problems, PDF management report | `test_dashboards`, `test_exports`; browser test downloads XLSX | Verified |
| 6 | Sentiment ≥ 80%, department ≥ 75% on a test set | Blind labelling UI, fixed 75/25 test/dev split, metrics on original model output, confusion matrix, per-language results | `test_quality_labeling_and_eval` | Mechanism verified. **Needs on site:** label 150–200 real messages and run with the API key. Synthetic-set numbers (rules: 89% / 97%) are in-sample and not a claim |
| 7 | Section 5: public data, minimal PII, advisory AI | Salted author hash only; masking before LLM; Direct restricted; "рекомендация" labels; human confirm/correct; deletion on request; retention job | `test_pii_never_in_list_or_export`, `test_direct_is_restricted`, `test_delete_on_request`, masking unit tests | Verified |
| 8 | Direct from ≥ 1 official account (or demo stream), restricted, PII masked | Telegram bot via Bot API, masked text by default, original only for operator/admin with audit log, operator replies, auto-ack | Bot payload parsing unit-tested; restrictions in API and browser tests | Verified with recorded payloads. **Needs on site:** bot token. Note: the spec targets the akimat's official accounts; a team bot is the demo stream allowed by 3.7.7 |
| 9 | Demo on real data | Scheduled + manual collection, collection log, origin filter that separates real from synthetic | — | **Needs on site:** connect real sources from Friday onward |

## Multi-platform Pavlodar monitoring (extension)

| Requirement | Implementation | Verification | Status |
| --- | --- | --- | --- |
| Pavlodar city only (not region) | `app/geo`: gazetteer + source scope + parent context + LLM contextual judgement; local / possible / not_local; other places skipped before the LLM | 20 geo tests incl. Kazakh forms, region wording, mixed mentions, incidental mention overridden by LLM | Verified |
| Possibly-local queue | **Геопривязка** page, operator decision logged and kept on reprocessing | `test_possible_queue_and_operator_decision`, browser test | Verified |
| Telegram: incremental, comments, replies, links | t.me/s incremental by last post id; Telethon comments with nested-reply parents and parent-post context; chats incremental by min_id | `test_telegram_web_incremental`, `test_telethon_comment_threading` | Verified offline; **needs on site:** live run (Telegram blocked in build sandbox) |
| Instagram (official API) | OAuth (Business Login), encrypted tokens, auto refresh; own-media comments + replies, business discovery, hashtags, Direct | Mocked Meta API: comments/replies, discovery, permission and expired-token errors, OAuth flow | Verified against mocks. **Needs:** Meta app + account connection; some modes need App Review |
| Threads (official API) | OAuth, keyword search (incremental), conversation replies, own posts, profile posts | Mocked API: search + replies + state, blocked replies reported | Verified against mocks. **Needs:** Meta app; public search needs approval |
| Source management | Platform tabs, search/filter, URL/description/scope, connection status, errors, enable, collect now, history, edit, delete, recommended one-click add | `test_recommended_sources`, `test_source_crud_with_geo_scope`, browser test | Verified |
| Cross-platform problems | Same clustering for all platforms; cluster platforms + source count; reposts counted | `test_cross_platform_problem_is_one_cluster`, `test_repost_on_another_platform_counts_for_problem` | Verified |
| Dashboards by platform | Volume and sentiment by platform, multi-platform problems, platform filter everywhere, Pavlodar districts | API test + browser screenshots | Verified |

## Other requirements covered

- Hourly schedule + manual run (3.1.4), dedup exact + near-duplicate, spam filter (3.1.5), Russian/Kazakh detection (3.1.6)
- Review queue below 0.6 (3.2.3), corrections as few-shot examples (3.2.5), entity extraction (3.2.4)
- Status workflow new → transferred → in progress → resolved → closed, propagated from problem to its messages (3.4.4)
- Weekly digest per department (3.4.5), AI chat with links to source messages (3.5.5)
- Admin: sources, departments directory, users and roles, audit and collection logs (3.6)
- Telegram alerts for new high-priority problems (3.8.5), department-scoped users (3.8.6)
- Explainability: rationale per message and priority breakdown per problem (section 4)

## Not implemented

- Dashboards 4–7 as separate pages (post-MVP per 3.8.7); district bars, source and operational counters are on the existing pages
- Instagram / WhatsApp Direct, Kazakh UI, saved filter presets, dark theme, Kazakhstan hosting
