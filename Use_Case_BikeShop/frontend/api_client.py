"""All calls to the BikeShop API live here, and only here.

Every page imports this module instead of using `requests` directly. That keeps
the details of HTTP (URLs, headers, error handling) in one place:

- The base URL comes from the environment variable BIKESHOP_API_URL
  (default http://localhost:8130; in docker compose it is http://api:8000).
- Signed-in calls send the API key as `Authorization: Bearer <key>`.
- Any answer that is not 2xx raises APIError, which carries the API's
  `detail` sentence so the page can show it to the user as it is.

Each function returns the parsed JSON (a dict or a list of dicts).
"""

import os

import requests

API_URL = os.environ.get("BIKESHOP_API_URL", "http://localhost:8130").rstrip("/")
TIMEOUT_SECONDS = 15


class APIError(Exception):
    """The API answered with an error (or could not be reached).

    status_code is the HTTP status (0 if the API was unreachable) and
    detail is the sentence to show to the user.
    """

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _detail_from(response: requests.Response) -> str:
    """Pull the human-readable error message out of an error response."""
    try:
        detail = response.json().get("detail")
    except ValueError:
        return f"The API answered with status {response.status_code}."
    # FastAPI's own validation errors (422) are a list of problems.
    if isinstance(detail, list):
        return "; ".join(str(item.get("msg", item)) for item in detail)
    return str(detail) if detail else f"The API answered with status {response.status_code}."


def _call(method: str, path: str, key: str | None = None, params: dict | None = None, body: dict | None = None):
    """Send one request to the API and return the JSON answer, or raise APIError."""
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    if params:
        # Leave out filters the user did not set.
        params = {name: value for name, value in params.items() if value not in (None, "")}
    try:
        response = requests.request(method, API_URL + path, headers=headers, params=params,
                                    json=body, timeout=TIMEOUT_SECONDS)
    except requests.RequestException:
        raise APIError(0, f"Cannot reach the BikeShop API at {API_URL}. Please try again later.")
    if not response.ok:
        raise APIError(response.status_code, _detail_from(response))
    return response.json()


# --- /auth: accounts and API keys (free) -------------------------------------

def register(username: str, email: str, password: str) -> dict:
    return _call("POST", "/auth/register", body={"username": username, "email": email, "password": password})


def generate_key(username: str, password: str, key_name: str, expires_in_days: int = 1) -> dict:
    """Sign in: trade username and password for a new API key. The answer includes the role."""
    return _call("POST", "/auth/generate-key", body={
        "username": username, "password": password, "name": key_name, "expires_in_days": expires_in_days,
    })


def my_keys(key: str) -> list[dict]:
    return _call("GET", "/auth/my-keys", key)["keys"]


def revoke_key(key: str, key_name: str) -> dict:
    return _call("DELETE", f"/auth/revoke-key/{key_name}", key)


# --- /billing: API tokens (free) ----------------------------------------------

def balance(key: str) -> dict:
    return _call("GET", "/billing/balance", key)


def purchase_tokens(key: str, amount: float) -> dict:
    return _call("POST", "/billing/purchase-tokens", key, body={"amount": amount})


def usage_stats(key: str, days: int = 30) -> dict:
    return _call("GET", "/billing/usage-stats", key, params={"days": days})


def rate_limit_status(key: str) -> dict:
    return _call("GET", "/billing/rate-limit-status", key)


# --- /api: the shop (each call costs API tokens) ------------------------------

def search_bikes(key: str, purpose: str | None = None, category: str | None = None,
                 frame_size: str | None = None, max_price_chf: float | None = None,
                 condition: str | None = None, q: str | None = None) -> list[dict]:
    return _call("GET", "/api/bikes", key, params={
        "purpose": purpose, "category": category, "frame_size": frame_size,
        "max_price_chf": max_price_chf, "condition": condition, "q": q,
    })


def get_bike(key: str, bike_id: int) -> dict:
    return _call("GET", f"/api/bikes/{bike_id}", key)


def rental_rates(key: str) -> list[dict]:
    return _call("GET", "/api/rental-rates", key)


def opening_hours(key: str) -> dict:
    return _call("GET", "/api/opening-hours", key)


def availability(key: str, start_at: str, end_at: str, category: str | None = None,
                 frame_size: str | None = None) -> dict:
    return _call("GET", "/api/availability", key, params={
        "start_at": start_at, "end_at": end_at, "category": category, "frame_size": frame_size,
    })


def quote_rental(key: str, bike_id: int, start_at: str, end_at: str) -> dict:
    return _call("POST", "/api/rentals/quote", key, body={"bike_id": bike_id, "start_at": start_at, "end_at": end_at})


def book_rental(key: str, bike_id: int, start_at: str, end_at: str) -> dict:
    return _call("POST", "/api/rentals", key, body={"bike_id": bike_id, "start_at": start_at, "end_at": end_at})


def my_rentals(key: str, status: str | None = None) -> list[dict]:
    return _call("GET", "/api/rentals", key, params={"status": status})


def cancel_my_rental(key: str, rental_id: int) -> dict:
    return _call("POST", f"/api/rentals/{rental_id}/cancel", key)


def reserve_bike(key: str, bike_id: int) -> dict:
    return _call("POST", "/api/orders", key, body={"bike_id": bike_id})


def my_orders(key: str) -> list[dict]:
    return _call("GET", "/api/orders", key)


def cancel_my_order(key: str, order_id: int) -> dict:
    return _call("POST", f"/api/orders/{order_id}/cancel", key)


# --- /staff: shop staff only (free) -------------------------------------------

def staff_bikes(key: str) -> list[dict]:
    return _call("GET", "/staff/bikes", key)


def create_bike(key: str, bike: dict) -> dict:
    return _call("POST", "/staff/bikes", key, body=bike)


def update_bike(key: str, bike_id: int, changes: dict) -> dict:
    return _call("PATCH", f"/staff/bikes/{bike_id}", key, body=changes)


def retire_bike(key: str, bike_id: int) -> dict:
    return _call("POST", f"/staff/bikes/{bike_id}/retire", key)


def inventory_summary(key: str) -> dict:
    return _call("GET", "/staff/inventory", key)


def set_rental_rate(key: str, category: str, hourly_chf: float, daily_chf: float, deposit_chf: float) -> dict:
    return _call("PUT", f"/staff/rental-rates/{category}", key, body={
        "hourly_chf": hourly_chf, "daily_chf": daily_chf, "deposit_chf": deposit_chf,
    })


def staff_rentals(key: str, status: str | None = None, on_date: str | None = None,
                  overdue: bool | None = None) -> list[dict]:
    """All rentals. on_date (YYYY-MM-DD) gives the rentals that start or end that day."""
    params = {"status": status, "date": on_date}
    if overdue:
        params["overdue"] = "true"
    return _call("GET", "/staff/rentals", key, params=params)


def pickup_rental(key: str, rental_id: int) -> dict:
    return _call("POST", f"/staff/rentals/{rental_id}/pickup", key)


def return_rental(key: str, rental_id: int) -> dict:
    return _call("POST", f"/staff/rentals/{rental_id}/return", key)


def staff_cancel_rental(key: str, rental_id: int) -> dict:
    return _call("POST", f"/staff/rentals/{rental_id}/cancel", key)


def staff_orders(key: str, status: str | None = None) -> list[dict]:
    return _call("GET", "/staff/orders", key, params={"status": status})


def complete_order(key: str, order_id: int) -> dict:
    return _call("POST", f"/staff/orders/{order_id}/complete", key)


def staff_cancel_order(key: str, order_id: int) -> dict:
    return _call("POST", f"/staff/orders/{order_id}/cancel", key)


# --- health (public) ----------------------------------------------------------

def health() -> dict:
    return _call("GET", "/health")
