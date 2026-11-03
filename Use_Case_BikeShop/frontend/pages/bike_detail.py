"""Bike detail: rent a rental bike or reserve a bike for sale.

The bike to show is chosen in the catalogue (st.session_state["selected_bike_id"]).

- Rental bike: pick-up and return inputs on the 15-minute grid. Every change
  asks the API for a quote (POST /api/rentals/quote); "Book" makes the
  booking (POST /api/rentals).
- Sale bike: "Reserve" holds it for you (POST /api/orders) until a date the
  API sets; you pay and collect it in the shop.

To save API tokens, the bike and the last quote are kept in st.session_state,
so moving a time input asks for one new quote and nothing else.
"""

import streamlit as st

import api_client
import ui
from api_client import APIError

ui.show_flash()

bike_id = st.session_state.get("selected_bike_id")
if bike_id is None:
    st.title("Bike details")
    st.info("Pick a bike in the catalogue first.")
    st.page_link(ui.CATALOGUE_PAGE, label="Go to the catalogue", icon=":material/storefront:")
    st.stop()

# Load the bike once per selection (GET /api/bikes/{id}).
if st.session_state.get("bike_detail", {}).get("id") != bike_id:
    try:
        st.session_state["bike_detail"] = api_client.get_bike(ui.api_key(), bike_id)
    except APIError as error:
        ui.show_error(error)
        st.stop()
bike = st.session_state["bike_detail"]

st.page_link(ui.CATALOGUE_PAGE, label="Back to the catalogue", icon=":material/arrow_back:")
st.title(ui.bike_title(bike))
st.write(bike["description"])
col1, col2, col3, col4 = st.columns(4)
col1.metric("Category", bike["category"])
col2.metric("Frame size", bike["frame_size"])
col3.metric("Year", bike["year"])
col4.metric("Status", bike["status"])
st.caption(f"Colour: {bike['color']} · condition: {bike['condition']}")

# --- Sale bike: reserve ---------------------------------------------------------
if bike["purpose"] == "sale":
    st.subheader(f"Price: {ui.fmt_chf(bike['sale_price_chf'])}")
    if bike["status"] != "available":
        st.warning(f"This bike is {bike['status']} and cannot be reserved right now.")
    else:
        st.write("Reserve the bike and we hold it for you. Pay and collect it in the shop.")
        if st.button("Reserve", type="primary"):
            try:
                order = api_client.reserve_bike(ui.api_key(), bike["id"])
                ui.cached_search_bikes.clear()
                st.session_state.pop("bike_detail", None)  # its status is now "reserved"
                ui.flash(f"Reserved! We hold {order['bike_name']} for you until {ui.fmt_time(order['expires_at'])}.")
                st.switch_page(ui.MY_BOOKINGS_PAGE)
            except APIError as error:
                ui.show_error(error)
    st.stop()

# --- Rental bike: quote and book ------------------------------------------------
rate = bike.get("rental_rate")
if rate:
    st.subheader(f"{ui.fmt_chf(rate['hourly_chf'])} per hour, at most {ui.fmt_chf(rate['daily_chf'])} per day")
    st.caption(f"Deposit at pick-up: {ui.fmt_chf(rate['deposit_chf'])}. "
               "Open Mon–Fri 09:00–18:30 and Sat 09:00–16:00; closed Sundays and public holidays.")
if bike["status"] != "available":
    st.warning(f"This bike is in {bike['status']} and cannot be booked right now.")

# A period chosen on the catalogue's availability check fills in the inputs.
prefill = st.session_state.pop("prefill_period", None)
if prefill:
    ui.prefill_period("bike_period", *prefill)

start_at, end_at = ui.period_inputs("bike_period")

# Ask for a new quote only when the bike or period has changed.
period = (bike["id"], start_at, end_at)
if st.session_state.get("quote_for") != period:
    st.session_state["quote_for"] = period
    try:
        st.session_state["quote"] = api_client.quote_rental(ui.api_key(), bike["id"], start_at, end_at)
        st.session_state["quote_error"] = None
    except APIError as error:
        st.session_state["quote"] = None
        st.session_state["quote_error"] = error

quote = st.session_state["quote"]
if st.session_state["quote_error"]:
    ui.show_error(st.session_state["quote_error"])
elif quote:
    st.success(f"{ui.fmt_time(quote['start_at'])} to {ui.fmt_time(quote['end_at'])}: "
               f"**{ui.fmt_chf(quote['total_chf'])}**")
    st.caption(f"{quote['hours']} started hours = {quote['full_days']} full days at "
               f"{ui.fmt_chf(quote['daily_chf'])} + {quote['rest_hours']} hours at "
               f"{ui.fmt_chf(quote['hourly_chf'])} (capped at the daily rate). "
               f"Deposit {ui.fmt_chf(quote['deposit_chf'])}, paid back on return.")

    if st.button("Book", type="primary"):
        try:
            rental = api_client.book_rental(ui.api_key(), bike["id"], start_at, end_at)
            st.session_state["quote_for"] = None
            ui.flash(f"Booked {rental['bike_name']} from {ui.fmt_time(rental['start_at'])} "
                     f"to {ui.fmt_time(rental['end_at'])} for {ui.fmt_chf(rental['quoted_price_chf'])}.")
            st.switch_page(ui.MY_BOOKINGS_PAGE)
        except APIError as error:
            ui.show_error(error)
