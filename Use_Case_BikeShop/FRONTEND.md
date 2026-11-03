# BikeShop frontend

The frontend is a static website in `frontend/`: one HTML page, one CSS file
and a few JavaScript modules. There is no framework and no build step, and
nothing is loaded from other sites, so you can open any file and read it. It
talks to the BikeShop API only, through one module (`frontend/js/api.js`),
exactly as any other client of the API would. It was generated from the API's
OpenAPI spec and the prompt below, then checked by hand against the running
API. The contract is `SPEC.md` §7.

```text
frontend/
├── index.html             the one page: header, menu, "waking up" banner, empty <main>
├── styles.css             the whole look: a few colour variables, cards, forms, tables
└── js/
    ├── api.js             the only module that calls the API (fetch); sign-in state
    ├── app.js             hash routing, menu by role, log out
    ├── ui.js              el() for safe rendering, formatting, messages, rental time inputs
    └── pages/
        ├── login.js           sign in / create an account
        ├── catalogue.js       Buy and Rent tabs, filters, availability check
        ├── bike.js            live rental quote + Book, or Reserve for sale bikes
        ├── my.js              my rentals and my orders, with Cancel
        ├── account.js         tokens, buy tokens, usage, rate limit, API keys
        ├── staff-board.js     today's pick-ups, returns, overdue, at risk
        ├── staff-inventory.js summary, all bikes, add / edit / retire
        ├── staff-prices.js    rental price list editor
        ├── staff-orders.js    complete or cancel reservations, scheduler status
        ├── staff-analytics.js anonymous analytics: totals, top bikes, per day
        └── staff-jobs.js      background jobs: status, attempts, errors
```

| page | address (hash route) | who sees it |
|---|---|---|
| Sign in / create an account | `#/login` | not signed in |
| Catalogue | `#/catalogue` (the default) | everyone signed in |
| Bike details | `#/bike/<id>` | everyone signed in |
| My rentals and orders | `#/my` | everyone signed in |
| Account | `#/account` | everyone signed in |
| Today's board | `#/staff/board` | staff |
| Inventory | `#/staff/inventory` | staff |
| Price list | `#/staff/prices` | staff |
| Orders | `#/staff/orders` | staff |
| Analytics | `#/staff/analytics` | staff |
| Jobs | `#/staff/jobs` | staff |

**The footer** of every page links to **Help · Privacy · Terms**: `/help`,
`/legal/privacy` and `/legal/terms`. Those are not pages of this frontend but
plain HTML pages that the API renders from the markdown in `docs/help/` and
`docs/legal/` (`api/content/`, `SPEC.md` §6), so they are ordinary links
without `#`, readable without signing in.

The part after `#` never reaches the server, so a page called `#/staff/board`
can't clash with the API's `/staff/…` paths. Customers who open a staff
address by hand see "This page is for shop staff only.", and the API answers
403 to their `/staff` calls anyway: hiding a page is not access control.

## Generating the Front End

1. Start the API and download its spec: open `http://localhost:8130/openapi.json`
   (or `https://demo.sai1.airs.iadsf.ch/openapi.json`) and save it.
2. Give Claude the file and the prompt below.

> Attached is the OpenAPI spec (`openapi.json`) of "BikeShop", a FastAPI
> backend for a bike shop that sells bikes and rents them out by the hour or
> day. Build its frontend as a static website in a folder `frontend/`:
> `index.html`, `styles.css`, `js/api.js`, `js/app.js`, `js/ui.js` and one
> module per page in `js/pages/`. Plain HTML, CSS and JavaScript modules: no
> framework, no build step, nothing loaded from a CDN or another site (no web
> fonts either; use a system font stack). It is a worked example for business
> students, so keep the code plain, short and commented, English only, with a
> short comment at the top of every file saying what it is for. The design
> should be calm and tidy (a bike shop, not a SaaS dashboard), readable on a
> phone, with visible keyboard focus.
>
> **Served by the API.** FastAPI serves `frontend/` under `/`, after all its
> own routes. Page and API share one origin, so use relative URLs
> (`/api/bikes`); no CORS, no second server.
>
> **`js/api.js` is the only module that calls `fetch`.**
> - Send the key as `Authorization: Bearer <key>`.
> - Give up after 60 seconds (AbortController). Any request that takes longer
>   than 2 seconds shows a banner "Waking up the shop, this can take up to 30
>   seconds" (the API may be starting from zero on Azure); hide it when done.
> - On a non-2xx answer throw an error that carries the API's `detail`
>   sentence; join FastAPI's 422 list into one sentence. A network failure or
>   a timeout gives a readable message, never a stack trace.
> - On a 401 forget the session and go to `#/login`. On a 402 (out of API
>   tokens) pages show the message plus a link to `#/account`.
>
> **Sign-in with API keys.** There are no sessions or cookies on the API side;
> every call needs an API key.
> - The sign-in form sends username and password to `POST /auth/generate-key`
>   with `name: "web-" + 8 random characters` and `expires_in_days: 1`, so every
>   browser tab has its own key. The answer includes `role`. Keep the key,
>   username, role and key name in `sessionStorage`.
> - Logout calls `DELETE /auth/revoke-key/{name}` with that key, then clears
>   the session. Registration is `POST /auth/register` (password at least 10
>   characters), then sign in.
>
> **Roles and pages.** Pages are hash routes: `#/login`, `#/catalogue`
> (default), `#/bike/<id>`, `#/my`, `#/account`, `#/staff/board`,
> `#/staff/inventory`, `#/staff/prices`, `#/staff/orders`, `#/staff/analytics`,
> `#/staff/jobs`. The menu shows the
> staff pages only for role `staff`; a customer who opens one sees "This page
> is for shop staff only." (The API enforces roles itself.)
> - Catalogue: "Buy" and "Rent" tabs with filters (category, frame size,
>   condition, max price for sale bikes, text). The Rent tab can check
>   availability for a period (`GET /api/availability`).
> - Bike detail: for rental bikes the rate, a date input plus start and end
>   `<select>`s with the quarter hours within that day's opening hours
>   (`GET /api/opening-hours`), a live quote (`POST /api/rentals/quote`) as
>   the times change, and a Book button. For sale bikes the price, a Reserve
>   button, and "held until …" after reserving.
> - My rentals and orders, with Cancel buttons; show an order's `expires_at`.
> - Account: token balance, buy tokens (`POST /billing/purchase-tokens`),
>   usage stats, rate-limit status, my API keys.
> - Staff, board: today's pick-ups and returns (`GET /staff/rentals?date=YYYY-MM-DD`,
>   in Zurich time), overdue, at-risk bookings, with Pick up / Return / Cancel.
>   Show the final price after a return.
> - Staff, inventory: table of `GET /staff/bikes`, the `/staff/inventory`
>   summary, add bike, edit bike (status available/maintenance for rental
>   bikes), retire.
> - Staff, prices: edit with `PUT /staff/rental-rates/{category}`.
> - Staff, orders: complete or cancel reservations; show `expires_at` and the
>   scheduler's last run from `GET /health`.
> - Staff, analytics: `GET /staff/analytics?days=30` (period 7/30/90/365):
>   totals per event, the quote → booking rate, the 10 most-viewed bikes as
>   bars, and a table of counts per day.
> - Staff, jobs: `GET /staff/jobs` with filters `status` and `kind`: a table
>   with status, attempts, times, result or error. A 404 means the server has
>   no job queue yet: show "No jobs yet". No polling; a Refresh button.
> - A footer on every page with plain links (no `#`) to `/help`,
>   `/legal/privacy` and `/legal/terms`, which the API renders itself.
>
> **The shield rule.** Never put API data into `innerHTML`. Build DOM nodes and
> set `textContent`; a small helper `el(tag, attrs, ...children)` in `ui.js`
> keeps this readable. A bike named `<img src=x onerror=alert(1)>` must show
> as that text.
>
> **Times and money.** The API returns ISO times with the Zurich offset and
> accepts times without an offset as Zurich time. Show times like
> "Sat 7 Nov 10:00". Money comes as CHF strings like "65.00".
>
> **Costs.** Every `/api` call costs API tokens and counts toward a limit of
> 60 calls per minute. Don't poll. Cache the catalogue and the rental rates
> for a minute at most.

## How it's served

There is no frontend server. `api/main.py` mounts the folder as static files,
after all the API's routes:

```python
self.app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
```

So `/` returns `index.html`, `/js/app.js` returns that file, and `/api/…`,
`/auth/…`, `/billing/…`, `/staff/…`, `/health` and `/docs` still go to the
API, because their routes were added first. Page and API share one origin
(one hostname, one port, one container): no CORS, no second container, and
no nginx path routing between two apps. The frontend ships inside the API's
Docker image.

**Why not Streamlit any more.** The first frontend was a Streamlit app in its
own container, replaced on 2026-11-03 (`SPEC.md` §12). On Azure Container
Apps that container scaled to zero while students still had the page open,
and the open tabs then broke, because a Streamlit page lives on the server.
A static page keeps all its state in the browser: when the API has scaled to
zero, the page stays as it is, and the next click shows "Waking up the shop"
and simply waits for the API.

## Running it locally

From the project root, with the API's venv:

```bash
export BIKESHOP_DATA_DIR=/tmp/bikeshop-data      # where the SQLite file goes
SEED_STAFF_PASSWORD=staffpass123 SEED_CUSTOMER_PASSWORD=custpass1234 \
  ADMIN_PASSWORD=adminpass123 .venv/bin/python -m scripts.seed
.venv/bin/uvicorn api.expose_api:app --port 8130 --reload
```

Open `http://localhost:8130/` and sign in with a seeded demo account
(`customer` or `staff`, with the passwords you gave the seed), or create a new
customer account on the sign-in page. To try it on your phone, start uvicorn
with `--host 0.0.0.0` and open `http://<your laptop's IP>:8130/` on the same
Wi-Fi.

Edit any file in `frontend/` and reload the browser tab: there is nothing to
build. The browser's developer tools (Console and Network tabs) show every
call the page makes.

### Good to know

- **Tokens.** Every `/api` call costs API tokens (a search or a quote 1, a
  booking or reservation 5). New accounts start with 100; the seeded demo
  accounts get 10,000. Buy more on the Account page.
- **Caching.** `api.js` keeps the bike lists, the price list and the opening
  hours for one minute, and forgets them after any change you make. A bike
  added by someone else can take up to a minute to show.
- **Waiting.** A request that takes longer than 2 seconds shows "Waking up the
  shop". If the server can't be reached, reading requests try again every 2
  seconds for up to 60 seconds; requests that change something (book,
  reserve) are never sent twice.
- **Signing out** revokes this tab's API key. Other tabs and devices have
  their own keys and stay signed in. Closing the tab forgets the key
  (`sessionStorage`); it also expires after one day.
