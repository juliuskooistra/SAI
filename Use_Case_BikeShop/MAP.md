# BikeShop on the lecture map

The final slide of *From prototype to production* shows every part of a
production system. This page puts BikeShop on that map: which boxes the app
has, where they are in the code, which boxes it leaves out on purpose, and
**what changes if you swap the bike shop for another use case**.

✅ in BikeShop · 🟡 partly · ⬜ not in BikeShop

```text
                         ┌──────────────── nDSG / GDPR 🟡 ────────────────────────┐
  User ─ Browser ─ DNS ✅▶│ Reverse proxy + HTTPS ✅  (nginx + certbot)             │
  (customer/staff)       │   ├─ Frontend ✅ (Streamlit) ── legal ⬜ help ⬜ analytics ⬜│
                         │   └─ API ✅ ─ sign-in ✅ roles ✅ rate limit ✅ shield 🟡   │
                         │        └─ Backend ✅ ─ Database ✅ (SQLite) ── Backups ⬜  │
                         │             ├─ Queue ⬜ ─ Worker ⬜   Scheduler ✅         │
                         │             └─ logs/metrics 🟡 ─▶ Monitoring ⬜ ─▶ 🔔 ⬜    │
                         └──────┬──────────┬───────────┬──────────────────────────┘
                     LLM provider ✅  Email ⬜    SSO provider ⬜
                      (BFH MLMP)
  Spec ✅ + CLAUDE.md ⬜ ─ Git ✅ ─ CI ⬜ (tests ✅) ─ deploy ✅ ─▶ dev ✅ / staging ⬜ / prod ✅  (rollback 🟡)
```

## Box by box

**Swap** says what happens to a box when the bike shop is replaced by another
use case, say a library that lends books or a gym that books classes:

- **stays**: reuse as it is.
- **adapt**: same mechanism, new names or settings.
- **replace**: written again for the new domain.

| Box (chapter) | BikeShop | Where | Swap |
|---|---|---|---|
| **User, browser** (1) | ✅ Two user types: customer and staff. | [SPEC §3](SPEC.md) | adapt: role names |
| **DNS** (2) | ✅ `demo.sai1.airs.iadsf.ch` → the server's IP. | [SPEC §10](SPEC.md) | adapt: a new hostname |
| **Server** (2) | ✅ One VM running Docker. | [docker-compose.yml](docker-compose.yml) | stays |
| **Reverse proxy + HTTPS** (2) | ✅ nginx sends API paths to FastAPI and the rest to Streamlit; certbot provides the certificate. | [deploy/nginx/](deploy/nginx/) | adapt: hostname, and the list of API prefixes |
| **Frontend** (1) | ✅ Streamlit, one page per screen. Only `api_client.py` talks to the API. | [frontend/](frontend/), [FRONTEND.md](FRONTEND.md) | sign-in, account page, `ui.py` stay; `api_client.py` keeps its auth/billing half; the shop pages are replaced |
| ↳ legal pages, help (7) | ⬜ None. It's a lecturer's demo; a public version would need a privacy page. | — | — |
| ↳ product analytics (6) | ⬜ None. The data to start from is there: `APIUsage` counts every API call per user and endpoint. | [api/models/models.py](api/models/models.py) | — |
| **API** (1) | ✅ FastAPI, built as a class with one router per area. Docs at `/docs`. | [api/main.py](api/main.py), [api/router/](api/router/) | `main.py` adapts: the list of routers. Auth and billing routers stay; the shop routers are replaced |
| ↳ sign-in (3) | ✅ Username + password give an API key; the key goes in every request. Passwords stored with bcrypt, keys as hashes. | [api/middleware/auth_middleware.py](api/middleware/auth_middleware.py), [api/services/auth_service.py](api/services/auth_service.py) | stays |
| ↳ roles (3) | ✅ `customer` / `staff`; `/staff/*` answers 403 to customers. Staff can only be created from the server's command line. | `auth_middleware.py`, [scripts/create_staff.py](scripts/create_staff.py) | adapt: role names and the staff-only path |
| ↳ rate limit (3) | ✅ 60 calls/minute, 1,000/hour, 5,000/day per user. | [api/middleware/rate_limit_middleware.py](api/middleware/rate_limit_middleware.py) | stays |
| ↳ shield (3) | 🟡 Input validation (Pydantic models, shop rules), SQL injection prevented by SQLAlchemy, CORS limited to the app's own origin. No prompt-injection guard yet: there is no LLM feature yet. | [api/models/models.py](api/models/models.py), [api/config.py](api/config.py) | the mechanisms stay; the validation rules are replaced with the models |
| *(not on the map)* token billing | Each `/api` call costs API tokens, copied from Use_Case_III. | [api/middleware/billing_middleware.py](api/middleware/billing_middleware.py) | stays; adapt the cost list in `config.py` |
| **Backend** (1) | ✅ The shop rules live in services, which know nothing about HTTP: pricing, availability, bookings, sales. | [api/services/](api/services/) | `errors.py`, auth, billing, rate limit, inference stay; pricing, rental, order, inventory are replaced. **This is the use case.** |
| **Database** (4) | ✅ SQLite, one file on a Docker volume. WAL mode + `BEGIN IMMEDIATE`, so two customers can't book the same bike. | [api/database.py](api/database.py) | stays |
| ↳ schema · migrations (4) | 🟡 The schema is in code (`models.py`), but tables are created with `create_all`: a new column on an existing table needs a migration tool (Alembic). | [api/models/models.py](api/models/models.py) | the user/key/usage tables stay; the shop tables (`Bike`, `RentalRate`, `Rental`, `Order`) are replaced |
| **Backups** (4) | ⬜ None. The data lives on the `bikeshop-data` volume; a nightly copy of the SQLite file would be the first step. | — | — |
| **Scheduler** (5) | ✅ Releases reserved sale bikes after 7 days, every 15 minutes. It runs in its own container, so it runs once and not once per API worker. | [scripts/scheduler.py](scripts/scheduler.py), [SPEC §5.7](SPEC.md) | the loop, the `JobRun` record and the container stay; the job it runs is replaced |
| **Queue → worker** (5) | ⬜ Not needed: nothing in the shop is slow. The LLM assistant may need one later. | — | — |
| **LLM provider** (5) | ✅ BFH inference (MLMP), CH, via the proxy. So far only connected and checked; the LLM tools are the next step (`api/tools/`). | [api/services/inference_service.py](api/services/inference_service.py), [SPEC §8](SPEC.md) | the connection stays; the tools are replaced |
| **Email** (5) | ⬜ None: no emails in this app. | — | — |
| **SSO provider** (3) | ⬜ None: own accounts with a password. At BFH this would be SWITCH edu-ID. | — | — |
| **logs · metrics** (6) | 🟡 Logs go to `docker compose logs`. `/health` reports the database, inference and the scheduler's last run. No metrics yet. | [api/main.py](api/main.py) (`health`) | stays |
| **Monitoring → alert** (6) | ⬜ Not connected. A monitoring system could check `/health` and alert when `scheduler.last_run_at` gets old. | — | — |
| **nDSG / GDPR frame** (7) | 🟡 Personal data: username, email, password hash, rentals and orders. No privacy page, no account deletion. MLMP's rule "no personal data" is in the contract for the LLM tools. | [SPEC §8.2](SPEC.md) | review again: which personal data the new use case holds |
| **Spec + CLAUDE.md** (8) | ✅ / ⬜ The spec is the contract and was written before the code. No CLAUDE.md yet. | [SPEC.md](SPEC.md) | §1–§7 are replaced (the domain); §8 inference, §10 deployment and the build-slice format stay |
| **Git** (2) | ✅ This repository. | — | stays |
| **CI (tests)** (2) | 🟡 About 75 tests, one group per build slice, run with `pytest`. No CI pipeline that runs them on every push. | [tests/](tests/) | `conftest.py` and the platform tests stay; the shop tests are replaced |
| **deploy** (2) | ✅ Docker Compose behind nginx, step by step in the runbook. | [DEPLOY.md](DEPLOY.md), [Dockerfile](Dockerfile) | stays; adapt the names |
| **dev / staging / prod** (2) | 🟡 dev = your laptop, prod = the VM. No staging. | [README.md](README.md) | stays |
| **rollback** (2) | 🟡 Check out the previous version and rebuild. Images aren't tagged per version, so there is nothing to switch back to in one step. | [DEPLOY.md](DEPLOY.md) | stays |
| **Secrets** (2) | ✅ Everything secret is in `.env` on the server (`chmod 600`), never in the repo; `.env.example` lists the keys. | [.env.example](.env.example) | stays |

## Swapping the use case, file by file

Roughly two fifths of the code is the platform, one fifth mixes both, and
two fifths is the bike shop (lines of code, tests included):

| | Files | Share |
|---|---|---|
| **stays** | `api/database.py`, `timeutils.py`, `expose_api.py`; `api/middleware/*`; `api/services/` auth, billing, rate_limit, inference, errors; `api/router/` auth, billing; `scripts/create_staff.py`, `scripts/scheduler.py` (loop); `Dockerfile`, `docker-compose.yml`, nginx config; `frontend/Dockerfile`, `ui.py`, `pages/account.py`; `tests/conftest.py`, `test_s1_s2_platform.py` | ~40% |
| **adapt** | `api/main.py` (which routers), `api/config.py` (shop rules, token costs), `api/models/models.py` (platform tables stay, shop tables go), `frontend/api_client.py` (shop calls go), `frontend/app.py` (which pages) | ~20% |
| **replace** | `api/services/` pricing, rental, order, inventory; `api/router/` bike, rental, order, staff; `scripts/seed.py`; `frontend/pages/` catalogue, bike_detail, my_bookings, staff_*; the shop tests; `api/tools/` (LLM tools) | ~40% |

The same order as for BikeShop: write the new use case's SPEC §1–§7 first,
then replace the files in the last row.

## Using it in class

The ⬜ boxes are the checklist from chapter 8: "what does this prototype still
need before real users?" Each one is a line in the spec first, then a prompt.
For example, "add a nightly backup of the SQLite file to a second location" or
"add a privacy page".
