"""Staff: orders. Complete or cancel reserved sale bikes.

A customer's reservation holds a sale bike until `expires_at`. When the
customer pays and collects the bike, staff "Complete" the order (the bike is
sold); "Cancel" puts the bike back on sale.

Reservations that run out are released by the scheduler, a separate process
that runs every 15 minutes. Its last run comes from GET /health.

Data: GET /staff/orders, POST /staff/orders/{id}/complete and /cancel.
"""

from datetime import datetime

import streamlit as st

import api_client
import ui
from api_client import APIError

ui.require_staff()
st.title("Orders")
ui.show_flash()

key = ui.api_key()

# --- the scheduler that releases expired reservations ---------------------------
try:
    job = api_client.health()["scheduler"]
    if job["last_run_at"] is None:
        st.warning("The reservation scheduler has not run yet. Expired reservations are not being released.")
    else:
        outcome = "OK" if job["last_ok"] else "FAILED"
        st.info(f"Reservation scheduler: last run {ui.fmt_time(job['last_run_at'])} ({outcome}): "
                f"{job['last_result'] or ''}")
except APIError as error:
    ui.show_error(error)

try:
    orders = api_client.staff_orders(key)
except APIError as error:
    ui.show_error(error)
    st.stop()


def time_left(expires_at: str) -> str:
    """'in 5 h' / 'in 2 days' / 'expired', for the hold on a reservation."""
    left = datetime.fromisoformat(expires_at) - datetime.now(ui.SHOP_TIMEZONE)
    hours = left.total_seconds() / 3600
    if hours <= 0:
        return "expired, waiting for the scheduler"
    if hours < 48:
        return f"expires in {hours:.0f} h"
    return f"expires in {hours / 24:.0f} days"


reserved = [o for o in orders if o["status"] == "reserved"]
st.header(f"Reserved ({len(reserved)})")
if not reserved:
    st.caption("No reservations to complete.")
for order in reserved:
    with st.container(border=True):
        info, complete_col, cancel_col = st.columns([4, 1, 1], vertical_alignment="center")
        info.markdown(f"**{order['bike_name']}** ({order['bike_code']}) · {ui.fmt_chf(order['price_chf'])} · "
                      f"{order['username'] or order['user_id']}  \n"
                      f"Reserved {ui.fmt_time(order['created_at'])} · held until "
                      f"{ui.fmt_time(order['expires_at'])} ({time_left(order['expires_at'])})")
        if complete_col.button("Complete", key=f"complete_{order['id']}", type="primary",
                               help="The customer has paid and collected the bike."):
            try:
                done = api_client.complete_order(key, order["id"])
                ui.cached_search_bikes.clear()
                ui.flash(f"Sold {done['bike_name']} to {done['username'] or 'the customer'} "
                         f"for {ui.fmt_chf(done['price_chf'])}.")
                st.rerun()
            except APIError as error:
                ui.show_error(error)
        if cancel_col.button("Cancel", key=f"cancel_{order['id']}"):
            try:
                done = api_client.staff_cancel_order(key, order["id"])
                ui.cached_search_bikes.clear()
                ui.flash(f"Reservation of {done['bike_name']} cancelled; the bike is for sale again.")
                st.rerun()
            except APIError as error:
                ui.show_error(error)

closed = [o for o in orders if o["status"] != "reserved"]
with st.expander(f"Closed orders ({len(closed)})"):
    for order in closed:
        st.markdown(f"{order['bike_name']} ({order['bike_code']}) · {ui.fmt_chf(order['price_chf'])} · "
                    f"{order['username']} · **{order['status']}** {ui.fmt_time(order['closed_at'])}")
