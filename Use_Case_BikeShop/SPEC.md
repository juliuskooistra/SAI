# BikeShop — specification

A small web app for a bike shop that sells bikes and rents them out. It is the
SAI1 use case that follows the deployment lecture ("From prototype to
production"). Students see a complete app, from domain logic to API to frontend to
deployment, and in a later session the app gets an LLM assistant that acts
through tools built on this API.

**Our job is the bare-minimum deployment stack**, shown end to end:

| piece | what |
|---|---|
| FastAPI | the backend (`api/`) |
| BFH inference | connection to BFH's LLM endpoint: config, client, reachability check (§8.1) |
| SQLite | the database, one file on a Docker volume |
| Static frontend | HTML, CSS and JavaScript in `frontend/`, served by FastAPI itself (§7) |
| VM + Docker | `docker compose` on a VM, behind the VM's nginx, which terminates HTTPS (§10.1) |
| or: Azure Container Apps | pay per use, scales to zero; a student can deploy it with Azure for Students. SQLite survives through Litestream copying it to Azure Blob Storage (§10.2) |

This file is the contract. Change it first, then the code (spec-first). The
LLM features are **out of scope** here: we only connect to BFH inference
and guarantee an API that the colleague can wrap as tools (§8).

Status: draft, 2026-11-02.

Students get the **finished app as a worked example**: they read and run it,
they don't rebuild it. They can deploy their own copy to Azure (§10.2). The app is **English only** (UI, error messages,
docs). It runs as a lecturer's demo at <https://demo.sai1.airs.iadsf.ch>.
Students watch; they don't sign in to it.

---

## 1. Goals and non-goals

**Goals**

- Customers browse the bikes for sale and for rent, check availability and
  prices, book and cancel rentals, and reserve a bike to buy.
- Staff manage the inventory, the rental price list, pick-ups and returns, and
  sales.
- Same structure as `SAI/Use_Case_III/VoltagePredictor`, so students can put
  the two side by side: class-based FastAPI app, routers → services →
  SQLModel, three middlewares (authentication, rate limiting, token billing),
  and a Dockerfile. The frontend is a static site served by FastAPI instead of the generated React app.
- Deployed on a VM and reachable over HTTPS.
- The deployed API can reach BFH inference, and `/health` shows whether it can.

**Non-goals**

- LLM features, prompts, tool definitions, agent loop (colleague, later).
  Nothing in the app calls the model except the reachability check.
- Real payments. Rentals and sales are paid at the counter; the app records
  prices only. The **token** billing is for API usage, as in VoltagePredictor,
  and has nothing to do with bike prices (§5.6).
- Multiple shops/branches, repairs/servicing workflow, accessories, delivery.
- Password reset, magic links.

## 2. Structure

Mirrors `Use_Case_III/VoltagePredictor` file for file; new files are marked ✚.

```text
Use_Case_BikeShop/              (in github.com/juliuskooistra/SAI)
├── SPEC.md                      ✚ this file (the contract)
├── MAP.md                       ✚ the app on the lecture's final map: which boxes it has, where
├── CLAUDE.md                    ✚ instructions for Claude: spec-first, how to run, house rules
├── README.md                    setup, run, invoke, deploy (like VoltagePredictor)
├── BACKEND.md                   docker build/run/logs
├── FRONTEND.md                  how the frontend was generated (the prompt), how it's served
├── MIDDLEWARE_ARCHITECTURE.md   the three middlewares, protection matrix
├── DEPLOY.md                    ✚ VM from zero to HTTPS, step by step (§10.1)
├── DEPLOY-azure.md              ✚ Azure Container Apps for students, step by step (§10.2)
├── Dockerfile                   the API image (also carries Litestream)
├── litestream.yml               ✚ where Litestream copies the SQLite file (§10.2)
├── docker-compose.yml           ✚ api + worker, one volume, port on 127.0.0.1 only
├── deploy/nginx/demo.sai1.airs.iadsf.ch.conf  ✚ the VM's nginx site (one host, path routing)
├── deploy/azure/compose.azurite.yml  ✚ the Azure set-up on your laptop, with a local Blob Storage (Azurite)
├── .env.example                 ✚ every setting, no secrets (the real .env stays on the VM)
├── requirements.in              ✚ direct deps; requirements.txt is compiled from it with uv
├── requirements.txt
├── api/
│   ├── __init__.py
│   ├── main.py                  class BikeShopAPI (≙ PeakVoltageAPI)
│   ├── expose_api.py            app = BikeShopAPI().app (uvicorn target)
│   ├── database.py              SQLModel engine, get_db, init_database
│   ├── config.py                ✚ shop rules: opening hours, limits, token costs
│   ├── timeutils.py             ✚ UTC ↔ Europe/Zurich, one place for "now" (tests freeze it)
│   ├── models/models.py         SQLModel tables + Pydantic request/response models
│   ├── middleware/
│   │   ├── auth_middleware.py          (copied, + sets request.state.role)
│   │   ├── rate_limit_middleware.py    (copied)
│   │   └── billing_middleware.py       (copied, new cost map)
│   ├── router/
│   │   ├── auth_router.py       (copied)
│   │   ├── billing_router.py    (copied)
│   │   ├── bike_router.py       ✚ catalogue + rental rates   (≙ peak_voltage_router)
│   │   ├── rental_router.py     ✚ availability, quotes, bookings
│   │   ├── order_router.py      ✚ buying a bike
│   │   └── staff_router.py      ✚ inventory, prices, pick-up/return, sales
│   ├── jobqueue/                ✚ the job queue + handlers (§5.8, adapted from AI Beacon)
│   ├── mail/                    ✚ Mailgun + logging mailer (§5.9, copied from kooistra-mailer)
│   ├── content/                 ✚ help + legal pages from markdown (§6, copied from kooistra-web)
│   ├── observability.py         ✚ JSON logs + Prometheus metrics (§10.3, copied from kooistra-logging)
│   ├── services/
│   │   ├── auth_service.py      (copied)
│   │   ├── rate_limit_service.py(copied)
│   │   ├── billing_service.py   (copied)
│   │   ├── inventory_service.py ✚
│   │   ├── pricing_service.py   ✚ pure functions, no DB
│   │   ├── rental_service.py    ✚
│   │   ├── order_service.py     ✚
│   │   └── inference_service.py ✚ BFH inference client + ping (§8.1)
│   └── data/                    ✚ SQLite file lives here (Docker volume, gitignored)
├── scripts/                     ✚ (≙ CreditScorer/scripts)
│   ├── seed.py                  demo inventory, price list, demo accounts
│   ├── worker.py                ✚ the worker: runs queued jobs + the reservation expiry (§5.7, §5.8)
│   ├── start.sh                 ✚ container start: APP_MODE=api (VM) or all (Azure: restore, seed, Litestream, API + worker)
│   └── create_staff.py          promote/create a staff user
├── docs/help/, docs/legal/      ✚ markdown for /help and /legal/* (§6)
├── tests/                       ✚ pytest
└── frontend/                    ✚ static site, served by FastAPI under / (replaces front_end/ React app)
    ├── index.html               the one HTML page; JavaScript fills it in
    ├── styles.css
    └── js/
        ├── api.js               the only module that calls the API (≙ client/src/lib/api.ts)
        ├── app.js               sign-in, menu by role, hash routing
        ├── ui.js                formatting, messages, safe rendering
        └── pages/               one module per page (§7)
```

### Deviations from Use_Case_III (veto any of these)

| Change | Why |
|---|---|
| No `ml_models/`; the services hold business rules instead of a model | There is no ML in a bike shop. |
| Four domain routers instead of one | The domain has catalogue, rentals, sales and staff work. |
| `request.state.role` + a staff check | Two roles (customer, staff). |
| SQLite in `api/data/` on a Docker volume | In VoltagePredictor `auth_demo.db` sits in the image and is lost on every rebuild: the "data" chapter of the lecture. |
| `config.py` for shop rules | Opening hours and limits in one place, so the LLM later reads the same rules. |
| Tests in `tests/`, not `api/test_*.py` | So the tests stay out of the Docker image's import path. |
| `uv pip compile` / `uv pip sync` instead of `pip install` | Reproducible lock. The README shows the `uv` commands. |
| `operation_id` + descriptions on every endpoint | Needed for the LLM tools (§8). |
| Static HTML/JS served by FastAPI instead of React + Vite + Express | No build step, no second server or container. The browser keeps all page state, so a backend that scales to zero never breaks an open page. (Streamlit was used first and replaced on 2026-11-03, §12.) |
| `docker compose` behind nginx + certbot instead of a bare `docker run -p 8000:8000` | HTTPS and a real hostname, which the reference skips. The VM already runs nginx on 80/443 for its other sites, so Caddy is not used. |
| Settings from `.env` | BFH inference key, CORS origin and passwords stay off the repo. |

Not imported on purpose: the `kooistra-*` packages. Their code is **copied**
into the app where it helps (logging and metrics, mailer, help and legal
pages), with a note naming the source, so students can read the whole app
in one place. The copied markdown renderer brings one dependency, `markdown`.

## 3. Roles

| Role | Gets it by | Can |
|---|---|---|
| `customer` | `POST /auth/register` (default) | Browse, check availability, quote, book/cancel own rentals, reserve/cancel own orders, manage own API keys and tokens |
| `staff` | `scripts/create_staff.py` or seed | Everything a customer can, plus `/staff/*` |

There is no endpoint that grants staff, so customers cannot promote themselves.

## 4. Data model (`api/models/models.py`)

Copied unchanged from VoltagePredictor: `APIKey`, `APIUsage`,
`TokenTransaction`, `RateLimitState`. `User` is copied with one new field.
Times are stored in UTC. Business rules are checked in shop time,
**Europe/Zurich**. The API accepts ISO 8601 times; a time without an offset
is read as Zurich time. It returns times in Zurich time with the offset
(`2026-11-07T10:00:00+01:00`). Money is in CHF, stored as `Decimal` with 2
places.

### User (+1 field)

| field | type | notes |
|---|---|---|
| `role` | `str` | `customer` \| `staff`, default `customer` |

### Bike

One row per physical bike.

| field | type | notes |
|---|---|---|
| `id` | int PK | |
| `code` | str, unique | human id on the frame sticker, e.g. `R-EBIKE-03`, `S-ROAD-12` |
| `name` | str | e.g. "Flyer Upstreet 5" |
| `brand` | str | |
| `category` | enum | `city`, `ebike`, `mountain`, `road`, `gravel`, `kids`, `cargo` |
| `frame_size` | enum | `XS`, `S`, `M`, `L`, `XL` |
| `color` | str | |
| `year` | int | model year |
| `purpose` | enum | `rental` \| `sale`, fixed for a bike's life |
| `condition` | enum | `new` \| `used` (sale bikes; rental bikes are `used`) |
| `sale_price_chf` | Decimal \| null | required if `purpose = sale`, null otherwise |
| `status` | enum | see below |
| `description` | str | free text shown to customers |
| `created_at`, `updated_at` | datetime | |

`status` values:

- Rental bikes: `available` · `maintenance` · `retired`. Whether a rental bike
  is out right now is **derived** from its rentals, not stored.
- Sale bikes: `available` · `reserved` · `sold` · `retired`.

### RentalRate

The price list: one row per category.

| field | type | notes |
|---|---|---|
| `category` | enum PK | |
| `hourly_chf` | Decimal | > 0 |
| `daily_chf` | Decimal | > 0, ≤ 24 × hourly |
| `deposit_chf` | Decimal | ≥ 0, informational: taken and returned at the counter |
| `updated_at` | datetime | |

### Rental

| field | type | notes |
|---|---|---|
| `id` | int PK | |
| `bike_id` | FK Bike | must be `purpose = rental` |
| `user_id` | FK User | the customer |
| `start_at`, `end_at` | datetime (UTC) | planned period |
| `status` | enum | `booked` → `active` → `returned`; `booked` → `cancelled` |
| `hourly_chf`, `daily_chf` | Decimal | copy of the category's rates at booking time |
| `quoted_price_chf` | Decimal | price at booking time; stays fixed if the price list changes |
| `picked_up_at` | datetime \| null | set by staff |
| `returned_at` | datetime \| null | set by staff |
| `final_price_chf` | Decimal \| null | set on return (§5.3) |
| `created_at` | datetime | |

### Order

A customer reserves a sale bike, pays and collects it in the shop.

| field | type | notes |
|---|---|---|
| `id` | int PK | |
| `bike_id` | FK Bike | must be `purpose = sale` |
| `user_id` | FK User | |
| `price_chf` | Decimal | sale price at reservation time |
| `expires_at` | datetime | `created_at` + hold period (§5.7); shown to the customer |
| `status` | enum | `reserved` → `completed`; `reserved` → `cancelled`; `reserved` → `expired` (worker) |
| `created_at`, `closed_at` | datetime | |

### JobRun

One row per scheduled job: the job's last run, for `/health` and the staff
board.

| field | type | notes |
|---|---|---|
| `name` | str PK | e.g. `expire-reservations` |
| `last_run_at` | datetime | |
| `last_ok` | bool | |
| `last_result` | str | e.g. "expired 2 orders", or the error |

### Job (table `job_queue`)

One unit of background work for the worker (§5.8).

| field | type | notes |
|---|---|---|
| `id` | int PK | |
| `kind` | str | `send_email`, `llm_task`, … (one handler per kind) |
| `payload` | JSON | the handler's input; no secrets. A `send_email` payload holds the recipient's address (personal data), which the API never returns |
| `status` | str | `queued` → `running` → `done` / `failed`; `running` → `queued` on retry |
| `attempts` | int | incremented at each claim; also the fencing token |
| `max_attempts` | int | default 3 |
| `run_after` | datetime | not claimed before this (retry back-off) |
| `user_id` | str \| null | owner, for `GET /api/jobs/{id}`; null for system jobs |
| `worker_id` | str \| null | which worker holds it |
| `heartbeat_at` | datetime \| null | refreshed while running |
| `enqueued_at`, `started_at`, `finished_at` | datetime | |
| `result` | JSON \| null | the handler's output |
| `error` | str \| null | last error, at most 2,000 characters |

### AnalyticsEvent

Anonymous product analytics (§5.10): **no user id, no IP, no time of day**.

| field | type | notes |
|---|---|---|
| `id` | int PK | |
| `day` | date | Zurich date |
| `name` | str | `catalogue_view`, `bike_view`, `quote`, `booking`, `reservation` |
| `bike_id` | int \| null | for bike-related events |
| `category` | str \| null | the bike's category |

## 5. Business rules

Constants live in `api/config.py`. The values below are the defaults.

### 5.1 Opening hours

| day | hours |
|---|---|
| Mon–Fri | 09:00–18:30 |
| Sat | 09:00–16:00 |
| Sun, Swiss public holidays | closed (holidays: a fixed list in `config.py`, from Christmas 2025 on, so the invented past year in §9.1 follows the same rules) |

A rental's `start_at` (pick-up) and `end_at` (return) must each fall within
opening hours. The bike may be out overnight and on closed days.

### 5.2 Rental period

- `start_at` is in the future, at most **60 days** ahead.
- `end_at > start_at`, duration **≥ 1 hour** and **≤ 14 days**.
- Times are on a 15-minute grid (…:00, :15, :30, :45). Other times are rejected.

### 5.3 Price (`pricing_service.py`, pure functions)

```
hours = ceil(duration in hours)          # every started hour counts
days, rest = divmod(hours, 24)
price = days × daily + min(rest × hourly, daily)
```

The daily rate caps every 24-hour block. Examples, with city bike = 8/h and
35/day:

| duration | price |
|---|---|
| 1 h | 8.00 |
| 3 h | 24.00 |
| 5 h | 35.00 (capped) |
| 26 h | 35 + 16 = 51.00 |
| 3 days | 105.00 |

- **Quote and booking** use the price list at that moment. The booking
  stores the rates (`hourly_chf`, `daily_chf`) and the price
  (`quoted_price_chf`).
- **On return**: `final = price(start_at, max(end_at, returned_at))` at the
  rates stored on the rental. Returning early gives no refund. Returning late
  is charged at the same rates.

### 5.4 Availability

A rental bike is available for `[start, end)` when:

1. `purpose = rental` and `status = available`, and
2. no rental of that bike in status `booked` or `active` overlaps:
   `other.start_at < end AND start < other.end_at`.

An `active` rental past its `end_at` (overdue) still blocks the bike until it
is returned.

Booking checks availability and inserts the rental **in one transaction**
(SQLite: `BEGIN IMMEDIATE`, so a second writer waits), so two customers
cannot book the same bike for overlapping times.

### 5.5 Rental and order lifecycle

| action | who | allowed when | effect |
|---|---|---|---|
| book | customer | bike available (§5.4), rules §5.1–5.2 hold | rental `booked` |
| cancel rental | owner | `booked` and `now < start_at` | `cancelled`, free |
| cancel rental | staff | `booked` | `cancelled` |
| pick up | staff | `booked`, today is the start date | `active`, `picked_up_at = now` |
| return | staff | `active` | `returned`, `returned_at = now`, `final_price_chf` |
| reserve | customer | sale bike `available` | order `reserved`, bike `reserved` |
| cancel order | owner or staff | `reserved` | order `cancelled`, bike `available` |
| complete order | staff | `reserved` | order `completed`, bike `sold` |
| expire order | worker | `reserved` and `now ≥ expires_at` | order `expired`, bike `available` (§5.7) |
| set maintenance | staff | rental bike | existing `booked` rentals stay; staff see them flagged as "at risk" |
| retire | staff | no `booked`/`active` rental, no `reserved` order | `retired`, hidden from customers |

A customer can hold at most **3** `booked`/`active` rentals and **2**
`reserved` orders at once.

### 5.6 Tokens (API usage billing, copied from VoltagePredictor)

Every user starts with 100 tokens (the seeded demo accounts get 10,000, so the
demo never runs dry). Each successful call to `/api/*` costs tokens
(the cost map is in `config.py`). Failed calls (non-2xx) cost nothing. When the
balance is too low, the call returns 402 with the balance in the message. Tokens
are bought through `/billing/purchase-tokens`, as in VoltagePredictor (no real
payment). `/auth/*`, `/billing/*` and `/staff/*` are free.

| call | tokens |
|---|---|
| any read (`GET /api/*`) | 1 |
| `POST /api/rentals/quote` | 1 |
| `POST /api/rentals`, `POST /api/orders` | 5 |
| cancel | 0 |

### 5.7 Reservation expiry (the scheduled job)

A reserved sale bike is held for **7 days** (`ORDER_HOLD_DAYS` in
`config.py`). After that the worker releases it. This is the app's
example of a scheduled job, like StudyBuddy's weekly email in the lecture.

- **Its own process.** The job runs in the **worker** (§5.8), a separate
  process (`python -m scripts.worker`; its own container on the VM), not
  inside the API. The API runs 4 uvicorn workers, so a loop inside it would
  run 4 times. (Until 2026-11-03 this was a separate `scheduler` process.)
- **Every 15 minutes** (`EXPIRE_EVERY_MINUTES`), plus once at start-up, so
  missed runs are made up after a restart.
- **Safe to run twice.** One conditional update per order
  (`… WHERE status = 'reserved' AND expires_at <= now`) changes the order and
  frees the bike in the same transaction. A second run, or a staff action at
  the same moment, finds nothing left to do.
- **Leaves a trace.** Each run writes `JobRun` (time, ok, result) and one log
  line. A failing run logs the error and the loop carries on.
- **Visible.** `/health` shows the job's last run (§8.1), the staff board
  shows "expires in …" per order, and customers see the hold date on their
  order.

### 5.8 Background jobs: the queue and the worker

Slow or failure-prone work (sending email now, LLM calls later) doesn't run
inside the request that triggers it. The request **enqueues a job**; the
**worker** runs it. Adapted from AI Beacon's Postgres job queue, for SQLite.

- **Enqueue in the same transaction** as the change that causes it: a
  booking and its confirmation email commit together, or neither does.
- **Claim**: the worker takes the oldest `queued` job whose `run_after` has
  passed, in one `BEGIN IMMEDIATE` transaction (SQLite has no
  `FOR UPDATE SKIP LOCKED`; the write lock does the same job). It sets
  `running`, `attempts + 1`, `worker_id`, `heartbeat_at`, `started_at`.
- **Fencing**: every later write about a claimed job matches
  `(id, attempts, status='running')`. If the job was requeued meanwhile, the
  write changes nothing and the worker drops it.
- **Heartbeat** every 15 s while a job runs. **Reaper**: a `running` job
  whose heartbeat is older than 120 s (its worker died) goes back to
  `queued` if it has attempts left, else `failed`.
- **Failure**: the error is stored (≤ 2,000 chars); with attempts left the
  job is requeued with `run_after = now + 30 s × attempts`, else `failed`.
- **Handlers** are registered per `kind`. A job whose kind has no handler
  fails at once with "No handler for job kind '…'".
- **One worker process** (poll every 2 s, `WORKER_POLL_SECONDS`). It also
  runs the reservation expiry every 15 minutes (§5.7). More workers would
  be safe: the claim is atomic.
- **Visible**: `/health` gets `worker` (when it last polled) and `queue`
  (counts by status); staff see recent jobs at `GET /staff/jobs`; a user
  sees their own job at `GET /api/jobs/{id}` (§6).

### 5.9 Notifications by email

Sent by the worker (`send_email` jobs), never inside a request.

| event | to | when |
|---|---|---|
| Booking confirmed | the customer | `book_rental` succeeds |
| Bike reserved, held until … | the customer | `reserve_bike` succeeds |
| Reservation expired | the customer | the worker expires it (§5.7) |

- **Mailgun, EU**: `MAILGUN_API_KEY` + `MAILGUN_DOMAIN` (`mail.kooistra.ch`),
  base URL `https://api.eu.mailgun.net/v3` (the US endpoint answers 401 for
  an EU domain), sender `MAIL_FROM` (`BikeShop <bikeshop@mail.kooistra.ch>`).
  Without credentials the **logging mailer** writes the email to the log and
  sends nothing (local development): it logs the recipient's domain and the
  subject, like every other log line about email.
- **`.test` addresses are skipped** (the seeded demo accounts, RFC 2606: never
  deliverable): the job finishes with result `skipped`.
- Plain text plus a simple HTML version, English. Logs record recipient
  domain and subject, never the body or the full address.
- Copied from `kooistra-mailer` (Mailgun + logging backends, metrics), not
  imported (§2).

### 5.10 Product analytics

First-party and anonymous, so it fits nDSG without cookies or consent.

- Recorded **server-side** in the routers, one `AnalyticsEvent` per
  successful `search_bikes` (`catalogue_view`), `get_bike` (`bike_view`),
  `quote_rental` (`quote`), `book_rental` (`booking`), `reserve_bike`
  (`reservation`). No user id, no IP, only the day. The frontend sends
  nothing extra.
- Recording never breaks a request: an error is logged and ignored.
- Staff see `GET /staff/analytics?days=30`: counts per day and event (days
  without events included), totals, the 10 most-viewed bikes, and the
  quote → booking rate = bookings ÷ quotes (`null` without quotes). The bike
  page asks for a fresh quote whenever the times change, so the rate reads
  low; the analytics page says so. `catalogue_view` has no bike and no
  category.
- Kept for 365 days; the worker deletes older events once a day.

## 6. API

Same mounting as VoltagePredictor. The docs are Scalar at `/docs`. Errors are
`{"detail": "<one sentence a customer would understand>"}`.

### Protection matrix

| prefix | auth (API key) | role | rate limit | billing |
|---|---|---|---|---|
| `/auth/*` (except key management) | – | – | – | – |
| `/billing/*` | ✓ | any | – | – |
| `/api/*` | ✓ | any | ✓ | ✓ |
| `/staff/*` | ✓ | staff (else 403) | – | – |
| `/docs`, `/openapi.json`, `/health` | – | – | – | – |
| `/help`, `/help/*`, `/legal/*` (HTML pages) | – | – | – | – |
| `/metrics` (§10.3) | – (never public: blocked by nginx, off on Azure) | – | – | – |
| `/` and frontend files (§7) | – | – | – | – |

### `/auth`, `/billing`

Copied from VoltagePredictor: register, login, `generate-key`, `my-keys`,
`revoke-key/{key_name}`; purchase tokens, balance, usage, rate-limit status.
The login response also returns `role`. Fixes to the copy, each noted in
`MIDDLEWARE_ARCHITECTURE.md`:

- `my-keys` and `revoke-key` need the caller's API key and act on the
  caller's own keys. In the reference, `my-keys` took any `user_id` from the
  body without auth, and `revoke-key` always returned 501.
- A successful billed call writes **one** `APIUsage` row. The reference
  wrote two (service + middleware), so the rate limiter counted every call
  twice.
- `my-keys` fills the response model's field names. The reference crashed on
  `api_key_name` vs `name`.
- Default rate limits are 60/minute, 1,000/hour, 5,000/day (`config.py`). The
  reference used 10/100/1,000, and a frontend demo hits 10 a minute by
  clicking around.

### `/api`: customers (`bike_router`, `rental_router`, `order_router`)

| method & path | operation_id | does |
|---|---|---|
| GET `/api/bikes` | `search_bikes` | filters: `purpose`, `category`, `frame_size`, `max_price_chf`, `condition`, `q` (text). Never shows `retired`, or `sold` bikes |
| GET `/api/bikes/{bike_id}` | `get_bike` | one bike, incl. its rental rate if a rental bike |
| GET `/api/rental-rates` | `list_rental_rates` | the price list |
| GET `/api/opening-hours` | `get_opening_hours` | weekly hours + upcoming closed days |
| GET `/api/availability` | `check_availability` | `start_at`, `end_at`, optional `category`, `frame_size` → available rental bikes, each with its quoted price |
| POST `/api/rentals/quote` | `quote_rental` | `{bike_id, start_at, end_at}` → price breakdown (hours, days, rates, total, deposit); books nothing |
| POST `/api/rentals` | `book_rental` | `{bike_id, start_at, end_at}` → rental |
| GET `/api/rentals` | `list_my_rentals` | own rentals, filter `status` |
| GET `/api/rentals/{rental_id}` | `get_my_rental` | own only (else 404) |
| POST `/api/rentals/{rental_id}/cancel` | `cancel_my_rental` | §5.5 |
| POST `/api/orders` | `reserve_bike` | `{bike_id}` → order |
| GET `/api/orders` | `list_my_orders` | own orders |
| POST `/api/orders/{order_id}/cancel` | `cancel_my_order` | §5.5 |
| GET `/api/jobs/{job_id}` | `get_my_job` | status, attempts, result, error of one of your jobs (else 404); for the LLM assistant later |

### `/staff` (`staff_router`)

| method & path | operation_id | does |
|---|---|---|
| GET `/staff/bikes` | `list_all_bikes` | every bike, retired and sold included |
| POST `/staff/bikes` | `create_bike` | add a bike |
| PATCH `/staff/bikes/{bike_id}` | `update_bike` | edit fields; status changes go through §5.5 |
| POST `/staff/bikes/{bike_id}/retire` | `retire_bike` | §5.5 |
| GET `/staff/inventory` | `inventory_summary` | counts by purpose × category × status; rental bikes out now; overdue rentals; at-risk bookings |
| PUT `/staff/rental-rates/{category}` | `set_rental_rate` | upsert a price; existing bookings keep their quote |
| GET `/staff/rentals` | `list_rentals` | all; filter `status`, `date`, `bike_id`, `user_id`, `overdue` |
| POST `/staff/rentals/{rental_id}/pickup` | `pickup_rental` | §5.5 |
| POST `/staff/rentals/{rental_id}/return` | `return_rental` | §5.5, returns the final price |
| POST `/staff/rentals/{rental_id}/cancel` | `staff_cancel_rental` | §5.5 |
| GET `/staff/orders` | `list_orders` | all; filter `status` |
| POST `/staff/orders/{order_id}/complete` | `complete_order` | §5.5 |
| POST `/staff/orders/{order_id}/cancel` | `staff_cancel_order` | §5.5 |
| GET `/staff/jobs` | `list_jobs` | recent jobs, filter `status`, `kind`; newest first, at most 100 |
| GET `/staff/analytics` | `analytics_summary` | §5.10; `days` 1–365, default 30 |

### Help and legal pages (HTML, not JSON)

| path | from |
|---|---|
| `/help`, `/help/<article>` | `docs/help/*.md` (`index.md` is the landing page) |
| `/legal/privacy` | `docs/legal/privacy-policy.md` |
| `/legal/terms` | `docs/legal/terms-of-service.md` |

Rendered server-side from markdown, no external assets, one same-origin
stylesheet; a route exists only if its file does. Copied from
`kooistra-web`'s `add_content_pages`. Operator on the legal pages: "BFH | W |
AIRS lab", contact julius.kooistra@bfh.ch; drafts from the kooistra legal
templates, pending review.

### Status codes

400 rule violated (opening hours, grid, duration) · 401 no or invalid key ·
402 not enough tokens · 403 not staff / not yours (for mutations) · 404 not
found or not yours (for reads) · 409 conflict (bike taken, wrong state, limit
reached) · 422 malformed input (FastAPI) · 429 rate limited.

## 7. Frontend (`frontend/`, static, served by FastAPI)

Replaces VoltagePredictor's React + Vite + Express app. It is generated the
same way: give the generator the OpenAPI spec from `/openapi.json` and a prompt,
and record the prompt in `FRONTEND.md`.

- **Plain HTML, CSS and JavaScript modules**: no framework, no build step,
  nothing loaded from other sites. Students can open any file and read it.
- **Served by FastAPI**: `main.py` mounts `frontend/` under `/` after all API
  routes, so `/` returns `index.html` and the API's prefixes keep priority.
  Page and API share one origin: no CORS, no second container or server.
- **Pages are hash routes** (`#/catalogue`, `#/bike/12`, `#/staff/board`, …).
  The part after `#` never reaches the server, so page names can't clash
  with API paths.
- **The browser keeps all state.** When the API scales to zero (Azure,
  §10.2), the page stays as it is; the next click just waits for the API to
  wake up. Any request that takes longer than 2 s shows "Waking up the shop,
  this can take up to 30 seconds"; requests give up after 60 s. While the
  server can't be reached (or answers 502/503/504), reads and other
  repeatable requests (GET, PUT, DELETE) are retried every 2 s within those
  60 s; POST and PATCH never are, so a booking can't be sent twice.
- **Talks to the API only through `js/api.js`**, with relative URLs
  (`/api/bikes`), the key as `Authorization: Bearer <key>`.
- **Sign-in**: the form sends username and password to `/auth/generate-key`
  (name `web-<random>`, expires in 1 day, one per tab, so logging out in one
  tab doesn't sign out another). The key, username and role are kept in
  `sessionStorage`: gone when the tab closes. Logout revokes the key.
- **Errors**: the API's `detail` is shown as it is. 401 sends the user back
  to sign-in; 402 (tokens) links to the Account page.
- **Shield**: text from the API is put on the page as text (`textContent`),
  never as HTML, so a bike named `<script>…` can't run code.

| page (hash route) | role |
|---|---|
| Sign in / register (`#/login`) | all |
| Catalogue: "Buy" and "Rent" tabs, filters (`#/catalogue`) | all |
| Bike detail: rent (date + times on the 15-min grid, live quote) or reserve (`#/bike/<id>`) | all |
| My rentals and orders, with cancel (`#/my`) | all |
| Account: API keys, token balance, buy tokens, usage (`#/account`) | all |
| Staff: today's board: pick-ups, returns, overdue, at risk (`#/staff/board`) | staff |
| Staff: inventory table + add/edit/retire bike (`#/staff/inventory`) | staff |
| Staff: price list editor (`#/staff/prices`) | staff |
| Staff: orders to complete or cancel (`#/staff/orders`) | staff |
| Staff: analytics: per day, top bikes, quote → booking (`#/staff/analytics`) | staff |
| Staff: background jobs: status, attempts, errors (`#/staff/jobs`) | staff |

Every page has a footer with **Help · Privacy · Terms**, linking to the
server-rendered pages (§6).

The frontend hides staff pages from customers, but the API enforces the
roles; hiding a page is not access control.

## 8. BFH inference and readiness for LLM tools (contract with the colleague)

### 8.1 BFH inference connection (ours)

BFH inference is an HTTPS LLM endpoint. The app calls it; nothing runs on it.
We build only the connection, not any feature that uses it.

- **Service**: MLMP inference (docs: <https://infra.pages.ti.bfh.ch/mlmp/src/llm/>),
  OpenAI-compatible. The demo VM is **outside the BFH network**, so the app
  uses the proxy:

  | setting (`.env`) | value |
  |---|---|
  | `MLMP_BASE_URL` | `https://inference.proxy.ti.bfh.ch/v1`. Not `/api/v1` as in the docs' SDK examples: on the proxy that path returns 404 (checked from the demo VM, 2026-11-02) |
  | `MLMP_API_KEY` | the lecturer's own MLMP key (<https://access.mlmp.ti.bfh.ch>). Keys **expire after 180 days**, and then `check()` reports `unauthorized`. `.env.example` has a comment line for the date the key was created |
  | `MLMP_MODEL` | default `gpt-oss:120b` (the colleague may change it). The exact id has to match what `/v1/models` lists |

  `MLMP_BASE_URL` defaults to the proxy and `MLMP_MODEL` to `gpt-oss:120b`. Without
  `MLMP_API_KEY` the app still starts and reports `not_configured`.
- **Limits** are per MLMP user: 2 concurrent requests, 30 requests per minute,
  150k tokens per minute. That is enough because the app is a lecturer's demo,
  and students don't call it themselves (§8.2).
- **`services/inference_service.py`**:
  - `get_client()` returns a configured OpenAI-compatible client (`openai`
    package, `base_url` + key), which the colleague's tools use.
  - `check()` lists the models (`GET {base}/models`, 5 s timeout, **no
    tokens spent**) and returns one of `ok`, `unreachable`, `unauthorized`,
    `model_missing` or `not_configured`. The result is cached for 60 s, so
    health checks don't hit the endpoint every time.
- **`GET /health`** → `{"status": "ok", "database": "ok", "inference": "<check()>",
  "scheduler": {"last_run_at": "…", "last_ok": true}}`.
  It returns 200 whenever the API itself is up. A down LLM endpoint must not
  make the shop look dead, because nothing in the shop needs it yet.
- The key is never logged and never returned by any endpoint.
- Not adopted: `kooistra-llm`'s `ModelGuard` does the same check with metrics.
  It is left out so students can read every line (§2).

### 8.2 What the colleague can count on

Nothing here is LLM code.

1. Every endpoint has a stable `operation_id` (the tables in §6), a one-line
   `summary`, a `description` that says when to use it, and request/response
   models whose fields have `description` and `examples`. The OpenAPI spec at
   `/openapi.json` is enough to generate tool definitions.
2. Error `detail`s are sentences that can be shown to a customer as they are
   ("This bike is already booked from 14:00 to 17:00 on 8 Nov.").
3. Services are callable without HTTP. They take a `Session` and plain
   arguments and never read a `Request`, so tools can call them in-process or
   over HTTP with an API key.
4. `quote_rental` and `check_availability` have no side effects, so an agent
   can call them freely. Only `book_rental`, `cancel_*`, `reserve_bike` and the
   staff mutations change state.
5. An agent acting for a customer uses that customer's API key, so roles, rate
   limits and token costs apply to it as to any client.
6. MLMP rules the colleague's prompts must respect: **no personal data**
   ("Do not upload sensitive or personal data"), so customer names, emails and
   usernames stay out of prompts. Tools return bikes, prices and rentals by id.
   The demo key allows 2 concurrent requests and 30 per minute. That is
   enough for one lecturer demoing, but the assistant should still show a
   clear "busy, try again" on 429 instead of failing. MLMP runs best-effort with no SLA; status:
   <https://kuma.monitor.ti.bfh.ch/status/mlmp-inference>.
7. **Slow LLM work goes through the queue** (§5.8): register a handler for
   `llm_task` in `api/tools/` (or a new kind), enqueue it from an endpoint,
   and let the frontend poll `GET /api/jobs/{id}` for the result. The single
   worker runs one job at a time, which also keeps MLMP's limit of 2
   concurrent requests. Until a handler exists, `llm_task` jobs fail with
   "No handler for job kind 'llm_task'".
8. **Data for development**: the deployed database is a SQLite file inside
   the container, with no port to connect to. Develop against a local copy
   (`scripts.seed`, then `scripts.seed_history`: the same year of data, §9.1),
   and test against the deployed app through its API with a staff API key.
   Nobody writes to the deployed file from outside the app (Litestream
   expects one writer).

## 9. Seed data (`scripts/seed.py`)

The script is idempotent: it creates only what is missing and leaves existing rows alone.

- Price list for all 7 categories, e.g. city 8/35, ebike 15/65, mountain
  12/50, road 12/50, gravel 12/50, kids 5/20, cargo 18/75 (CHF hourly/daily).
- About 20 rental bikes across categories and sizes, including 1 in `maintenance`.
- About 15 sale bikes, new and used, CHF 400–6000.
- Accounts `staff@bikeshop.test` (staff) and `customer@bikeshop.test`
  (customer). Passwords come from env vars, not the repo.
- An `admin` account (staff role) when `ADMIN_PASSWORD` is set, so every
  deployment (VM, Azure, local) has one without a manual step. "Admin" is
  the staff role; there is no separate admin role (§3).
- A few rentals in the past and future, including one overdue, so the staff board
  isn't empty, and one reserved order that expires within a day. Most of
  these belong to two walk-in customers (`lena`, `marco`, random passwords
  nobody knows), so the demo customer starts well below its limits (3 open
  rentals, 2 reservations) and can book live.
- Demo accounts get 10,000 API tokens.
- Re-running adds only missing bikes, rates and users. Rentals and orders are
  seeded only into an empty database.

### 9.1 A year of past usage (`scripts/seed_history.py`)

Invented history, so the analytics, and later the management agents (fleet
investments, spare parts), have a year of data to work with. It is a separate
script, run by hand after the seed: `python -m scripts.seed_history`.

- **Period**: the 365 days up to yesterday (Zurich), counted from the day the
  script runs. A fixed random seed, so the same day gives the same data.
- **Only existing tables**: `User`, `Rental`, `Order`, `Bike`,
  `AnalyticsEvent`. No new columns.
  - 120 invented customers `guest001` … `guest120` (`@bikeshop.test`, one
    random password nobody knows). A few of them rent often, most once or
    twice. Each one's `created_at` is just before their first booking.
  - About 25 sale bikes sold during the year (status `sold`), each with its
    `completed` order, some after an earlier reservation that expired.
  - Seeded bikes get a past `created_at`: the rental fleet from before the
    period, each sale bike from the day it was listed (P7).
- **Rentals follow the business rules**: pick-up and return within opening
  hours on open days (§5.1), on the 15-minute grid, 1 hour to 14 days
  (§5.2), no overlap with another non-cancelled rental of the same bike,
  including rentals already in the database (§5.4). Each stores the category's
  rates on the day it was booked and the quoted price; returned rentals get
  `picked_up_at`, `returned_at` and the final price (§5.3), and some are
  returned late. About 7% are `cancelled` (never picked up). All of them end
  before today, so today's board, availability and limits don't change.
- **Analytics agree with the rentals**: one `booking` event per rental on the
  day it was booked, one `reservation` per order on the day it was made.
  Quotes, bike views and catalogue views are invented around them. Nothing
  is older than 365 days.
- **Run once**: if `guest001` exists, the script does nothing.
- **Into a deployed app**: by hand, inside the running container
  (`az containerapp exec`, then `python -m scripts.seed_history`), staging
  first. Not part of `SEED_ON_START`: the dates count from the day it runs,
  so the lecturer picks that day. Litestream copies the new rows like any
  other write.

**Planted patterns.** This is the answer key: an analysis, by staff or
by an agent, should find these. P8 is a red herring.

| # | pattern | where it shows |
|---|---|---|
| P1 | Season: April–September busy, December–February quiet; Saturdays about twice a weekday | rentals and events per day |
| P2 | The two e-bikes in size L (`R-EBIKE-02`, `R-EBIKE-05`) are rented almost every Saturday from May to September. On those weekends many e-bike quotes don't become bookings: demand is turned away | rentals per bike and weekday, quotes vs bookings |
| P3 | Cargo bikes are rarely rented, and then mostly for several days | rentals per bike, duration |
| P4 | Kids' bikes are rented almost only in school holidays | rentals per week |
| P5 | E-bike prices went up on 1 June (14/60 → 15/65 CHF hourly/daily), and bookings did not drop | `hourly_chf` / `daily_chf` on rentals, bookings per week |
| P6 | Gravel is growing: its share of all rentals roughly doubles over the year | rentals per category and month |
| P7 | Sales: new e-bikes and used city, mountain and kids' bikes under CHF 700 sell within two weeks; used road bikes take two to four months. The Stromer ST5 (`S-EBIKE-03`, CHF 5,990) has been listed for 100 days, is viewed often and never reserved. The used road bike `S-ROAD-02` has been listed for 140 days, and two reservations expired | orders, bike `created_at`, bike views |
| P8 | One day in April has six times the usual catalogue views (a newspaper article), with no extra bookings | `catalogue_view` per day |

## 10. Deployment

**The demo runs on Azure (§10.2)** at <https://demo.sai1.airs.iadsf.ch>
(decided 2026-11-03). §10.1 stays as the documented alternative for anyone
with a VM; the app runs the same on both.

### 10.1 Docker behind nginx on a VM (alternative)

The app runs on an Ubuntu VM that already serves other sites. Its nginx holds
ports 80/443 and serves each site from `/etc/nginx/conf.d/<host>.conf`, with
one certbot certificate per hostname. BikeShop follows that convention. The
app runs in Docker Compose, and nginx proxies to it. (The demo VM's own
runbook, with its host details, is kept privately, outside this repo.)

```text
                       https://demo.sai1.airs.iadsf.ch
internet ─443─► nginx (host, certbot TLS) ──► 127.0.0.1:8130 → api:8000 (FastAPI: API + static frontend)

api, worker ─► volume bikeshop-data → /app/api/data/bikeshop.db
api            ─► https://inference.proxy.ti.bfh.ch/v1 (outbound)
```

- **One hostname, one upstream**: `demo.sai1.airs.iadsf.ch` (DNS A record →
  the VM's IP). nginx passes everything to FastAPI, which serves both the
  API and the frontend (§7): one origin, one certificate, no CORS.
- **API image**: `Dockerfile` as in VoltagePredictor (`python:3.12-slim`,
  `uvicorn api.expose_api:app --workers 4`), installing from the uv-compiled
  `requirements.txt`. The image also carries `frontend/`.
- **`docker-compose.yml`**: services `api` and `worker` (same image as
  `api`, command `python -m scripts.worker`, no ports), both with
  `restart: unless-stopped`. The port is published **on 127.0.0.1 only**
  (`127.0.0.1:8130:8000`). Docker's port publishing
  bypasses `ufw`, so `8130:8000` without the address would put the bare API
  on the internet. One volume, `bikeshop-data`, holds SQLite and is shared by
  `api` and `worker`.
- **nginx** (`deploy/nginx/demo.sai1.airs.iadsf.ch.conf`, copied to
  `/etc/nginx/conf.d/`; on a VM whose `nginx.conf` names every site instead of
  including `conf.d/*.conf`, also an explicit `include` line): one `server`
  block with one `location /`, proxied to 8130 with `X-Forwarded-*` headers.
  Certificate: `sudo certbot --nginx -d demo.sai1.airs.iadsf.ch`, following
  the one-certificate-per-host convention. `sudo nginx -t` must pass before every reload, because a broken
  config takes down every site on the VM.
- **SQLite under 4 workers**: `database.py` turns on WAL mode and a 5 s
  `busy_timeout`, so concurrent requests wait instead of failing with
  "database is locked".
- **Settings**: everything comes from `.env` next to `docker-compose.yml` on the VM
  (`.env.example` in the repo lists every key): `CORS_ORIGINS`
  (`https://demo.sai1.airs.iadsf.ch`), BFH inference (§8.1),
  seed passwords. The file has `chmod 600`.
- **Disk** (precondition): Docker Engine plus both images need about
  1.5 GB; have at least **3 GB** free before installing. Docker's container logs
  are capped in `/etc/docker/daemon.json` (`json-file`, `max-size 10m`,
  `max-file 3`), and every deploy ends with `docker image prune -f`.
- **Seeding**: `docker compose exec api python -m scripts.seed`.
- **Getting the code there**: `git clone` of this repository (public, HTTPS,
  no deploy key needed) to `/opt/sai`; the app is `Use_Case_BikeShop/`.
- **Updating**: `git pull`, then `docker compose up -d --build && docker image prune -f`.
  The data survives because it lives on the volume.
- **`DEPLOY.md`**: the runbook. It covers the disk check/cleanup, installing
  Docker Engine + compose plugin from Docker's apt repo (with log caps),
  DNS, cloning to `/opt/sai`, `.env`, `docker compose up -d`, the nginx
  site + `nginx -t` + reload, certbot, seeding, and checking `/health`.
- Not in this spec: adding BikeShop to the VM's monitoring.

### 10.2 Azure Container Apps with Litestream (pay per use)

So students can deploy their own copy without a VM: **Azure Container Apps**
on the Consumption plan (billed per second, scales to zero, free monthly
allowance), paid from **Azure for Students** ($100 credit, no credit card).

Containers on Container Apps keep no files: when the app scales to zero or
is redeployed, its disk is gone. SQLite stays, and **Litestream** keeps it:

```text
browser ─HTTPS─► bikeshop (one container app, 0–1 instances)
                   │  Litestream ── restore on start
                   │   ├─ uvicorn (API + static frontend)   ── copies every change,
                   │   └─ worker                            ~1 s later ──► Azure Blob Storage
                   └─► BFH inference (MLMP)                      (container "litestream")
```

- **One container app**, `bikeshop`, runs the API image with
  `APP_MODE=all`. It serves the API and the frontend at one
  `https://bikeshop.<env>.<region>.azurecontainerapps.io` address with a
  certificate from Azure. No nginx needed.
- **A classic Consumption environment** (`--environment-mode
  ConsumptionOnly`), not the "Express" type the CLI picks by default. Express
  can't take a custom domain, ignores a longer scale-down delay, and can't
  pull images with a managed identity (all found 2026-11-03). Same pay-per-use
  pricing; logs go to a Log Analytics workspace.
- **Custom domain**: `demo.sai1.airs.iadsf.ch` is a CNAME to the app's
  address, plus a TXT record `asuid.demo.sai1` with the environment's
  verification ID; Azure issues and renews a free managed certificate
  (from DigiCert). A CAA record `sai1.airs.iadsf.ch CAA 0 issue
  "digicert.com"` is needed: without it, certificate authorities climb to
  `airs.iadsf.ch`, whose CAA records (set by Vercel) don't allow DigiCert,
  and the certificate stays "Pending" (found 2026-11-03).
- **Staging**: a second app, `bikeshop-staging`, in the same environment, at
  `staging.sai1.airs.iadsf.ch` (CNAME + `asuid.staging.sai1` TXT). Same
  image, its own data: `LITESTREAM_PATH=bikeshop-staging` (production uses
  the default `bikeshop`; two apps on one path would overwrite each other's
  database), fresh seed data, no Mailgun key (emails go to the log).
  **Release flow**: push image `:N` → update staging to `:N` → check
  (`/health`, a booking) → update production to the same `:N`. Production only
  ever gets an image that ran on staging; rollback is updating back to
  `:N-1`.
- **`scripts/start.sh` with `APP_MODE=all`** does, in order:
  1. `litestream restore` the database from Blob Storage, if a copy exists
     and the local file doesn't;
  2. seed if `SEED_ON_START=1` (idempotent, so a restored database is left
     as it is);
  3. `litestream replicate -exec …`, which runs uvicorn and the worker
     as its child processes and copies every change to Blob Storage about
     once a second. If the API stops, Litestream stops too, so the container
     restarts as a whole.
  With `APP_MODE=api` (the default) it starts uvicorn as before, so the VM
  set-up in §10.1 doesn't change.
- **Exactly one instance** of `bikeshop` (min 0, max 1). Two instances
  would each restore and then overwrite each other's copy. The API runs 2
  uvicorn workers (`UVICORN_WORKERS=2`) on 0.5 vCPU / 1 GiB.
- **The app scales to zero after 1 hour without requests**
  (`cooldownPeriod` 3600 s, set with a PATCH on the app; the CLI has no flag
  for it). A class doesn't lose it mid-session; overnight it costs nothing.
  When it does wake, the static frontend keeps working in the browser and
  the next click waits (10–30 s, "Waking up the shop…"). With Streamlit, an
  open tab broke instead, which is why the frontend was replaced (§12).
- **The worker only runs while the app is awake.** When the app wakes
  up, the worker's start-up run makes up for the expiries it missed (§5.7).
  `/health` shows when it last ran.
- **Data loss window**: what was written in the last ~1 s before a crash.
  During a redeploy Azure starts the new revision before stopping the old
  one; a write in those few seconds can be lost. For the demo that's
  acceptable; the runbook says so.
- **Region**: Switzerland North (data in Switzerland). Storage account and
  apps in the same region.
- **Secrets** are Container Apps secrets, referenced from environment
  variables: `MLMP_API_KEY`, `API_KEY_SECRET`, `LITESTREAM_AZURE_ACCOUNT_KEY`,
  the seed passwords, `ADMIN_PASSWORD`. Nothing secret in the image.
- **Images** are built on the student's laptop with
  `docker buildx --platform linux/amd64` and pushed to the registry. Azure for
  Students blocks building in Azure (ACR Tasks), found on the first real run
  (2026-11-03). Container apps pull with the registry's admin credentials.
- **Allowed regions** on Azure for Students (policy, 2026-11-03):
  Switzerland North, France Central, Italy North, Austria East, Belgium
  Central. West Europe is not allowed.
- **Cost**: Container Apps stays within the free monthly allowance when the
  demo is idle most of the time; Blob Storage costs cents. The container
  registry (ACR Basic) costs about $5 a month even when idle, so the runbook
  ends with deleting the resource group. Azure for Students stops the
  subscription when the credit runs out; it never charges a card.
- **Locally**: `deploy/azure/compose.azurite.yml` runs the same set-up with
  Azurite, Microsoft's local Blob Storage emulator, so the restore can be
  tried without an Azure account.
- **`DEPLOY-azure.md`**: the runbook for students, with `az` commands from
  an empty subscription to a working URL, and how to tear it down.

### 10.3 Logs, metrics, monitoring

- **JSON logs** to stdout, one line per event (`ts`, `level`, `service`,
  `logger`, `msg`, extra fields; tracebacks folded into one line), from the
  API and the worker. Copied from `kooistra-logging`.
- **`/metrics`** in Prometheus format. Counted in the API:
  `http_requests_total{handler,method,status}` and
  `http_request_duration_seconds` (status grouped `2xx`…`5xx`, `handler` the
  route template, `frontend` for static files). **Read from the database at
  scrape time**, because on the VM the worker is its own container and its
  counters would never reach the API: `job_queue_jobs{kind,status}` (email
  outcomes are `kind="send_email"`), and from `JobRun`
  `job_last_run_timestamp_seconds{job}`, `job_last_run_ok{job}` and
  `job_last_success_timestamp_seconds{job}` (the kooistra-jobs name, so its
  staleness alert fits).
- **Several API processes**: the 4 uvicorn workers write to
  `PROMETHEUS_MULTIPROC_DIR` (cleared at container start), so `/metrics`
  shows one total, not one worker's share. Without it every counter is
  wrong (found on other services, 2026-10-23).
- **Never public.** On a VM the public nginx site answers 404 for
  `/metrics` and Prometheus scrapes it over a private link. On Azure
  `METRICS_ENABLED=0` removes the route: a scraper polling a public URL every
  few seconds would also keep the app from ever scaling to zero.
- **On Azure (the demo)**: the JSON log lines go to the environment's Log
  Analytics workspace, where they can be queried (exceptions, job outcomes,
  emails); Azure records requests, response codes, restarts and replica
  counts per app on its own.
- **Alerts on Azure: Azure Monitor**, emailing the lecturer
  (julius.kooistra@bfh.ch) through one action group. Rules on production:
  any 5xx responses in 5 minutes; container restarts; log lines with an
  exception in 15 minutes; jobs that failed for good (`outcome: failed`) in
  15 minutes. No "worker stale" rule: while the app sleeps (scale to zero)
  the worker is meant to be silent. The lecturer's Grafana can't read Azure:
  the BFH tenant doesn't let student accounts register the app it would need
  (2026-11-03).
- **On a VM**: Prometheus/Grafana scrape `/metrics`; a dashboard and alerts
  (stale worker, failed jobs including emails, 5xx) were prepared for the
  lecturer's monitoring stack but not applied, since the demo moved to Azure.

### 10.4 CI/CD

One GitHub Actions workflow, `.github/workflows/bikeshop.yml` in the
repository root, for every push and pull request that touches
`Use_Case_BikeShop/`:

1. **test**: Python 3.12, `uv pip sync requirements-dev.txt`, `pytest`.
   Every push and pull request.
2. **build** (pushes to `main` only, after the tests pass): build the image
   on GitHub's amd64 runner and push it to the registry as
   `bikeshop:<short commit hash>`, so every image traces back to a commit.
3. **staging**: update `bikeshop-staging` to that image, then wait until its
   `/health` answers `ok` (it may first have to wake up).
4. **production**: the same image to `bikeshop`, then the same check. This
   job runs in the GitHub environment `production`, which **waits for the
   lecturer's approval**: production only gets what ran on staging, and
   only when someone says so.

- **Azure login without secrets**: GitHub's OIDC token is exchanged for an
  Azure token of the user-assigned managed identity `bikeshop-github`
  (federated credentials for the `main` branch and the environments `staging`
  and `production`). No password is stored anywhere. A managed identity is an
  Azure resource in the subscription, so it works where the BFH tenant
  forbids app registrations.
- **Least privilege**: the identity may push to the registry (`AcrPush`) and
  change the two container apps (`Contributor` on each app), nothing else.
- **Settings** are GitHub repository variables (not secrets: none of them
  is secret): `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`,
  `AZURE_RESOURCE_GROUP`, `ACR_NAME`.
- **Rollback**: re-run the production job of an earlier successful run, or
  `az containerapp update --image bikeshop:<earlier hash>`.
- Manual deploys from a laptop (`DEPLOY-azure.md`) still work, for students
  without the pipeline.
- **One pipeline only.** The Azure portal's *Continuous deployment* (and
  `az containerapp github-action add`) is not used: it commits a second
  workflow that deploys to production on every push, without tests,
  staging or approval, and stores the login as `<APP>_AZURE_*` secrets
  that this workflow doesn't read.

## 11. Build slices and acceptance criteria

Each slice is done when its Given/When/Then pass as pytest (`tests/`) or as a
manual check, as marked.

### S1 Skeleton
Files: `api/main.py`, `api/expose_api.py`, `api/database.py`,
`api/config.py`, `requirements.in/.txt`, `README.md`.

- **Given** a fresh checkout, **when** I run `uvicorn api.expose_api:app`,
  **then** `/docs` shows Scalar and `/health` returns 200.
- **Given** no database file, **when** the app starts, **then**
  `api/data/bikeshop.db` is created with all tables.

### S2 Auth, roles, rate limit, billing (copy and adapt)
Files: `middleware/*`, `router/auth_router.py`, `router/billing_router.py`,
`services/auth_service.py`, `services/rate_limit_service.py`,
`services/billing_service.py`, `models/models.py`,
`scripts/create_staff.py`, `MIDDLEWARE_ARCHITECTURE.md`.

- **Given** a new registration, **then** the user's role is `customer`.
- **Given** a customer key, **when** it calls `/staff/inventory`, **then** 403.
- **Given** a staff key, **when** it calls `/staff/inventory`, **then** 200,
  and the balance does not change.
- **Given** a customer with 0 tokens, **when** they call `GET /api/bikes`,
  **then** 402 and no usage is charged.
- **Given** a customer, **when** `POST /api/rentals` succeeds, **then** the balance
  drops by 5. **When** it fails with 409, **then** the balance is unchanged.
- **Given** a user whose per-minute limit is N, **when** call N+1 to `/api`
  arrives within a minute, **then** 429 (and call N did not).
- **Given** a customer key, **when** it calls `/auth/my-keys`, **then** it sees
  only its own keys. **When** it revokes one by name, **then** that key gets
  401 afterwards.

### S3 Catalogue and inventory
Files: `router/bike_router.py`, `router/staff_router.py`,
`services/inventory_service.py`, `models/models.py`.

- **Given** sale and rental bikes, **when** a customer searches
  `purpose=sale&max_price_chf=1500`, **then** only sale bikes ≤ 1500 that are
  not retired or sold are returned.
- **Given** staff creates a sale bike without `sale_price_chf`, **then** 422.
- **Given** a rental bike with a future booking, **when** staff retires it,
  **then** 409. **When** staff sets it to `maintenance`, **then** 200 and the
  booking is listed as at risk in `/staff/inventory`.

### S4 Pricing
Files: `services/pricing_service.py`, `router/bike_router.py`
(`rental-rates`), `router/staff_router.py` (`set_rental_rate`).

- **Given** city = 8/35, **then** the example table in §5.3 holds (unit
  tests, no DB).
- **Given** a rate with `daily > 24 × hourly`, **when** staff saves it,
  **then** 422.
- **Given** a booking quoted at 35.00, **when** staff raises the city daily
  rate to 40, **then** the booking still shows 35.00.

### S5 Availability, quotes, bookings
Files: `router/rental_router.py`, `services/rental_service.py`,
`services/pricing_service.py`, `api/config.py`.

- **Given** bike 3 booked Sat 10:00–14:00, **when** availability is asked for
  Sat 13:00–15:00, **then** bike 3 is missing. **For** Sat 14:00–16:00
  **then** it is listed (end is exclusive).
- **Given** a request starting Sunday 10:00, **then** 400 "The shop is closed
  on Sundays…".
- **Given** a request at 10:07, **then** 400 (15-minute grid).
- **Given** two concurrent bookings for the same bike and period, **then**
  exactly one succeeds and the other gets 409.
- **Given** a customer with 3 open rentals, **when** they book a 4th, **then** 409.
- **Given** a booked rental starting tomorrow, **when** the owner cancels,
  **then** `cancelled`. **When** another customer tries, **then** 404.

### S6 Pick-up and return
Files: `router/staff_router.py`, `services/rental_service.py`.

- **Given** a rental booked for today, **when** staff picks it up, **then**
  `active` and `picked_up_at` is set. **Given** one booked for tomorrow,
  **then** 409.
- **Given** a 3 h city rental returned 2 h late, **then**
  `final_price_chf = 35.00` (5 h, capped). **Returned** 1 h early, **then**
  24.00 (no refund).
- **Given** an active rental past `end_at`, **then** it appears in
  `/staff/rentals?overdue=true` and still blocks availability.

### S7 Sales
Files: `router/order_router.py`, `router/staff_router.py`,
`services/order_service.py`.

- **Given** an available sale bike, **when** a customer reserves it, **then**
  the order is `reserved`, the bike is `reserved`, and other customers get 409.
- **Given** a reserved order, **when** the owner cancels, **then** the bike is
  `available` again.
- **Given** a reserved order, **when** staff completes it, **then** the bike is
  `sold` and disappears from `/api/bikes`.

### S8 Reservation expiry (worker)
Files: `scripts/worker.py`, `services/order_service.py`
(`expire_reservations()`), `models/models.py` (`Order.expires_at`, `JobRun`),
`api/config.py`, `docker-compose.yml`, `api/main.py` (`/health`).

- **Given** an order reserved 7 days and 1 minute ago, **when** the job runs,
  **then** the order is `expired`, the bike is `available` again, and
  `JobRun` says "expired 1 orders".
- **Given** an order reserved 6 days ago, **when** the job runs, **then** it
  stays `reserved`.
- **Given** the job runs twice in a row, **then** the second run expires
  nothing and changes nothing.
- **Given** staff completes an order at the moment the job runs, **then** the
  order ends `completed` or `expired`, never both, and the bike matches it.
- **Given** the job raises, **then** `JobRun.last_ok` is false with the
  error, and the next run still happens.
- **Given** the stack is running, **when** I call `/health`, **then**
  `scheduler.last_run_at` is less than 15 minutes old.

### S9 Seed
Files: `scripts/seed.py`.

- **Given** an empty DB, **when** I run the seed twice, **then** the counts are
  the same as after one run.
- **Given** `ADMIN_PASSWORD` is set, **when** the seed runs, **then** `admin`
  can sign in and has the staff role. **Given** it isn't set, **then** no
  `admin` account is created and the seed says so.
- **Given** seeded data, **when** I log in as staff, **then** the board shows
  at least one pick-up, one return, one overdue rental, and one reserved
  order that expires within a day.

### S10 Frontend
Files: `frontend/**`, `api/main.py` (static mount), `FRONTEND.md`.

Automated (pytest):

- **Given** the app, **when** I open `/`, **then** I get `index.html`; the
  CSS and JS files are served with the right content types; `/api/bikes`
  without a key still answers 401 (the static mount doesn't swallow API
  paths).

Manual, in a browser (or a headless browser script):

- **Given** the customer account, **when** I pick an e-bike, choose Sat
  10:00–15:00 and confirm, **then** the rental appears under My rentals with
  the quoted price.
- **Given** the customer account, **then** no staff pages are in the menu;
  opening `#/staff/board` by hand shows "for shop staff only", and the API
  answers 403 anyway.
- **Given** the staff account, **when** I return a rental on the board,
  **then** the final price is shown.
- **Given** I log out, **then** the tab's API key is revoked.
- **Given** a bike whose name is `<img src=x onerror=alert(1)>`, **then** the
  catalogue shows that text and runs nothing.
- **Given** the API is stopped while the page is open, **when** I click,
  **then** the page shows the waiting message and then a readable error,
  and works again once the API is back, without a reload.

### S11 BFH inference connection
Files: `api/services/inference_service.py`, `api/main.py` (`/health`),
`api/config.py`, `.env.example`, `requirements.in`.

- **Given** valid settings, **when** I call `/health`, **then**
  `"inference": "ok"`.
- **Given** no inference settings, **then** the app starts and `/health`
  says `"not_configured"` with status 200.
- **Given** a wrong key, **then** `"unauthorized"`. **Given** an unknown
  model name, **then** `"model_missing"`. **Given** an unreachable URL,
  **then** `"unreachable"` within ~5 s (tests mock the HTTP call).
- **Given** two `/health` calls within 60 s, **then** the endpoint is called
  once.
- **Given** any log line or response, **then** the API key does not appear.

### S12 Deployment on the VM (manual check)
Files: `Dockerfile`, `docker-compose.yml`,
`deploy/nginx/demo.sai1.airs.iadsf.ch.conf`, `.env.example`, `DEPLOY.md`,
`BACKEND.md`, `README.md`.

- **Given** `DEPLOY.md`, **when** I follow it on the VM, **then**
  `https://demo.sai1.airs.iadsf.ch` serves the app and `/docs` serves Scalar,
  both with a valid certificate, and **every other
  site on the VM still answers** (check a few with `curl -I`).
- **Given** the running stack, **when** I seed, then run
  `docker compose down && docker compose up -d`, **then** the data is still
  there.
- **Given** the VM, **when** I call its IP on port 8130 from outside,
  **then** the connection is refused (port bound to 127.0.0.1).
- **Given** the deployed API, **when** I call
  `https://demo.sai1.airs.iadsf.ch/health`, **then** `"inference": "ok"`
  (the VM reaches BFH inference through the proxy).
- **Given** the deployment finished, **then** the root disk is below 90%.
- **Given** the deployed URL, **when** someone opens it on a phone, **then**
  the catalogue loads (the hook of the deployment lecture, closed).

### S13 Azure Container Apps with Litestream
Files: `scripts/start.sh`, `litestream.yml`, `Dockerfile`, `.env.example`,
`deploy/azure/compose.azurite.yml`, `DEPLOY-azure.md`, `MAP.md`.

Locally with Azurite (automated as far as possible, otherwise manual):

- **Given** an empty Blob container, **when** the API starts with
  `APP_MODE=all` and `SEED_ON_START=1`, **then** the shop is seeded and the
  copy appears in Blob Storage.
- **Given** a booking made through the API, **when** the API container is
  removed (disk gone) and started again, **then** the booking is still
  there (restored from Blob Storage), and the seed did not add duplicates.
- **Given** `APP_MODE=all`, **then** one process tree runs Litestream,
  uvicorn and the worker, and `/health` shows the expiry job's run.
- **Given** `APP_MODE` unset, **then** the container behaves as in §10.1
  (uvicorn only), and the VM's compose file works unchanged.

On Azure (manual):

- **Given** `DEPLOY-azure.md` and an Azure for Students subscription,
  **when** a student follows it, **then** the URL works over HTTPS and
  `/health` shows `"inference": "ok"`.
- **Given** the app scaled to zero (no traffic for a while), **when**
  someone opens it again, **then** it starts within about 30 s and the
  earlier bookings are still there.

### S14 Queue and worker
Files: `api/jobqueue/`, `scripts/worker.py` (replaces `scripts/scheduler.py`),
`api/models/models.py` (`Job`), `api/router/job_router.py` (`get_my_job`, and
`list_jobs` on its staff router), `api/main.py` (`/health`),
`docker-compose.yml`, `scripts/start.sh`.

- **Given** a queued job, **when** two workers claim at the same moment,
  **then** exactly one gets it.
- **Given** a handler that raises, **then** the job is requeued with a later
  `run_after`, and after 3 attempts it is `failed` with the error stored.
- **Given** a `running` job whose heartbeat is 3 minutes old, **when** the
  reaper runs, **then** it is `queued` again (attempts left) or `failed`.
- **Given** a job requeued by the reaper, **when** the old worker finishes it,
  **then** its write changes nothing (fencing).
- **Given** an unknown kind, **then** the job fails with "No handler for job
  kind '…'".
- **Given** my job, **then** `GET /api/jobs/{id}` shows it; another customer
  gets 404.
- **Given** the worker runs, **then** reservations still expire (§5.7) and
  `/health` shows `worker` and `queue`.

### S15 Email notifications
Files: `api/mail/` (copied mailer), `api/jobqueue/handlers.py`
(`send_email`), `api/services/notification_service.py`,
`api/services/rental_service.py`, `api/services/order_service.py`,
`api/config.py`, `.env.example`.

- **Given** a booking, **then** a `send_email` job is enqueued in the same
  transaction; a failed booking enqueues nothing.
- **Given** the worker and no Mailgun settings, **then** the email appears in
  the log (logging mailer) and the job is `done`.
- **Given** Mailgun settings, **then** the request goes to the EU endpoint
  with the domain and sender from the settings (tests mock HTTP).
- **Given** a `.test` address, **then** nothing is sent and the job result
  is `skipped`.
- **Given** a reservation the worker expires, **then** a "reservation
  expired" email is enqueued.

### S16 Help and legal pages
Files: `api/content/` (copied from kooistra-web), `docs/help/*.md`,
`docs/legal/privacy-policy.md`, `docs/legal/terms-of-service.md`,
`api/main.py`, `frontend/` (footer).

- **Given** the files, **then** `/help`, an article, `/legal/privacy` and
  `/legal/terms` return HTML that loads only same-origin assets.
- **Given** a missing file, **then** its route answers 404.
- **Given** any frontend page, **then** the footer links to all three.

### S17 Analytics
Files: `api/services/analytics_service.py`, the routers named in §5.10,
`api/router/staff_router.py` (`analytics_summary`), `api/models/models.py`
(`AnalyticsEvent`), `frontend/js/pages/staff-analytics.js`.

- **Given** a customer views a bike, quotes and books, **then** one event of
  each kind exists, with no user id.
- **Given** events over several days, **then** `/staff/analytics` returns
  per-day counts, the top bikes and the quote → booking rate.
- **Given** the analytics table can't be written, **then** the customer's
  request still succeeds.
- **Given** events older than 365 days, **when** the worker's daily clean-up
  runs, **then** they are gone.

### S18 Logs and metrics
Files: `api/observability.py`, `api/main.py`, `scripts/worker.py`,
`scripts/start.sh`, `deploy/nginx/…conf`, private monitoring repository.

- **Given** requests, **then** `/metrics` shows `http_requests_total` with the
  route template as `handler`.
- **Given** 4 uvicorn workers, **then** the counters on `/metrics` add up
  across them (multiprocess mode).
- **Given** `METRICS_ENABLED=0`, **then** `/metrics` answers 404.
- **Given** the public nginx site, **then** `/metrics` answers 404.
- **Given** an exception in a request, **then** the log has one JSON line
  with the traceback folded in.

### S19 CI (tests)
Files: `.github/workflows/bikeshop.yml` (job `test`).

- **Given** a push that touches `Use_Case_BikeShop/`, **then** GitHub Actions
  runs the tests and shows the result on the commit and the PR.

### S22 CD (deploy through staging to production)
Files: `.github/workflows/bikeshop.yml` (jobs `build`, `staging`,
`production`), `DEPLOY-azure.md`, `CLAUDE.md`.

- **Given** a pull request, **then** only the tests run; nothing is built or
  deployed.
- **Given** a merge to `main` with green tests, **then** an image
  `bikeshop:<hash>` is pushed and staging runs it, with `/health` ok.
- **Given** that, **then** production waits for approval; after approval it
  runs the same `<hash>`, with `/health` ok.
- **Given** failing tests, **then** nothing is built or deployed.
- **Given** the workflow, **then** no Azure password or key is stored in
  GitHub (OIDC only).

### S20 Staging
Files: `litestream.yml`, `scripts/start.sh` (`LITESTREAM_PATH`),
`.env.example`, `DEPLOY-azure.md`.

- **Given** `LITESTREAM_PATH` unset, **then** the database copy goes to
  `bikeshop/` as before; **given** `bikeshop-staging`, **then** to
  `bikeshop-staging/`, and a restore reads only that path.
- **Given** a booking on staging, **then** production doesn't have it, and
  the other way round.
- **Given** a new image, **when** I follow the release flow, **then**
  staging runs it first and production gets the same tag.
- **Given** `https://staging.sai1.airs.iadsf.ch`, **then** it serves the app
  with a valid certificate.

### S21 Alerts on Azure (manual check)
Files: `DEPLOY-azure.md`.

- **Given** the rules, **when** the API answers 5xx (e.g. a forced error),
  **then** an email reaches the lecturer within about 10 minutes.
- **Given** a log line with an exception, **then** the "exceptions" rule
  fires on its next run.
- **Given** the app scaled to zero overnight, **then** no rule fires.

### S23 A year of past usage
Files: `scripts/seed_history.py`, `api/config.py` (`HOLIDAYS` back to
Christmas 2025), `tests/test_s23_history.py`.

- **Given** a seeded database, **when** I run the history twice, **then** the
  counts are the same as after one run, and the demo customer can still book.
- **Given** the history, **then** every rental starts and ends within opening
  hours on the 15-minute grid, lasts 1 hour to 14 days, ends before now,
  doesn't overlap another non-cancelled rental of its bike, and its quoted
  and final prices follow §5.3 at the rates it stores.
- **Given** the history, **then** for each day the `booking` events equal the
  invented rentals booked that day, and the `reservation` events equal the orders made
  that day, and no event is older than 365 days.
- **Given** the history, **then** each planted pattern P1–P8 (§9.1) holds:
  - P1: more rentals start in July than in January.
  - P2: the L e-bikes are out on at least 80% of the Saturdays from May to September.
  - P3: cargo has the fewest rentals per bike of the adult categories.
  - P4: at least 80% of kids' rentals start in school holidays.
  - P5: e-bike rentals booked before 1 June store 14/60, later ones 15/65, and June has at least as many e-bike bookings as May.
  - P6: gravel's share of rentals in the last three months is at least 1.5 × its share in the first three.
  - P7: `S-EBIKE-03` is listed 100 days with no order; `S-ROAD-02` 140 days with two expired orders.
  - P8: one April day has at least 4 × the median daily catalogue views.
- **Given** the history, **when** staff open `/staff/analytics?days=365`,
  **then** they see a full year.

## 12. Decisions log

No open questions. Decided 2026-11-02:

- Host: the lecturer's existing VM, Docker compose behind its nginx; no
  Caddy because nginx owns 80/443 there. Code arrives by `git clone`/`git pull`
  of this repository (`Use_Case_BikeShop/`).
- Domain: `demo.sai1.airs.iadsf.ch`, one hostname with path routing.
- BFH inference through the proxy `https://inference.proxy.ti.bfh.ch/v1`,
  with the lecturer's own MLMP key (renew every 180 days). The app is a
  lecturer's demo, so MLMP's notice for classes of 15+ doesn't apply.
- Students get the finished app as a worked example.
- Reserved sale bikes expire after 7 days via a scheduler container (§5.7).
- English only.
- 2026-11-03: **CI/CD** in GitHub Actions: test → build → staging →
  approval → production, logging in to Azure through a managed identity
  with OIDC (no stored secrets; app registrations are blocked in the BFH
  tenant, managed identities are not). Image tags become commit hashes.
- 2026-11-03: a **staging** copy on Azure (`staging.sai1`, own data path,
  no real emails) and **Azure Monitor alerts** by email, since Grafana can't
  be connected to Azure from a student account.
- 2026-11-03: **Azure only.** The demo runs on Azure Container Apps at
  `demo.sai1.airs.iadsf.ch`; the switchengine deployment is dropped. The
  Express environment was replaced by a classic Consumption one for the
  custom domain and the 1-hour scale-down.
- 2026-11-03: filling the lecture map further. A job queue and worker
  (adapted from AI Beacon), email notifications via Mailgun EU on
  `mail.kooistra.ch` (from kooistra-mailer), help and legal pages (from
  kooistra-web), first-party anonymous analytics, JSON logs and Prometheus
  metrics wired into the existing Grafana on the VM, and CI. Code from the
  kooistra packages is **copied** into the app with a note naming its source,
  not imported, so students can read everything in one place.
- 2026-11-03: the frontend is a static site served by FastAPI instead of
  Streamlit. On Azure the frontend container scaled to zero under open
  tabs, which then broke; a static page keeps its state in the browser and
  just waits for the API. It also removes a container, a URL, CORS and
  nginx's path routing. Cost: the pages are JavaScript instead of Python,
  and the colleague's chat box needs a small widget instead of
  `st.chat_message`.
- 2026-11-03: **a year of invented usage** (§9.1, S23), so the planned
  management agents (fleet investments, spare-parts reordering with staff
  approval) have data to work on. It goes into the existing tables only, as
  a separate script run by hand, so the seed and its tests stay as they are.
  The planted patterns are written down as the answer key, so students can
  check whether an analysis finds them. Missing for those agents and left
  for their own slices: costs (purchase price, maintenance), unmet demand
  (a `no_availability` event), price history as a table, parts and suppliers.
- 2026-11-03: **one deployment pipeline**, ours (§10.4). The portal's
  *Continuous deployment* was tried and added a second workflow that
  deployed to production directly and failed (it builds from the repository
  root, where there is no Dockerfile).
- 2026-11-03: a second deployment target for students, Azure Container Apps
  (pay per use, Azure for Students), with Litestream keeping SQLite in Azure
  Blob Storage. Managed PostgreSQL was considered: it scales out but
  needs locking changes in `database.py`, and it's unclear whether student
  subscriptions may create it. Recorded in MAP.md as the next step.
