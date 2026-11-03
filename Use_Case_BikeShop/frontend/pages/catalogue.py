"""Catalogue: browse the bikes for sale ("Buy") and for rent ("Rent").

Both tabs search GET /api/bikes with the chosen filters. The answers are
cached for a minute (see ui.cached_search_bikes), because Streamlit reruns the
page on every click and each /api call costs a token.

The Rent tab can also check which bikes are free for a period
(GET /api/availability), which returns each free bike with its price.
Clicking "View" opens the bike detail page.
"""

import streamlit as st

import api_client
import ui
from api_client import APIError

st.title("Catalogue")
ui.show_flash()


def bike_row(bike: dict, price_text: str, button_key: str, start_at: str | None = None,
             end_at: str | None = None) -> None:
    """One line of the bike list: description, price and a View button."""
    info, price, action = st.columns([6, 2, 1], vertical_alignment="center")
    info.markdown(f"**{ui.bike_title(bike)}**  \n"
                  f"{bike['category']} · frame {bike['frame_size']} · {bike['color']} · "
                  f"{bike['year']} · {bike['condition']}")
    price.write(price_text)
    if action.button("View", key=button_key):
        ui.open_bike(bike["id"], start_at, end_at)


def optional(label: str, options: list[str], key: str) -> str | None:
    """A select box whose first choice, 'Any', means 'no filter'."""
    choice = st.selectbox(label, ["Any"] + options, key=key)
    return None if choice == "Any" else choice


buy_tab, rent_tab = st.tabs(["Buy", "Rent"])

# --- Buy ------------------------------------------------------------------------
with buy_tab:
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        category = optional("Category", ui.CATEGORIES, "buy_category")
    with col2:
        frame_size = optional("Frame size", ui.FRAME_SIZES, "buy_frame")
    with col3:
        condition = optional("Condition", ui.CONDITIONS, "buy_condition")
    with col4:
        max_price = st.number_input("Max price (CHF)", min_value=0, step=100, value=0,
                                    help="0 means no limit", key="buy_max_price")
    with col5:
        text = st.text_input("Search", placeholder="name, brand, description", key="buy_text")

    try:
        bikes = ui.cached_search_bikes(ui.api_key(), purpose="sale", category=category, frame_size=frame_size,
                                       condition=condition, max_price_chf=max_price or None, q=text or None)
    except APIError as error:
        ui.show_error(error)
        bikes = []

    st.caption(f"{len(bikes)} bikes for sale")
    for bike in bikes:
        status = "" if bike["status"] == "available" else f" ({bike['status']})"
        bike_row(bike, ui.fmt_chf(bike["sale_price_chf"]) + status, f"buy_view_{bike['id']}")

# --- Rent -----------------------------------------------------------------------
with rent_tab:
    col1, col2, col3 = st.columns(3)
    with col1:
        rent_category = optional("Category", ui.CATEGORIES, "rent_category")
    with col2:
        rent_frame = optional("Frame size", ui.FRAME_SIZES, "rent_frame")
    with col3:
        rent_text = st.text_input("Search", placeholder="name, brand, description", key="rent_text")

    st.subheader("Which bikes are free when?")
    start_at, end_at = ui.period_inputs("cat_period")
    if st.button("Check availability", type="primary"):
        try:
            st.session_state["availability"] = api_client.availability(
                ui.api_key(), start_at, end_at, category=rent_category, frame_size=rent_frame)
        except APIError as error:
            st.session_state.pop("availability", None)
            ui.show_error(error)

    found = st.session_state.get("availability")
    if found:
        st.write(f"Free from **{ui.fmt_time(found['start_at'])}** to **{ui.fmt_time(found['end_at'])}**: "
                 f"{len(found['bikes'])} bikes")
        if not found["bikes"]:
            st.info("No bike is free for that period. Try other times or another category.")
        for item in found["bikes"]:
            bike, quote = item["bike"], item["quote"]
            bike_row(bike, ui.fmt_chf(quote["total_chf"]), f"avail_view_{bike['id']}",
                     found["start_at"], found["end_at"])

    st.subheader("All rental bikes")
    try:
        rental_bikes = ui.cached_search_bikes(ui.api_key(), purpose="rental", category=rent_category,
                                              frame_size=rent_frame, q=rent_text or None)
        rates = {rate["category"]: rate for rate in ui.cached_rental_rates(ui.api_key())}
    except APIError as error:
        ui.show_error(error)
        rental_bikes, rates = [], {}

    st.caption(f"{len(rental_bikes)} rental bikes")
    for bike in rental_bikes:
        rate = rates.get(bike["category"])
        price = f"{ui.fmt_chf(rate['hourly_chf'])}/h, {ui.fmt_chf(rate['daily_chf'])}/day" if rate else "–"
        if bike["status"] != "available":
            price += f" ({bike['status']})"
        bike_row(bike, price, f"rent_view_{bike['id']}")
