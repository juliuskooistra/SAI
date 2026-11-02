# Middleware architecture

Same three middlewares as `Use_Case_III/VoltagePredictor`: authentication,
rate limiting and token billing. Each one checks the request's path and only
acts on the paths it protects.

## Execution order

Middlewares run in **reverse order of registration** (`api/main.py`,
`_configure_middleware`):

```text
Request  → CORS → Authentication → Rate limiting → Billing → endpoint
Response ← CORS ← Authentication ← Rate limiting ← Billing ← endpoint
```

## Protection matrix

| Path | Authentication | Role | Rate limit | Billing |
|---|---|---|---|---|
| `/auth/register`, `/auth/login`, `/auth/generate-key` | – | – | – | – |
| `/auth/my-keys`, `/auth/revoke-key/*` | ✓ | any | – | – |
| `/billing/*` | ✓ | any | – | – |
| `/api/*` | ✓ | any | ✓ | ✓ |
| `/staff/*` | ✓ | staff, else 403 | – | – |
| `/docs`, `/openapi.json`, `/health` | – | – | – | – |

## The three middlewares

**AuthenticationMiddleware** (`middleware/auth_middleware.py`) reads
`Authorization: Bearer <key>` and checks the key's hash in the database. It
sets `request.state.user_id`, `api_key_id` and `role`. It answers 401 when
the key is missing or invalid, and 403 when a non-staff key calls `/staff/*`.

**RateLimitMiddleware** (`middleware/rate_limit_middleware.py`) counts the
caller's successful calls in the last minute, hour and day (`APIUsage`
rows). Over the limit, it answers 429 with `Retry-After: 60`. The limits are
in `config.py`.

**BillingMiddleware** (`middleware/billing_middleware.py`) works out what the
call costs (`TOKEN_COST_RULES` in `config.py`) and answers 402 when the
balance is too low. It charges only after a 2xx response and writes one
`APIUsage` row per call.

## What changed compared to VoltagePredictor

| Change | Why |
|---|---|
| Authentication sets `request.state.role` and blocks `/staff/*` for non-staff | BikeShop has two roles. |
| Cost per call comes from `config.py` (reads 1, booking/reserving 5, cancel 0) | VoltagePredictor charged per predicted row. |
| **Fix:** one `APIUsage` row per call | The reference wrote two (in `BillingService.consume_tokens` and in the middleware), so the rate limiter counted every call twice. |
| **Fix:** `/auth/my-keys` and `/auth/revoke-key` need the caller's key and act on the caller's own keys | The reference listed the keys of any `user_id` sent in the request body, without authentication, and `revoke-key` always answered 501. |
| **Fix:** `my-keys` fills the response's `name` field | The reference set `api_key_name` and crashed. |
| Errors are built with `JSONResponse` | The reference built JSON by hand with f-strings, which breaks on quotes in messages. |
| Rate limits 60/1,000/5,000 instead of 10/100/1,000 | Clicking around the Streamlit demo makes more than 10 calls a minute. |
| Times are timezone-aware UTC | SQLModel 0.0.48 rejects naive datetimes, so `datetime.utcnow()` from the reference no longer works. |

Services raise `ShopError` subclasses (`services/errors.py`) instead of
`HTTPException`. `main.py` turns them into `{"detail": ...}` with the right
status code, so the services can also be called without HTTP (SPEC §8.3).
