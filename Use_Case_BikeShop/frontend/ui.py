"""Small helpers shared by the pages: formatting, error messages, cached reads.

Nothing in here talks to the API directly; the cached functions go through
api_client like everything else.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

import api_client
from api_client import APIError

SHOP_TIMEZONE = ZoneInfo("Europe/Zurich")

CATEGORIES = ["city", "ebike", "mountain", "road", "gravel", "kids", "cargo"]
FRAME_SIZES = ["XS", "S", "M", "L", "XL"]
CONDITIONS = ["new", "used"]

# Where each page lives, for links and st.switch_page.
ACCOUNT_PAGE = "pages/account.py"
BIKE_PAGE = "pages/bike_detail.py"
CATALOGUE_PAGE = "pages/catalogue.py"
MY_BOOKINGS_PAGE = "pages/my_bookings.py"


# --- the signed-in user -------------------------------------------------------

def api_key() -> str:
    """The API key of the signed-in user (set by app.py at sign-in)."""
    return st.session_state["api_key"]


def is_staff() -> bool:
    return st.session_state.get("role") == "staff"


def require_staff() -> None:
    """Stop the page for anyone who is not staff.

    The menu already hides staff pages from customers, and the API refuses
    /staff calls from them anyway. This is just a friendly message.
    """
    if not is_staff():
        st.error("This page is for shop staff only.")
        st.stop()


def forget_session(message: str | None = None) -> None:
    """Drop the signed-in user from this browser session (does not call the API)."""
    st.session_state.clear()
    if message:
        st.session_state["flash"] = ("info", message)


# --- showing results and errors -----------------------------------------------

def show_error(error: APIError) -> None:
    """Show the API's error message as it is, with a hint where that helps."""
    if error.status_code == 401:
        # The key has expired or was revoked: back to the sign-in form.
        forget_session(error.detail + " Please sign in again.")
        st.rerun()
    st.error(error.detail)
    if error.status_code == 402:
        st.page_link(ACCOUNT_PAGE, label="Buy more API tokens on the Account page", icon=":material/toll:")


def flash(message: str, kind: str = "success") -> None:
    """Remember a message to show after the next rerun (e.g. after a button click)."""
    st.session_state["flash"] = (kind, message)


def show_flash() -> None:
    """Show (once) the message stored by flash()."""
    if "flash" in st.session_state:
        kind, message = st.session_state.pop("flash")
        getattr(st, kind)(message)


# --- formatting ---------------------------------------------------------------

def fmt_time(iso_text: str | None) -> str:
    """'2026-11-07T10:00:00+01:00' -> 'Sat 7 Nov 10:00' (shop time)."""
    if not iso_text:
        return "–"
    moment = datetime.fromisoformat(iso_text)
    if moment.tzinfo is not None:
        moment = moment.astimezone(SHOP_TIMEZONE)
    return f"{moment:%a} {moment.day} {moment:%b %H:%M}"


def fmt_chf(amount: str | float | None) -> str:
    """'65.00' -> 'CHF 65.00'."""
    if amount is None:
        return "–"
    return f"CHF {float(amount):,.2f}".replace(",", "'")


def shop_today() -> date:
    """Today's date in Zurich (the server itself may run on UTC)."""
    return datetime.now(SHOP_TIMEZONE).date()


def naive_iso(day: date, time_of_day) -> str:
    """Date + time as '2026-11-07T10:00'. The API reads times without an offset as Zurich time."""
    return f"{day.isoformat()}T{time_of_day:%H:%M}"


def bike_title(bike: dict) -> str:
    """'Flyer Upstreet 5 (R-EBIKE-01)'; no double brand for names like 'Stromer ST3'."""
    name = bike["name"] if bike["name"].startswith(bike["brand"]) else f"{bike['brand']} {bike['name']}"
    return f"{name} ({bike['code']})"


# --- cached reads ---------------------------------------------------------------
# Every /api call costs a token and counts toward the rate limit, and Streamlit
# reruns the page on every click. The catalogue and the price list change
# rarely, so we keep their answers for one minute.

@st.cache_data(ttl=60, show_spinner=False)
def cached_search_bikes(key: str, **filters) -> list[dict]:
    return api_client.search_bikes(key, **filters)


@st.cache_data(ttl=60, show_spinner=False)
def cached_rental_rates(key: str) -> list[dict]:
    return api_client.rental_rates(key)


def open_bike(bike_id: int, start_at: str | None = None, end_at: str | None = None) -> None:
    """Go to the bike detail page for this bike (optionally with a rental period filled in)."""
    st.session_state["selected_bike_id"] = bike_id
    st.session_state["prefill_period"] = (start_at, end_at) if start_at else None
    st.switch_page(BIKE_PAGE)


# --- choosing a rental period ---------------------------------------------------

def default_pickup_day() -> date:
    """Tomorrow, or Monday if tomorrow is a Sunday (the shop is closed on Sundays)."""
    day = shop_today() + timedelta(days=1)
    if day.weekday() == 6:
        day += timedelta(days=1)
    return day


def period_inputs(prefix: str) -> tuple[str, str]:
    """Date and time inputs for a rental period, on the shop's 15-minute grid.

    Returns (start_at, end_at) as ISO text without an offset (Zurich time).
    Pre-set values can be put into st.session_state under the same keys first.
    """
    today = shop_today()
    st.session_state.setdefault(f"{prefix}_day", default_pickup_day())
    st.session_state.setdefault(f"{prefix}_start", time(10, 0))
    st.session_state.setdefault(f"{prefix}_end", time(15, 0))
    st.session_state.setdefault(f"{prefix}_extra_days", 0)

    col_day, col_start, col_end, col_days = st.columns(4)
    pick_day = col_day.date_input("Pick-up date", key=f"{prefix}_day", min_value=today,
                                  max_value=today + timedelta(days=60), format="DD.MM.YYYY")
    start = col_start.time_input("Pick-up time", key=f"{prefix}_start", step=timedelta(minutes=15))
    end = col_end.time_input("Return time", key=f"{prefix}_end", step=timedelta(minutes=15))
    extra_days = col_days.number_input("Return after … days (0 = same day)", key=f"{prefix}_extra_days",
                                       min_value=0, max_value=14, step=1)
    return_day = pick_day + timedelta(days=int(extra_days))
    return naive_iso(pick_day, start), naive_iso(return_day, end)


def prefill_period(prefix: str, start_at: str, end_at: str) -> None:
    """Fill the inputs of period_inputs(prefix) with a given period before they are drawn."""
    start, end = datetime.fromisoformat(start_at), datetime.fromisoformat(end_at)
    st.session_state[f"{prefix}_day"] = start.date()
    st.session_state[f"{prefix}_start"] = start.time().replace(tzinfo=None)
    st.session_state[f"{prefix}_end"] = end.time().replace(tzinfo=None)
    st.session_state[f"{prefix}_extra_days"] = (end.date() - start.date()).days
