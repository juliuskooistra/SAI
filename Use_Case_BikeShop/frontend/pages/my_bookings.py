"""My rentals and my orders, each with a Cancel button.

- Rentals come from GET /api/rentals. A booking can be cancelled for free
  until its pick-up time (POST /api/rentals/{id}/cancel).
- Orders come from GET /api/orders. A reserved bike is held until
  `expires_at`; after that the shop's scheduler releases it. A reservation
  can be cancelled (POST /api/orders/{id}/cancel).

The page loads both lists once per visit or click (2 API tokens).
"""

import streamlit as st

import api_client
import ui
from api_client import APIError

st.title("My rentals and orders")
ui.show_flash()

rentals_tab, orders_tab = st.tabs(["Rentals", "Orders"])

with rentals_tab:
    try:
        rentals = api_client.my_rentals(ui.api_key())
    except APIError as error:
        ui.show_error(error)
        rentals = []

    if not rentals:
        st.info("You have no rentals yet. Find a bike under Catalogue → Rent.")
    for rental in rentals:
        with st.container(border=True):
            info, action = st.columns([5, 1], vertical_alignment="center")
            line = (f"**{rental['bike_name']}** ({rental['bike_code']}) · "
                    f"{ui.fmt_time(rental['start_at'])} → {ui.fmt_time(rental['end_at'])} · "
                    f"status **{rental['status']}**")
            if rental["overdue"]:
                line += " · **overdue, please bring the bike back**"
            price = f"Quoted {ui.fmt_chf(rental['quoted_price_chf'])}"
            if rental["final_price_chf"]:
                price += f" · final {ui.fmt_chf(rental['final_price_chf'])}"
            info.markdown(line + "  \n" + price)
            if rental["status"] == "booked" and action.button("Cancel", key=f"cancel_rental_{rental['id']}"):
                try:
                    api_client.cancel_my_rental(ui.api_key(), rental["id"])
                    ui.flash(f"Your booking of {rental['bike_name']} is cancelled.")
                    st.rerun()
                except APIError as error:
                    ui.show_error(error)

with orders_tab:
    try:
        orders = api_client.my_orders(ui.api_key())
    except APIError as error:
        ui.show_error(error)
        orders = []

    if not orders:
        st.info("You have no orders yet. Find a bike under Catalogue → Buy.")
    for order in orders:
        with st.container(border=True):
            info, action = st.columns([5, 1], vertical_alignment="center")
            line = (f"**{order['bike_name']}** ({order['bike_code']}) · {ui.fmt_chf(order['price_chf'])} · "
                    f"status **{order['status']}**")
            if order["status"] == "reserved":
                line += f"  \nHeld for you until {ui.fmt_time(order['expires_at'])}. Pay and collect it in the shop."
            info.markdown(line)
            if order["status"] == "reserved" and action.button("Cancel", key=f"cancel_order_{order['id']}"):
                try:
                    api_client.cancel_my_order(ui.api_key(), order["id"])
                    ui.cached_search_bikes.clear()  # the bike is for sale again
                    ui.flash(f"Your reservation of {order['bike_name']} is cancelled.")
                    st.rerun()
                except APIError as error:
                    ui.show_error(error)
