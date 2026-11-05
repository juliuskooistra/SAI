# BikeShop on the lecture map

The final slide of *From prototype to production* shows every part of a
production system. This page puts BikeShop on that map: which boxes the app
has, where they are in the code, which boxes it leaves out on purpose, and
**what changes if you swap the bike shop for another use case**.

✅ in BikeShop · 🟡 partly · ⬜ not in BikeShop

```text
                         ┌──────────────── nDSG / GDPR 🟡 ────────────────────────────────┐
  User ─ Browser ─ DNS ✅▶│ Reverse proxy + HTTPS ✅  (Azure ingress, managed certificate)   │
  (customer/staff)       │   ├─ Frontend ✅ (static) ── legal 🟡 help ✅ analytics ✅           │
                         │   └─ API ✅ ─ sign-in ✅ roles ✅ rate limit ✅ shield ✅          │
                         │        └─ Backend ✅ ─ Database ✅ (SQLite) ── Backups ✅ (Litestream)│
                         │             ├─ Queue ✅ ─ Worker ✅   Scheduler ✅ (in the worker)   │
                         │             └─ logs/metrics ✅ ─▶ Monitoring ✅ ─▶ 🔔 ✅            │
                         └──────┬──────────────┬───────────────┬───────────────────────────┘
                     LLM provider ✅    Email ✅ (Mailgun EU)   SSO provider ⬜
                      (BFH MLMP)
  Spec ✅ + CLAUDE.md ✅ ─ Git ✅ ─ CI ✅ (tests) ─ deploy ✅ ─▶ dev ✅ / staging ✅ / prod ✅  (rollback 🟡)
```

The demo runs on **Azure Container Apps** at <https://demo.sai1.airs.iadsf.ch>
(SPEC §10.2). Running it on your own VM behind nginx is documented as an
alternative (SPEC §10.1).

## Box by box

**Swap** says what happens to a box when the bike shop is replaced by another
use case, say a library that lends books or a gym that books classes:

- **stays**: reuse as it is.
- **adapt**: same mechanism, new names or settings.
- **replace**: written again for the new domain.

| Box (chapter) | BikeShop | Where | Swap |
|---|---|---|---|
| **User, browser** (1) | ✅ Two user types: customer and staff. | [SPEC §3](SPEC.md) | adapt: role names |
| **DNS** (2) | ✅ `demo.sai1.airs.iadsf.ch` is a CNAME to the Azure app; a TXT record proves the domain is ours. | [SPEC §10.2](SPEC.md), [DEPLOY-azure.md](DEPLOY-azure.md) | adapt: a new hostname |
| **Server** (2) | ✅ Azure Container Apps: one container runs the API, the website and the worker, and scales to zero after an hour without visitors. A VM with Docker works too. | [DEPLOY-azure.md](DEPLOY-azure.md), [docker-compose.yml](docker-compose.yml) | stays |
| **Reverse proxy + HTTPS** (2) | ✅ Azure's ingress terminates HTTPS with a free managed certificate. On a VM: nginx + certbot. | [DEPLOY-azure.md](DEPLOY-azure.md), [deploy/nginx/](deploy/nginx/) | adapt: the hostname |
| **Frontend** (1) | ✅ A static site: HTML, CSS and JavaScript, no framework, no build step, served by FastAPI itself. Only `js/api.js` talks to the API. The browser keeps all state, so a backend that scales to zero never breaks an open page. The *Assistant* page is a chat with the AI assistant: the conversation stays in the tab, and the page polls the queue for each answer. (Streamlit was used first; SPEC §12.) | [frontend/](frontend/), [FRONTEND.md](FRONTEND.md), [frontend/js/pages/assistant.js](frontend/js/pages/assistant.js) | `index.html`, `styles.css`, `ui.js`, the sign-in, account, jobs, analytics and assistant pages stay; `api.js` and `app.js` adapt; the shop pages are replaced |
| ↳ legal pages (7) | 🟡 Privacy policy and terms at `/legal/privacy` and `/legal/terms`, rendered from markdown. Drafts, pending review. | [docs/legal/](docs/legal/), [api/content/](api/content/) | the renderer stays; the texts are rewritten |
| ↳ help (7) | ✅ A help centre at `/help`: getting started, renting, buying, account and tokens, staff. Linked from every page's footer. | [docs/help/](docs/help/) | the renderer stays; the articles are rewritten |
| ↳ product analytics (6) | ✅ First-party and anonymous: one row per catalogue view, bike view, quote, booking and reservation, with the day only (no cookies, no user id, no IP). A staff page shows per-day counts, top bikes and the quote → booking rate, over up to a year, and how many bookings came through the AI assistant (a `channel` per event: how, never who). | [api/services/analytics_service.py](api/services/analytics_service.py), [frontend/js/pages/staff-analytics.js](frontend/js/pages/staff-analytics.js) | stays; adapt the event names |
| **API** (1) | ✅ FastAPI, built as a class with one router per area. Docs at `/docs`. | [api/main.py](api/main.py), [api/router/](api/router/) | `main.py` adapts (which routers); the auth, billing and job routers stay; the shop routers are replaced |
| ↳ sign-in (3) | ✅ Username + password give an API key; the key goes in every request. Passwords stored with bcrypt, keys as hashes. | [api/middleware/auth_middleware.py](api/middleware/auth_middleware.py), [api/services/auth_service.py](api/services/auth_service.py) | stays |
| ↳ roles (3) | ✅ `customer` / `staff`; `/staff/*` answers 403 to customers. Staff accounts come from the seed or the command line, never from the API. | `auth_middleware.py`, [scripts/create_staff.py](scripts/create_staff.py) | adapt: role names and the staff-only path |
| ↳ rate limit (3) | ✅ 60 calls/minute, 1,000/hour, 5,000/day per user. | [api/middleware/rate_limit_middleware.py](api/middleware/rate_limit_middleware.py) | stays |
| ↳ shield (3) | ✅ Input validation (Pydantic models, shop rules), SQL injection prevented by SQLAlchemy, CORS limited to the app's own origin, and the frontend puts API text on the page as text, never as HTML. **Prompt injection**, in five layers (SPEC §13.8): the browser can't change the system prompt and may send only short `user`/`assistant` text; a guard copied from `kooistra-pii` refuses known injection phrasings before any AI call; the system prompt says customer text and tool results are data; the tools can only act for the signed-in customer, with every shop rule enforced, at most 6 tool rounds and one booking and one hand-off per message; answers are shown as text. | [api/models/models.py](api/models/models.py), [frontend/js/ui.js](frontend/js/ui.js), [api/services/guard_service.py](api/services/guard_service.py), [api/router/assistant_router.py](api/router/assistant_router.py), [api/services/chat_service.py](api/services/chat_service.py) | the mechanisms stay, the prompt guard too; the validation rules go with the models |
| *(not on the map)* token billing | Each `/api` call costs API tokens, copied from Use_Case_III. | [api/middleware/billing_middleware.py](api/middleware/billing_middleware.py) | stays; adapt the cost list in `config.py` |
| **Backend** (1) | ✅ The shop rules live in services, which know nothing about HTTP: pricing, availability, bookings, sales. | [api/services/](api/services/) | errors, auth, billing, rate limit, inference and analytics stay; pricing, rental, order, inventory and notification are replaced. **This is the use case.** |
| **Database** (4) | ✅ SQLite, one file (on Azure on the container's own disk, restored by Litestream). WAL mode + `BEGIN IMMEDIATE`, so two customers can't book the same bike. The seed adds bikes, prices and demo accounts; a year of invented rentals, orders and analytics, with patterns to discover, comes on top (SPEC §9.1). | [api/database.py](api/database.py), [scripts/seed.py](scripts/seed.py), [scripts/seed_history.py](scripts/seed_history.py) | `database.py` stays; the seed and the history are replaced |
| ↳ schema · migrations (4) | 🟡 The schema is in code (`models.py`) and tables are created with `create_all`. New tables appear by themselves; a new column on an existing table is added by a small start-up migration (`ADDED_COLUMNS` in `database.py`, e.g. `analyticsevent.channel`). Anything bigger (renames, data changes) needs a migration tool (Alembic). | [api/models/models.py](api/models/models.py), [api/database.py](api/database.py) | the user, key, usage, job and analytics tables stay; the shop tables are replaced |
| ↳ the Workshop *(an LLM workflow, not on the map)* | ✅ Staff-only maintenance agent: a simulated diagnostic machine, a safety gate in code, an agent that analyses, discusses with a person and plans, and staff actions it can't reach. Bikes in repair stay listed with an expected date; booking logic is unchanged. Ten planted cases are its answer key. | [WORKSHOP.md](WORKSHOP.md), [api/services/workshop_service.py](api/services/workshop_service.py), [api/services/workshop_agent.py](api/services/workshop_agent.py), [api/tools/workshop_tools.py](api/tools/workshop_tools.py), [SPEC §14](SPEC.md) | the workflow's shape stays (stages, one round per job, budget, gate); the machine, tools and data are replaced |
| **Backups** (4) | ✅ On Azure the container keeps no files, so Litestream copies every change to Azure Blob Storage within about a second and restores it when a container starts: a continuous backup of the database. | [litestream.yml](litestream.yml), [scripts/start.sh](scripts/start.sh) | stays |
| **Queue → worker** (5) | ✅ A job queue in SQLite: claim in `BEGIN IMMEDIATE`, retries with back-off, a heartbeat, a reaper for jobs whose worker died. The worker runs the jobs: `send_email`, and `assistant_reply`, one answer of the website's AI assistant (one attempt only, so a retry can't book twice). `workshop_step`, one round of the Workshop's agent, runs in a lane of its own, so a customer's answer never waits behind it. A request enqueues; `GET /api/jobs/{id}` shows the result. | [api/jobqueue/](api/jobqueue/), [scripts/worker.py](scripts/worker.py), [SPEC §5.8](SPEC.md) | the queue stays; the handlers are replaced |
| **Scheduler** (5) | ✅ The worker also releases reserved sale bikes after 7 days (every 15 minutes) and deletes old analytics once a day. One process, so it runs once and not once per API worker. | [scripts/worker.py](scripts/worker.py), [SPEC §5.7](SPEC.md) | the loop stays; the periodic jobs are replaced |
| **LLM provider** (5) | ✅ BFH inference (MLMP), CH, via the proxy, checked on `/health`. The assistant's five tools call the services. On the website (*Assistant* page) it always uses BFH, through the queue; in the terminal lesson Claude, ChatGPT, Gemini, Mistral or Ollama can be chosen in `.env`. One tool uses a small ML model (demand forecast) trained on made-up history, into the image during the build. The hand-off to staff sends a real email. The Workshop (SPEC §14) is a second, staff-only LLM workflow: `glm-5.3-flash` reads the diagnostic machine's scan through read-only tools, briefs staff, discusses their choice, and writes the plan. One model round per job, inside a budget, so it fits BFH's limits next to the assistant. | [WORKSHOP.md](WORKSHOP.md), [api/services/inference_service.py](api/services/inference_service.py), [api/services/llm_service.py](api/services/llm_service.py), [api/tools/](api/tools/), [ASSISTANT.md](ASSISTANT.md), [SPEC §8, §13](SPEC.md) | the connection and `llm_service.py` stay; the tools and the demand model are replaced |
| **Email** (5) | ✅ Booking confirmed, bike reserved, reservation expired: sent by the worker through Mailgun's EU endpoint (`mail.kooistra.ch`), never inside a request. Without a Mailgun key the email goes to the log instead. Demo accounts (`.test`) are skipped. | [api/mail/](api/mail/), [api/services/notification_service.py](api/services/notification_service.py) | the mailer stays; the messages are replaced |
| **SSO provider** (3) | ⬜ None: own accounts with a password. At BFH this would be SWITCH edu-ID. | — | — |
| **logs · metrics** (6) | ✅ JSON log lines from the API and the worker (Azure keeps them in Log Analytics). `/metrics` for Prometheus on a VM, with requests by route, the queue and the periodic jobs; off on Azure. `/health` shows the database, inference, the worker and the queue. | [api/observability.py](api/observability.py), [api/main.py](api/main.py) | stays |
| **Monitoring → alert** (6) | ✅ Azure Monitor: logs in Log Analytics, Azure's own request, error and replica metrics, and four alert rules that email the lecturer: 5xx responses, container restarts, exceptions in the logs, jobs that failed for good. (Grafana can't read Azure from a BFH student account; for a VM a Grafana dashboard was prepared.) | [SPEC §10.3](SPEC.md), [COSTS.md](COSTS.md) | stays |
| **nDSG / GDPR frame** (7) | 🟡 Personal data: username, email, password hash, rentals and orders, and the recipient address in email jobs. A draft privacy policy; no account deletion yet. Analytics are anonymous. MLMP's "no personal data" rule holds for the assistant: no tool takes a name, and no user id, username or email goes to the AI. The website's conversation stays in the browser tab; the hand-off to staff emails them the customer's username and address, which never go to the AI. | [docs/legal/](docs/legal/), [SPEC §8.2, §13.4](SPEC.md) | review again: which personal data the new use case holds |
| **Spec + CLAUDE.md** (8) | ✅ The spec is the contract and was written before the code. `CLAUDE.md` tells Claude to change the spec first, to keep this map up to date, how to run the app and the tests, the house rules, demo data and the git workflow. The `CLAUDE.md` at the repository root imports it. | [SPEC.md](SPEC.md), [CLAUDE.md](CLAUDE.md), [../CLAUDE.md](../CLAUDE.md) | §1–§7 are replaced (the domain); queue, email, inference, deployment and the build-slice format stay |
| **Git** (2) | ✅ This repository. The earlier use cases are in the history under the tag `pre-bikeshop`. | — | stays |
| **CI (tests)** (2) | ✅ About 285 tests, one group per build slice; GitHub Actions runs them on every push. | [tests/](tests/), [.github/workflows/bikeshop.yml](../.github/workflows/bikeshop.yml) | `conftest.py` and the platform tests stay; the shop tests are replaced |
| **deploy** (2) | ✅ GitHub Actions on every merge to `main`: tests → image `bikeshop:<commit>` → staging (checked with `/health`) → your approval → the same image to production. Azure login through a managed identity and OIDC, no stored secrets. One pipeline only: the portal's "Continuous deployment" would add a second workflow that fights this one. Each deploy stops the old version before it starts the new one, so two copies never write the database (about a minute of downtime). Manual deploys still work, through the same script. | [.github/workflows/bikeshop.yml](../.github/workflows/bikeshop.yml), [deploy/azure/release.sh](deploy/azure/release.sh), [deploy/azure/update.sh](deploy/azure/update.sh), [DEPLOY-azure.md](DEPLOY-azure.md) | stays; rename the apps |
| **dev / staging / prod** (2) | ✅ dev = your laptop (uvicorn, or Docker; `deploy/azure/compose.azurite.yml` mimics Azure). staging = `bikeshop-staging` at `staging.sai1.airs.iadsf.ch`, with its own data and no real emails. prod = `bikeshop` at `demo.sai1.airs.iadsf.ch`. | [SPEC §10.2](SPEC.md), [DEPLOY-azure.md](DEPLOY-azure.md) | stays |
| **rollback** (2) | 🟡 Every image is tagged with its commit, so re-running an earlier production deploy (or `deploy/azure/release.sh bikeshop <registry>/bikeshop:<hash>`) goes back. Data changes are not rolled back. | [DEPLOY-azure.md](DEPLOY-azure.md) | stays |
| **Secrets** (2) | ✅ Azure Container Apps secrets (or `.env` on a VM), never in the repo or the image; `.env.example` lists the keys. | [.env.example](.env.example) | stays |

## Swapping the use case, file by file

About half of the code is the platform that stays, an eighth mixes both, and two
fifths is the bike shop (lines of code, tests and help texts included):

| | Files | Share |
|---|---|---|
| **stays** | `api/database.py`, `timeutils.py`, `expose_api.py`, `observability.py`; `api/middleware/*`; `api/jobqueue/queue.py`; `api/mail/`; `api/content/`; `api/services/` auth, billing, rate_limit, inference, analytics, errors, llm, chat, guard; `api/router/` auth, billing, job; `scripts/worker.py`, `create_staff.py`, `start.sh`; `api/router/assistant_router.py`; `Dockerfile`, compose files, `litestream.yml`, nginx config; `frontend/index.html`, `styles.css`, `js/ui.js`, `js/pages/` login, account, staff-jobs, staff-analytics, assistant; `tests/conftest.py`, the platform, queue, content and web-assistant tests | ~48% |
| **adapt** | `api/main.py` (which routers), `api/config.py` (shop rules, token costs), `api/models/models.py` (platform tables stay, shop tables go), `api/jobqueue/handlers.py` (which jobs), `frontend/js/api.js` (shop calls go), `frontend/js/app.js` (routes and menu) | ~12% |
| **replace** | `api/services/` pricing, rental, order, inventory, notification; `api/router/` bike, rental, order, staff; `scripts/seed.py`, `seed_history.py`; `docs/help/`, `docs/legal/`; `frontend/js/pages/` catalogue, bike, my, staff-board, staff-inventory, staff-prices, staff-orders; the shop tests; `api/tools/assistant_tools.py` and `demand.py` (LLM tools), `scripts/train_demand_model.py` and the lesson scripts `assistant_step*.py`; the Workshop's `scan_service.py`, `workshop_service.py`, `workshop_tools.py`, `seed_workshop.py`, `workshop_evaluate.py`, `staff-workshop.js` | ~40% |

The same order as for BikeShop: write the new use case's SPEC §1–§7 first,
then replace the files in the last row.

## Using it in class

The ⬜ boxes are the checklist from chapter 8: "what does this prototype still
need before real users?" Each one is a line in the spec first, then a prompt.
For example, "add sign-in with SWITCH edu-ID".
