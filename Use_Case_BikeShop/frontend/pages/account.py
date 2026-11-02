"""Account: API token balance, buying tokens, usage, rate limits and API keys.

Every call to /api/* costs tokens (a search 1, a booking 5). When the balance
runs out the API answers 402 and the other pages link here. Buying tokens is a
demo (no real payment): POST /billing/purchase-tokens.

API keys: this browser session signed in with its own key ("streamlit-…").
Other keys (other devices, scripts) can be revoked here.
All /billing and /auth calls are free.
"""

import pandas as pd
import streamlit as st

import api_client
import ui
from api_client import APIError

st.title("Account")
ui.show_flash()
st.write(f"Signed in as **{st.session_state['username']}** (role: {st.session_state['role']}).")

key = ui.api_key()

# --- tokens ---------------------------------------------------------------------
st.header("API tokens")
try:
    balance = api_client.balance(key)
    col1, col2, col3 = st.columns(3)
    col1.metric("Balance", f"{balance['current_balance']:,.0f}")
    col2.metric("Bought in total", f"{balance['total_purchased']:,.0f}")
    col3.metric("Used in total", f"{balance['total_used']:,.0f}")
except APIError as error:
    ui.show_error(error)

with st.form("buy_tokens"):
    amount = st.number_input("Tokens to buy (demo, no payment)", min_value=1, max_value=10_000, value=100, step=100)
    if st.form_submit_button("Buy tokens", type="primary"):
        try:
            result = api_client.purchase_tokens(key, amount)
            ui.flash(f"Added {result['tokens_added']:,.0f} tokens. New balance: {result['new_balance']:,.0f}.")
            st.rerun()
        except APIError as error:
            ui.show_error(error)

# --- usage ----------------------------------------------------------------------
st.header("Usage")
days = st.selectbox("Period", [1, 7, 30], index=2, format_func=lambda d: f"last {d} days")
try:
    usage = api_client.usage_stats(key, days)
    col1, col2 = st.columns(2)
    col1.metric("Requests", usage["total_requests"])
    col2.metric("Tokens used", f"{usage['total_tokens_consumed']:,.0f}")
    if usage["endpoint_breakdown"]:
        st.dataframe(pd.DataFrame(usage["endpoint_breakdown"]), hide_index=True)

    limits = api_client.rate_limit_status(key)
    st.caption("Rate limit: " + ", ".join(
        f"{limits['remaining'][period]} of {limits['limits'][f'requests_per_{period}']} left this {period}"
        for period in ("minute", "hour", "day")))
except APIError as error:
    ui.show_error(error)

# --- API keys -------------------------------------------------------------------
st.header("My API keys")
try:
    keys = api_client.my_keys(key)
except APIError as error:
    ui.show_error(error)
    keys = []

for item in keys:
    this_session = item["name"] == st.session_state["key_name"]
    with st.container(border=True):
        info, action = st.columns([5, 1], vertical_alignment="center")
        state = "active" if item["is_active"] else "revoked"
        label = f"**{item['name']}**" + (" (this browser session)" if this_session else "")
        info.markdown(f"{label} · {state} · created {ui.fmt_time(item['created_at'])} · "
                      f"last used {ui.fmt_time(item['last_used'])}")
        if item["is_active"] and not this_session and action.button("Revoke", key=f"revoke_{item['name']}"):
            try:
                api_client.revoke_key(key, item["name"])
                ui.flash(f"Key {item['name']} is revoked.")
                st.rerun()
            except APIError as error:
                ui.show_error(error)
st.caption("To revoke this session's key, use Log out in the sidebar.")
