# Pavlodar sources and platform capabilities

Checked on 30.10.2026. Nothing here is guessed: every row says what was actually verified.
The same list is built into the app (**Источники и сбор → Рекомендованные**) and can be added with one click.

## Telegram

| Source | URL | What it is | Verified | Collection |
| --- | --- | --- | --- | --- |
| Типичный Павлодар | https://t.me/tipavlo | Largest city public page found; local incidents and resident videos | Exists, 36,031 subscribers (t.me page) | Posts via t.me/s if the web preview is on (checked on first run); comments via Telethon if discussion is enabled |
| Павлодар онлайн | https://t.me/pavlodaronline | News of Pavlodar (pavon.kz): heating season, water outages, waste; also region news (Ekibastuz, Aksu, Bayanaul) | Web preview open with Pavlodar city posts | Accessible; geo filter excludes region items |
| АО «Павлодарэнерго» | https://t.me/pavlodarenergo | Official utility channel: heating, hot water, power outages, network repairs | Web preview open; posts on hot-water connection tests in Pavlodar | Accessible; official side to compare with resident complaints |
| Press Pavlodar region | https://t.me/baspasozpvl | Regional akimat press service (KZ/RU) | Exists; the viewed part had older posts, current activity unconfirmed | Accessible; low priority (mostly region) |
| Pavlodar Chat | https://t.me/pvl_chat_14 | Public city chat | Listed in the telegid.me Pavlodar catalogue only | Telethon; review content before enabling |
| Chat.Pavlodar \| Павлодар | https://t.me/chat_pavlodara | Public city chat | Catalogue listing only | Telethon; review before enabling |
| Павлодар | https://t.me/pavlo_rf | Chat of relocated and local residents: housing, jobs | Catalogue listing with description | Telethon |

Not included:
- **Private invite-only chats.** Examples are "Павлодар 🇰🇿 Чат TravelAsk" (1,199 members) and "Чат Павлодар" (325 members). The spec forbids closed chats.
- **Dating, classifieds and vape groups.**
- **The akimat's appeal bot** (@PVLSailau_bot, linked from gov.kz). Messages to another party's bot cannot be read; the akimat would need to give its token.

No verified, public, high-volume Telegram group where Pavlodar residents mainly post complaints was found. Comments under @tipavlo are the most promising source of resident voices.

## Instagram (official Instagram Platform API)

| Capability | Status | Requirement |
| --- | --- | --- |
| Comments and replies on posts of the connected professional account | Implemented, tested with mocked API | `instagram_business_basic`, `instagram_business_manage_comments`; the account owner connects it |
| Public posts (caption, link, counts) of other professional accounts (Business Discovery) | Implemented | Documented for Facebook Login tokens (`INSTAGRAM_API_HOST=graph.facebook.com`); comments of those posts are not available |
| Recent public posts by hashtag | Implemented | App Review for Instagram Public Content Access; 30 hashtags per 7 days |
| Direct messages to the connected account | Implemented | `instagram_business_manage_messages`; without Advanced Access only users with a role on the app |
| Comments under other accounts' posts, private accounts, arbitrary public comments | Not possible | No official endpoint; not attempted |

Most valuable target: **@pavlodar_akimdigi**, the city akimat's official account (linked from gov.kz). Full comment collection needs the akimat to connect that account through the Connect button.

## Threads (official Threads API, graph.threads.com/v1.0)

| Capability | Status | Requirement |
| --- | --- | --- |
| Posts of the connected account and all replies (`/me/threads`, `/{id}/conversation`) | Implemented, tested with mocked API | `threads_basic`, `threads_read_replies` |
| Keyword search of public posts (`/keyword_search`, RECENT, incremental) | Implemented | `threads_keyword_search`; before Meta approves it, only the connected account's own posts are searched; 2,200 queries/24 h |
| Replies to other users' public posts | Implemented, degrades with a logged warning | Advanced Access |
| Posts of public profiles (`/profile_posts`) | Implemented | `threads_profile_discovery`; standard access returns only Meta's own accounts |
| Likes and views | Not collected | Would need `threads_manage_insights` |

No verified Pavlodar Threads accounts were found, so the recommended source is a keyword search ("Павлодар", "Pavlodar", "Павлодарда", "павлодарцы") with geo scope "national". The geo filter keeps only city-related posts.

## Sources

- [Telegram catalogue telegid.me — Pavlodar](https://telegid.me/catalog/kazahstan/pavlodar)
- [t.me/tipavlo](https://t.me/tipavlo)
- [t.me/s/pavlodaronline](https://t.me/s/pavlodaronline)
- [t.me/s/pavlodarenergo](https://t.me/s/pavlodarenergo?before=727)
- [t.me/s/baspasozpvl](https://t.me/s/baspasozpvl?after=3674)
- [Pavlodar city akimat on gov.kz](https://www.gov.kz/memleket/entities/pavlodar-pvl?lang=ru)
- [Threads keyword search](https://developers.facebook.com/documentation/threads/keyword-search)
- [Threads replies and conversations](https://developers.facebook.com/documentation/threads/retrieve-and-manage-replies/replies-and-conversations.md)
- [Threads retrieve posts](https://developers.facebook.com/documentation/threads/retrieve-and-discover-posts/retrieve-posts.md)
- [Threads profiles](https://developers.facebook.com/documentation/threads/threads-profiles)
- [Threads access tokens](https://developers.facebook.com/documentation/threads/get-started/get-access-tokens-and-permissions.md)
- [Threads long-lived tokens](https://developers.facebook.com/documentation/threads/get-started/long-lived-tokens.md)
- [Instagram Business Login](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login.md)
- [Instagram media comments](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-media/comments.md)
- [Instagram Business Discovery](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/business-discovery)
- [Instagram Hashtag Search](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/hashtag-search)
