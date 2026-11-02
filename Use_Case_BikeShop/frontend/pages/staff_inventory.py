"""Staff: inventory. Every bike, a summary, and forms to add, edit and retire bikes.

- Summary: GET /staff/inventory (counts by purpose, category and status;
  bikes out now; overdue rentals; at-risk bookings; reservations expiring soon).
- Table: GET /staff/bikes (all bikes, sold and retired included).
- Add: POST /staff/bikes. Sale bikes need a price; rental bikes take their
  price from the price list.
- Edit: PATCH /staff/bikes/{id}, sending only the fields that changed. Rental
  bikes can be switched between "available" and "maintenance" here.
- Retire: POST /staff/bikes/{id}/retire (not while rented out or reserved).
"""

import pandas as pd
import streamlit as st

import api_client
import ui
from api_client import APIError

ui.require_staff()
st.title("Inventory")
ui.show_flash()

key = ui.api_key()
try:
    summary = api_client.inventory_summary(key)
    bikes = api_client.staff_bikes(key)
except APIError as error:
    ui.show_error(error)
    st.stop()

# --- summary --------------------------------------------------------------------
col1, col2, col3, col4 = st.columns(4)
col1.metric("Rental bikes out now", summary["rental_bikes_out_now"])
col2.metric("Overdue rentals", len(summary["overdue_rentals"]))
col3.metric("At-risk bookings", len(summary["at_risk_bookings"]))
col4.metric("Reservations expiring within 24 h", len(summary["orders_expiring_within_24h"]))

counts = pd.DataFrame(summary["counts"])
if not counts.empty:
    table = counts.pivot_table(index=["purpose", "category"], columns="status", values="count",
                               fill_value=0, aggfunc="sum")
    st.dataframe(table)

# --- all bikes ------------------------------------------------------------------
st.header("All bikes")
columns = ["id", "code", "name", "brand", "purpose", "category", "frame_size", "color", "year",
           "condition", "sale_price_chf", "status"]
st.dataframe(pd.DataFrame(bikes)[columns], hide_index=True)


def bike_label(bike: dict) -> str:
    return f"{bike['code']}: {bike['brand']} {bike['name']} ({bike['status']})"


# --- add a bike -----------------------------------------------------------------
st.header("Add a bike")
with st.form("add_bike", clear_on_submit=True):
    col1, col2, col3 = st.columns(3)
    code = col1.text_input("Code", placeholder="R-CITY-09 or S-ROAD-12")
    name = col2.text_input("Name")
    brand = col3.text_input("Brand")
    purpose = col1.selectbox("Purpose", ["rental", "sale"])
    category = col2.selectbox("Category", ui.CATEGORIES)
    frame_size = col3.selectbox("Frame size", ui.FRAME_SIZES, index=2)
    color = col1.text_input("Colour")
    year = col2.number_input("Year", min_value=1990, max_value=2100, value=ui.shop_today().year)
    condition = col3.selectbox("Condition", ui.CONDITIONS, index=1, help="Rental bikes are always 'used'.")
    sale_price = col1.number_input("Sale price (CHF, sale bikes only)", min_value=0.0, step=50.0)
    description = st.text_area("Description")
    if st.form_submit_button("Add bike", type="primary"):
        if not (code.strip() and name.strip() and brand.strip() and color.strip()):
            st.error("Code, name, brand and colour are required.")
        else:
            new_bike = {
                "code": code, "name": name, "brand": brand, "purpose": purpose, "category": category,
                "frame_size": frame_size, "color": color, "year": int(year), "condition": condition,
                "sale_price_chf": sale_price if purpose == "sale" else None, "description": description,
            }
            try:
                created = api_client.create_bike(key, new_bike)
                ui.cached_search_bikes.clear()
                ui.flash(f"Added {bike_label(created)}.")
                st.rerun()
            except APIError as error:
                ui.show_error(error)

# --- edit or retire a bike ------------------------------------------------------
st.header("Edit or retire a bike")
bikes_by_id = {b["id"]: b for b in bikes}
bike_id = st.selectbox("Bike", list(bikes_by_id), format_func=lambda i: bike_label(bikes_by_id[i]))
bike = bikes_by_id.get(bike_id)
if bike and bike["status"] == "retired":
    st.info("This bike is retired. Retired bikes can no longer be edited.")
elif bike:
    with st.form(f"edit_bike_{bike['id']}"):
        col1, col2, col3 = st.columns(3)
        edited = {
            "name": col1.text_input("Name", bike["name"]),
            "brand": col2.text_input("Brand", bike["brand"]),
            "color": col3.text_input("Colour", bike["color"]),
            "category": col1.selectbox("Category", ui.CATEGORIES, index=ui.CATEGORIES.index(bike["category"])),
            "frame_size": col2.selectbox("Frame size", ui.FRAME_SIZES,
                                         index=ui.FRAME_SIZES.index(bike["frame_size"])),
            "year": int(col3.number_input("Year", min_value=1990, max_value=2100, value=bike["year"])),
            "condition": col1.selectbox("Condition", ui.CONDITIONS, index=ui.CONDITIONS.index(bike["condition"])),
            "description": st.text_area("Description", bike["description"]),
        }
        if bike["purpose"] == "sale":
            edited["sale_price_chf"] = col2.number_input("Sale price (CHF)", min_value=0.0, step=50.0,
                                                         value=float(bike["sale_price_chf"] or 0))
        if bike["purpose"] == "rental" and bike["status"] in ("available", "maintenance"):
            edited["status"] = col3.selectbox("Status", ["available", "maintenance"],
                                              index=["available", "maintenance"].index(bike["status"]),
                                              help="Bookings stay when a bike goes into maintenance; "
                                                   "they show as 'at risk' on the board.")
        if st.form_submit_button("Save changes", type="primary"):
            # Send only what changed (the API's PATCH leaves other fields alone).
            changes = {field: value for field, value in edited.items()
                       if (float(value) != float(bike[field] or 0) if field == "sale_price_chf"
                           else value != bike[field])}
            if not changes:
                st.info("Nothing changed.")
            else:
                try:
                    updated = api_client.update_bike(key, bike["id"], changes)
                    ui.cached_search_bikes.clear()
                    ui.flash(f"Saved {bike_label(updated)}.")
                    st.rerun()
                except APIError as error:
                    ui.show_error(error)

    if bike["status"] not in ("retired", "sold"):
        st.write("Retiring takes the bike out of the shop for good (it stays in this table).")
        if st.button(f"Retire {bike['code']}"):
            try:
                retired = api_client.retire_bike(key, bike["id"])
                ui.cached_search_bikes.clear()
                ui.flash(f"Retired {bike_label(retired)}.")
                st.rerun()
            except APIError as error:
                ui.show_error(error)
