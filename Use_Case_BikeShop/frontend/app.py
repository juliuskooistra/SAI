"""BikeShop frontend: the entry point (run with `streamlit run app.py`).

- Not signed in: shows the sign-in / register form.
- Signed in: builds the menu with st.navigation. Staff pages are only added
  for users with role "staff". (Hiding a page is not access control: the API
  refuses /staff calls from customers anyway.)

Sign-in creates a fresh API key for this browser session, named
"streamlit-<random>", valid for one day. The key, role and username live in
st.session_state. Logout revokes that key, so other devices stay signed in.

URL paths: in production one hostname serves both the API and this app, and
nginx sends /auth/ /billing/ /api/ /staff/ /docs /openapi.json /health to the
API. So no page here may use one of those as its URL path; every page sets
url_path explicitly (e.g. "staff_board", which nginx's /staff/ rule doesn't match).
"""

import secrets

import streamlit as st

import api_client
import ui
from api_client import APIError

st.set_page_config(page_title="BikeShop", page_icon=":material/pedal_bike:", layout="wide")


def sign_in(username: str, password: str) -> None:
    """Get a new API key for this browser session and remember who is signed in."""
    key_name = f"streamlit-{secrets.token_hex(4)}"  # 8 random characters
    answer = api_client.generate_key(username, password, key_name, expires_in_days=1)
    st.session_state["api_key"] = answer["api_key"]
    st.session_state["key_name"] = answer["name"]
    st.session_state["role"] = answer["role"]
    st.session_state["username"] = username


def sign_out() -> None:
    """Revoke this session's API key, then forget the user."""
    try:
        api_client.revoke_key(st.session_state["api_key"], st.session_state["key_name"])
    except APIError:
        pass  # the key may already have expired; we sign out locally either way
    ui.forget_session("You are signed out.")


def login_page() -> None:
    """The page shown to visitors who are not signed in."""
    st.title("BikeShop")
    st.write("Buy a bike or rent one by the hour or day.")
    ui.show_flash()

    sign_in_tab, register_tab = st.tabs(["Sign in", "Create an account"])

    with sign_in_tab:
        with st.form("sign_in"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Sign in", type="primary"):
                try:
                    sign_in(username, password)
                    st.rerun()
                except APIError as error:
                    st.error(error.detail)

    with register_tab:
        with st.form("register"):
            new_username = st.text_input("Username", key="reg_username")
            email = st.text_input("Email")
            new_password = st.text_input("Password (at least 10 characters)", type="password", key="reg_password")
            if st.form_submit_button("Create account", type="primary"):
                if len(new_password) < 10:
                    st.error("The password needs at least 10 characters.")
                else:
                    try:
                        api_client.register(new_username, email, new_password)
                        sign_in(new_username, new_password)
                        ui.flash(f"Welcome, {new_username}! Your account is ready.")
                        st.rerun()
                    except APIError as error:
                        st.error(error.detail)


signed_in = "api_key" in st.session_state

if not signed_in:
    navigation = st.navigation([st.Page(login_page, title="Sign in", url_path="login", icon=":material/login:")])
else:
    with st.sidebar:
        st.write(f"Signed in as **{st.session_state['username']}** ({st.session_state['role']})")
        if st.button("Log out", icon=":material/logout:"):
            sign_out()
            st.rerun()

    pages = {
        "Shop": [
            st.Page("pages/catalogue.py", title="Catalogue", url_path="catalogue",
                    icon=":material/storefront:", default=True),
            st.Page("pages/bike_detail.py", title="Bike details", url_path="bike", icon=":material/pedal_bike:"),
            st.Page("pages/my_bookings.py", title="My rentals and orders", url_path="my_rentals",
                    icon=":material/event:"),
            st.Page("pages/account.py", title="Account", url_path="account", icon=":material/person:"),
        ],
    }
    if st.session_state["role"] == "staff":
        pages["Staff"] = [
            st.Page("pages/staff_board.py", title="Today's board", url_path="staff_board",
                    icon=":material/today:"),
            st.Page("pages/staff_inventory.py", title="Inventory", url_path="staff_inventory",
                    icon=":material/inventory_2:"),
            st.Page("pages/staff_prices.py", title="Price list", url_path="staff_prices",
                    icon=":material/sell:"),
            st.Page("pages/staff_orders.py", title="Orders", url_path="staff_orders",
                    icon=":material/receipt_long:"),
        ]
    navigation = st.navigation(pages)

navigation.run()
