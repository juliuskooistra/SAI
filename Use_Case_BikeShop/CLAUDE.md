# BikeShop: instructions for Claude

A teaching app (SAI1): a bike shop that sells and rents bikes. FastAPI +
SQLite + a static frontend, deployed to Azure Container Apps. Read
`README.md` for what it is and `MAP.md` for how it maps onto the lecture.

## The spec comes first

`SPEC.md` is the contract; the code follows it.

1. **Before changing behaviour** (data model, API, business rules,
   validation, deployment), change `SPEC.md` first: the section that
   describes it, and the build slice in §11 with Given/When/Then.
2. **A new feature** gets a new build slice in §11 (acceptance criteria and
   the files it touches) before any code.
3. Then the code, then the tests from the slice.
4. Decisions with a "why" go into the decisions log, §12.

Pure mechanical changes (typos, formatting, comments) skip step 1.

## Running it

```bash
uv venv --python 3.12 && uv pip sync requirements-dev.txt   # once
.venv/bin/python -m pytest -q                                # all tests
.venv/bin/uvicorn api.expose_api:app --reload --port 8130    # API + website on http://localhost:8130
.venv/bin/python -m scripts.worker                           # the worker (queue + reservation expiry)
```

Dependencies: declare in `requirements.in`, then
`uv pip compile requirements.in -o requirements.txt` (and the same for
`requirements-dev`). Use `uv`, never `pip`.

## House rules

- **Layers**: routers (HTTP only) → services (rules; they take a `Session`
  and plain arguments, never a `Request`, and raise `ShopError`s from
  `services/errors.py`) → models. Services must stay callable without HTTP:
  the LLM tools use them directly (SPEC §8.2).
- **Every endpoint**: the function name is its `operation_id`, plus a
  `summary`, a docstring that says when to use it, and typed request/response
  models. Error messages are sentences a customer can read.
- **Database**: SQLite. Plain reads run outside transactions; a service that
  reads, decides and writes starts with `start_write_transaction(db)`
  (`BEGIN IMMEDIATE`). Don't go back to opening a transaction for every read:
  that caused "database is locked". No new columns on existing tables without
  a migration plan (`create_all` only adds tables).
- **Time**: always `timeutils.utcnow()` (tests freeze it); store UTC, show
  Zurich time.
- **Slow or failing work** (email, LLM calls) goes through the job queue
  (`api/jobqueue/`, SPEC §5.8), never inside a request.
- **Frontend**: plain HTML/CSS/JS modules, no framework, no build step,
  nothing from other sites. Only `js/api.js` calls `fetch`. Never put API
  text into `innerHTML`; use `el()`/`textContent`.
- **Code from the `kooistra-*` packages** is copied into the app with a
  comment naming its source, never imported.
- **No personal data to the LLM** (BFH MLMP terms), no secrets in the repo
  or the image (`.env` / Azure secrets; `.env.example` lists the keys).
- **English only**, for code, UI and docs. The code is read by business
  students: prefer clear and commented over clever.

## Deploying

Normally by merging to `main`: GitHub Actions tests, builds `bikeshop:<commit>`,
deploys to staging, and after approval to production (`.github/workflows/bikeshop.yml`).
By hand: `DEPLOY-azure.md`. The apps must stay at max 1 replica (Litestream).
Costs: `COSTS.md`. A VM: `DEPLOY.md`.
