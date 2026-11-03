"""Staff: today's board. What has to happen at the counter today.

- Pick-ups due: booked rentals that start on the chosen day.
- Returns due: active rentals that end on the chosen day.
- Overdue: active rentals past their return time (any day).
- At risk: bookings for a bike that staff have since put into maintenance.

Data: GET /staff/rentals?date=YYYY-MM-DD (rentals starting or ending that day),
GET /staff/rentals?overdue=true and GET /staff/inventory (at-risk bookings).
Buttons: Pick up, Return (shows the final price) and Cancel.
/staff calls are free and not rate limited.
"""

import streamlit as st

import api_client
import ui
from api_client import APIError

ui.require_staff()
st.title("Today's board")
ui.show_flash()

key = ui.api_key()
day = st.date_input("Day", value=ui.shop_today(), format="DD.MM.YYYY")


def same_day(iso_text: str) -> bool:
    return iso_text[:10] == day.isoformat()


def act(action, rental: dict, done_message) -> None:
    """Call a staff action; on success remember a message and reload the board."""
    try:
        result = action(key, rental["id"])
        ui.flash(done_message(result))
        st.rerun()
    except APIError as error:
        ui.show_error(error)


def rental_card(rental: dict, section: str) -> None:
    """One rental with the buttons that make sense for its status."""
    with st.container(border=True):
        info, buttons = st.columns([4, 2], vertical_alignment="center")
        line = (f"**{rental['bike_name']}** ({rental['bike_code']}) · {rental['username'] or rental['user_id']}  \n"
                f"{ui.fmt_time(rental['start_at'])} → {ui.fmt_time(rental['end_at'])} · "
                f"status {rental['status']} · quoted {ui.fmt_chf(rental['quoted_price_chf'])}")
        if rental["overdue"]:
            line += " · **overdue**"
        if rental["at_risk"]:
            line += " · **at risk: bike in maintenance**"
        info.markdown(line)

        left, right = buttons.columns(2)
        prefix = f"{section}_{rental['id']}"
        if rental["status"] == "booked":
            if left.button("Pick up", key=f"pickup_{prefix}", type="primary"):
                act(api_client.pickup_rental, rental,
                    lambda r: f"{r['bike_name']} handed over to {r['username'] or 'the customer'}.")
            if right.button("Cancel", key=f"cancel_{prefix}"):
                act(api_client.staff_cancel_rental, rental,
                    lambda r: f"Booking of {r['bike_name']} cancelled.")
        elif rental["status"] == "active":
            if left.button("Return", key=f"return_{prefix}", type="primary"):
                act(api_client.return_rental, rental,
                    lambda r: f"{r['bike_name']} returned. Final price: {ui.fmt_chf(r['final_price_chf'])} "
                              f"(quoted {ui.fmt_chf(r['quoted_price_chf'])}).")


try:
    on_day = api_client.staff_rentals(key, on_date=day.isoformat())
    overdue = api_client.staff_rentals(key, overdue=True)
    at_risk = api_client.inventory_summary(key)["at_risk_bookings"]
except APIError as error:
    ui.show_error(error)
    st.stop()

pickups = [r for r in on_day if r["status"] == "booked" and same_day(r["start_at"])]
returns = [r for r in on_day if r["status"] == "active" and same_day(r["end_at"]) and not r["overdue"]]

col1, col2, col3, col4 = st.columns(4)
col1.metric("Pick-ups due", len(pickups))
col2.metric("Returns due", len(returns))
col3.metric("Overdue", len(overdue))
col4.metric("At risk", len(at_risk))

sections = [
    ("pickups", "Pick-ups due", pickups, "No pick-ups due."),
    ("returns", "Returns due", returns, "No returns due."),
    ("overdue", "Overdue", overdue, "Nothing overdue."),
    ("atrisk", "At-risk bookings (bike in maintenance)", at_risk, "No bookings at risk."),
]
for section, heading, rentals, empty_text in sections:
    st.subheader(heading)
    if not rentals:
        st.caption(empty_text)
    for rental in rentals:
        rental_card(rental, section)

done = [r for r in on_day if r["status"] in ("returned", "cancelled")]
if done:
    with st.expander(f"Finished on this day ({len(done)})"):
        for rental in done:
            final = f" · final {ui.fmt_chf(rental['final_price_chf'])}" if rental["final_price_chf"] else ""
            st.markdown(f"{rental['bike_name']} ({rental['bike_code']}) · {rental['username']} · "
                        f"{rental['status']}{final}")
