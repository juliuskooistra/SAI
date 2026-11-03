# BikeShop

A small web app for a bike shop that sells bikes and rents them out: the SAI1
use case after the lecture *From prototype to production*. Live demo:
<https://demo.sai1.airs.iadsf.ch> (API docs at `/docs`).

- **What it does, and why**: [SPEC.md](SPEC.md), the contract. It was written
  before the code; change it first, then the code.
- **Where each part sits on the lecture's map**: [MAP.md](MAP.md)
- Middlewares: [MIDDLEWARE_ARCHITECTURE.md](MIDDLEWARE_ARCHITECTURE.md) ·
  Frontend: [FRONTEND.md](FRONTEND.md) · Docker: [BACKEND.md](BACKEND.md) ·
  Server: [DEPLOY.md](DEPLOY.md)

The structure follows `SAI/Use_Case_III/VoltagePredictor`: `api/main.py` holds
the app class, and requests go through routers → services → database. The
frontend is a static site (HTML, CSS, JavaScript) that FastAPI serves itself.

# Setup

Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv venv --python 3.12
uv pip sync requirements-dev.txt     # API + pytest
cp .env.example .env                 # fill in at least MLMP_API_KEY if you have one
```

The lock files are compiled from the `.in` files with
`uv pip compile requirements.in -o requirements.txt` (the same for
`requirements-dev`). The frontend has no dependencies: it's plain HTML, CSS
and JavaScript.

## Demo data

```bash
SEED_STAFF_PASSWORD=staff-pass-123 SEED_CUSTOMER_PASSWORD=customer-pass-123 \
  .venv/bin/python -m scripts.seed
```

This creates 35 bikes, the price list, the users `staff` and `customer` (with
those passwords), and a few rentals and orders. The database file is
`api/data/bikeshop.db`.

# Running the API

```bash
set -a; . ./.env; set +a
.venv/bin/uvicorn api.expose_api:app --reload --port 8130
```

Open <http://127.0.0.1:8130/> for the website and <http://127.0.0.1:8130/docs>
for the API docs. To try a call in the docs:

1. `POST /auth/generate-key` with `{"username": "customer", "password": "customer-pass-123", "name": "docs"}` returns an `api_key`.
2. Put it in the auth field as a Bearer token.
3. Try `GET /api/availability` with `start_at=2026-11-07T10:00` and `end_at=2026-11-07T15:00` (a Saturday; Sundays are closed).

The worker runs separately: `.venv/bin/python -m scripts.worker` (add
`--once` for one cycle). It runs the background jobs from the queue (emails
now, LLM tasks later) and the reservation expiry every 15 minutes. Without
`MAILGUN_API_KEY` emails only go to its log.

# The frontend

FastAPI serves it from `frontend/` at `/`, so running the API runs the
website too. How it was made and how it works: [FRONTEND.md](FRONTEND.md).

# Tests

```bash
.venv/bin/python -m pytest
```

There is one test file per group of build slices (SPEC §11). The tests use a
throwaway database and a frozen clock, Monday 2 Nov 2026 09:00 Zurich time.

# Deploying

Everything runs with `docker compose` behind nginx on the server; the steps
are in [DEPLOY.md](DEPLOY.md).
