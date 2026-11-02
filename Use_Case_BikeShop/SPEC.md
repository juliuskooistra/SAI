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
| Streamlit | the frontend (`frontend/`) |
| VM + Docker | `docker compose` on a VM, behind the VM's nginx, which terminates HTTPS (§10) |

This file is the contract. Change it first, then the code (spec-first). The
LLM features are **out of scope** here: we only connect to BFH inference
and guarantee an API that the colleague can wrap as tools (§8).

Status: draft, 2026-11-02.

Students get the **finished app as a worked example**: they read and run it,
they don't rebuild it. The app is **English only** (UI, error messages,
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
  and a Dockerfile. The frontend is Streamlit instead of the generated React app.
- Deployed on a VM and reachable over HTTPS.
- The deployed API can reach BFH inference, and `/health` shows whether it can.

**Non-goals**

- LLM features, prompts, tool definitions, agent loop (colleague, later).
  Nothing in the app calls the model except the reachability check.
- Real payments. Rentals and sales are paid at the counter; the app records
  prices only. The **token** billing is for API usage, as in VoltagePredictor,
  and has nothing to do with bike prices (§5.6).
- Multiple shops/branches, repairs/servicing workflow, accessories, delivery.
- Email notifications, password reset, magic links.

## 2. Structure

Mirrors `Use_Case_III/VoltagePredictor` file for file; new files are marked ✚.

```text
Use_Case_BikeShop/              (in github.com/juliuskooistra/SAI)
├── SPEC.md                      ✚ this file (the contract)
├── MAP.md                       ✚ the app on the lecture's final map: which boxes it has, where
├── README.md                    setup, run, invoke, deploy (like VoltagePredictor)
├── BACKEND.md                   docker build/run/logs
├── FRONTEND.md                  how the Streamlit app was generated (the prompt)
├── MIDDLEWARE_ARCHITECTURE.md   the three middlewares, protection matrix
├── DEPLOY.md                    ✚ VM from zero to HTTPS, step by step (§10)
├── Dockerfile                   the API image
├── docker-compose.yml           ✚ api + scheduler + frontend, one volume, ports on 127.0.0.1 only
├── deploy/nginx/demo.sai1.airs.iadsf.ch.conf  ✚ the VM's nginx site (one host, path routing)
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
│   ├── scheduler.py             ✚ the scheduled-job loop (runs in its own container, §5.7)
│   └── create_staff.py          promote/create a staff user
├── tests/                       ✚ pytest
└── frontend/                    ✚ Streamlit (replaces front_end/ React app)
    ├── Dockerfile
    ├── requirements.in / requirements.txt
    ├── app.py                   entry: login, navigation by role
    ├── api_client.py            the only module that calls the API (≙ client/src/lib/api.ts)
    └── pages/                   one file per page (§7)
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
| Streamlit instead of React + Vite + Express | Bare-minimum stack: Python only, one small container, no Node build. |
| `docker compose` behind nginx + certbot instead of a bare `docker run -p 8000:8000` | HTTPS and a real hostname, which the reference skips. The VM already runs nginx on 80/443 for its other sites, so Caddy is not used. |
| Settings from `.env` | BFH inference key, CORS origin and passwords stay off the repo. |

Not adopted on purpose: the `kooistra-*` packages. The point is that students
can read the whole app and compare it to Use_Case_III, so nothing is hidden
in a package.

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
| `status` | enum | `reserved` → `completed`; `reserved` → `cancelled`; `reserved` → `expired` (scheduler) |
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

## 5. Business rules

Constants live in `api/config.py`. The values below are the defaults.

### 5.1 Opening hours

| day | hours |
|---|---|
| Mon–Fri | 09:00–18:30 |
| Sat | 09:00–16:00 |
| Sun, Swiss public holidays | closed (holidays: a fixed list in `config.py`) |

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
| expire order | scheduler | `reserved` and `now ≥ expires_at` | order `expired`, bike `available` (§5.7) |
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
`config.py`). After that the scheduler releases it. This is the app's
example of a scheduled job, like StudyBuddy's weekly email in the lecture.

- **Its own process.** The job runs in a separate `scheduler` container
  (`python -m scripts.scheduler`), not inside the API. The API runs 4 uvicorn
  workers, so a loop inside it would run 4 times.
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
  reference used 10/100/1,000, and a Streamlit demo hits 10 a minute by
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

### Status codes

400 rule violated (opening hours, grid, duration) · 401 no or invalid key ·
402 not enough tokens · 403 not staff / not yours (for mutations) · 404 not
found or not yours (for reads) · 409 conflict (bike taken, wrong state, limit
reached) · 422 malformed input (FastAPI) · 429 rate limited.

## 7. Frontend (`frontend/`, Streamlit)

Replaces VoltagePredictor's React + Vite + Express app. It is generated the
same way: give the generator the OpenAPI spec from `/openapi.json` and a prompt,
and record the prompt in `FRONTEND.md`.

- **Talks to the API only through `api_client.py`**, at `BIKESHOP_API_URL`.
  In compose that is the internal address `http://api:8000`. Streamlit calls
  the API from its server, not from the browser, so CORS does not apply to it.
- **Sign-in**: the login form sends the username and password to
  `/auth/generate-key` (name `streamlit-<random>`, one per browser session, expires in 1 day,
  so logging out on one device doesn't sign out another). The key and
  the role go into `st.session_state`, which replaces the Express session shim.
  Logout revokes the key.
- **Errors**: the API's `detail` is shown with `st.error` as it is. A 402
  (tokens) links to the Account page.

| page (`pages/`) | role |
|---|---|
| Login / register (`app.py`) | all |
| Catalogue: "Buy" and "Rent" tabs, filters | all |
| Bike detail: rent (date + time inputs on the 15-min grid, live quote) or reserve | all |
| My rentals / my orders, with cancel | customer |
| Account: API keys, token balance, buy tokens, usage | all |
| Staff: inventory table + add/edit/retire bike | staff |
| Staff: today's board (pick-ups due, returns due, overdue) | staff |
| Staff: price list editor | staff |
| Staff: orders to complete | staff |

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

## 9. Seed data (`scripts/seed.py`)

The script is idempotent: it creates only what is missing and leaves existing rows alone.

- Price list for all 7 categories, e.g. city 8/35, ebike 15/65, mountain
  12/50, road 12/50, gravel 12/50, kids 5/20, cargo 18/75 (CHF hourly/daily).
- About 20 rental bikes across categories and sizes, including 1 in `maintenance`.
- About 15 sale bikes, new and used, CHF 400–6000.
- Accounts `staff@bikeshop.test` (staff) and `customer@bikeshop.test`
  (customer). Passwords come from env vars, not the repo.
- A few rentals in the past and future, including one overdue, so the staff board
  isn't empty, and one reserved order that expires within a day. Most of
  these belong to two walk-in customers (`lena`, `marco`, random passwords
  nobody knows), so the demo customer starts well below its limits (3 open
  rentals, 2 reservations) and can book live.
- Demo accounts get 10,000 API tokens.
- Re-running adds only missing bikes, rates and users. Rentals and orders are
  seeded only into an empty database.

## 10. Deployment (Docker behind nginx on a VM)

The app runs on an Ubuntu VM that already serves other sites. Its nginx holds
ports 80/443 and serves each site from `/etc/nginx/conf.d/<host>.conf`, with
one certbot certificate per hostname. BikeShop follows that convention. The
app runs in Docker Compose, and nginx proxies to it. (The demo VM's own
runbook, with its host details, is kept privately, outside this repo.)

```text
                       https://demo.sai1.airs.iadsf.ch
internet ─443─► nginx (host, certbot TLS) ─┬─ /auth/ /billing/ /api/ /staff/ /docs /openapi.json /health
                                            │      └─► 127.0.0.1:8130 → api:8000 (FastAPI)
                                            └─ everything else
                                                   └─► 127.0.0.1:8131 → frontend:8501 (Streamlit)

api, scheduler ─► volume bikeshop-data → /app/api/data/bikeshop.db
api            ─► https://inference.proxy.ti.bfh.ch/v1 (outbound)
```

- **One hostname, path routing**: `demo.sai1.airs.iadsf.ch` (DNS A record →
  the VM's IP). nginx sends the API's prefixes to the API and everything
  else to Streamlit, so there is one origin, one certificate, and no CORS
  between the two. Rule: **no Streamlit page may use a URL path equal to an
  API prefix** (`auth`, `billing`, `api`, `staff`, `docs`, `health`). Pages
  are named e.g. `staff_board`, which nginx's `location /staff/` doesn't
  match. Adding a new API prefix means adding it to the nginx site too.
- **API image**: `Dockerfile` as in VoltagePredictor (`python:3.12-slim`,
  `uvicorn api.expose_api:app --workers 4`), installing from the uv-compiled
  `requirements.txt`. **Frontend image**: `frontend/Dockerfile`, running
  `streamlit run app.py --server.port 8501 --server.address 0.0.0.0`.
- **`docker-compose.yml`**: services `api`, `scheduler` (same image as `api`,
  command `python -m scripts.scheduler`, no ports) and `frontend`, all with
  `restart: unless-stopped`. The frontend reaches the API at `http://api:8000`
  on the compose network. Ports are published **on 127.0.0.1 only**
  (`127.0.0.1:8130:8000`, `127.0.0.1:8131:8501`). Docker's port publishing
  bypasses `ufw`, so `8130:8000` without the address would put the bare API
  on the internet. One volume, `bikeshop-data`, holds SQLite and is shared by
  `api` and `scheduler`.
- **nginx** (`deploy/nginx/demo.sai1.airs.iadsf.ch.conf`, copied to
  `/etc/nginx/conf.d/`; on a VM whose `nginx.conf` names every site instead of
  including `conf.d/*.conf`, also an explicit `include` line): one `server` block. The API prefixes get one
  `location` each, proxied to 8130; `location /` is proxied to 8131. All of
  them set `X-Forwarded-*` headers. `location /` also passes the
  websocket (`Upgrade`/`Connection` headers, `proxy_http_version 1.1`,
  `proxy_read_timeout 86400`); without that Streamlit hangs on "Connecting…".
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

### S8 Reservation expiry (scheduler)
Files: `scripts/scheduler.py`, `services/order_service.py`
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
- **Given** seeded data, **when** I log in as staff, **then** the board shows
  at least one pick-up, one return, one overdue rental, and one reserved
  order that expires within a day.

### S10 Frontend (manual check)
Files: `frontend/**`, `FRONTEND.md`.

- **Given** the customer account, **when** I pick an e-bike, choose Sat
  10:00–15:00 and confirm, **then** the rental appears under My rentals with
  the quoted price.
- **Given** the customer account, **then** no staff pages are reachable from
  the menu, and calling `/staff/*` with that key gives 403.
- **Given** the staff account, **when** I return a rental on the board,
  **then** the final price is shown.
- **Given** I log out, **then** the session's API key is revoked
  (`/auth/my-keys` no longer lists it as active).

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
Files: `Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml`,
`deploy/nginx/demo.sai1.airs.iadsf.ch.conf`, `.env.example`, `DEPLOY.md`,
`BACKEND.md`, `README.md`.

- **Given** `DEPLOY.md`, **when** I follow it on the VM, **then**
  `https://demo.sai1.airs.iadsf.ch` serves the app and `/docs` serves Scalar,
  both with a valid certificate, and **every other
  site on the VM still answers** (check a few with `curl -I`).
- **Given** the running stack, **when** I seed, then run
  `docker compose down && docker compose up -d`, **then** the data is still
  there.
- **Given** the VM, **when** I call its IP on port 8130 or 8131 from
  outside, **then** the connection is refused (ports bound to 127.0.0.1).
- **Given** a Streamlit page left open for 10 minutes, **then** it still
  responds (the websocket survives nginx).
- **Given** the deployed API, **when** I call
  `https://demo.sai1.airs.iadsf.ch/health`, **then** `"inference": "ok"`
  (the VM reaches BFH inference through the proxy).
- **Given** the deployment finished, **then** the root disk is below 90%.
- **Given** the Streamlit page `staff_board`, **then** it loads Streamlit,
  not the API (path routing doesn't catch it).
- **Given** the deployed URL, **when** someone opens it on a phone, **then**
  the catalogue loads (the hook of the deployment lecture, closed).

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
