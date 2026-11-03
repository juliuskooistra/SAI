# BikeShop: instructions for Claude

A teaching app (SAI1): a bike shop that sells and rents bikes. FastAPI +
SQLite + a static frontend, deployed to Azure Container Apps. Read
`README.md` for what it is and `MAP.md` for how it maps onto the lecture.

Start Claude in this folder or in the repository root (whose `CLAUDE.md`
imports this file). Paths and commands here are relative to this folder.

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

## Keep the map up to date

`MAP.md` (the table) and `map.html` (the interactive diagram) show where each
part of the app sits on the lecture's map, with its status (✅ 🟡 ⬜), what it
does and its files. **Every change that adds, finishes or moves a part
updates both files in the same commit**: the row in `MAP.md`, the matching
entry in `map.html` (same text, `s: "present" | "partial" | "missing"`), and
the test count and the stays / adapt / replace lists when they change.

## Running it

```bash
uv venv --python 3.12 && uv pip sync requirements-dev.txt   # once
set -a; . ./.env; set +a                                     # the app doesn't read .env itself (Docker Compose does)
.venv/bin/python -m pytest -q                                # all tests
.venv/bin/uvicorn api.expose_api:app --reload --port 8130    # API + website on http://localhost:8130
.venv/bin/python -m scripts.worker                           # the worker (queue + reservation expiry)

# Demo data in api/data/bikeshop.db: bikes, accounts, a few rentals ...
SEED_STAFF_PASSWORD=staff-pass-123 SEED_CUSTOMER_PASSWORD=customer-pass-123 .venv/bin/python -m scripts.seed
.venv/bin/python -m scripts.seed_history                     # ... then a year of past usage (SPEC §9.1)
```

The deployed database can't be reached from outside: develop against this
local copy, and test against the deployed app through its API (SPEC §8.2).

## Tests

One file per group of build slices: `tests/test_s<N>_….py` tests slice S<N>
from SPEC §11. `tests/conftest.py` gives every test a fresh database and
freezes the clock at Monday 2 Nov 2026, 09:00 Zurich. The history's planted
patterns P1–P8 (SPEC §9.1) are the answer key for the analytics agents, and
`tests/test_s23_history.py` checks them: if you change the history script,
those tests must still pass.

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
- **LLM features** (chat assistant, management agents) build on SPEC §8:
  tools live in `api/tools/` and call the services in-process; the model
  client is `inference_service.get_client()` (BFH MLMP, OpenAI-compatible,
  2 concurrent requests and 30 per minute); long runs are `llm_task` jobs on
  the queue. Prompts get bikes, prices and ids, never names, emails or
  usernames. The agent's tools may only do what its user's role allows:
  anything that needs a human's approval is a separate staff endpoint the
  agent can't call. The website's assistant (SPEC §13.8) runs each answer
  as an `assistant_reply` job and keeps the five prompt-injection layers:
  don't remove one, and give any new tool that changes data a
  once-per-message limit in `api/tools/chat.py`.
- **Frontend**: plain HTML/CSS/JS modules, no framework, no build step,
  nothing from other sites. Only `js/api.js` calls `fetch`. Never put API
  text into `innerHTML`; use `el()`/`textContent`.
- **Code from the `kooistra-*` packages** is copied into the app with a
  comment naming its source, never imported.
- **No personal data to the LLM** (BFH MLMP terms), no secrets in the repo
  or the image (`.env` / Azure secrets; `.env.example` lists the keys).
- **English only**, for code, UI and docs. The code is read by business
  students: prefer clear and commented over clever.

## Git and deploying

- Work on a branch and open a pull request: CI runs the tests on it. Don't
  push to `main` directly: every merge to `main` deploys.
- Merging to `main`: GitHub Actions tests, builds `bikeshop:<commit>`,
  deploys to staging, and after the lecturer's approval to production
  (`.github/workflows/bikeshop.yml`, SPEC §10.4). That is the only
  pipeline: don't add another deploy workflow, and don't use the Azure
  portal's *Continuous deployment*.
- By hand, and setting up the pipeline: `DEPLOY-azure.md` (it also has a
  table of pipeline errors and their fixes). The apps must stay at max
  1 replica (Litestream). Costs: `COSTS.md`. A VM: `DEPLOY.md`.
- Commit messages and docs: say what changed and why, in plain English.
