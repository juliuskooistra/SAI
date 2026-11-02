# BikeShop frontend

The frontend is a Streamlit app in `frontend/`. It talks to the BikeShop API
only, through one module (`frontend/api_client.py`), exactly as any other
client of the API would. It was generated from the API's OpenAPI spec and the
prompt below, then checked by hand against the running API.

```text
frontend/
├── app.py              entry point: sign-in / register, menu (st.navigation), logout
├── api_client.py       the only module that calls the API
├── ui.py               shared helpers: formatting, error messages, cached reads
├── pages/
│   ├── catalogue.py        Buy and Rent tabs, filters, availability check
│   ├── bike_detail.py      live rental quote + Book, or Reserve for sale bikes
│   ├── my_bookings.py      my rentals and my orders, with Cancel
│   ├── account.py          tokens, buy tokens, usage, API keys
│   ├── staff_board.py      today's pick-ups, returns, overdue, at risk
│   ├── staff_inventory.py  summary, all bikes, add / edit / retire
│   ├── staff_prices.py     rental price list editor
│   └── staff_orders.py     complete or cancel reservations, scheduler status
├── requirements.in / requirements.txt
└── Dockerfile
```

| page | URL path | who sees it |
|---|---|---|
| Sign in / create an account | `/login` | not signed in |
| Catalogue | `/catalogue` (also `/`) | everyone signed in |
| Bike details | `/bike` | everyone signed in |
| My rentals and orders | `/my_rentals` | everyone signed in |
| Account | `/account` | everyone signed in |
| Today's board | `/staff_board` | staff |
| Inventory | `/staff_inventory` | staff |
| Price list | `/staff_prices` | staff |
| Orders | `/staff_orders` | staff |

## Generating the Front End

1. Start the API and download its spec: open `http://localhost:8130/openapi.json`
   (or `https://demo.sai1.airs.iadsf.ch/openapi.json`) and save it.
2. Give Claude the file and the prompt below.

> Attached is the OpenAPI spec (`openapi.json`) of "BikeShop", a FastAPI
> backend for a bike shop that sells bikes and rents them out by the hour or
> day. Build a Streamlit frontend for it in a folder `frontend/`. It is a
> worked example for business students, so keep the code plain and readable,
> English only, with a short docstring at the top of every file.
>
> **Structure**
> - `app.py` is the entry point. Use `st.navigation` with `st.Page`; one file
>   per page in `pages/`.
> - `api_client.py` is the only module that calls the API (with `requests`).
>   Base URL from the environment variable `BIKESHOP_API_URL`, default
>   `http://localhost:8130`. Send the key as `Authorization: Bearer <key>`.
>   On a non-2xx answer raise an exception that carries the API's `detail`
>   string; pages show it with `st.error` exactly as it is. A 402 (out of API
>   tokens) also links to the Account page.
>
> **Sign-in with API keys.** There are no sessions or cookies on the API side;
> every call needs an API key.
> - The login form sends username and password to `POST /auth/generate-key`
>   with `name="streamlit-<8 random characters>"` and `expires_in_days=1`, so
>   every browser session has its own key. Keep `api_key`, `role`, `username`
>   and the key name in `st.session_state`.
> - Logout calls `DELETE /auth/revoke-key/{name}` with that key, then clears
>   the session. Registration is `POST /auth/register` (password at least 10
>   characters), then sign in.
>
> **Roles.** The response of `generate-key` contains `role`: `customer` or
> `staff`. Show the staff pages in the menu only to staff. (The API enforces
> roles itself; hiding pages is only for convenience.)
>
> **Pages**
> - Catalogue: "Buy" and "Rent" tabs with filters (category, frame size, max
>   price for sale bikes, condition, text). The Rent tab can check availability
>   for a period (`GET /api/availability`). Selecting a bike opens the detail page.
> - Bike detail: for rental bikes, date and start/end time inputs on the
>   15-minute grid, a live quote (`POST /api/rentals/quote`) and a Book button;
>   for sale bikes a Reserve button.
> - My rentals and orders, with Cancel buttons; show an order's `expires_at`
>   as "held until …".
> - Account: token balance, buy tokens (`POST /billing/purchase-tokens`),
>   usage stats, my API keys.
> - Staff, inventory: table of `GET /staff/bikes`, the `/staff/inventory`
>   summary, add bike, edit bike (incl. status available/maintenance for rental
>   bikes), retire.
> - Staff, today's board: pick-ups due today, returns due today, overdue,
>   at-risk bookings, with Pick up / Return / Cancel buttons
>   (`GET /staff/rentals?date=YYYY-MM-DD` and `?overdue=true`). Show the final
>   price after a return.
> - Staff, price list editor: `PUT /staff/rental-rates/{category}`.
> - Staff, orders: complete or cancel reserved orders, show `expires_at` and
>   the scheduler's last run from `GET /health` (`scheduler.last_run_at`).
>
> **URL paths (important).** In production one hostname serves both apps:
> nginx sends `/auth/ /billing/ /api/ /staff/ /docs /openapi.json /health` to
> the API and everything else to Streamlit. So no page may have a `url_path`
> equal to `auth`, `billing`, `api`, `staff`, `docs` or `health`, or starting
> with one of them followed by `/`. Set `url_path` explicitly on every page,
> e.g. `catalogue`, `bike`, `my_rentals`, `account`, `staff_inventory`,
> `staff_board`, `staff_prices`, `staff_orders`.
>
> **Times and money.** The API returns ISO times with the Zurich offset and
> accepts times without an offset as Zurich time. Show times like
> "Sat 7 Nov 10:00". Money comes as CHF strings like "65.00".
>
> **Costs.** Every `/api` call costs API tokens and counts toward a limit of
> 60 calls per minute, and Streamlit reruns the page on every click. Don't
> re-fetch on every rerun needlessly; use `st.cache_data` with a short TTL for
> the catalogue and the rental rates only.
>
> Also write `frontend/Dockerfile`: `python:3.12-slim`, install
> `requirements.txt` with uv (`COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv`,
> then `uv pip install --system --no-cache -r requirements.txt`),
> `EXPOSE 8501`, and run `streamlit run app.py --server.port 8501
> --server.address 0.0.0.0 --server.headless true --browser.gatherUsageStats false`.

## Running the thing

### Locally

Start the API first; from the project root, with the API's own venv:

```bash
.venv/bin/uvicorn api.expose_api:app --port 8130
```

Then, in a second terminal, also from the project root:

```bash
uv venv frontend/.venv --python 3.12
VIRTUAL_ENV=frontend/.venv uv pip sync frontend/requirements.txt

cd frontend
export BIKESHOP_API_URL=http://localhost:8130   # the default, so optional
.venv/bin/streamlit run app.py
```

Streamlit opens `http://localhost:8501`. Sign in with a seeded demo account
(`customer` or `staff`, passwords from `SEED_CUSTOMER_PASSWORD` /
`SEED_STAFF_PASSWORD` when you ran `python -m scripts.seed`), or create a new
customer account on the sign-in page.

To change the dependencies, edit `frontend/requirements.in` and recompile:

```bash
cd frontend && uv pip compile requirements.in -o requirements.txt
```

### In Docker

The frontend runs in `docker compose` as the service `frontend`, built from
`frontend/Dockerfile`. On the compose network it reaches the API at
`http://api:8000`, so compose sets `BIKESHOP_API_URL=http://api:8000` for it.
Its port is published on `127.0.0.1:8131` only; nginx forwards everything that
is not an API path to it (see `SPEC.md` §10).

```bash
docker compose up -d --build     # api, scheduler and frontend
docker compose logs -f frontend
curl http://127.0.0.1:8131/_stcore/health    # "ok"
```

To try the image on its own against an API running on your machine:

```bash
docker build -t bikeshop-frontend frontend
docker run --rm -p 127.0.0.1:8501:8501 \
  -e BIKESHOP_API_URL=http://host.docker.internal:8130 bikeshop-frontend
```

### Good to know

- **Tokens.** Every `/api` call costs API tokens (a search or a quote 1, a
  booking or reservation 5). New accounts start with 100; the seeded demo
  accounts get 10,000. Buy more on the Account page.
- **Caching.** The catalogue and the price list are cached for one minute, so a
  bike added in the inventory can take up to a minute to show in another
  user's catalogue.
- **Signing out** revokes this browser's API key. Other devices keep their own
  keys and stay signed in. Reloading the browser tab starts a new Streamlit
  session, so you sign in again.
