"""Staff: the rental price list, one row per bike category.

Reads GET /api/rental-rates (cached for a minute) and saves a category with
PUT /staff/rental-rates/{category}. A price is per started hour, capped by the
daily rate for every 24 hours. Existing bookings keep the price they were
quoted; new quotes use the new rates straight away.
"""

import streamlit as st

import api_client
import ui
from api_client import APIError

ui.require_staff()
st.title("Price list")
ui.show_flash()
st.write("Rental price per started hour, capped at the daily rate for every 24 hours. "
         "Changes apply to new quotes and bookings; existing bookings keep their price.")

try:
    rates = {rate["category"]: rate for rate in ui.cached_rental_rates(ui.api_key())}
except APIError as error:
    ui.show_error(error)
    st.stop()

for category in ui.CATEGORIES:
    rate = rates.get(category)
    with st.form(f"rate_{category}"):
        st.subheader(category if rate else f"{category} (no price yet)")
        col1, col2, col3, col4 = st.columns([2, 2, 2, 1], vertical_alignment="bottom")
        hourly = col1.number_input("Per hour (CHF)", min_value=0.0, step=1.0,
                                   value=float(rate["hourly_chf"]) if rate else 0.0)
        daily = col2.number_input("Per day (CHF)", min_value=0.0, step=5.0,
                                  value=float(rate["daily_chf"]) if rate else 0.0)
        deposit = col3.number_input("Deposit (CHF)", min_value=0.0, step=50.0,
                                    value=float(rate["deposit_chf"]) if rate else 0.0)
        if col4.form_submit_button("Save", type="primary"):
            try:
                saved = api_client.set_rental_rate(ui.api_key(), category, hourly, daily, deposit)
                ui.cached_rental_rates.clear()
                ui.flash(f"Saved {category}: {ui.fmt_chf(saved['hourly_chf'])}/h, "
                         f"{ui.fmt_chf(saved['daily_chf'])}/day, deposit {ui.fmt_chf(saved['deposit_chf'])}.")
                st.rerun()
            except APIError as error:
                ui.show_error(error)
