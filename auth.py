import hashlib
import os

import streamlit as st
from streamlit_cookies_controller import CookieController

_COOKIE_NAME = "auth"
_COOKIE_MAX_AGE = 60 * 60 * 24 * 365 * 50  # 50 years


def _token() -> str:
    return hashlib.sha256(os.environ.get("APP_PASSWORD", "").encode()).hexdigest()[:16]


def check_password() -> bool:
    # Instantiate before any early returns so the component always renders and
    # can process pending set/remove operations on every script run.
    cookies = CookieController()
    token = _token()

    if st.session_state.get("authenticated"):
        return True

    if cookies.get(_COOKIE_NAME) == token:
        st.session_state.authenticated = True
        return True

    login_area = st.empty()
    login_success = False

    with login_area.container():
        st.title("Email Intent Viewer")
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            if password == os.environ.get("APP_PASSWORD", ""):
                login_success = True
            else:
                st.error("Incorrect password")

    if login_success:
        login_area.empty()
        # cookies.set() is called OUTSIDE the login_area container so clearing
        # the container doesn't erase the set component before the browser runs it.
        cookies.set(_COOKIE_NAME, token, max_age=_COOKIE_MAX_AGE)
        st.session_state.authenticated = True
        return True

    return False
